"""Atomic, owner-scoped write boundary for Founder Graph value objects.

This module is deliberately persistence-agnostic.  The in-memory implementation
is a deterministic contract adapter for tests and local development; a Neo4j
adapter must preserve the same command, idempotency, revision, and audit rules.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from .founder_graph import (
    CampaignAuthorizationRegistry,
    ContentChunk,
    EgressPolicy,
    DomainValidationError,
    Evidence,
    NodeType,
    PersonAsset,
    RelationAssertion,
    RelationType,
    ReportVersion,
    Relationship,
    ResearchCampaign,
    ResearchRun,
    Source,
    SourceRevision,
    MaterialKind,
    Status,
    _ALLOWED_RELATION_ENDPOINTS,
    build_content_chunks,
    validate_report_references,
    validate_run_campaign_reference,
    validate_source_revision_history,
)


class GraphWriteError(DomainValidationError):
    """Base class for write-boundary failures."""


class IdempotencyConflictError(GraphWriteError):
    """An idempotency key was reused with a different command payload."""


class RevisionConflictError(GraphWriteError):
    """A command was based on a stale expected revision."""


class GraphWriteNotFoundError(GraphWriteError):
    """A command referenced an entity that is not in the write boundary."""


class NodeAlreadyExistsError(GraphWriteError):
    """An immutable node id is already registered."""


class GraphWritePort(Protocol):
    """Owner-bound command port shared by in-memory and persistent adapters."""

    @property
    def owner_id(self) -> str:
        """The only owner this port may read or mutate."""

    def put_node(
        self,
        node: Any,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        operation: str = "put_node",
        actor: str = "local-owner",
    ) -> "WriteReceipt":
        """Persist one owner-scoped domain node."""

    def capture_idea(
        self,
        idea: Any,
        source: Source,
        source_revision: SourceRevision,
        *,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> "WriteReceipt":
        """Persist an idea and its conversation source in one write boundary."""

    def capture_source(self, source: Source, source_revision: SourceRevision, *, idempotency_key: str, actor: str = "local-owner") -> "WriteReceipt":
        """Persist one local-only web source, its authored revision, and chunks atomically."""

    def link_entities(
        self,
        relationship: Relationship,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        actor: str = "local-owner",
    ) -> "WriteReceipt":
        """Persist one owner-scoped relationship."""

    def confirm_person_merge(
        self,
        assertion: RelationAssertion,
        *,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> "WriteReceipt":
        """Archive one Person and record its confirmed MERGED_INTO assertion."""

    def record_correction(
        self,
        previous_id: str,
        replacement: Any,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        actor: str = "local-owner",
    ) -> "WriteReceipt":
        """Persist a replacement that supersedes a prior node."""

    def get_node(self, node_id: str) -> Any | None:
        """Resolve one owner-scoped node for command validation."""


@dataclass(frozen=True, slots=True)
class AuditEvent:
    operation: str
    target_id: str
    target_type: str
    owner_id: str
    actor: str
    idempotency_key: str
    payload_fingerprint: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class WriteReceipt:
    operation: str
    target_id: str
    target_type: str
    revision: int
    idempotency_key: str
    replayed: bool = False
    source_revision_id: str | None = None
    content_chunk_ids: tuple[str, ...] = ()


def _stable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if is_dataclass(value):
        # Timestamps and provenance carry a fresh transport event identity;
        # the command idempotency key, not those volatile fields, defines a
        # replay-equivalent payload. SourceRevision.retrieved_at is likewise
        # transport metadata, while its content hash remains in the payload.
        return {
            field.name: _stable(getattr(value, field.name))
            for field in fields(value)
            if field.name not in {"created_at", "updated_at", "retrieved_at", "provenance"}
        }
    if isinstance(value, Mapping):
        return {str(key): _stable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_stable(item) for item in value]
    return value


def payload_fingerprint(*values: Any) -> str:
    encoded = json.dumps(_stable(values), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def capture_idea_payload_fingerprint(
    idea: Any,
    source: Source,
    source_revision: SourceRevision,
    content_chunks: tuple[ContentChunk, ...],
    owner_id: str,
) -> str:
    """Fingerprint capture_idea with the durable pre-ContentChunk contract."""

    return payload_fingerprint("capture_idea", idea, source, source_revision, owner_id)


def capture_source_payload_fingerprint(source: Source, revision: SourceRevision, owner_id: str) -> str:
    return payload_fingerprint("capture_source", source, revision, owner_id)


def validate_capture_source(source: Source, revision: SourceRevision, owner_id: str) -> None:
    if not isinstance(source, Source) or not isinstance(revision, SourceRevision):
        raise GraphWriteError("capture_source requires a Source and SourceRevision")
    if source.owner_id != owner_id or revision.owner_id != owner_id:
        raise GraphWriteError("capture_source nodes must belong to the local owner")
    if source.kind is not MaterialKind.WEB or source.egress_policy is not EgressPolicy.LOCAL_ONLY or revision.egress_policy is not EgressPolicy.LOCAL_ONLY:
        raise GraphWriteError("captured research sources must be local-only web sources")
    if source.status.value != "active" or revision.status.value != "active":
        raise GraphWriteError("captured research source and revision must be active")
    if source.id == revision.id or source.revision != 1 or revision.revision != 1 or source.current_revision_id != revision.id or revision.source_id != source.id:
        raise GraphWriteError("capture_source requires a matching initial Source revision")
    if not isinstance(revision.content, str) or not revision.content.strip() or len(revision.content) > 4000:
        raise GraphWriteError("authored summary must contain 1 to 4000 characters")
    for value, field in ((source.locator, "url"), (revision.locator, "url"), (source.title, "title")):
        if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
            raise GraphWriteError(f"{field} is invalid")
    if len(source.title) > 500:
        raise GraphWriteError("title exceeds the allowed length")
    if source.locator != revision.locator or len(source.locator) > 2048:
        raise GraphWriteError("Source URL must match its revision URL")
    parsed = urlsplit(source.locator)
    if any(char.isspace() for char in source.locator) or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise GraphWriteError("url must be an absolute HTTP(S) URL without credentials")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphWriteError(f"{field_name} must be a non-empty string")
    return value.strip()


def _node_type(node: Any) -> NodeType:
    try:
        value = node.node_type
    except AttributeError as error:
        raise GraphWriteError("node must expose a core node_type") from error
    try:
        return value if isinstance(value, NodeType) else NodeType(value)
    except (TypeError, ValueError) as error:
        raise GraphWriteError("node type is not in the Founder Graph allowlist") from error


class InMemoryGraphWriteService:
    """Thread-safe append-only write boundary used before Neo4j integration."""

    _OPERATIONS = frozenset({
        "put_node",
        "capture_idea",
        "capture_source",
        "capture_person",
        "capture_organization",
        "append_claim",
        "link_entities",
        "save_research_report",
        "record_decision",
        "record_correction",
        "confirm_person_merge",
    })

    def __init__(self, owner_id: str) -> None:
        self.owner_id = _required_text(owner_id, "owner_id")
        self._nodes: dict[str, Any] = {}
        self._node_history: dict[str, list[Any]] = {}
        self._relations: dict[str, Relationship] = {}
        self._structural_edges: list[tuple[str, str, str]] = []
        self._idempotency: dict[str, tuple[str, WriteReceipt]] = {}
        self._audit: list[AuditEvent] = []
        self._lock = RLock()

    def put_node(
        self,
        node: Any,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        operation: str = "put_node",
        actor: str = "local-owner",
    ) -> WriteReceipt:
        operation = self._validate_command(operation, actor, idempotency_key)
        node_id = _required_text(getattr(node, "id", None), "node.id")
        node_type = _node_type(node)
        node_owner = _required_text(getattr(node, "owner_id", None), "node.owner_id")
        if node_owner != self.owner_id:
            raise GraphWriteError("node owner does not match the local owner")
        fingerprint = payload_fingerprint(operation, node, expected_revision, self.owner_id)
        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            self._validate_report_references_locked(node)
            self._validate_source_reference_locked(node)
            current = self._nodes.get(node_id)
            if current is not None:
                current_revision = self._revision(current)
                if expected_revision is not None and current_revision != expected_revision:
                    raise RevisionConflictError("expected node revision does not match current revision")
                if (
                    node_type in {NodeType.RESEARCH_CAMPAIGN, NodeType.SOURCE}
                    and _node_type(current) is node_type
                    and expected_revision is not None
                    and self._revision(node) == current_revision + 1
                ):
                    receipt = WriteReceipt(operation, node_id, node_type.value, self._revision(node), idempotency_key)
                    prior_history = list(self._node_history[node_id])
                    prior_structural_edges = list(self._structural_edges)
                    self._nodes[node_id] = node
                    self._node_history[node_id].append(node)
                    if node_type is NodeType.SOURCE:
                        self._structural_edges = [
                            edge for edge in self._structural_edges
                            if not (edge[0] == node_id and edge[1] == "CURRENT_SOURCE_REVISION")
                        ]
                        if node.current_revision_id is not None:
                            self._structural_edges.append(
                                (node_id, "CURRENT_SOURCE_REVISION", node.current_revision_id)
                            )
                    try:
                        self._append_audit(receipt, actor, fingerprint)
                    except Exception:
                        self._nodes[node_id] = current
                        self._node_history[node_id] = prior_history
                        self._structural_edges = prior_structural_edges
                        raise
                    self._idempotency[idempotency_key] = (fingerprint, receipt)
                    return receipt
                raise NodeAlreadyExistsError(f"node id is already registered: {node_id}")
            if expected_revision not in (None, 0):
                raise RevisionConflictError("new nodes require expected_revision=0 or omitted")
            receipt = WriteReceipt(operation, node_id, node_type.value, self._revision(node), idempotency_key)
            self._nodes[node_id] = node
            self._node_history[node_id] = [node]
            try:
                self._append_audit(receipt, actor, fingerprint)
            except Exception:
                self._nodes.pop(node_id, None)
                self._node_history.pop(node_id, None)
                raise
            self._idempotency[idempotency_key] = (fingerprint, receipt)
            return receipt

    def capture_idea(
        self,
        idea: Any,
        source: Source,
        source_revision: SourceRevision,
        *,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        operation = self._validate_command("capture_idea", actor, idempotency_key)
        nodes = (idea, source, source_revision)
        if not isinstance(source, Source) or not isinstance(source_revision, SourceRevision):
            raise GraphWriteError("capture_idea requires an Idea, Source, and SourceRevision")
        if _node_type(idea) is not NodeType.IDEA:
            raise GraphWriteError("capture_idea requires an Idea node")
        if source_revision.source_id != source.id or source.current_revision_id != source_revision.id:
            raise GraphWriteError("capture_idea source revision does not match the Source current pointer")
        if any(getattr(node, "owner_id", None) != self.owner_id for node in nodes):
            raise GraphWriteError("capture_idea nodes must belong to the local owner")
        content_chunks = build_content_chunks(source_revision)
        if any(chunk.owner_id != self.owner_id for chunk in content_chunks):
            raise GraphWriteError("capture_idea content chunks must belong to the local owner")
        nodes = (*nodes, *content_chunks)
        node_ids = tuple(_required_text(getattr(node, "id", None), "node.id") for node in nodes)
        if len(set(node_ids)) != len(node_ids):
            raise GraphWriteError("capture_idea nodes must have distinct ids")
        fingerprint = capture_idea_payload_fingerprint(idea, source, source_revision, content_chunks, self.owner_id)
        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            if any(node_id in self._nodes for node_id in node_ids):
                raise NodeAlreadyExistsError("capture_idea node id is already registered")
            audit_length = len(self._audit)
            try:
                validate_source_revision_history(source, (source_revision,))
                for node in nodes:
                    self._validate_report_references_locked(node)
                for node in nodes:
                    self._nodes[node.id] = node
                    self._node_history[node.id] = [node]
                receipt = WriteReceipt(
                    operation,
                    idea.id,
                    NodeType.IDEA.value,
                    self._revision(idea),
                    idempotency_key,
                    source_revision_id=source_revision.id,
                    content_chunk_ids=tuple(chunk.id for chunk in content_chunks),
                )
                self._append_audit(receipt, actor, fingerprint)
            except Exception:
                for node_id in node_ids:
                    self._nodes.pop(node_id, None)
                    self._node_history.pop(node_id, None)
                del self._audit[audit_length:]
                raise
            self._idempotency[idempotency_key] = (fingerprint, receipt)
            return receipt

    def capture_source(self, source: Source, source_revision: SourceRevision, *, idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        operation = self._validate_command("capture_source", actor, idempotency_key)
        validate_capture_source(source, source_revision, self.owner_id)
        chunks = build_content_chunks(source_revision, operation=operation)
        nodes = (source, source_revision, *chunks)
        node_ids = tuple(_required_text(node.id, "node.id") for node in nodes)
        if len(set(node_ids)) != len(node_ids):
            raise GraphWriteError("capture_source nodes must have distinct ids")
        fingerprint = capture_source_payload_fingerprint(source, source_revision, self.owner_id)
        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            if any(node_id in self._nodes for node_id in node_ids):
                raise NodeAlreadyExistsError("capture_source node id is already registered")
            audit_length = len(self._audit)
            edge_length = len(self._structural_edges)
            try:
                for node in nodes:
                    self._nodes[node.id] = node
                    self._node_history[node.id] = [node]
                self._structural_edges.extend((
                    (source.id, "HAS_SOURCE_REVISION", source_revision.id),
                    (source.id, "CURRENT_SOURCE_REVISION", source_revision.id),
                    *((source_revision.id, "HAS_CHUNK", chunk.id) for chunk in chunks),
                ))
                receipt = WriteReceipt(operation, source.id, NodeType.SOURCE.value, 1, idempotency_key,
                    source_revision_id=source_revision.id, content_chunk_ids=tuple(chunk.id for chunk in chunks))
                self._append_audit(receipt, actor, fingerprint)
            except Exception:
                for node_id in node_ids:
                    self._nodes.pop(node_id, None)
                    self._node_history.pop(node_id, None)
                del self._structural_edges[edge_length:]
                del self._audit[audit_length:]
                raise
            self._idempotency[idempotency_key] = (fingerprint, receipt)
            return receipt

    def link_entities(
        self,
        relationship: Relationship,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        operation = self._validate_command("link_entities", actor, idempotency_key)
        if not isinstance(relationship, Relationship):
            raise GraphWriteError("relationship must be a Relationship")
        if relationship.owner_id != self.owner_id:
            raise GraphWriteError("relationship owner does not match the local owner")
        if expected_revision not in (None, 0):
            raise RevisionConflictError("relationships do not have mutable revisions")
        fingerprint = payload_fingerprint(operation, relationship, expected_revision, self.owner_id)
        relation_id = fingerprint
        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            source = self._nodes.get(relationship.source_id)
            target = self._nodes.get(relationship.target_id)
            if source is None or target is None:
                raise GraphWriteNotFoundError("relationship endpoints must already exist")
            source_type = _node_type(source)
            target_type = _node_type(target)
            if (source_type, target_type) not in _ALLOWED_RELATION_ENDPOINTS[relationship.relation]:
                raise GraphWriteError("relationship endpoint types are not allowlisted")
            if getattr(source, "owner_id", None) != self.owner_id or getattr(target, "owner_id", None) != self.owner_id:
                raise GraphWriteError("relationship endpoints must belong to the local owner")
            for evidence_id in relationship.evidence_ids:
                evidence = self._nodes.get(evidence_id)
                if evidence is None or _node_type(evidence) is not NodeType.EVIDENCE:
                    raise GraphWriteNotFoundError("relationship evidence must already exist")
                if getattr(evidence, "owner_id", None) != self.owner_id:
                    raise GraphWriteError("relationship evidence must belong to the local owner")
            if relation_id in self._relations:
                raise NodeAlreadyExistsError("identical relationship is already registered")
            receipt = WriteReceipt(operation, relation_id, "relationship", 0, idempotency_key)
            self._relations[relation_id] = relationship
            try:
                self._append_audit(receipt, actor, fingerprint)
            except Exception:
                self._relations.pop(relation_id, None)
                raise
            self._idempotency[idempotency_key] = (fingerprint, receipt)
            return receipt

    def confirm_person_merge(
        self,
        assertion: RelationAssertion,
        *,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        """Atomically archive the losing Person and persist a confirmed merge assertion."""

        operation = self._validate_command("confirm_person_merge", actor, idempotency_key)
        if not isinstance(assertion, RelationAssertion):
            raise GraphWriteError("person merge requires a RelationAssertion")
        if assertion.owner_id != self.owner_id:
            raise GraphWriteError("relation assertion owner does not match the local owner")
        if (
            assertion.predicate is not RelationType.MERGED_INTO
            or assertion.status.value != "confirmed"
            or assertion.source_kind is not NodeType.PERSON
            or assertion.target_kind is not NodeType.PERSON
        ):
            raise GraphWriteError("person merge requires a confirmed Person-to-Person MERGED_INTO assertion")
        # ``valid_from`` is assigned when this command object is rebuilt for a
        # retry.  It is audit metadata, not caller intent, so it must not make
        # an otherwise identical confirmation conflict with its idempotency key.
        fingerprint = payload_fingerprint(
            operation,
            assertion.id,
            assertion.source_id,
            assertion.target_id,
            assertion.assertion_family_id,
            assertion.predicate,
            assertion.status,
            assertion.evidence_ids,
            self.owner_id,
        )
        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            loser = self._nodes.get(assertion.source_id)
            winner = self._nodes.get(assertion.target_id)
            if not isinstance(loser, PersonAsset) or not isinstance(winner, PersonAsset):
                raise GraphWriteError("person merge endpoints must already be Person records")
            if loser.status is not Status.ACTIVE or winner.status is not Status.ACTIVE:
                raise GraphWriteError("person merge endpoints must both be active")
            if assertion.id in self._nodes:
                raise NodeAlreadyExistsError("relation assertion id is already registered")
            for evidence_id in assertion.evidence_ids:
                evidence = self._nodes.get(evidence_id)
                if not isinstance(evidence, Evidence):
                    raise GraphWriteNotFoundError("person merge evidence must already exist")
                if evidence.owner_id != self.owner_id:
                    raise GraphWriteError("person merge evidence must belong to the local owner")
            archived_loser = replace(loser, status=Status.ARCHIVED)
            receipt = WriteReceipt(operation, assertion.id, NodeType.RELATION_ASSERTION.value, assertion.revision, idempotency_key)
            prior_history = list(self._node_history[loser.id])
            try:
                self._nodes[loser.id] = archived_loser
                self._node_history[loser.id].append(archived_loser)
                self._nodes[assertion.id] = assertion
                self._node_history[assertion.id] = [assertion]
                self._append_audit(receipt, actor, fingerprint)
            except Exception:
                self._nodes[loser.id] = loser
                self._node_history[loser.id] = prior_history
                self._nodes.pop(assertion.id, None)
                self._node_history.pop(assertion.id, None)
                raise
            self._idempotency[idempotency_key] = (fingerprint, receipt)
            return receipt

    def record_correction(
        self,
        previous_id: str,
        replacement: Any,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        previous_id = _required_text(previous_id, "previous_id")
        previous = self.get_node(previous_id)
        if previous is None:
            raise GraphWriteNotFoundError(f"previous node does not exist: {previous_id}")
        if getattr(replacement, "supersedes_id", None) != previous_id:
            raise GraphWriteError("correction must supersede the previous node")
        if expected_revision is not None and self._revision(previous) != expected_revision:
            raise RevisionConflictError("expected previous revision does not match current revision")
        return self.put_node(
            replacement,
            idempotency_key=idempotency_key,
            expected_revision=0,
            operation="record_correction",
            actor=actor,
        )

    def get_node(self, node_id: str) -> Any | None:
        with self._lock:
            return self._nodes.get(_required_text(node_id, "node_id"))

    def nodes(self) -> tuple[Any, ...]:
        with self._lock:
            return tuple(self._nodes.values())

    def structural_edges(self) -> tuple[tuple[str, str, str], ...]:
        with self._lock:
            return tuple(self._structural_edges)

    def node_history(self, node_id: str) -> tuple[Any, ...]:
        with self._lock:
            return tuple(self._node_history.get(_required_text(node_id, "node_id"), ()))

    def relations(self) -> tuple[Relationship, ...]:
        with self._lock:
            return tuple(self._relations.values())

    def audit_events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._audit)

    def _validate_command(self, operation: str, actor: str, idempotency_key: str) -> str:
        operation = _required_text(operation, "operation")
        actor = _required_text(actor, "actor")
        _required_text(idempotency_key, "idempotency_key")
        if operation not in self._OPERATIONS:
            raise GraphWriteError("operation is not allowlisted")
        return operation

    def _replay_or_raise(self, idempotency_key: str, fingerprint: str) -> WriteReceipt | None:
        existing = self._idempotency.get(idempotency_key)
        if existing is None:
            return None
        prior_fingerprint, receipt = existing
        if prior_fingerprint != fingerprint:
            raise IdempotencyConflictError("idempotency key was reused with a different payload")
        return WriteReceipt(
            receipt.operation,
            receipt.target_id,
            receipt.target_type,
            receipt.revision,
            receipt.idempotency_key,
            replayed=True,
            source_revision_id=receipt.source_revision_id,
            content_chunk_ids=receipt.content_chunk_ids,
        )

    def _append_audit(self, receipt: WriteReceipt, actor: str, fingerprint: str) -> None:
        self._audit.append(
            AuditEvent(
                receipt.operation,
                receipt.target_id,
                receipt.target_type,
                self.owner_id,
                actor,
                receipt.idempotency_key,
                fingerprint,
                datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _revision(node: Any) -> int:
        if getattr(node, "node_type", None) is NodeType.RESEARCH_CAMPAIGN:
            value = getattr(node, "aggregate_revision", 0)
        else:
            value = getattr(node, "revision", 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise GraphWriteError("node revision must be a non-negative integer")
        return value

    def _validate_source_reference_locked(self, node: Any) -> None:
        if isinstance(node, SourceRevision):
            source = self._nodes.get(node.source_id)
            if source is None:
                raise GraphWriteNotFoundError(f"source does not exist: {node.source_id}")
            if not isinstance(source, Source) or source.owner_id != self.owner_id:
                raise GraphWriteError("source revision must reference the local Source")
            prior = tuple(
                value for value in self._nodes.values()
                if isinstance(value, SourceRevision) and value.source_id == source.id
            )
            if any(value.revision == node.revision for value in prior):
                raise GraphWriteError("source revision number is already registered")
            expected = max((value.revision for value in prior), default=0) + 1
            if node.revision != expected:
                raise GraphWriteError("source revision numbers must be appended contiguously")
            if node.revision == 1 and node.supersedes_id is not None:
                raise GraphWriteError("first source revision cannot supersede another revision")
            if node.revision > 1 and node.supersedes_id != max(prior, key=lambda value: value.revision).id:
                raise GraphWriteError("source revision must supersede the prior revision")
            return
        if isinstance(node, Source):
            revisions = tuple(
                value for value in self._nodes.values()
                if isinstance(value, SourceRevision) and value.source_id == node.id
            )
            if node.current_revision_id is not None:
                validate_source_revision_history(node, revisions)

    def _validate_report_references_locked(self, node: Any) -> None:
        """Resolve ReportVersion references before the immutable node is stored."""

        if not isinstance(node, ReportVersion):
            return

        if node.parent_id is not None:
            parent = self._nodes.get(node.parent_id)
            if parent is None:
                raise GraphWriteNotFoundError(f"report parent does not exist: {node.parent_id}")
            if _node_type(parent) is not NodeType.REPORT_VERSION:
                raise GraphWriteError("report parent has an invalid node type")
            if getattr(parent, "owner_id", None) != self.owner_id:
                raise GraphWriteError("report parent owner does not match the local owner")

        runs = tuple(self._resolve_report_nodes(node.run_ids, NodeType.RESEARCH_RUN, "report run"))
        campaigns: dict[str, ResearchCampaign] = {}
        for run in runs:
            campaign = self._nodes.get(run.campaign_id)
            if campaign is None:
                raise GraphWriteNotFoundError(f"report campaign does not exist: {run.campaign_id}")
            if not isinstance(campaign, ResearchCampaign) or _node_type(campaign) is not NodeType.RESEARCH_CAMPAIGN:
                raise GraphWriteError("report run campaign must be a ResearchCampaign")
            if campaign.owner_id != self.owner_id:
                raise GraphWriteError("report campaign owner does not match the local owner")
            try:
                registry = CampaignAuthorizationRegistry.from_campaign_history(self._node_history[campaign.id])
                validate_run_campaign_reference(
                    run,
                    campaign,
                    campaign.authorization_snapshot,
                    authorization_registry=registry,
                )
            except DomainValidationError as error:
                raise GraphWriteError(f"report run authorization is invalid: {error}") from error
            campaigns[campaign.id] = campaign
        if len(campaigns) > 1:
            raise GraphWriteError("report runs must belong to one campaign")

        evidence = tuple(self._resolve_report_nodes(node.evidence_ids, NodeType.EVIDENCE, "report evidence"))
        claims = self._resolve_report_nodes(
            tuple(
                claim_id
                for section in node.sections
                for claim_id in section.claim_ids
            ),
            NodeType.CLAIM,
            "report section claim",
        )
        # Keep the sequence stable while removing duplicate section references.
        unique_claims = tuple({claim.id: claim for claim in claims}.values())
        validate_report_references(node, runs, evidence, unique_claims)

    def _resolve_report_nodes(
        self,
        identifiers: Any,
        expected_type: NodeType,
        label: str,
    ) -> tuple[Any, ...]:
        if isinstance(identifiers, str):
            identifiers = (identifiers,)
        resolved: list[Any] = []
        for identifier in identifiers:
            item = self._nodes.get(identifier)
            if item is None:
                raise GraphWriteNotFoundError(f"{label} does not exist: {identifier}")
            if _node_type(item) is not expected_type:
                raise GraphWriteError(f"{label} has an invalid node type")
            if getattr(item, "owner_id", None) != self.owner_id:
                raise GraphWriteError(f"{label} owner does not match the local owner")
            resolved.append(item)
        return tuple(resolved)
