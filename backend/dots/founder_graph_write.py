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
    Claim,
    ContentChunk,
    EgressPolicy,
    DomainValidationError,
    Evidence,
    EvidenceEdgeType,
    EvidencePolarity,
    Idea,
    NodeType,
    PersonAsset,
    RelationAssertion,
    RelationAssertionEdgeType,
    RelationType,
    RelationshipStatus,
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
    relation_assertion_structural_edges,
)
from .idea_brief import IdeaBriefVersion


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

    def capture_evidence(self, claim_id: str, content_chunk_id: str, *, polarity: EvidencePolarity | str | None = None,
                         confidence: float = 1.0, egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY,
                         idempotency_key: str, actor: str = "local-owner") -> "WriteReceipt":
        """Cite a persisted same-owner ContentChunk without accepting source text."""

    def link_entities(
        self,
        relationship: Relationship,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        actor: str = "local-owner",
    ) -> "WriteReceipt":
        """Persist one owner-scoped relationship."""

    def save_relation_assertion(
        self,
        assertion: RelationAssertion,
        *,
        expected_family_revision: int | None,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> "WriteReceipt":
        """Atomically persist one formal assertion and its canonical references."""

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


@dataclass(frozen=True, slots=True)
class SourceChainRepairPlan:
    owner_id: str
    source_count: int
    revision_count: int
    chunk_count: int
    edges_to_add: tuple[tuple[str, str, str], ...]
    edges_added: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class GraphReadSnapshot:
    """Coherent immutable collection of values consumed by the memory reader."""

    nodes: tuple[Any, ...]
    relations: tuple[Relationship, ...]
    structural_edges: tuple[tuple[str, str, str], ...]
    idea_briefs: tuple[IdeaBriefVersion, ...]
    latest_idea_briefs: tuple[tuple[str, IdeaBriefVersion], ...]


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


def _source_chain_repair_plan(
    owner_id: str,
    nodes_by_id: Mapping[str, Any],
    structural_edges: tuple[tuple[str, str, str], ...] | list[tuple[str, str, str]],
) -> tuple[int, int, int, tuple[tuple[str, str, str], ...]]:
    """Validate the complete local source graph before deriving safe edge repairs."""

    sources: dict[str, Source] = {}
    revisions: dict[str, SourceRevision] = {}
    chunks: dict[str, ContentChunk] = {}
    for key, node in nodes_by_id.items():
        if isinstance(node, (Source, SourceRevision, ContentChunk)):
            if key != getattr(node, "id", None):
                raise GraphWriteError("source-chain node identity does not match its stored key")
            if node.owner_id != owner_id:
                raise GraphWriteError("source-chain node does not belong to the local owner")
            target = sources if isinstance(node, Source) else revisions if isinstance(node, SourceRevision) else chunks
            if node.id in target:
                raise GraphWriteError("source-chain node identity is duplicated")
            target[node.id] = node
        elif getattr(node, "node_type", None) in (
            NodeType.SOURCE, NodeType.SOURCE_REVISION, NodeType.CONTENT_CHUNK,
            NodeType.SOURCE.value, NodeType.SOURCE_REVISION.value, NodeType.CONTENT_CHUNK.value,
        ):
            raise GraphWriteError("source-chain record has an invalid value type")

    revisions_by_source: dict[str, list[SourceRevision]] = {}
    for revision in revisions.values():
        source = sources.get(revision.source_id)
        if source is None:
            raise GraphWriteError("source revision references a missing local Source")
        if revision.owner_id != source.owner_id:
            raise GraphWriteError("source revision owner does not match its Source")
        if sha256(revision.content.encode("utf-8")).hexdigest() != revision.content_hash:
            raise GraphWriteError("source revision content hash does not match its content")
        revisions_by_source.setdefault(source.id, []).append(revision)

    expected_edges: list[tuple[str, str, str]] = []
    expected_chunk_by_id: dict[str, ContentChunk] = {}
    for source in sorted(sources.values(), key=lambda value: value.id):
        history = sorted(revisions_by_source.get(source.id, ()), key=lambda value: value.revision)
        if history:
            try:
                current = validate_source_revision_history(source, history)
            except DomainValidationError as error:
                raise GraphWriteError("source revision history or current pointer is inconsistent") from error
            expected_edges.extend(
                (source.id, "HAS_SOURCE_REVISION", revision.id) for revision in history
            )
            expected_edges.append((source.id, "CURRENT_SOURCE_REVISION", current.id))
        elif source.current_revision_id is not None:
            raise GraphWriteError("Source has a current revision pointer without local history")

        for revision in history:
            try:
                expected_chunks = build_content_chunks(revision)
            except DomainValidationError as error:
                raise GraphWriteError("source revision cannot produce valid deterministic chunks") from error
            for chunk in expected_chunks:
                expected_chunk_by_id[chunk.id] = chunk
                expected_edges.append((revision.id, "HAS_CHUNK", chunk.id))

    if set(chunks) != set(expected_chunk_by_id):
        raise GraphWriteError("source revision ContentChunks are missing or unexpected")
    for chunk_id, expected in expected_chunk_by_id.items():
        actual = chunks[chunk_id]
        if (
            actual.owner_id != expected.owner_id
            or actual.source_revision_id != expected.source_revision_id
            or actual.ordinal != expected.ordinal
            or actual.char_start != expected.char_start
            or actual.char_end != expected.char_end
            or actual.text != expected.text
            or actual.text_hash != expected.text_hash
        ):
            raise GraphWriteError("ContentChunk ordinal, range, text, or hash conflicts with its revision")

    expected_set = set(expected_edges)
    edge_counts: dict[tuple[str, str, str], int] = {}
    lineage_types = {"HAS_SOURCE_REVISION", "CURRENT_SOURCE_REVISION", "HAS_CHUNK"}
    for edge in structural_edges:
        if not isinstance(edge, tuple) or len(edge) != 3:
            raise GraphWriteError("structural edge is malformed")
        if any(not isinstance(part, str) or not part for part in edge):
            raise GraphWriteError("structural edge endpoint or type is malformed")
        if edge[1] not in lineage_types:
            continue
        if edge not in expected_set:
            raise GraphWriteError("source-chain structural edge has a contradictory endpoint or direction")
        edge_counts[edge] = edge_counts.get(edge, 0) + 1
        if edge_counts[edge] > 1:
            raise GraphWriteError("source-chain structural edge is duplicated")
    missing = tuple(edge for edge in expected_edges if edge not in edge_counts)
    return len(sources), len(revisions), len(chunks), missing


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


def research_run_payload_fingerprint(
    run: ResearchRun,
    expected_campaign_revision: int,
    owner_id: str,
) -> str:
    """Fingerprint Run intent while ignoring regenerated event timestamps only."""

    stable_run = {
        field.name: getattr(run, field.name)
        for field in fields(run)
        if field.name not in {"started_at", "finished_at", "provenance"}
    }
    stable_run["provenance"] = {
        field.name: getattr(run.provenance, field.name)
        for field in fields(run.provenance)
        if field.name != "occurred_at"
    }
    return payload_fingerprint("record_research_run", stable_run, expected_campaign_revision, owner_id)


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
        "capture_evidence",
        "record_research_run",
        "save_idea_brief",
        "capture_person",
        "capture_organization",
        "append_claim",
        "link_entities",
        "save_relation_assertion",
        "save_research_report",
        "record_decision",
        "record_correction",
        "confirm_person_merge",
    })

    def __init__(self, owner_id: str) -> None:
        self.owner_id = _required_text(owner_id, "owner_id")
        self._nodes: dict[str, Any] = {}
        self._node_history: dict[str, list[Any]] = {}
        self._idea_briefs: dict[str, IdeaBriefVersion] = {}
        self._idea_brief_ids_by_root: dict[str, list[str]] = {}
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
        if isinstance(node, RelationAssertion):
            raise GraphWriteError("RelationAssertion must be saved with save_relation_assertion")
        if isinstance(node, Evidence) and node.content_chunk_id is not None:
            raise GraphWriteError("source-grounded Evidence must be saved with capture_evidence")
        fingerprint = payload_fingerprint(operation, node, expected_revision, self.owner_id)
        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            if node_id in self._idea_briefs:
                raise NodeAlreadyExistsError("node id is already registered as an Idea brief")
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
            if any(node_id in self._nodes or node_id in self._idea_briefs for node_id in node_ids):
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
            if any(node_id in self._nodes or node_id in self._idea_briefs for node_id in node_ids):
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

    def capture_evidence(self, claim_id: str, content_chunk_id: str, *, polarity: EvidencePolarity | str | None = None,
                         confidence: float = 1.0, egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY,
                         idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        operation = self._validate_command("capture_evidence", actor, idempotency_key)
        try:
            polarity = EvidencePolarity.SUPPORTS if polarity is None else EvidencePolarity(polarity)
            policy = EgressPolicy(egress_policy)
            claim_id = _required_text(claim_id, "claim_id")
            content_chunk_id = _required_text(content_chunk_id, "content_chunk_id")
        except (ValueError, TypeError) as error:
            raise GraphWriteError("capture_evidence arguments are invalid") from error
        fingerprint = payload_fingerprint(operation, claim_id, content_chunk_id, polarity, confidence, policy, self.owner_id)
        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            claim, chunk = self._nodes.get(claim_id), self._nodes.get(content_chunk_id)
            if not isinstance(claim, Claim) or claim.owner_id != self.owner_id or claim.status is not Status.ACTIVE:
                raise GraphWriteNotFoundError("claim does not exist")
            if not isinstance(chunk, ContentChunk) or chunk.owner_id != self.owner_id or chunk.status is not Status.ACTIVE:
                raise GraphWriteNotFoundError("content chunk does not exist")
            revision = self._nodes.get(chunk.source_revision_id)
            if not isinstance(revision, SourceRevision) or revision.owner_id != self.owner_id or revision.status is not Status.ACTIVE:
                raise GraphWriteNotFoundError("content chunk does not exist")
            required_edge = (revision.id, "HAS_CHUNK", chunk.id)
            if self._structural_edges.count(required_edge) != 1:
                raise GraphWriteError("content chunk source lineage is invalid")
            evidence_id = f"evidence-{sha256((self.owner_id + ':' + idempotency_key).encode()).hexdigest()[:24]}"
            evidence = Evidence(
                owner_id=self.owner_id, id=evidence_id, material_id=None, claim_id=claim.id,
                source_revision_id=revision.id, content_chunk_id=chunk.id, excerpt="",
                locator=f"chars:{chunk.char_start}-{chunk.char_end}", char_start=chunk.char_start,
                char_end=chunk.char_end, polarity=polarity, confidence=confidence,
                content_hash=chunk.text_hash, egress_policy=policy,
            )
            receipt = WriteReceipt(operation, evidence.id, NodeType.EVIDENCE.value, 1, idempotency_key)
            audit_length, edge_length = len(self._audit), len(self._structural_edges)
            try:
                if evidence.id in self._nodes:
                    raise NodeAlreadyExistsError("evidence id is already registered")
                self._nodes[evidence.id] = evidence
                self._node_history[evidence.id] = [evidence]
                self._structural_edges.append((evidence.id, EvidenceEdgeType.EVIDENCE_FROM.value, chunk.id))
                self._append_audit(receipt, actor, fingerprint)
            except Exception:
                self._nodes.pop(evidence.id, None)
                self._node_history.pop(evidence.id, None)
                del self._structural_edges[edge_length:]
                del self._audit[audit_length:]
                raise
            self._idempotency[idempotency_key] = (fingerprint, receipt)
            return receipt

    def preview_source_chain_repair(self) -> SourceChainRepairPlan:
        """Preflight every local Source chain and report missing v2 edges."""

        with self._lock:
            sources, revisions, chunks, missing = _source_chain_repair_plan(
                self.owner_id, self._nodes, self._structural_edges,
            )
            return SourceChainRepairPlan(self.owner_id, sources, revisions, chunks, missing)

    def apply_source_chain_repair(self, *, actor: str = "local-owner") -> SourceChainRepairPlan:
        """Add only validated missing source-chain edges, with one audit event."""

        actor = _required_text(actor, "actor")
        with self._lock:
            source_count, revision_count, chunk_count, missing = _source_chain_repair_plan(
                self.owner_id, self._nodes, self._structural_edges,
            )
            if not missing:
                return SourceChainRepairPlan(self.owner_id, source_count, revision_count, chunk_count, ())

            fingerprint = payload_fingerprint("repair_source_chain_edges", self.owner_id, missing)
            audit_key = f"source-chain-repair:{fingerprint[:32]}"
            prior_edges = list(self._structural_edges)
            prior_audit = len(self._audit)
            try:
                self._structural_edges.extend(missing)
                if not any(event.idempotency_key == audit_key for event in self._audit):
                    self._append_audit(
                        WriteReceipt("repair_source_chain_edges", self.owner_id, "source_chain", 0, audit_key),
                        actor,
                        fingerprint,
                    )
            except Exception:
                self._structural_edges = prior_edges
                del self._audit[prior_audit:]
                raise
            return SourceChainRepairPlan(
                self.owner_id, source_count, revision_count, chunk_count, missing, missing,
            )

    def record_research_run(
        self,
        run: ResearchRun,
        *,
        expected_campaign_revision: int,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        """Persist a terminal Run and consume one Campaign trial atomically."""

        operation = self._validate_command("record_research_run", actor, idempotency_key)
        if not isinstance(run, ResearchRun):
            raise GraphWriteError("record_research_run requires a ResearchRun")
        if (
            not isinstance(expected_campaign_revision, int)
            or isinstance(expected_campaign_revision, bool)
            or expected_campaign_revision < 0
        ):
            raise RevisionConflictError("expected campaign revision must be a non-negative integer")
        fingerprint = research_run_payload_fingerprint(run, expected_campaign_revision, self.owner_id)

        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            campaign = self._nodes.get(run.campaign_id)
            if campaign is None:
                raise GraphWriteNotFoundError("research campaign does not exist")
            if not isinstance(campaign, ResearchCampaign):
                raise GraphWriteError("research run campaign has an invalid type")
            if campaign.owner_id != self.owner_id or run.owner_id != self.owner_id:
                raise GraphWriteError("research run and campaign must belong to the local owner")
            if self._revision(campaign) != expected_campaign_revision:
                raise RevisionConflictError("expected campaign revision does not match current revision")
            if type(run.authorization_revision) is not int or run.authorization_revision < 1:
                raise GraphWriteError("research run authorization revision must be a positive integer")
            if run.status not in {Status.COMPLETED, Status.PARTIAL, Status.FAILED, Status.CANCELLED}:
                raise GraphWriteError("only terminal research runs can be recorded")

            now = datetime.now(timezone.utc)
            try:
                from .founder_graph_research_run import validate_research_run_timing

                validate_research_run_timing(run, campaign, at=now)
                registry = CampaignAuthorizationRegistry.from_campaign_history(self._node_history[campaign.id])
                validate_run_campaign_reference(
                    run,
                    campaign,
                    campaign.authorization_snapshot,
                    authorization_registry=registry,
                    at=now,
                )
                if not campaign.can_start_run(at=now):
                    raise DomainValidationError("campaign is not authorized for another run")
                updated_campaign = campaign.register_run(at=now)
            except DomainValidationError:
                raise GraphWriteError("research campaign authorization or Run timing is invalid") from None

            if run.id in self._nodes or run.id in self._idea_briefs:
                raise NodeAlreadyExistsError("research run id is already registered")

            receipt = WriteReceipt(
                operation,
                run.id,
                NodeType.RESEARCH_RUN.value,
                self._revision(run),
                idempotency_key,
            )
            previous_campaign_history = list(self._node_history[campaign.id])
            previous_audit_count = len(self._audit)
            previous_edge_count = len(self._structural_edges)
            self._nodes[campaign.id] = updated_campaign
            self._node_history[campaign.id].append(updated_campaign)
            self._nodes[run.id] = run
            self._node_history[run.id] = [run]
            self._structural_edges.append((campaign.id, RelationType.HAS_RUN.value, run.id))
            try:
                self._append_audit(receipt, actor, fingerprint)
            except Exception:
                self._nodes[campaign.id] = campaign
                self._node_history[campaign.id] = previous_campaign_history
                self._nodes.pop(run.id, None)
                self._node_history.pop(run.id, None)
                del self._structural_edges[previous_edge_count:]
                del self._audit[previous_audit_count:]
                raise
            self._idempotency[idempotency_key] = (fingerprint, receipt)
            return receipt

    def save_idea_brief(
        self,
        brief: IdeaBriefVersion,
        *,
        expected_latest_revision: int | None,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        """Save an immutable, owner-bound brief version in this memory adapter.

        This concrete-only method is intentionally absent from GraphWritePort
        until the persistent adapter implements the same command contract.
        """
        operation = self._validate_command("save_idea_brief", actor, idempotency_key)
        if not isinstance(brief, IdeaBriefVersion):
            raise GraphWriteError("save_idea_brief requires an IdeaBriefVersion")
        if brief.owner_id != self.owner_id:
            raise GraphWriteError("brief owner does not match the local owner")
        if expected_latest_revision is not None and (
            type(expected_latest_revision) is not int or expected_latest_revision < 1
        ):
            raise RevisionConflictError("expected latest brief revision must be a positive integer or None")
        # The general node fingerprint excludes created_at as transport time;
        # for a brief it bounds the accepted Run history and is part of intent.
        fingerprint = payload_fingerprint(
            operation, brief, brief.created_at, expected_latest_revision, self.owner_id
        )

        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay

            current_idea = self._resolve_current_idea_locked(brief.idea_lineage_root_id)
            if current_idea.id != brief.based_on_idea_id:
                raise GraphWriteError("brief must reference the exact current Idea revision")
            if current_idea.status in {Status.ARCHIVED, Status.SUPERSEDED, Status.RETRACTED}:
                raise GraphWriteError("brief cannot reference an archived or superseded Idea")

            lineage_ids = self._idea_brief_ids_by_root.get(brief.idea_lineage_root_id, [])
            latest = self._idea_briefs[lineage_ids[-1]] if lineage_ids else None
            actual_latest_revision = None if latest is None else latest.revision
            if expected_latest_revision != actual_latest_revision:
                raise RevisionConflictError("expected latest brief revision does not match the current version")
            if latest is None:
                if brief.revision != 1 or brief.supersedes_id is not None:
                    raise GraphWriteError("first brief version must start a new lineage at revision one")
            elif (
                brief.idea_lineage_root_id != latest.idea_lineage_root_id
                or brief.revision != latest.revision + 1
                or brief.supersedes_id != latest.id
            ):
                raise GraphWriteError("brief revision must extend the exact latest version")
            if brief.id in self._idea_briefs or brief.id in self._nodes:
                raise NodeAlreadyExistsError("idea brief id is already registered")

            self._validate_brief_research_locked(brief, current_idea)
            receipt = WriteReceipt(
                operation,
                brief.id,
                "idea_brief_version",
                brief.revision,
                idempotency_key,
            )
            lineage = self._idea_brief_ids_by_root.setdefault(brief.idea_lineage_root_id, [])
            audit_length = len(self._audit)
            try:
                self._idea_briefs[brief.id] = brief
                lineage.append(brief.id)
                self._append_audit(receipt, actor, fingerprint)
                self._idempotency[idempotency_key] = (fingerprint, receipt)
            except Exception:
                self._idea_briefs.pop(brief.id, None)
                if lineage and lineage[-1] == brief.id:
                    lineage.pop()
                if not lineage:
                    self._idea_brief_ids_by_root.pop(brief.idea_lineage_root_id, None)
                del self._audit[audit_length:]
                self._idempotency.pop(idempotency_key, None)
                raise
            return receipt

    def get_idea_brief(self, brief_id: str) -> IdeaBriefVersion | None:
        """Return one immutable brief value from this owner-bound adapter."""
        with self._lock:
            return self._idea_briefs.get(_required_text(brief_id, "brief_id"))

    def get_latest_idea_brief(self, idea_lineage_root_id: str) -> IdeaBriefVersion | None:
        """Resolve the authoritative newest brief for one Idea lineage."""
        with self._lock:
            lineage = self._idea_brief_ids_by_root.get(_required_text(idea_lineage_root_id, "idea_lineage_root_id"), ())
            return None if not lineage else self._idea_briefs[lineage[-1]]

    def save_relation_assertion(
        self,
        assertion: RelationAssertion,
        *,
        expected_family_revision: int | None,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        """Atomically save a formal assertion and its canonical structural refs.

        This memory-only method is intentionally absent from GraphWritePort
        until a persistent adapter can implement the same transaction contract.
        """
        operation = self._validate_command("save_relation_assertion", actor, idempotency_key)
        if not isinstance(assertion, RelationAssertion):
            raise GraphWriteError("save_relation_assertion requires a RelationAssertion")
        if assertion.owner_id != self.owner_id:
            raise GraphWriteError("relation assertion owner does not match the local owner")
        if assertion.status is RelationshipStatus.SUPERSEDED:
            raise GraphWriteError("a new relation assertion cannot start in superseded status")
        if expected_family_revision is not None and (
            type(expected_family_revision) is not int or expected_family_revision < 1
        ):
            raise RevisionConflictError("expected family revision must be a positive integer or None")
        intent = tuple(
            (field.name, getattr(assertion, field.name))
            for field in fields(assertion)
            if field.name != "valid_from"
        )
        fingerprint = payload_fingerprint(operation, intent, expected_family_revision, self.owner_id)

        with self._lock:
            replay = self._replay_or_raise(idempotency_key, fingerprint)
            if replay is not None:
                return replay
            if assertion.id in self._nodes or assertion.id in self._idea_briefs:
                raise NodeAlreadyExistsError("relation assertion id is already registered")

            endpoints = (assertion.source_id, assertion.target_id)
            resolved: dict[str, Any] = {}
            for node_id, declared_kind in (
                (assertion.source_id, assertion.source_kind),
                (assertion.target_id, assertion.target_kind),
            ):
                node = self._nodes.get(node_id)
                if node is None:
                    raise GraphWriteNotFoundError("relation assertion endpoint does not exist")
                if _node_type(node) is not declared_kind:
                    raise GraphWriteError("relation assertion endpoint type does not match its declaration")
                if getattr(node, "owner_id", None) != self.owner_id:
                    raise GraphWriteError("relation assertion endpoints must belong to the local owner")
                status = getattr(node, "status", None)
                if status in {
                    Status.ARCHIVED, Status.SUPERSEDED, Status.RETRACTED,
                    Status.EXPIRED, Status.CANCELLED, Status.REVOKED, Status.FAILED,
                }:
                    raise GraphWriteError("relation assertion endpoint is not current and active")
                if assertion.egress_policy is EgressPolicy.SHAREABLE and getattr(
                    node, "egress_policy", None
                ) is not EgressPolicy.SHAREABLE:
                    raise GraphWriteError("shareable relation assertion requires shareable endpoints")
                if any(
                    getattr(candidate, "owner_id", None) == self.owner_id
                    and getattr(candidate, "supersedes_id", None) == node_id
                    for candidate in self._nodes.values()
                ):
                    raise GraphWriteError("relation assertion endpoint has a superseding revision")
                resolved[node_id] = node
            for node_id in endpoints:
                node = resolved[node_id]
                if isinstance(node, Idea) and self._current_idea_revision_locked(node) is not node:
                    raise GraphWriteError("relation assertion must reference the current Idea revision")

            if not assertion.evidence_ids:
                raise GraphWriteError("formal relation assertion requires Evidence")
            for evidence_id in assertion.evidence_ids:
                evidence = self._nodes.get(evidence_id)
                if not isinstance(evidence, Evidence):
                    raise GraphWriteNotFoundError("relation assertion Evidence does not exist")
                if evidence.owner_id != self.owner_id:
                    raise GraphWriteError("relation assertion Evidence must belong to the local owner")
                if evidence.status is not Status.ACTIVE:
                    raise GraphWriteError("relation assertion Evidence must be active")
                if assertion.egress_policy is EgressPolicy.SHAREABLE and evidence.egress_policy is not EgressPolicy.SHAREABLE:
                    raise GraphWriteError("shareable relation assertion requires shareable Evidence")

            idea_nodes = tuple(node for node in resolved.values() if isinstance(node, Idea))
            if idea_nodes:
                based_on_idea = (
                    resolved[assertion.source_id]
                    if isinstance(resolved[assertion.source_id], Idea)
                    else resolved[assertion.target_id]
                )
                root_idea_id = self._idea_root_id_locked(based_on_idea)
                lineage = self._idea_brief_ids_by_root.get(root_idea_id, ())
                latest_brief = self._idea_briefs[lineage[-1]] if lineage else None
                if (
                    assertion.based_on_brief_id is None
                    or latest_brief is None
                    or assertion.based_on_brief_id != latest_brief.id
                    or latest_brief.based_on_idea_id != based_on_idea.id
                    or not latest_brief.research_run_ids
                ):
                    raise GraphWriteError("Idea relation requires the exact latest researched Brief")
                section = latest_brief.sections[assertion.based_on_brief_section_index]
                if not set(assertion.evidence_ids).issubset(section.evidence_ids):
                    raise GraphWriteError("relation Evidence must be cited by the selected Brief section")
                self._validate_brief_research_locked(latest_brief, based_on_idea)
            elif assertion.based_on_brief_id is not None:
                raise GraphWriteError("non-Idea relation cannot claim an Idea Brief reference")

            predecessor = None
            family_members = tuple(
                node for node in self._nodes.values()
                if isinstance(node, RelationAssertion)
                and node.owner_id == self.owner_id
                and node.assertion_family_id == assertion.assertion_family_id
            )
            family_revisions = tuple(sorted(node.revision for node in family_members))
            if family_revisions and family_revisions != tuple(range(1, family_revisions[-1] + 1)):
                raise GraphWriteError("relation assertion family history is ambiguous")
            actual_family_revision = family_revisions[-1] if family_revisions else None
            if expected_family_revision != actual_family_revision:
                raise RevisionConflictError("expected relation assertion family revision is stale")

            if assertion.supersedes_id is None:
                if family_members or assertion.revision != 1:
                    raise RevisionConflictError("new relation family must start at revision one")
            else:
                prior = self._nodes.get(assertion.supersedes_id)
                if not isinstance(prior, RelationAssertion) or prior.owner_id != self.owner_id:
                    raise GraphWriteNotFoundError("relation assertion predecessor is not owner-scoped")
                predecessor = prior
                successors = tuple(
                    node for node in self._nodes.values()
                    if isinstance(node, RelationAssertion)
                    and node.owner_id == self.owner_id
                    and node.supersedes_id == prior.id
                )
                if successors:
                    raise GraphWriteError("relation assertion predecessor already has a successor")
                if prior.assertion_family_id == assertion.assertion_family_id:
                    if prior.revision != actual_family_revision or assertion.revision != prior.revision + 1:
                        raise RevisionConflictError("same-family correction must extend the exact latest revision")
                    if (prior.source_id, prior.predicate, prior.target_id) != (
                        assertion.source_id, assertion.predicate, assertion.target_id
                    ):
                        raise GraphWriteError("same-family correction cannot change endpoints or predicate")
                elif family_members or assertion.revision != 1:
                    raise RevisionConflictError("changed relation family must start at revision one")
                elif (prior.source_id, prior.predicate, prior.target_id) == (
                    assertion.source_id, assertion.predicate, assertion.target_id
                ):
                    raise GraphWriteError("unchanged relation must remain in its existing family")

            try:
                structural_edges = relation_assertion_structural_edges(assertion)
            except DomainValidationError as error:
                raise GraphWriteError(str(error)) from error
            receipt = WriteReceipt(
                operation, assertion.id, NodeType.RELATION_ASSERTION.value, assertion.revision, idempotency_key,
            )
            audit_length = len(self._audit)
            edge_length = len(self._structural_edges)
            prior_history = list(self._node_history[predecessor.id]) if predecessor is not None else None
            if predecessor is not None and (not prior_history or prior_history[-1] != predecessor):
                raise GraphWriteError("relation assertion predecessor history is inconsistent")
            try:
                if predecessor is not None and predecessor.status is not RelationshipStatus.REJECTED:
                    self._nodes[predecessor.id] = replace(predecessor, status=RelationshipStatus.SUPERSEDED)
                    self._node_history[predecessor.id].append(self._nodes[predecessor.id])
                self._nodes[assertion.id] = assertion
                self._node_history[assertion.id] = [assertion]
                self._structural_edges.extend(structural_edges)
                self._append_audit(receipt, actor, fingerprint)
                self._idempotency[idempotency_key] = (fingerprint, receipt)
            except Exception:
                self._nodes.pop(assertion.id, None)
                self._node_history.pop(assertion.id, None)
                if predecessor is not None and prior_history is not None:
                    self._nodes[predecessor.id] = prior_history[-1]
                    self._node_history[predecessor.id] = prior_history
                del self._structural_edges[edge_length:]
                del self._audit[audit_length:]
                self._idempotency.pop(idempotency_key, None)
                raise
            return receipt

    def _idea_root_id_locked(self, idea: Idea) -> str:
        current = idea
        seen = {current.id}
        while current.supersedes_id is not None:
            parent = self._nodes.get(current.supersedes_id)
            if (
                not isinstance(parent, Idea)
                or parent.owner_id != self.owner_id
                or parent.id in seen
                or current.revision != parent.revision + 1
            ):
                raise GraphWriteError("Idea lineage is not authoritative")
            seen.add(parent.id)
            current = parent
        return current.id

    def _current_idea_revision_locked(self, idea: Idea) -> Idea:
        root_id = self._idea_root_id_locked(idea)
        return self._resolve_current_idea_locked(root_id)

    def _resolve_current_idea_locked(self, lineage_root_id: str) -> Idea:
        root = self._nodes.get(_required_text(lineage_root_id, "idea_lineage_root_id"))
        if not isinstance(root, Idea) or root.owner_id != self.owner_id or root.supersedes_id is not None:
            raise GraphWriteNotFoundError("brief Idea lineage root does not resolve to an owned root Idea")
        ideas_by_parent: dict[str, list[Idea]] = {}
        for node in self._nodes.values():
            if isinstance(node, Idea) and node.owner_id == self.owner_id and node.supersedes_id is not None:
                ideas_by_parent.setdefault(node.supersedes_id, []).append(node)
        current = root
        seen = {current.id}
        while True:
            children = ideas_by_parent.get(current.id, [])
            if len(children) > 1:
                raise GraphWriteError("Idea lineage has multiple competing revisions")
            if not children:
                return current
            child = children[0]
            if child.id in seen or child.revision != current.revision + 1:
                raise GraphWriteError("Idea lineage revision history is invalid")
            seen.add(child.id)
            current = child

    def _validate_brief_research_locked(self, brief: IdeaBriefVersion, idea: Idea) -> None:
        if not brief.research_run_ids:
            return
        runs: list[ResearchRun] = []
        campaigns_by_id: dict[str, tuple[ResearchCampaign, ...]] = {}
        for run_id in brief.research_run_ids:
            run = self._nodes.get(run_id)
            if not isinstance(run, ResearchRun) or run.owner_id != self.owner_id:
                raise GraphWriteError("researched brief references an unregistered owner-scoped Run")
            matching_edges = tuple(
                edge for edge in self._structural_edges
                if edge == (run.campaign_id, RelationType.HAS_RUN.value, run.id)
            )
            if len(matching_edges) != 1:
                raise GraphWriteError("researched brief Run must have exactly one registered HAS_RUN edge")
            receipt_entries = tuple(
                (key, stored_fingerprint, receipt)
                for key, (stored_fingerprint, receipt) in self._idempotency.items()
                if receipt.operation == "record_research_run"
                and receipt.target_id == run.id
                and receipt.target_type == NodeType.RESEARCH_RUN.value
                and receipt.revision == self._revision(run)
            )
            if len(receipt_entries) != 1:
                raise GraphWriteError("researched brief Run must have exactly one write receipt")
            receipt_key, stored_fingerprint, receipt = receipt_entries[0]
            if receipt.idempotency_key != receipt_key:
                raise GraphWriteError("researched brief Run receipt identity is inconsistent")
            audits = tuple(
                event for event in self._audit
                if event.operation == "record_research_run"
                and event.owner_id == self.owner_id
                and event.idempotency_key == receipt_key
                and event.target_id == run.id
                and event.target_type == NodeType.RESEARCH_RUN.value
                and event.payload_fingerprint == stored_fingerprint
            )
            if len(audits) != 1:
                raise GraphWriteError("researched brief Run must have exactly one matching audit record")
            campaign = self._nodes.get(run.campaign_id)
            history = self._node_history.get(run.campaign_id, ())
            if not isinstance(campaign, ResearchCampaign) or campaign.owner_id != self.owner_id or not history or not all(
                isinstance(item, ResearchCampaign) and item.owner_id == self.owner_id for item in history
            ):
                raise GraphWriteError("researched brief Run requires authoritative typed Campaign history")
            prior = campaigns_by_id.get(run.campaign_id)
            if prior is not None and prior != tuple(history):
                raise GraphWriteError("researched brief Campaign history is inconsistent")
            campaigns_by_id[run.campaign_id] = tuple(history)
            runs.append(run)

        try:
            from .founder_graph_historical_brief import (
                HistoricalResearchValidationError,
                validate_historical_researched_brief,
            )

            validate_historical_researched_brief(
                brief,
                idea,
                tuple(runs),
                tuple(campaign for history in campaigns_by_id.values() for campaign in history),
            )
        except HistoricalResearchValidationError:
            raise GraphWriteError("researched brief authorization history is not proven") from None

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
        if (
            relationship.relation is RelationType.SUPERSEDES
            and relationship.source_kind is NodeType.RELATION_ASSERTION
            and relationship.target_kind is NodeType.RELATION_ASSERTION
        ):
            raise GraphWriteError("RelationAssertion supersession must use save_relation_assertion")
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
            if (
                relationship.relation is RelationType.SUPERSEDES
                and isinstance(source, RelationAssertion)
                and isinstance(target, RelationAssertion)
            ):
                raise GraphWriteError("RelationAssertion supersession must use save_relation_assertion")
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
            if assertion.id in self._nodes or assertion.id in self._idea_briefs:
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

    def read_snapshot(self) -> GraphReadSnapshot:
        """Return all memory read inputs from one lock-held point in time."""
        with self._lock:
            latest_briefs = tuple(
                (root_id, self._idea_briefs[brief_ids[-1]])
                for root_id, brief_ids in self._idea_brief_ids_by_root.items()
                if brief_ids
            )
            return GraphReadSnapshot(
                nodes=tuple(self._nodes.values()),
                relations=tuple(self._relations.values()),
                structural_edges=tuple(self._structural_edges),
                idea_briefs=tuple(self._idea_briefs.values()),
                latest_idea_briefs=latest_briefs,
            )

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
