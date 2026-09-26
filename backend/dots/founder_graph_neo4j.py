"""Parameterized Neo4j gateway for the local Founder Graph.

The gateway intentionally exposes typed write methods only.  It accepts a
driver-like object so contract tests do not need a running database; the real
``neo4j.Driver`` is injected by the application composition root later.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Iterator, Mapping
from uuid import uuid4

from .founder_graph import (
    CampaignAuthorizationRegistry,
    ContentChunk,
    DomainValidationError,
    EgressPolicy,
    NodeType,
    Provenance,
    ReportVersion,
    RelationAssertion,
    RelationAssertionEdgeType,
    Relationship,
    RelationshipStatus,
    RelationType,
    ResearchRun,
    Source,
    SourceRevision,
    Status,
    build_content_chunks,
    validate_run_campaign_reference,
    validate_source_revision_history,
    _ALLOWED_RELATION_ENDPOINTS,
    relation_assertion_structural_edges,
)
from .founder_graph_write import (
    GraphWriteError,
    GraphWriteNotFoundError,
    IdempotencyConflictError,
    NodeAlreadyExistsError,
    RevisionConflictError,
    WriteReceipt,
    capture_idea_payload_fingerprint,
    capture_source_payload_fingerprint,
    validate_capture_source,
    payload_fingerprint,
    research_run_payload_fingerprint,
)
from .founder_graph_schema import SCHEMA_VERSION, migration_queries, rollback_queries
from .founder_graph_read import _FIELD_ALLOWLIST
from .founder_graph_neo4j_campaign import CampaignDecodeError, decode_persisted_research_campaign
from .founder_graph_neo4j_idea import IdeaDecodeError, decode_persisted_idea
from .founder_graph_neo4j_idea_brief import _decode_persisted_idea_brief, _serialize_persisted_idea_brief
from .founder_graph_neo4j_run import ResearchRunDecodeError, decode_persisted_research_run
from .founder_graph_research_run import validate_research_run_timing
from .idea_brief import IdeaBriefValidationError, IdeaBriefVersion
from .founder_graph_historical_brief import HistoricalResearchValidationError, validate_historical_researched_brief


class Neo4jGatewayError(GraphWriteError):
    """Base class for recoverable gateway failures."""


class Neo4jUnavailableError(Neo4jGatewayError):
    """The injected driver could not open or complete a session."""


class Neo4jQueryContractError(Neo4jGatewayError):
    """A gateway operation would require a query outside the static contract."""


@dataclass(frozen=True, slots=True)
class AcceptedIdeaBriefProof:
    """Minimal internal proof for a same-transaction relation assertion."""

    brief_id: str
    brief_revision: int
    section_index: int | None
    idea_root_ids: tuple[str, ...]
    idea_leaf_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


_LABEL_BY_NODE_TYPE: Mapping[NodeType, str] = MappingProxyType({
    node_type: "".join(part.capitalize() for part in node_type.value.split("_"))
    for node_type in NodeType
})
_RELATION_TYPE_BY_ENUM: Mapping[RelationType, str] = MappingProxyType({
    relation: relation.value for relation in RelationType
})


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _node_revision(node: Any) -> int:
    value = getattr(node, "aggregate_revision", getattr(node, "revision", 0))
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GraphWriteError("node revision must be a non-negative integer")
    return value


def _node_properties(node: Any) -> dict[str, Any]:
    node_type = node.node_type if isinstance(node.node_type, NodeType) else NodeType(node.node_type)
    payload = _json_value(node)
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Keep the persistent search projection aligned with the in-memory read
    # contract.  In particular, local-only ContentChunk text may stay in the
    # stored payload but must not become a searchable or browser-visible field
    # through the safe read adapter.
    fields_for_search = (
        {field_name: payload[field_name] for field_name in _FIELD_ALLOWLIST[node_type] if field_name in payload}
        if isinstance(payload, Mapping)
        else {"value": payload}
    )
    search_text = " ".join(str(item) for item in fields_for_search.values())
    status = getattr(node, "status", None)
    egress_policy = getattr(node, "egress_policy", None)
    properties = {
        "id": str(node.id),
        "owner_id": str(node.owner_id),
        "node_type": node_type.value,
        "status": status.value if isinstance(status, Enum) else (str(status) if status is not None else None),
        "egress_policy": egress_policy.value if isinstance(egress_policy, Enum) else (str(egress_policy) if egress_policy is not None else None),
        "revision": _node_revision(node),
        "payload_json": payload_json,
        "search_text": search_text[:16_000],
    }
    # Keep typed reference fields queryable without asking Neo4j to interpret
    # the opaque payload JSON.  These values are still supplied as parameters
    # through the map assignment below; they are not interpolated into Cypher.
    if node_type is NodeType.SOURCE:
        current_revision_id = getattr(node, "current_revision_id", None)
        if current_revision_id is not None:
            properties["current_revision_id"] = str(current_revision_id)
    elif node_type is NodeType.IDEA:
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
    elif node_type is NodeType.SOURCE_REVISION:
        properties["source_id"] = str(node.source_id)
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
    elif node_type is NodeType.CLAIM:
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
    elif node_type is NodeType.RELATION_ASSERTION:
        properties["assertion_family_id"] = str(node.assertion_family_id)
        if node.supersedes_id is not None:
            properties["supersedes_id"] = str(node.supersedes_id)
    return properties


def _single(result: Any) -> Any | None:
    single = getattr(result, "single", None)
    if callable(single):
        try:
            return single(strict=False)
        except TypeError:
            return single()
    try:
        return next(iter(result), None)
    except TypeError:
        return None


def _rows(result: Any) -> tuple[Any, ...]:
    """Return all records from a Neo4j/fake result without query coupling."""

    try:
        return tuple(result)
    except TypeError:
        value = _single(result)
        return () if value is None else (value,)


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


def _content_chunk_ids(value: Any) -> tuple[str, ...]:
    """Decode the opaque chunk-id list persisted on a capture audit."""

    if value is None:
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as error:
            raise GraphWriteError("capture audit content chunk ids are invalid") from error
    if not isinstance(value, (tuple, list)):
        raise GraphWriteError("capture audit content chunk ids are invalid")
    identifiers = tuple(item for item in value if isinstance(item, str) and item.strip())
    if len(identifiers) != len(value):
        raise GraphWriteError("capture audit content chunk ids are invalid")
    return identifiers


class Neo4jGraphGateway:
    """Owner-scoped, typed write and migration gateway.

    The injected driver is expected to implement the public Neo4j Python
    driver shape: ``session(database=...)`` returning a context manager whose
    ``execute_write`` / ``execute_read`` accepts a transaction callback.
    """

    def __init__(self, driver: Any, owner_id: str, *, database: str = "neo4j") -> None:
        if driver is None:
            raise Neo4jUnavailableError("a Neo4j driver is required")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise GraphWriteError("owner_id must be a non-empty string")
        if not isinstance(database, str) or not database.strip():
            raise GraphWriteError("database must be a non-empty string")
        self.driver = driver
        self.owner_id = owner_id.strip()
        self.database = database.strip()

    @classmethod
    def label_for(cls, node_type: NodeType | str) -> str:
        try:
            normalized = node_type if isinstance(node_type, NodeType) else NodeType(node_type)
            return _LABEL_BY_NODE_TYPE[normalized]
        except (KeyError, TypeError, ValueError) as error:
            raise Neo4jQueryContractError("node type is not in the static label allowlist") from error

    @classmethod
    def relation_type_for(cls, relation: RelationType | str) -> str:
        try:
            normalized = relation if isinstance(relation, RelationType) else RelationType(relation)
            return _RELATION_TYPE_BY_ENUM[normalized]
        except (KeyError, TypeError, ValueError) as error:
            raise Neo4jQueryContractError("relation type is not in the static relationship allowlist") from error

    @contextmanager
    def _session(self) -> Iterator[Any]:
        try:
            session = self.driver.session(database=self.database)
        except Exception as error:  # pragma: no cover - concrete driver failure
            raise Neo4jUnavailableError("Neo4j session is unavailable") from error
        try:
            yield session
        except GraphWriteError:
            raise
        except Exception as error:  # pragma: no cover - concrete driver failure
            raise Neo4jUnavailableError("Neo4j operation failed") from error
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _execute_write(session: Any, callback: Any) -> Any:
        execute = getattr(session, "execute_write", None)
        if callable(execute):
            return execute(callback)
        return callback(session)

    @staticmethod
    def _execute_read(session: Any, callback: Any) -> Any:
        execute = getattr(session, "execute_read", None)
        if callable(execute):
            return execute(callback)
        return callback(session)

    def _source_revision_rows(self, tx: Any, source_id: str) -> tuple[Any, ...]:
        """Fetch only the fields needed to validate one source history chain."""

        label = self.label_for(NodeType.SOURCE_REVISION)
        result = tx.run(
            f"MATCH (r:{label} {{source_id: $source_id}}) "
            "RETURN r.id AS id, r.owner_id AS owner_id, r.node_type AS node_type, "
            "r.source_id AS source_id, r.revision AS revision, "
            "r.supersedes_id AS supersedes_id ORDER BY r.revision ASC",
            source_id=source_id,
        )
        return _rows(result)

    def _campaign_authorization_registry_tx(self, tx: Any, campaign_id: str) -> CampaignAuthorizationRegistry:
        """Resolve a complete typed Campaign history inside the caller's transaction.

        In a write transaction the caller must already hold the owner-scoped
        Campaign lock. The current Campaign is returned separately from
        immutable prior states, so no revision is counted twice.
        """

        campaign_label = self.label_for(NodeType.RESEARCH_CAMPAIGN)
        current_record = _single(tx.run(
            f"MATCH (c:{campaign_label} {{id: $campaign_id, owner_id: $owner_id}}) "
            "RETURN c.id AS id, c.owner_id AS owner_id, c.node_type AS node_type, "
            "c.revision AS revision, c.payload_json AS payload_json",
            campaign_id=campaign_id,
            owner_id=self.owner_id,
        ))
        if current_record is None:
            raise GraphWriteNotFoundError("research campaign does not exist for the local owner")
        try:
            current = decode_persisted_research_campaign(current_record, owner_id=self.owner_id)
        except CampaignDecodeError:
            raise GraphWriteError("persisted campaign authorization is invalid") from None

        prior_records = _rows(tx.run(
            "MATCH (h:FounderGraphHistory {owner_id: $owner_id, target_id: $campaign_id}) "
            "RETURN h.target_id AS id, h.owner_id AS owner_id, $node_type AS node_type, "
            "h.revision AS revision, h.payload_json AS payload_json ORDER BY h.revision ASC",
            owner_id=self.owner_id,
            campaign_id=campaign_id,
            node_type=NodeType.RESEARCH_CAMPAIGN.value,
        ))
        prior_campaigns = []
        try:
            for record in prior_records:
                prior = decode_persisted_research_campaign(record, owner_id=self.owner_id)
                if prior.id != current.id or prior.aggregate_revision >= current.aggregate_revision:
                    raise CampaignDecodeError("persisted campaign history revision is invalid")
                prior_campaigns.append(prior)
        except CampaignDecodeError:
            raise GraphWriteError("persisted campaign history is invalid") from None

        campaigns = (*prior_campaigns, current)
        revisions = tuple(campaign.aggregate_revision for campaign in campaigns)
        if revisions != tuple(range(current.aggregate_revision + 1)):
            raise GraphWriteError("persisted campaign history is incomplete")
        try:
            return CampaignAuthorizationRegistry.from_campaign_history(campaigns)
        except DomainValidationError:
            raise GraphWriteError("persisted campaign history is invalid") from None

    def _store_prior_campaign_revision_tx(self, tx: Any, record: Any) -> None:
        """Store the exact typed Campaign state being superseded by a writer."""

        try:
            campaign = decode_persisted_research_campaign(record, owner_id=self.owner_id)
        except CampaignDecodeError:
            raise GraphWriteError("persisted campaign authorization is invalid") from None
        revision = _record_value(record, "revision")
        payload_json = _record_value(record, "payload_json")
        existing = _single(tx.run(
            "MATCH (h:FounderGraphHistory {owner_id: $owner_id, target_id: $target_id, revision: $revision}) "
            "RETURN h.id AS id",
            owner_id=self.owner_id,
            target_id=campaign.id,
            revision=revision,
        ))
        if existing is not None:
            raise GraphWriteError("persisted campaign history already contains the current revision")
        history_id = f"history_{sha256(f'{campaign.id}:{revision}'.encode()).hexdigest()[:32]}"
        tx.run(
            "CREATE (h:FounderGraphHistory {id: $history_id, owner_id: $owner_id, "
            "target_id: $target_id, revision: $revision, payload_json: $payload_json})",
            history_id=history_id,
            owner_id=self.owner_id,
            target_id=campaign.id,
            revision=revision,
            payload_json=payload_json,
        )

    def _lock_revisioned_node_tx(self, tx: Any, label: str, node_id: str) -> Any | None:
        """Lock an existing local Source/Campaign before reading its revision.

        The temporary property write acquires a Neo4j node write lock before
        the returned revision is read. REMOVE runs in the same statement; the
        lock itself is retained by Neo4j until the surrounding transaction
        commits or rolls back.
        """

        return _single(tx.run(
            f"MATCH (n:{label} {{id: $id, owner_id: $owner_id}}) "
            "SET n._dots_revision_write_lock = $lock_token "
            "REMOVE n._dots_revision_write_lock "
            "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
            "n.revision AS revision",
            id=node_id,
            owner_id=self.owner_id,
            lock_token=uuid4().hex,
        ))

    def _idea_record_tx(self, tx: Any, idea_id: str) -> Any | None:
        label = self.label_for(NodeType.IDEA)
        return _single(tx.run(
            f"MATCH (i:{label} {{id: $id, owner_id: $owner_id}}) "
            "RETURN i.id AS id, i.owner_id AS owner_id, i.node_type AS node_type, "
            "i.revision AS revision, i.payload_json AS payload_json",
            id=idea_id, owner_id=self.owner_id,
        ))

    def _decode_idea_record(self, record: Any, *, expected_id: str | None = None) -> Any:
        try:
            return decode_persisted_idea({
                key: _record_value(record, key)
                for key in ("id", "owner_id", "node_type", "revision", "payload_json")
            }, owner_id=self.owner_id, expected_id=expected_id)
        except IdeaDecodeError:
            raise GraphWriteError("persisted Idea authorization state is invalid") from None

    def _idea_children_tx(self, tx: Any, parent_id: str) -> tuple[Any, ...]:
        label = self.label_for(NodeType.IDEA)
        rows = _rows(tx.run(
            f"MATCH (i:{label} {{owner_id: $owner_id}}) "
            "RETURN i.id AS id, i.owner_id AS owner_id, i.node_type AS node_type, "
            "i.revision AS revision, i.supersedes_id AS supersedes_id, i.payload_json AS payload_json",
            owner_id=self.owner_id,
        ))
        children = []
        for row in rows:
            idea = self._decode_idea_record(row)
            scalar_parent = _record_value(row, "supersedes_id")
            if scalar_parent is not None and scalar_parent != idea.supersedes_id:
                raise GraphWriteError("persisted Idea lineage is invalid")
            if idea.supersedes_id == parent_id:
                children.append(idea)
        return tuple(children)

    def _idea_chain_tx(self, tx: Any, root_id: str) -> tuple[Any, ...]:
        root_record = self._idea_record_tx(tx, root_id)
        if root_record is None:
            raise GraphWriteNotFoundError("Idea lineage root does not exist for the local owner")
        root = self._decode_idea_record(root_record, expected_id=root_id)
        if root.supersedes_id is not None:
            raise GraphWriteError("Idea lineage root is invalid")
        chain = [root]
        seen = {root.id}
        while True:
            children = self._idea_children_tx(tx, chain[-1].id)
            if len(children) > 1:
                raise GraphWriteError("Idea lineage has multiple competing revisions")
            if not children:
                return tuple(chain)
            child = children[0]
            if child.id in seen or child.revision != chain[-1].revision + 1:
                raise GraphWriteError("Idea lineage revision history is invalid")
            seen.add(child.id)
            chain.append(child)

    def _lock_idea_tx(self, tx: Any, idea_id: str) -> Any:
        label = self.label_for(NodeType.IDEA)
        locked = _single(tx.run(
            f"MATCH (i:{label} {{id: $id, owner_id: $owner_id}}) "
            "SET i._dots_idea_write_lock = $lock_token REMOVE i._dots_idea_write_lock "
            "RETURN i.id AS id, i.owner_id AS owner_id, i.node_type AS node_type, i.revision AS revision",
            id=idea_id, owner_id=self.owner_id, lock_token=uuid4().hex,
        ))
        if locked is None:
            raise GraphWriteNotFoundError("Idea does not exist for the local owner")
        return locked

    def _idea_root_for_tx(self, tx: Any, idea_id: str) -> str:
        current = self._decode_idea_record(self._idea_record_tx(tx, idea_id), expected_id=idea_id)
        seen = {current.id}
        while current.supersedes_id is not None:
            parent_id = current.supersedes_id
            if parent_id in seen:
                raise GraphWriteError("Idea lineage contains a cycle")
            parent = self._decode_idea_record(self._idea_record_tx(tx, parent_id), expected_id=parent_id)
            if current.revision != parent.revision + 1:
                raise GraphWriteError("Idea lineage revision history is invalid")
            current = parent
            seen.add(current.id)
        return current.id

    def _lock_idea_successor_tx(self, tx: Any, idea: Any) -> tuple[Any, ...] | None:
        if idea.supersedes_id is None:
            return None
        root_id = self._idea_root_for_tx(tx, idea.supersedes_id)
        self._lock_idea_tx(tx, root_id)
        chain = self._idea_chain_tx(tx, root_id)
        parent = chain[-1]
        if parent.id != idea.supersedes_id or idea.revision != parent.revision + 1:
            raise RevisionConflictError("Idea correction must extend the current leaf revision")
        if parent.id != root_id:
            self._lock_idea_tx(tx, parent.id)
        confirmed = self._idea_chain_tx(tx, root_id)
        if confirmed[-1].id != parent.id:
            raise RevisionConflictError("Idea correction lost the current leaf revision")
        return confirmed

    def _lock_current_idea_tx(self, tx: Any, root_id: str) -> tuple[Any, ...]:
        self._lock_idea_tx(tx, root_id)
        chain = self._idea_chain_tx(tx, root_id)
        leaf = chain[-1]
        if leaf.id != root_id:
            self._lock_idea_tx(tx, leaf.id)
        confirmed = self._idea_chain_tx(tx, root_id)
        if tuple(item.id for item in confirmed) != tuple(item.id for item in chain):
            raise RevisionConflictError("Idea lineage changed during brief validation")
        return confirmed

    def _idea_brief_replay_tx(self, tx: Any, *, key: str, fingerprint: str, brief_id: str,
                              expected_revision: int) -> WriteReceipt | None:
        record = _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $key}) "
            "RETURN a.operation AS operation, a.payload_fingerprint AS payload_fingerprint, "
            "a.target_id AS target_id, a.target_type AS target_type, a.revision AS revision",
            owner_id=self.owner_id, key=key,
        ))
        return self._idea_brief_receipt_from_record(
            record, key=key, fingerprint=fingerprint, brief_id=brief_id,
            expected_revision=expected_revision,
        )

    def _idea_brief_audit_tx(self, tx: Any, key: str) -> Any | None:
        return _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $key}) "
            "RETURN a.operation AS operation, a.payload_fingerprint AS payload_fingerprint, "
            "a.target_id AS target_id, a.target_type AS target_type, a.revision AS revision",
            owner_id=self.owner_id, key=key,
        ))

    def _recover_idea_brief_receipt(self, brief: IdeaBriefVersion, key: str, fingerprint: str, failure: Neo4jUnavailableError) -> WriteReceipt:
        try:
            with self._session() as session:
                row = self._execute_read(session, lambda tx: self._idea_brief_audit_tx(tx, key))
        except Exception:
            raise failure from None
        replay = self._idea_brief_receipt_from_record(
            row, key=key, fingerprint=fingerprint, brief_id=brief.id,
            expected_revision=brief.revision,
        )
        if replay is None:
            raise failure from None
        return replay

    def _idea_brief_receipt_from_record(
        self, record: Any | None, *, key: str, fingerprint: str, brief_id: str,
        expected_revision: int,
    ) -> WriteReceipt | None:
        if record is None:
            return None
        if (
            _record_value(record, "operation") != "save_idea_brief"
            or _record_value(record, "payload_fingerprint") != fingerprint
            or _record_value(record, "target_id") != brief_id
            or _record_value(record, "target_type") != "idea_brief_version"
        ):
            raise IdempotencyConflictError("idempotency key was reused with a different payload")
        revision = _record_value(record, "revision")
        if type(revision) is not int:
            raise GraphWriteError("persisted IdeaBrief receipt is invalid")
        if revision != expected_revision:
            raise IdempotencyConflictError("idempotency key was reused with a different payload")
        return WriteReceipt("save_idea_brief", brief_id, "idea_brief_version", revision, key, replayed=True)

    def _put_node_replay_tx(
        self, tx: Any, *, operation: str, idempotency_key: str, fingerprint: str,
    ) -> WriteReceipt | None:
        replay = _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $idempotency_key}) "
            "RETURN a.payload_fingerprint AS payload_fingerprint, a.target_id AS target_id, "
            "a.target_type AS target_type, a.revision AS revision",
            owner_id=self.owner_id,
            idempotency_key=idempotency_key,
        ))
        if replay is None:
            return None
        prior = _record_value(replay, "payload_fingerprint")
        if prior != fingerprint:
            raise IdempotencyConflictError("idempotency key was reused with a different payload")
        return WriteReceipt(
            operation,
            _record_value(replay, "target_id"),
            _record_value(replay, "target_type"),
            _record_value(replay, "revision", 0),
            idempotency_key,
            replayed=True,
        )

    def _report_node_rows(self, tx: Any, node_ids: set[str]) -> dict[str, Any]:
        """Resolve report references inside the same owner-scoped transaction."""

        if not node_ids:
            return {}
        rows = _rows(tx.run(
            "MATCH (n) WHERE n.id IN $node_ids AND n.owner_id = $owner_id "
            "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
            "n.payload_json AS payload_json",
            node_ids=sorted(node_ids),
            owner_id=self.owner_id,
        ))
        resolved: dict[str, Any] = {}
        for row in rows:
            identifier = _record_value(row, "id")
            if not isinstance(identifier, str) or identifier in resolved:
                raise GraphWriteError("report reference query returned an invalid node")
            if _record_value(row, "owner_id") != self.owner_id:
                raise GraphWriteError("report reference owner does not match the local owner")
            resolved[identifier] = row
        missing = node_ids.difference(resolved)
        if missing:
            raise GraphWriteNotFoundError(f"report reference does not exist: {sorted(missing)[0]}")
        return resolved

    @staticmethod
    def _report_payload(row: Any) -> Mapping[str, Any]:
        raw = _record_value(row, "payload_json")
        if not isinstance(raw, str) or not raw.strip():
            raise GraphWriteError("report reference payload is missing")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise GraphWriteError("report reference payload is invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise GraphWriteError("report reference payload must be an object")
        return payload

    def _validate_report_references_tx(self, tx: Any, node: Any) -> None:
        """Mirror the report reference boundary before a persistent CREATE."""

        if not isinstance(node, ReportVersion):
            return
        section_claim_ids = {
            claim_id
            for section in node.sections
            for claim_id in section.claim_ids
        }
        section_evidence_ids = {
            evidence_id
            for section in node.sections
            for evidence_id in section.evidence_ids
        }
        report_evidence_ids = set(node.evidence_ids)
        run_ids = set(node.run_ids)
        all_ids = run_ids | section_claim_ids | section_evidence_ids | report_evidence_ids
        if node.parent_id is not None:
            all_ids.add(node.parent_id)
        rows = self._report_node_rows(tx, all_ids)

        # Campaigns are reached through each persisted run's payload.  Resolve
        # those IDs in a second owner-scoped query instead of interpolating
        # relationship paths or trusting a caller-supplied campaign list.
        campaign_ids: set[str] = set()
        for run_id in sorted(run_ids):
            run_row = rows[run_id]
            if _record_value(run_row, "node_type") != NodeType.RESEARCH_RUN.value:
                raise GraphWriteError(f"report reference has an invalid node type: {run_id}")
            run_payload = self._report_payload(run_row)
            campaign_id = run_payload.get("campaign_id")
            if not isinstance(campaign_id, str) or not campaign_id:
                raise GraphWriteError("report run campaign reference is missing")
            campaign_ids.add(campaign_id)
        rows.update(self._report_node_rows(tx, campaign_ids.difference(rows)))

        def require(identifier: str, expected: NodeType) -> Mapping[str, Any]:
            row = rows.get(identifier)
            if row is None:
                raise GraphWriteNotFoundError(f"report reference does not exist: {identifier}")
            actual = _record_value(row, "node_type")
            if actual != expected.value:
                raise GraphWriteError(f"report reference has an invalid node type: {identifier}")
            payload = self._report_payload(row)
            if payload.get("owner_id") != self.owner_id:
                raise GraphWriteError("report reference owner does not match the local owner")
            return payload

        if node.parent_id is not None:
            require(node.parent_id, NodeType.REPORT_VERSION)

        campaigns: dict[str, Mapping[str, Any]] = {}
        for run_id in sorted(run_ids):
            run = require(run_id, NodeType.RESEARCH_RUN)
            campaign_id = run.get("campaign_id")
            if not isinstance(campaign_id, str) or not campaign_id:
                raise GraphWriteError("report run campaign reference is missing")
            campaign = campaigns.setdefault(campaign_id, require(campaign_id, NodeType.RESEARCH_CAMPAIGN))
            if campaign.get("authorized") is not True:
                raise GraphWriteError("report run campaign is not authorized")
            if run.get("authorization_snapshot_id") != campaign.get("authorization_snapshot_id"):
                raise GraphWriteError("report run authorization snapshot does not match campaign")
            if run.get("authorization_revision") != campaign.get("authorization_revision"):
                raise GraphWriteError("report run authorization revision does not match campaign")
            expires_at = campaign.get("expires_at")
            if not isinstance(expires_at, str) or not expires_at.strip():
                raise GraphWriteError("report run campaign expiration is missing")
            try:
                expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise GraphWriteError("report run campaign expiration is invalid") from error
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expires:
                raise GraphWriteError("report run campaign authorization is expired")

        for identifier in sorted(report_evidence_ids | section_evidence_ids):
            require(identifier, NodeType.EVIDENCE)
        for identifier in sorted(section_claim_ids):
            require(identifier, NodeType.CLAIM)
        for section in node.sections:
            claim_ids = set(section.claim_ids)
            for evidence_id in section.evidence_ids:
                evidence = require(evidence_id, NodeType.EVIDENCE)
                if evidence.get("claim_id") not in claim_ids:
                    raise GraphWriteError("report section evidence must identify a referenced claim")

    def _validate_source_reference_tx(self, tx: Any, node: Any, node_type: NodeType) -> None:
        """Validate source references before any current-node mutation.

        The in-memory write service performs this check while holding its
        lock.  The Neo4j equivalent runs all reads in the same transaction as
        the eventual CREATE/SET, so a direct gateway caller cannot bypass the
        owner and append-only source history contract.
        """

        if node_type is NodeType.SOURCE_REVISION:
            source_id = getattr(node, "source_id", None)
            if not isinstance(source_id, str) or not source_id:
                raise GraphWriteError("source revision requires a source_id")
            source_label = self.label_for(NodeType.SOURCE)
            source = _single(tx.run(
                f"MATCH (s:{source_label} {{id: $source_id}}) "
                "RETURN s.owner_id AS owner_id, s.node_type AS node_type",
                source_id=source_id,
            ))
            if source is None:
                raise GraphWriteNotFoundError(f"source does not exist: {source_id}")
            source_owner = _record_value(source, "owner_id")
            if source_owner != self.owner_id:
                raise GraphWriteError("source revision must reference the local Source")

            prior = self._source_revision_rows(tx, source_id)
            for record in prior:
                if _record_value(record, "owner_id") != self.owner_id:
                    raise GraphWriteError("source revision must reference the local Source")
                if _record_value(record, "source_id", source_id) != source_id:
                    raise GraphWriteError("source revision source_id does not match source")
            revisions: list[int] = []
            for record in prior:
                record_revision = _record_value(record, "revision")
                if not isinstance(record_revision, int) or isinstance(record_revision, bool) or record_revision < 1:
                    raise GraphWriteError("source revision must be a positive integer")
                revisions.append(record_revision)
            revision = getattr(node, "revision", None)
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise GraphWriteError("source revision must be a positive integer")
            if revision in revisions:
                raise GraphWriteError("source revision number is already registered")
            expected = max(revisions, default=0) + 1
            if revision != expected:
                raise GraphWriteError("source revision numbers must be appended contiguously")
            supersedes_id = getattr(node, "supersedes_id", None)
            if revision == 1 and supersedes_id is not None:
                raise GraphWriteError("first source revision cannot supersede another revision")
            if revision > 1:
                latest = max(prior, key=lambda record: _record_value(record, "revision", 0), default=None)
                if latest is None or supersedes_id != _record_value(latest, "id"):
                    raise GraphWriteError("source revision must supersede the prior revision")
            return

        if node_type is not NodeType.SOURCE or getattr(node, "current_revision_id", None) is None:
            return

        source_id = getattr(node, "id", None)
        current_revision_id = getattr(node, "current_revision_id", None)
        if not isinstance(source_id, str) or not source_id:
            raise GraphWriteError("source requires an id")
        prior = self._source_revision_rows(tx, source_id)
        if not prior:
            raise GraphWriteError("source history requires at least one revision")

        by_id: dict[str, Any] = {}
        by_number: dict[int, Any] = {}
        for record in prior:
            if _record_value(record, "owner_id") != self.owner_id:
                raise GraphWriteError("source revision owner does not match source")
            if _record_value(record, "source_id", source_id) != source_id:
                raise GraphWriteError("source revision source_id does not match source")
            revision_id = _record_value(record, "id")
            revision_number = _record_value(record, "revision")
            if revision_id in by_id:
                raise GraphWriteError("source revision history contains duplicate revision id")
            if revision_number in by_number:
                raise GraphWriteError("source revision history contains duplicate revision number")
            if not isinstance(revision_number, int) or isinstance(revision_number, bool) or revision_number < 1:
                raise GraphWriteError("source revision must be a positive integer")
            by_id[revision_id] = record
            by_number[revision_number] = record

        ordered = sorted(by_number.items(), key=lambda item: item[0])
        for expected_revision, (revision_number, record) in enumerate(ordered, start=1):
            if revision_number != expected_revision:
                raise GraphWriteError("source revision numbers must be monotonic and contiguous")
            supersedes_id = _record_value(record, "supersedes_id")
            if expected_revision == 1:
                if supersedes_id is not None:
                    raise GraphWriteError("first source revision cannot supersede another revision")
                continue
            previous_id = _record_value(ordered[expected_revision - 2][1], "id")
            if supersedes_id != previous_id:
                raise GraphWriteError("source revision supersedes chain is not monotonic")

        current = by_id.get(current_revision_id)
        if current is None:
            raise GraphWriteError("source current_revision_id does not resolve to a revision")
        if _record_value(current, "revision") != ordered[-1][0]:
            raise GraphWriteError("source current revision must be the latest revision")

    def migrate(self, *, current_version: int = 0, target_version: int = SCHEMA_VERSION) -> int:
        queries = migration_queries(current_version, target_version)
        with self._session() as session:
            try:
                for query in queries:
                    result = session.run(query)
                    consume = getattr(result, "consume", None)
                    if callable(consume):
                        consume()
            except Exception as error:  # pragma: no cover - concrete driver failure
                raise Neo4jUnavailableError("Neo4j schema migration failed") from error
        return len(queries)

    def rollback(self, *, current_version: int = SCHEMA_VERSION, target_version: int = 1) -> int:
        """Remove only schema-v2 constraints and indexes, never graph data."""

        queries = rollback_queries(current_version, target_version)
        with self._session() as session:
            try:
                for query in queries:
                    result = session.run(query)
                    consume = getattr(result, "consume", None)
                    if callable(consume):
                        consume()
            except Exception as error:  # pragma: no cover - concrete driver failure
                raise Neo4jUnavailableError("Neo4j schema rollback failed") from error
        return len(queries)

    def health(self) -> bool:
        with self._session() as session:
            try:
                _single(session.run("RETURN 1 AS ok"))
                return True
            except Exception as error:  # pragma: no cover - concrete driver failure
                raise Neo4jUnavailableError("Neo4j health check failed") from error

    def fetch_node_record(self, node_id: str) -> Mapping[str, Any] | None:
        """Fetch the bounded persisted projection used by command adapters.

        The gateway returns the opaque domain payload only after applying the
        owner predicate in Cypher.  Callers must still validate the node type
        before reconstructing any domain value.
        """

        if not isinstance(node_id, str) or not node_id.strip():
            raise GraphWriteError("node_id must be a non-empty string")
        with self._session() as session:
            result = self._execute_read(
                session,
                lambda tx: _single(tx.run(
                    "MATCH (n {id: $node_id, owner_id: $owner_id}) "
                    "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
                    "n.revision AS revision, n.status AS status, n.assertion_family_id AS assertion_family_id, "
                    "n.supersedes_id AS supersedes_id, n.payload_json AS payload_json LIMIT 1",
                    node_id=node_id.strip(),
                    owner_id=self.owner_id,
                )),
            )
            row = result
        if row is None:
            return None
        values = {
            "id": _record_value(row, "id"),
            "owner_id": _record_value(row, "owner_id"),
            "node_type": _record_value(row, "node_type"),
            "revision": _record_value(row, "revision", 0),
            "status": _record_value(row, "status"),
            "assertion_family_id": _record_value(row, "assertion_family_id"),
            "supersedes_id": _record_value(row, "supersedes_id"),
            "payload_json": _record_value(row, "payload_json"),
        }
        if values["owner_id"] != self.owner_id:
            return None
        if not isinstance(values["id"], str) or not isinstance(values["node_type"], str):
            raise GraphWriteError("Neo4j node record is missing its identity")
        if not isinstance(values["payload_json"], str) or not values["payload_json"].strip():
            raise GraphWriteError("Neo4j node payload is missing")
        return values

    def put_node(
        self,
        node: Any,
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
        operation: str = "put_node",
        actor: str = "local-owner",
    ) -> WriteReceipt:
        if getattr(node, "owner_id", None) != self.owner_id:
            raise GraphWriteError("node owner does not match the local owner")
        node_type = node.node_type if isinstance(node.node_type, NodeType) else NodeType(node.node_type)
        label = self.label_for(node_type)
        fingerprint = payload_fingerprint(operation, node, expected_revision, self.owner_id)
        with self._session() as session:
            return self._execute_write(
                session,
                lambda tx: self._put_node_tx(tx, node, node_type, label, idempotency_key, expected_revision, operation, actor, fingerprint),
            )

    def capture_idea(
        self,
        idea: Any,
        source: Source,
        source_revision: SourceRevision,
        *,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        """Persist an idea and its source chain in one Neo4j transaction."""

        if not isinstance(source, Source) or not isinstance(source_revision, SourceRevision):
            raise GraphWriteError("capture_idea requires an Idea, Source, and SourceRevision")
        try:
            idea_type = idea.node_type if isinstance(idea.node_type, NodeType) else NodeType(idea.node_type)
        except (AttributeError, TypeError, ValueError) as error:
            raise GraphWriteError("capture_idea requires an Idea node") from error
        if idea_type is not NodeType.IDEA:
            raise GraphWriteError("capture_idea requires an Idea node")
        if getattr(idea, "owner_id", None) != self.owner_id or source.owner_id != self.owner_id or source_revision.owner_id != self.owner_id:
            raise GraphWriteError("capture_idea nodes must belong to the local owner")
        if source_revision.source_id != source.id or source.current_revision_id != source_revision.id:
            raise GraphWriteError("capture_idea source revision does not match the Source current pointer")
        content_chunks = build_content_chunks(source_revision)
        if any(chunk.owner_id != self.owner_id for chunk in content_chunks):
            raise GraphWriteError("capture_idea content chunks must belong to the local owner")
        fingerprint = capture_idea_payload_fingerprint(idea, source, source_revision, content_chunks, self.owner_id)
        with self._session() as session:
            return self._execute_write(
                session,
                lambda tx: self._capture_idea_tx(
                    tx,
                    idea,
                    source,
                    source_revision,
                    content_chunks,
                    idempotency_key,
                    actor,
                    fingerprint,
                ),
            )

    def capture_source(self, source: Source, source_revision: SourceRevision, *, idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise GraphWriteError("idempotency_key must be a non-empty string")
        if not isinstance(actor, str) or not actor.strip():
            raise GraphWriteError("actor must be a non-empty string")
        validate_capture_source(source, source_revision, self.owner_id)
        chunks = build_content_chunks(source_revision, operation="capture_source")
        fingerprint = capture_source_payload_fingerprint(source, source_revision, self.owner_id)
        with self._session() as session:
            return self._execute_write(session, lambda tx: self._capture_source_tx(
                tx, source, source_revision, chunks, idempotency_key, actor, fingerprint
            ))

    def record_research_run(
        self,
        run: ResearchRun,
        *,
        expected_campaign_revision: int,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        if not isinstance(run, ResearchRun):
            raise GraphWriteError("record_research_run requires a ResearchRun")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise GraphWriteError("idempotency_key must be a non-empty string")
        if not isinstance(actor, str) or not actor.strip():
            raise GraphWriteError("actor must be a non-empty string")
        if (
            not isinstance(expected_campaign_revision, int)
            or isinstance(expected_campaign_revision, bool)
            or expected_campaign_revision < 0
        ):
            raise RevisionConflictError("expected campaign revision must be a non-negative integer")
        if run.owner_id != self.owner_id:
            raise GraphWriteError("research run must belong to the local owner")
        if type(run.authorization_revision) is not int or run.authorization_revision < 1:
            raise GraphWriteError("research run authorization revision must be a positive integer")

        fingerprint = research_run_payload_fingerprint(run, expected_campaign_revision, self.owner_id)
        try:
            with self._session() as session:
                return self._execute_write(
                    session,
                    lambda tx: self._record_research_run_tx(
                        tx, run, expected_campaign_revision, idempotency_key, actor, fingerprint,
                    ),
                )
        except Neo4jUnavailableError as error:
            return self._recover_research_run_receipt(run, idempotency_key, fingerprint, error)
        except GraphWriteError:
            raise
        except Exception:
            return self._recover_research_run_receipt(
                run, idempotency_key, fingerprint, Neo4jUnavailableError("Neo4j operation failed"),
            )

    def save_idea_brief(
        self, brief: IdeaBriefVersion, *, expected_latest_revision: int | None,
        idempotency_key: str, actor: str = "local-owner",
    ) -> WriteReceipt:
        if not isinstance(brief, IdeaBriefVersion) or brief.owner_id != self.owner_id:
            raise GraphWriteError("brief owner does not match the local owner")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise GraphWriteError("idempotency_key must be a non-empty string")
        if not isinstance(actor, str) or not actor.strip():
            raise GraphWriteError("actor must be a non-empty string")
        if expected_latest_revision is not None and (type(expected_latest_revision) is not int or expected_latest_revision < 1):
            raise RevisionConflictError("expected latest brief revision must be positive or None")
        fingerprint = payload_fingerprint(
            "save_idea_brief", brief, brief.created_at, expected_latest_revision, self.owner_id,
        )
        try:
            with self._session() as session:
                return self._execute_write(session, lambda tx: self._save_idea_brief_tx(
                    tx, brief, expected_latest_revision, idempotency_key, actor, fingerprint,
                ))
        except Neo4jUnavailableError as error:
            return self._recover_idea_brief_receipt(brief, idempotency_key, fingerprint, error)
        except GraphWriteError:
            raise
        except Exception:
            return self._recover_idea_brief_receipt(
                brief, idempotency_key, fingerprint, Neo4jUnavailableError("Neo4j operation failed"),
            )

    def _save_idea_brief_tx(self, tx: Any, brief: IdeaBriefVersion, expected_revision: int | None,
                            key: str, actor: str, fingerprint: str) -> WriteReceipt:
        replay = self._idea_brief_replay_tx(tx, key=key, fingerprint=fingerprint, brief_id=brief.id,
                                            expected_revision=brief.revision)
        if replay is not None:
            return replay
        chain = self._lock_current_idea_tx(tx, brief.idea_lineage_root_id)
        idea = chain[-1]
        if brief.based_on_idea_id != idea.id or idea.status in {Status.ARCHIVED, Status.SUPERSEDED, Status.RETRACTED}:
            raise GraphWriteError("brief must reference the exact current active Idea revision")
        replay = self._idea_brief_replay_tx(tx, key=key, fingerprint=fingerprint, brief_id=brief.id,
                                            expected_revision=brief.revision)
        if replay is not None:
            return replay
        existing = self._idea_briefs_for_root_tx(tx, brief.idea_lineage_root_id)
        latest = existing[-1] if existing else None
        actual_revision = None if latest is None else latest.revision
        if expected_revision != actual_revision:
            raise RevisionConflictError("expected latest brief revision does not match the current version")
        if latest is None:
            if brief.revision != 1 or brief.supersedes_id is not None:
                raise GraphWriteError("first brief version must start a lineage at revision one")
        elif brief.revision != latest.revision + 1 or brief.supersedes_id != latest.id:
            raise GraphWriteError("brief revision must extend the exact latest version")
        if brief.research_run_ids:
            self._validate_latest_researched_brief_tx(
                tx, primary_idea_id=idea.id, owner_id=self.owner_id, brief_id=brief.id,
                section_index=None, evidence_ids=(), locked_ideas=(idea,), brief_override=brief,
            )
        collision = _single(tx.run("MATCH (n {id: $id}) RETURN n.id AS id", id=brief.id))
        if collision is not None:
            raise NodeAlreadyExistsError("idea brief id is already registered")
        properties = _serialize_persisted_idea_brief(brief)
        tx.run("CREATE (b:IdeaBriefVersion) SET b = $properties", properties=properties)
        receipt = WriteReceipt("save_idea_brief", brief.id, "idea_brief_version", brief.revision, key)
        audit_id = f"audit_{sha256(f'{self.owner_id}:{key}'.encode()).hexdigest()[:32]}"
        tx.run(
            "CREATE (a:FounderGraphAudit {id: $audit_id, owner_id: $owner_id, actor: $actor, "
            "operation: $operation, target_id: $target_id, target_type: $target_type, revision: $revision, "
            "idempotency_key: $key, payload_fingerprint: $fingerprint})",
            audit_id=audit_id, owner_id=self.owner_id, actor=actor, operation=receipt.operation,
            target_id=receipt.target_id, target_type=receipt.target_type, revision=receipt.revision,
            key=key, fingerprint=fingerprint,
        )
        return receipt

    def get_idea_brief(self, brief_id: str) -> IdeaBriefVersion | None:
        if not isinstance(brief_id, str) or not brief_id.strip():
            raise GraphWriteError("brief_id must be a non-empty string")
        label = "IdeaBriefVersion"
        with self._session() as session:
            row = self._execute_read(session, lambda tx: _single(tx.run(
                f"MATCH (b:{label} {{id: $id, owner_id: $owner_id}}) "
                "RETURN b.id AS id, b.owner_id AS owner_id, b.node_type AS node_type, b.revision AS revision, "
                "b.idea_lineage_root_id AS idea_lineage_root_id, b.supersedes_id AS supersedes_id, "
                "b.payload_json AS payload_json",
                id=brief_id.strip(), owner_id=self.owner_id,
            )))
        return None if row is None else self._decode_idea_brief(row)

    def get_latest_idea_brief(self, idea_lineage_root_id: str) -> IdeaBriefVersion | None:
        if not isinstance(idea_lineage_root_id, str) or not idea_lineage_root_id.strip():
            raise GraphWriteError("idea_lineage_root_id must be a non-empty string")
        with self._session() as session:
            rows = self._execute_read(session, lambda tx: _rows(tx.run(
                "MATCH (b:IdeaBriefVersion {owner_id: $owner_id, idea_lineage_root_id: $root_id}) "
                "RETURN b.id AS id, b.owner_id AS owner_id, b.node_type AS node_type, b.revision AS revision, "
                "b.idea_lineage_root_id AS idea_lineage_root_id, b.supersedes_id AS supersedes_id, "
                "b.payload_json AS payload_json ORDER BY b.revision ASC",
                owner_id=self.owner_id, root_id=idea_lineage_root_id.strip(),
            )))
        briefs = tuple(self._decode_idea_brief(row) for row in rows)
        if not briefs:
            return None
        self._validate_idea_brief_chain(briefs, idea_lineage_root_id.strip())
        return briefs[-1]

    def _decode_idea_brief(self, row: Any) -> IdeaBriefVersion:
        try:
            return _decode_persisted_idea_brief({
                key: _record_value(row, key) for key in (
                    "id", "owner_id", "node_type", "revision", "idea_lineage_root_id", "supersedes_id", "payload_json",
                )
            }, owner_id=self.owner_id)
        except (IdeaBriefValidationError, TypeError, ValueError):
            raise GraphWriteError("persisted IdeaBrief is invalid") from None

    def _idea_briefs_for_root_tx(self, tx: Any, root_id: str) -> tuple[IdeaBriefVersion, ...]:
        rows = _rows(tx.run(
            "MATCH (b:IdeaBriefVersion {owner_id: $owner_id, idea_lineage_root_id: $root_id}) "
            "RETURN b.id AS id, b.owner_id AS owner_id, b.node_type AS node_type, b.revision AS revision, "
            "b.idea_lineage_root_id AS idea_lineage_root_id, b.supersedes_id AS supersedes_id, "
            "b.payload_json AS payload_json ORDER BY b.revision ASC",
            owner_id=self.owner_id, root_id=root_id,
        ))
        briefs = tuple(self._decode_idea_brief(row) for row in rows)
        if briefs:
            self._validate_idea_brief_chain(briefs, root_id)
        return briefs

    @staticmethod
    def _validate_idea_brief_chain(briefs: tuple[IdeaBriefVersion, ...], root_id: str) -> None:
        if any(brief.idea_lineage_root_id != root_id for brief in briefs):
            raise GraphWriteError("persisted IdeaBrief lineage is invalid")
        if briefs[0].revision != 1 or briefs[0].supersedes_id is not None:
            raise GraphWriteError("persisted IdeaBrief lineage is incomplete")
        for prior, current in zip(briefs, briefs[1:]):
            if current.revision != prior.revision + 1 or current.supersedes_id != prior.id:
                raise GraphWriteError("persisted IdeaBrief lineage is ambiguous")

    def _validate_latest_researched_brief_tx(
        self, tx: Any, *, primary_idea_id: str, owner_id: str, brief_id: str,
        section_index: int | None, evidence_ids: tuple[str, ...], locked_ideas: tuple[Any, ...],
        brief_override: IdeaBriefVersion | None = None,
    ) -> AcceptedIdeaBriefProof:
        if owner_id != self.owner_id or not locked_ideas:
            raise GraphWriteError("researched IdeaBrief proof requires locked owner-scoped Ideas")
        root_ids: list[str] = []
        leaves: list[Any] = []
        for locked_idea in locked_ideas:
            root_id = self._idea_root_for_tx(tx, locked_idea.id)
            chain = self._idea_chain_tx(tx, root_id)
            if chain[-1] != locked_idea:
                raise RevisionConflictError("Idea endpoint is no longer the current leaf")
            root_ids.append(root_id)
            leaves.append(chain[-1])
        primary = next((idea for idea in leaves if idea.id == primary_idea_id), None)
        if primary is None:
            raise GraphWriteError("researched IdeaBrief source endpoint is not locked")
        brief = brief_override
        if brief is None:
            rows = self._idea_briefs_for_root_tx(tx, self._idea_root_for_tx(tx, primary.id))
            brief = next((item for item in rows if item.id == brief_id), None)
            if brief is None or not rows or rows[-1].id != brief_id:
                raise GraphWriteError("relation requires the latest researched IdeaBrief")
        if brief.id != brief_id or brief.based_on_idea_id != primary.id:
            raise GraphWriteError("researched IdeaBrief does not match the current Idea")
        selected_evidence = tuple(evidence_ids)
        if section_index is not None:
            if type(section_index) is not int or not 0 <= section_index < 8:
                raise GraphWriteError("researched IdeaBrief section is invalid")
            section = brief.sections[section_index]
            if not section.content.strip() or not set(selected_evidence).issubset(section.evidence_ids):
                raise GraphWriteError("evidence is outside the selected researched section")
        if brief.research_run_ids:
            self._validate_brief_run_history_tx(tx, brief, primary)
        elif section_index is not None:
            raise GraphWriteError("relation requires a researched IdeaBrief")
        return AcceptedIdeaBriefProof(
            brief.id, brief.revision, section_index, tuple(sorted(set(root_ids))),
            tuple(sorted(idea.id for idea in leaves)), selected_evidence,
        )

    def _validate_brief_run_history_tx(self, tx: Any, brief: IdeaBriefVersion, idea: Any) -> None:
        run_label = self.label_for(NodeType.RESEARCH_RUN)
        runs = []
        campaign_ids: set[str] = set()
        for run_id in brief.research_run_ids:
            row = _single(tx.run(
                f"MATCH (r:{run_label} {{id: $id, owner_id: $owner_id}}) "
                "RETURN r.id AS id, r.owner_id AS owner_id, r.node_type AS node_type, "
                "r.revision AS revision, r.payload_json AS payload_json",
                id=run_id, owner_id=self.owner_id,
            ))
            if row is None:
                raise GraphWriteError("researched IdeaBrief references an unregistered Run")
            try:
                run = decode_persisted_research_run(row, owner_id=self.owner_id, expected_id=run_id)
            except ResearchRunDecodeError:
                raise GraphWriteError("persisted research Run is invalid") from None
            edge_rows = _rows(tx.run(
                "MATCH (c:ResearchCampaign)-[:HAS_RUN]->(r:ResearchRun {id: $run_id, owner_id: $owner_id}) "
                "RETURN c.id AS campaign_id, c.owner_id AS owner_id",
                run_id=run.id, owner_id=self.owner_id,
            ))
            if len(edge_rows) != 1 or _record_value(edge_rows[0], "campaign_id") != run.campaign_id or _record_value(edge_rows[0], "owner_id") != self.owner_id:
                raise GraphWriteError("researched Run must have exactly one matching HAS_RUN edge")
            audits = _rows(tx.run(
                "MATCH (a:FounderGraphAudit {owner_id: $owner_id, operation: 'record_research_run', target_id: $run_id}) "
                "RETURN a.idempotency_key AS idempotency_key, a.target_type AS target_type, "
                "a.revision AS revision, a.payload_fingerprint AS payload_fingerprint",
                owner_id=self.owner_id, run_id=run.id,
            ))
            if len(audits) != 1 or _record_value(audits[0], "target_type") != NodeType.RESEARCH_RUN.value or _record_value(audits[0], "revision") != 0 or not _record_value(audits[0], "idempotency_key") or not _record_value(audits[0], "payload_fingerprint"):
                raise GraphWriteError("researched Run must have exactly one matching audit receipt")
            runs.append(run)
            campaign_ids.add(run.campaign_id)
        histories = []
        campaign_label = self.label_for(NodeType.RESEARCH_CAMPAIGN)
        for campaign_id in sorted(campaign_ids):
            if self._lock_revisioned_node_tx(tx, campaign_label, campaign_id) is None:
                raise GraphWriteNotFoundError("research campaign does not exist for the local owner")
            try:
                registry = self._campaign_authorization_registry_tx(tx, campaign_id)
            except DomainValidationError:
                raise GraphWriteError("persisted campaign authorization history is invalid") from None
            histories.extend(registry.campaigns)
        try:
            validate_historical_researched_brief(brief, idea, tuple(runs), tuple(histories))
        except HistoricalResearchValidationError:
            raise GraphWriteError("researched IdeaBrief authorization proof is invalid") from None

    def _research_run_audit_tx(self, tx: Any, idempotency_key: str) -> Any | None:
        return _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $idempotency_key}) "
            "RETURN a.operation AS operation, a.payload_fingerprint AS payload_fingerprint, "
            "a.target_id AS target_id, a.target_type AS target_type, a.revision AS revision",
            owner_id=self.owner_id,
            idempotency_key=idempotency_key,
        ))

    def _research_run_replay_from_record(
        self, record: Any | None, run: ResearchRun, idempotency_key: str, fingerprint: str,
    ) -> WriteReceipt | None:
        if record is None:
            return None
        if (
            _record_value(record, "operation") != "record_research_run"
            or _record_value(record, "payload_fingerprint") != fingerprint
            or _record_value(record, "target_id") != run.id
            or _record_value(record, "target_type") != NodeType.RESEARCH_RUN.value
        ):
            raise IdempotencyConflictError("idempotency key was reused with a different payload")
        revision = _record_value(record, "revision")
        if type(revision) is not int or revision < 0:
            raise GraphWriteError("persisted research run receipt is invalid")
        return WriteReceipt(
            "record_research_run", run.id, NodeType.RESEARCH_RUN.value, revision, idempotency_key, replayed=True,
        )

    def _research_run_replay_tx(
        self, tx: Any, run: ResearchRun, idempotency_key: str, fingerprint: str,
    ) -> WriteReceipt | None:
        return self._research_run_replay_from_record(
            self._research_run_audit_tx(tx, idempotency_key), run, idempotency_key, fingerprint,
        )

    def _recover_research_run_receipt(
        self, run: ResearchRun, idempotency_key: str, fingerprint: str, failure: Neo4jUnavailableError,
    ) -> WriteReceipt:
        try:
            with self._session() as session:
                record = self._execute_read(session, lambda tx: self._research_run_audit_tx(tx, idempotency_key))
        except Exception:
            raise failure from None
        replay = self._research_run_replay_from_record(record, run, idempotency_key, fingerprint)
        if replay is None:
            raise failure from None
        return replay

    def _record_research_run_tx(
        self,
        tx: Any,
        run: ResearchRun,
        expected_campaign_revision: int,
        idempotency_key: str,
        actor: str,
        fingerprint: str,
    ) -> WriteReceipt:
        replay = self._research_run_replay_tx(tx, run, idempotency_key, fingerprint)
        if replay is not None:
            return replay

        campaign_label = self.label_for(NodeType.RESEARCH_CAMPAIGN)
        locked = self._lock_revisioned_node_tx(tx, campaign_label, run.campaign_id)
        if locked is None:
            raise GraphWriteNotFoundError("research campaign does not exist for the local owner")
        replay = self._research_run_replay_tx(tx, run, idempotency_key, fingerprint)
        if replay is not None:
            return replay

        record = _single(tx.run(
            f"MATCH (c:{campaign_label} {{id: $campaign_id, owner_id: $owner_id}}) "
            "RETURN c.id AS id, c.owner_id AS owner_id, c.node_type AS node_type, "
            "c.revision AS revision, c.payload_json AS payload_json",
            campaign_id=run.campaign_id, owner_id=self.owner_id,
        ))
        if record is None:
            raise GraphWriteNotFoundError("research campaign does not exist for the local owner")
        try:
            campaign = decode_persisted_research_campaign(record, owner_id=self.owner_id)
        except CampaignDecodeError:
            raise GraphWriteError("persisted campaign authorization is invalid") from None
        if (
            campaign.id != run.campaign_id
            or _record_value(locked, "id") != campaign.id
            or _record_value(locked, "revision") != campaign.aggregate_revision
        ):
            raise GraphWriteError("locked research campaign state is invalid")
        if expected_campaign_revision != campaign.aggregate_revision:
            raise RevisionConflictError("expected campaign revision does not match current revision")
        if run.status not in {Status.COMPLETED, Status.PARTIAL, Status.FAILED, Status.CANCELLED}:
            raise GraphWriteError("only terminal research runs can be recorded")

        now = datetime.now(timezone.utc)
        try:
            validate_research_run_timing(run, campaign, at=now)
            validate_run_campaign_reference(
                run, campaign, campaign.authorization_snapshot,
                authorization_registry=CampaignAuthorizationRegistry.from_campaign(campaign), at=now,
            )
            if not campaign.can_start_run(at=now):
                raise DomainValidationError("campaign is not authorized for another run")
            updated_campaign = campaign.register_run(at=now)
        except DomainValidationError:
            raise GraphWriteError("research campaign authorization or Run timing is invalid") from None

        if _single(tx.run("MATCH (n {id: $run_id}) RETURN n.id AS id", run_id=run.id)) is not None:
            raise NodeAlreadyExistsError("research run id is already registered")

        self._store_prior_campaign_revision_tx(tx, record)
        tx.run(
            f"MATCH (c:{campaign_label} {{id: $campaign_id, owner_id: $owner_id}}) SET c = $properties",
            campaign_id=campaign.id, owner_id=self.owner_id, properties=_node_properties(updated_campaign),
        )
        run_label = self.label_for(NodeType.RESEARCH_RUN)
        tx.run(f"CREATE (r:{run_label}) SET r = $properties", properties=_node_properties(run))
        linked = _single(tx.run(
            f"MATCH (c:{campaign_label} {{id: $campaign_id, owner_id: $owner_id}}), "
            f"(r:{run_label} {{id: $run_id, owner_id: $owner_id}}) "
            "CREATE (c)-[:HAS_RUN]->(r) RETURN r.id AS id",
            campaign_id=campaign.id, run_id=run.id, owner_id=self.owner_id,
        ))
        if linked is None:
            raise GraphWriteNotFoundError("research campaign or Run disappeared during write")

        receipt = WriteReceipt(
            "record_research_run", run.id, NodeType.RESEARCH_RUN.value, _node_revision(run), idempotency_key,
        )
        audit_id = f"audit_{sha256(f'{self.owner_id}:{idempotency_key}'.encode()).hexdigest()[:32]}"
        tx.run(
            "CREATE (a:FounderGraphAudit {id: $audit_id, owner_id: $owner_id, actor: $actor, "
            "operation: $operation, target_id: $target_id, target_type: $target_type, revision: $revision, "
            "idempotency_key: $idempotency_key, payload_fingerprint: $payload_fingerprint})",
            audit_id=audit_id, owner_id=self.owner_id, actor=actor, operation=receipt.operation,
            target_id=receipt.target_id, target_type=receipt.target_type, revision=receipt.revision,
            idempotency_key=idempotency_key, payload_fingerprint=fingerprint,
        )
        return receipt

    def _capture_source_tx(self, tx: Any, source: Source, revision: SourceRevision, chunks: tuple[ContentChunk, ...],
                           idempotency_key: str, actor: str, fingerprint: str) -> WriteReceipt:
        replay = _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $idempotency_key}) "
            "RETURN a.payload_fingerprint AS payload_fingerprint, a.target_id AS target_id, a.target_type AS target_type, "
            "a.revision AS revision, a.source_revision_id AS source_revision_id, a.content_chunk_ids AS content_chunk_ids",
            owner_id=self.owner_id, idempotency_key=idempotency_key))
        if replay is not None:
            if _record_value(replay, "payload_fingerprint") != fingerprint or _record_value(replay, "target_id") != source.id or _record_value(replay, "target_type") != NodeType.SOURCE.value:
                raise IdempotencyConflictError("idempotency key was reused with a different payload")
            replay_chunks = _content_chunk_ids(_record_value(replay, "content_chunk_ids"))
            expected = tuple(chunk.id for chunk in chunks)
            if _record_value(replay, "source_revision_id") != revision.id or replay_chunks != expected:
                raise GraphWriteError("capture audit references do not match the retry")
            return WriteReceipt("capture_source", source.id, NodeType.SOURCE.value, 1, idempotency_key,
                                replayed=True, source_revision_id=revision.id, content_chunk_ids=expected)
        node_ids = [source.id, revision.id, *(chunk.id for chunk in chunks)]
        if len(set(node_ids)) != len(node_ids):
            raise GraphWriteError("capture_source nodes must have distinct ids")
        if _rows(tx.run("MATCH (n) WHERE n.id IN $node_ids RETURN n.id AS id", node_ids=node_ids)):
            raise NodeAlreadyExistsError("capture_source node id is already registered")
        source_label, revision_label, chunk_label = (self.label_for(NodeType.SOURCE), self.label_for(NodeType.SOURCE_REVISION), self.label_for(NodeType.CONTENT_CHUNK))
        tx.run(f"CREATE (n:{source_label}) SET n = $properties", properties=_node_properties(replace(source, current_revision_id=None)))
        tx.run(f"CREATE (n:{revision_label}) SET n = $properties", properties=_node_properties(revision))
        for chunk in chunks:
            tx.run(f"CREATE (n:{chunk_label}) SET n = $properties", properties=_node_properties(chunk))
        tx.run(f"MATCH (n:{source_label} {{id: $id, owner_id: $owner_id}}) SET n = $properties",
               id=source.id, owner_id=self.owner_id, properties=_node_properties(source))
        tx.run(
            f"MATCH (s:{source_label} {{id: $source_id, owner_id: $owner_id}}), "
            f"(r:{revision_label} {{id: $revision_id, owner_id: $owner_id}}) "
            "CREATE (s)-[:HAS_SOURCE_REVISION]->(r), (s)-[:CURRENT_SOURCE_REVISION]->(r)",
            source_id=source.id,
            revision_id=revision.id,
            owner_id=self.owner_id,
        )
        for chunk in chunks:
            tx.run(
                f"MATCH (r:{revision_label} {{id: $revision_id, owner_id: $owner_id}}), "
                f"(c:{self.label_for(NodeType.CONTENT_CHUNK)} {{id: $chunk_id, owner_id: $owner_id}}) "
                "CREATE (r)-[:HAS_CHUNK]->(c)",
                revision_id=revision.id,
                chunk_id=chunk.id,
                owner_id=self.owner_id,
            )
        receipt = WriteReceipt("capture_source", source.id, NodeType.SOURCE.value, 1, idempotency_key,
                               source_revision_id=revision.id, content_chunk_ids=tuple(chunk.id for chunk in chunks))
        audit_id = f"audit_{sha256(f'{self.owner_id}:{idempotency_key}'.encode()).hexdigest()[:32]}"
        tx.run("CREATE (a:FounderGraphAudit {id: $audit_id, owner_id: $owner_id, actor: $actor, operation: $operation, "
               "target_id: $target_id, target_type: $target_type, revision: 1, idempotency_key: $idempotency_key, "
               "payload_fingerprint: $fingerprint, source_revision_id: $revision_id, content_chunk_ids: $chunk_ids})",
               audit_id=audit_id, owner_id=self.owner_id, actor=actor, operation="capture_source", target_id=source.id,
               target_type=NodeType.SOURCE.value, idempotency_key=idempotency_key, fingerprint=fingerprint,
               revision_id=revision.id, chunk_ids=list(receipt.content_chunk_ids))
        return receipt

    def _backfill_legacy_capture_idea_tx(
        self,
        tx: Any,
        idea: Any,
        source: Source,
        source_revision: SourceRevision,
        content_chunks: tuple[ContentChunk, ...],
        idempotency_key: str,
        actor: str,
        audit_revision: int,
    ) -> None:
        """Add missing deterministic chunks for an old receipt-less capture audit."""

        anchors = _single(tx.run(
            "MATCH (i:Idea {id: $idea_id, owner_id: $owner_id}), "
            "(s:Source {id: $source_id, owner_id: $owner_id}), "
            "(r:SourceRevision {id: $source_revision_id, owner_id: $owner_id}) "
            "RETURN r.owner_id AS owner_id, r.payload_json AS payload_json",
            idea_id=str(idea.id),
            source_id=source.id,
            source_revision_id=source_revision.id,
            owner_id=self.owner_id,
        ))
        if anchors is None:
            raise GraphWriteNotFoundError("legacy capture nodes are missing or not owned by the local owner")
        anchor_payload_json = _record_value(anchors, "payload_json")
        try:
            anchor_payload = json.loads(anchor_payload_json) if isinstance(anchor_payload_json, str) else None
        except (TypeError, ValueError):
            anchor_payload = None
        if (
            _record_value(anchors, "owner_id") != self.owner_id
            or not isinstance(anchor_payload, Mapping)
            or anchor_payload.get("source_id") != source.id
            or anchor_payload.get("content_hash") != source_revision.content_hash
            or anchor_payload.get("revision") != source_revision.revision
        ):
            raise IdempotencyConflictError("legacy capture source revision does not match the retried payload")

        chunk_ids = tuple(str(chunk.id) for chunk in content_chunks)
        existing_chunks: dict[str, Any] = {}
        if chunk_ids:
            rows = _rows(tx.run(
                "MATCH (n) WHERE n.id IN $chunk_ids "
                "RETURN n.id AS id, n.owner_id AS owner_id, labels(n) AS labels, n.payload_json AS payload_json",
                chunk_ids=list(chunk_ids),
            ))
            chunks_by_id = {str(chunk.id): chunk for chunk in content_chunks}
            for row in rows:
                chunk_id = _record_value(row, "id")
                if not isinstance(chunk_id, str) or chunk_id not in chunks_by_id or chunk_id in existing_chunks:
                    raise GraphWriteError("legacy capture content chunk identity is invalid")
                labels = _record_value(row, "labels")
                chunk = chunks_by_id[chunk_id]
                payload_json = _record_value(row, "payload_json")
                try:
                    payload = json.loads(payload_json) if isinstance(payload_json, str) else None
                except (TypeError, ValueError):
                    payload = None
                if (
                    not isinstance(labels, (tuple, list, set, frozenset))
                    or "ContentChunk" not in labels
                    or _record_value(row, "owner_id") != self.owner_id
                    or not isinstance(payload, Mapping)
                    or payload.get("source_revision_id") != source_revision.id
                    or payload.get("ordinal") != chunk.ordinal
                    or payload.get("char_start") != chunk.char_start
                    or payload.get("char_end") != chunk.char_end
                    or payload.get("text_hash") != chunk.text_hash
                    or payload.get("text") != chunk.text
                ):
                    raise GraphWriteError("legacy capture content chunk conflicts with its deterministic identity")
                existing_chunks[chunk_id] = row

        chunk_label = self.label_for(NodeType.CONTENT_CHUNK)
        for chunk in content_chunks:
            if chunk.id not in existing_chunks:
                tx.run(
                    f"CREATE (n:{chunk_label}) SET n = $properties",
                    properties=_node_properties(chunk),
                )

        backfill_digest = sha256(
            f"{self.owner_id}:{idempotency_key}:capture_idea_chunk_backfill".encode("utf-8")
        ).hexdigest()[:32]
        backfill_audit_id = f"audit_backfill_{backfill_digest}"
        backfill_idempotency_key = f"capture_idea_chunk_backfill:{backfill_digest}"
        backfill_fingerprint = payload_fingerprint(
            "capture_idea_chunk_backfill", source_revision.id, chunk_ids, self.owner_id
        )
        event = _single(tx.run(
            "MERGE (a:FounderGraphAudit {id: $audit_id}) "
            "ON CREATE SET a.owner_id = $owner_id, a.actor = $actor, a.operation = $operation, "
            "a.target_id = $target_id, a.target_type = $target_type, a.revision = $revision, "
            "a.idempotency_key = $idempotency_key, a.payload_fingerprint = $payload_fingerprint, "
            "a.source_revision_id = $source_revision_id, a.content_chunk_ids = $content_chunk_ids "
            "RETURN a.owner_id AS owner_id, a.operation AS operation, a.target_id AS target_id, "
            "a.target_type AS target_type, a.revision AS revision, a.idempotency_key AS idempotency_key, "
            "a.payload_fingerprint AS payload_fingerprint, a.source_revision_id AS source_revision_id, "
            "a.content_chunk_ids AS content_chunk_ids",
            audit_id=backfill_audit_id,
            owner_id=self.owner_id,
            actor=actor,
            operation="capture_idea_chunk_backfill",
            target_id=str(idea.id),
            target_type=NodeType.IDEA.value,
            revision=audit_revision,
            idempotency_key=backfill_idempotency_key,
            payload_fingerprint=backfill_fingerprint,
            source_revision_id=source_revision.id,
            content_chunk_ids=list(chunk_ids),
        ))
        if (
            event is None
            or _record_value(event, "owner_id") != self.owner_id
            or _record_value(event, "operation") != "capture_idea_chunk_backfill"
            or _record_value(event, "target_id") != str(idea.id)
            or _record_value(event, "target_type") != NodeType.IDEA.value
            or _record_value(event, "revision") != audit_revision
            or _record_value(event, "idempotency_key") != backfill_idempotency_key
            or _record_value(event, "payload_fingerprint") != backfill_fingerprint
            or _record_value(event, "source_revision_id") != source_revision.id
            or _content_chunk_ids(_record_value(event, "content_chunk_ids")) != chunk_ids
        ):
            raise GraphWriteError("legacy capture backfill audit conflicts with the deterministic event")

    def _capture_idea_tx(
        self,
        tx: Any,
        idea: Any,
        source: Source,
        source_revision: SourceRevision,
        content_chunks: tuple[ContentChunk, ...],
        idempotency_key: str,
        actor: str,
        fingerprint: str,
    ) -> WriteReceipt:
        replay = _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $idempotency_key}) "
            "RETURN a.payload_fingerprint AS payload_fingerprint, a.target_id AS target_id, "
            "a.target_type AS target_type, a.revision AS revision, "
            "a.source_revision_id AS source_revision_id, a.content_chunk_ids AS content_chunk_ids",
            owner_id=self.owner_id,
            idempotency_key=idempotency_key,
        ))
        if replay is not None:
            prior = _record_value(replay, "payload_fingerprint")
            if prior != fingerprint:
                raise IdempotencyConflictError("idempotency key was reused with a different payload")
            target_id = _record_value(replay, "target_id")
            target_type = _record_value(replay, "target_type")
            if target_id != str(idea.id) or target_type != NodeType.IDEA.value:
                raise IdempotencyConflictError("capture audit target does not match the retried payload")
            audit_revision = int(_record_value(replay, "revision", 0))
            source_revision_id = _record_value(replay, "source_revision_id")
            raw_chunk_ids = _record_value(replay, "content_chunk_ids")
            expected_chunk_ids = tuple(str(chunk.id) for chunk in content_chunks)
            if source_revision_id is None and raw_chunk_ids is None:
                self._backfill_legacy_capture_idea_tx(
                    tx,
                    idea,
                    source,
                    source_revision,
                    content_chunks,
                    idempotency_key,
                    actor,
                    audit_revision,
                )
                source_revision_id = source_revision.id
                replay_chunk_ids = expected_chunk_ids
            else:
                if source_revision_id is None:
                    raise GraphWriteError("capture audit is missing its SourceRevision reference")
                replay_chunk_ids = _content_chunk_ids(raw_chunk_ids)
                if source_revision_id != source_revision.id or replay_chunk_ids != expected_chunk_ids:
                    raise IdempotencyConflictError("capture audit references do not match the retried payload")
            return WriteReceipt(
                "capture_idea",
                str(target_id),
                str(target_type),
                audit_revision,
                idempotency_key,
                replayed=True,
                source_revision_id=source_revision_id,
                content_chunk_ids=replay_chunk_ids,
            )

        if idea.supersedes_id is not None:
            self._lock_idea_successor_tx(tx, idea)
        elif idea.revision != 0:
            raise GraphWriteError("new Idea lineage must start at revision zero")

        validate_source_revision_history(source, (source_revision,))
        node_ids = [str(idea.id), str(source.id), str(source_revision.id), *(str(chunk.id) for chunk in content_chunks)]
        existing = _rows(tx.run(
            "MATCH (n) WHERE n.id IN $node_ids RETURN n.id AS id, n.owner_id AS owner_id",
            node_ids=node_ids,
        ))
        if existing:
            raise NodeAlreadyExistsError("capture_idea node id is already registered")

        source_label = self.label_for(NodeType.SOURCE)
        revision_label = self.label_for(NodeType.SOURCE_REVISION)
        chunk_label = self.label_for(NodeType.CONTENT_CHUNK)
        idea_label = self.label_for(NodeType.IDEA)
        source_without_pointer = replace(source, current_revision_id=None)
        tx.run(f"CREATE (n:{source_label}) SET n = $properties", properties=_node_properties(source_without_pointer))
        tx.run(f"CREATE (n:{revision_label}) SET n = $properties", properties=_node_properties(source_revision))
        for chunk in content_chunks:
            tx.run(f"CREATE (n:{chunk_label}) SET n = $properties", properties=_node_properties(chunk))
        tx.run(f"CREATE (n:{idea_label}) SET n = $properties", properties=_node_properties(idea))
        tx.run(
            f"MATCH (n:{source_label} {{id: $id, owner_id: $owner_id}}) SET n = $properties",
            id=str(source.id),
            owner_id=self.owner_id,
            properties=_node_properties(source),
        )

        receipt = WriteReceipt(
            "capture_idea",
            str(idea.id),
            NodeType.IDEA.value,
            _node_revision(idea),
            idempotency_key,
            source_revision_id=source_revision.id,
            content_chunk_ids=tuple(chunk.id for chunk in content_chunks),
        )
        audit_id = f"audit_{sha256(f'{self.owner_id}:{idempotency_key}'.encode()).hexdigest()[:32]}"
        tx.run(
            "CREATE (a:FounderGraphAudit {id: $audit_id, owner_id: $owner_id, actor: $actor, "
            "operation: $operation, target_id: $target_id, target_type: $target_type, "
            "revision: $revision, idempotency_key: $idempotency_key, payload_fingerprint: $payload_fingerprint, "
            "source_revision_id: $source_revision_id, content_chunk_ids: $content_chunk_ids})",
            audit_id=audit_id,
            owner_id=self.owner_id,
            actor=actor,
            operation="capture_idea",
            target_id=receipt.target_id,
            target_type=receipt.target_type,
            revision=receipt.revision,
            idempotency_key=idempotency_key,
            payload_fingerprint=fingerprint,
            source_revision_id=receipt.source_revision_id,
            content_chunk_ids=list(receipt.content_chunk_ids),
        )
        return receipt

    def _put_node_tx(self, tx: Any, node: Any, node_type: NodeType, label: str, idempotency_key: str, expected_revision: int | None, operation: str, actor: str, fingerprint: str) -> WriteReceipt:
        replay = self._put_node_replay_tx(
            tx, operation=operation, idempotency_key=idempotency_key, fingerprint=fingerprint,
        )
        if replay is not None:
            return replay

        if node_type is NodeType.IDEA:
            self._lock_idea_successor_tx(tx, node)

        revisioned_types = {NodeType.RESEARCH_CAMPAIGN, NodeType.SOURCE}
        existing = None
        if node_type in revisioned_types:
            existing = self._lock_revisioned_node_tx(tx, label, str(node.id))
            lock_acquired = existing is not None
            if existing is None:
                # Preserve the existing cross-owner/type collision check, but
                # do not take a lock on a node outside the caller's boundary.
                existing = _single(tx.run(
                    "MATCH (n {id: $id}) RETURN n.owner_id AS owner_id, n.node_type AS node_type, "
                    "n.revision AS revision",
                    id=str(node.id),
                ))
            else:
                # Another same-key transaction may have committed while this
                # request waited for the node lock. Recheck before validation
                # or history/payload writes so its exact replay stays a no-op.
                replay = self._put_node_replay_tx(
                    tx, operation=operation, idempotency_key=idempotency_key, fingerprint=fingerprint,
                )
                if replay is not None:
                    return replay
            if existing is not None:
                existing_owner = _record_value(existing, "owner_id")
                existing_type = _record_value(existing, "node_type")
                if existing_owner != self.owner_id:
                    raise GraphWriteError("node owner does not match the local owner")
                if existing_type != node_type.value:
                    raise NodeAlreadyExistsError("node id is already registered with another type")
                if not lock_acquired:
                    raise GraphWriteError("revisioned node could not be locked by its expected type label")
            self._validate_source_reference_tx(tx, node, node_type)
            self._validate_report_references_tx(tx, node)
        else:
            self._validate_source_reference_tx(tx, node, node_type)
            self._validate_report_references_tx(tx, node)
            existing = _single(tx.run(
                "MATCH (n {id: $id}) RETURN n.owner_id AS owner_id, n.node_type AS node_type, "
                "n.revision AS revision",
                id=str(node.id),
            ))

        current_revision = 0
        if existing is not None:
            owner = existing.get("owner_id") if isinstance(existing, Mapping) else existing["owner_id"]
            current_type = existing.get("node_type") if isinstance(existing, Mapping) else existing["node_type"]
            current_revision = existing.get("revision", 0) if isinstance(existing, Mapping) else existing.get("revision", 0)
            if owner != self.owner_id:
                raise GraphWriteError("node owner does not match the local owner")
            if current_type != node_type.value:
                raise NodeAlreadyExistsError("node id is already registered with another type")
            if node_type not in {NodeType.RESEARCH_CAMPAIGN, NodeType.SOURCE}:
                raise NodeAlreadyExistsError(f"node id is already registered: {node.id}")
            if expected_revision != current_revision or _node_revision(node) != current_revision + 1:
                raise RevisionConflictError("expected node revision does not match current revision")
            if node_type is NodeType.RESEARCH_CAMPAIGN:
                campaign_record = _single(tx.run(
                    f"MATCH (n:{label} {{id: $id, owner_id: $owner_id}}) "
                    "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
                    "n.revision AS revision, n.payload_json AS payload_json",
                    id=str(node.id),
                    owner_id=self.owner_id,
                ))
                if campaign_record is None or _record_value(campaign_record, "revision") != current_revision:
                    raise GraphWriteError("locked research campaign state is invalid")
                self._store_prior_campaign_revision_tx(tx, campaign_record)
            else:
                history_id = f"history_{sha256(f'{node.id}:{current_revision}'.encode()).hexdigest()[:32]}"
                tx.run(
                    "CREATE (h:FounderGraphHistory {id: $history_id, owner_id: $owner_id, "
                    "target_id: $target_id, revision: $revision, payload_json: $payload_json})",
                    history_id=history_id,
                    owner_id=self.owner_id,
                    target_id=str(node.id),
                    revision=current_revision,
                    payload_json=json.dumps({"id": str(node.id), "node_type": node_type.value, "revision": current_revision}, sort_keys=True),
                )
            tx.run(
                f"MATCH (n:{label} {{id: $id, owner_id: $owner_id}}) SET n = $properties",
                id=str(node.id), owner_id=self.owner_id, properties=_node_properties(node),
            )
            if node_type is NodeType.SOURCE:
                tx.run(
                    "MATCH (s:Source {id: $source_id, owner_id: $owner_id}) "
                    "-[edge:CURRENT_SOURCE_REVISION]->() DELETE edge",
                    source_id=str(node.id),
                    owner_id=self.owner_id,
                )
                current_revision_id = getattr(node, "current_revision_id", None)
                if current_revision_id is not None:
                    linked = _single(tx.run(
                        "MATCH (s:Source {id: $source_id, owner_id: $owner_id}), "
                        "(r:SourceRevision {id: $source_revision_id, owner_id: $owner_id}) "
                        "CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r) RETURN r.id AS id",
                        source_id=str(node.id),
                        source_revision_id=str(current_revision_id),
                        owner_id=self.owner_id,
                    ))
                    if linked is None:
                        raise GraphWriteNotFoundError("source current revision does not exist for the local owner")
        else:
            if expected_revision not in (None, 0):
                raise RevisionConflictError("new nodes require expected_revision=0 or omitted")
            tx.run(f"CREATE (n:{label}) SET n = $properties", properties=_node_properties(node))

        revision = _node_revision(node)
        receipt = WriteReceipt(operation, str(node.id), node_type.value, revision, idempotency_key)
        audit_id = f"audit_{sha256(f'{self.owner_id}:{idempotency_key}'.encode()).hexdigest()[:32]}"
        tx.run(
            "CREATE (a:FounderGraphAudit {id: $audit_id, owner_id: $owner_id, actor: $actor, "
            "operation: $operation, target_id: $target_id, target_type: $target_type, "
            "revision: $revision, idempotency_key: $idempotency_key, payload_fingerprint: $payload_fingerprint})",
            audit_id=audit_id,
            owner_id=self.owner_id,
            actor=actor,
            operation=operation,
            target_id=receipt.target_id,
            target_type=receipt.target_type,
            revision=revision,
            idempotency_key=idempotency_key,
            payload_fingerprint=fingerprint,
        )
        return receipt

    def link_entities(self, relationship: Relationship, *, idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        if relationship.owner_id != self.owner_id:
            raise GraphWriteError("relationship owner does not match the local owner")
        relation_type = self.relation_type_for(relationship.relation)
        fingerprint = payload_fingerprint("link_entities", relationship, self.owner_id)
        with self._session() as session:
            return self._execute_write(session, lambda tx: self._link_tx(tx, relationship, relation_type, idempotency_key, actor, fingerprint))

    def save_relation_assertion(
        self,
        assertion: RelationAssertion,
        *,
        expected_family_revision: int | None,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        """Atomically persist a typed assertion, structural edges, and audit."""
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
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise GraphWriteError("idempotency_key must be a non-empty string")
        if not isinstance(actor, str) or not actor.strip():
            raise GraphWriteError("actor must be a non-empty string")
        intent = tuple(
            (field.name, getattr(assertion, field.name))
            for field in fields(assertion)
            if field.name != "valid_from"
        )
        fingerprint = payload_fingerprint(
            "save_relation_assertion", intent, expected_family_revision, self.owner_id,
        )
        try:
            with self._session() as session:
                return self._execute_write(session, lambda tx: self._save_relation_assertion_tx(
                    tx, assertion, expected_family_revision, idempotency_key, actor, fingerprint,
                ))
        except Neo4jUnavailableError as failure:
            return self._recover_relation_assertion_receipt(
                assertion, idempotency_key, fingerprint, failure,
            )

    def _relation_assertion_audit_tx(self, tx: Any, key: str) -> Any | None:
        return _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $idempotency_key}) "
            "RETURN a.operation AS operation, a.payload_fingerprint AS payload_fingerprint, "
            "a.target_id AS target_id, a.target_type AS target_type, a.revision AS revision",
            owner_id=self.owner_id, idempotency_key=key,
        ))

    def _relation_assertion_receipt(self, record: Any | None, assertion: RelationAssertion,
                                    key: str, fingerprint: str) -> WriteReceipt | None:
        if record is None:
            return None
        if (
            _record_value(record, "operation") != "save_relation_assertion"
            or _record_value(record, "payload_fingerprint") != fingerprint
            or _record_value(record, "target_id") != assertion.id
            or _record_value(record, "target_type") != NodeType.RELATION_ASSERTION.value
        ):
            raise IdempotencyConflictError("idempotency key was reused with a different payload")
        revision = _record_value(record, "revision")
        if type(revision) is not int:
            raise GraphWriteError("persisted relation assertion receipt is invalid")
        if revision != assertion.revision:
            raise IdempotencyConflictError("idempotency key was reused with a different payload")
        return WriteReceipt(
            "save_relation_assertion", assertion.id, NodeType.RELATION_ASSERTION.value,
            revision, key, replayed=True,
        )

    def _recover_relation_assertion_receipt(
        self, assertion: RelationAssertion, key: str, fingerprint: str, failure: Neo4jUnavailableError,
    ) -> WriteReceipt:
        try:
            with self._session() as session:
                record = self._execute_read(session, lambda tx: self._relation_assertion_audit_tx(tx, key))
        except Exception:
            raise failure from None
        receipt = self._relation_assertion_receipt(record, assertion, key, fingerprint)
        if receipt is None:
            raise failure from None
        return receipt

    def _relation_assertion_record_tx(self, tx: Any, assertion_id: str) -> Any | None:
        return _single(tx.run(
            "MATCH (n:RelationAssertion {id: $id, owner_id: $owner_id}) "
            "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
            "n.revision AS revision, n.status AS status, n.assertion_family_id AS assertion_family_id, "
            "n.supersedes_id AS supersedes_id, n.payload_json AS payload_json",
            id=assertion_id, owner_id=self.owner_id,
        ))

    def _decode_relation_assertion_record(self, record: Any) -> RelationAssertion:
        if record is None or _record_value(record, "owner_id") != self.owner_id or _record_value(
            record, "node_type"
        ) != NodeType.RELATION_ASSERTION.value:
            raise GraphWriteNotFoundError("relation assertion predecessor is not owner-scoped")
        raw = _record_value(record, "payload_json")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            raise GraphWriteError("persisted relation assertion is invalid") from None
        expected_fields = {item.name for item in fields(RelationAssertion)}
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise GraphWriteError("persisted relation assertion is invalid")
        if payload.get("id") != _record_value(record, "id") or payload.get("owner_id") != self.owner_id:
            raise GraphWriteError("persisted relation assertion is invalid")
        revision = _record_value(record, "revision")
        if type(revision) is not int or payload.get("revision") != revision:
            raise GraphWriteError("persisted relation assertion is invalid")
        if _record_value(record, "assertion_family_id") != payload.get("assertion_family_id"):
            raise GraphWriteError("persisted relation assertion is invalid")
        if _record_value(record, "supersedes_id") != payload.get("supersedes_id"):
            raise GraphWriteError("persisted relation assertion is invalid")
        if _record_value(record, "status") != payload.get("status"):
            raise GraphWriteError("persisted relation assertion is invalid")
        try:
            for name in ("valid_from", "expires_at"):
                value = payload.get(name)
                if isinstance(value, str):
                    payload[name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                elif value is not None and not isinstance(value, datetime):
                    raise ValueError
            provenance = payload.get("provenance")
            if not isinstance(provenance, dict) or set(provenance) != {item.name for item in fields(Provenance)}:
                raise ValueError
            occurred_at = provenance.get("occurred_at")
            if isinstance(occurred_at, str):
                provenance["occurred_at"] = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            payload["provenance"] = Provenance(**provenance)
            decoded = RelationAssertion(**payload)
        except (TypeError, ValueError, KeyError):
            raise GraphWriteError("persisted relation assertion is invalid") from None
        if _json_value(decoded) != json.loads(raw):
            raise GraphWriteError("persisted relation assertion is invalid")
        return decoded

    def _lock_assertion_families_tx(self, tx: Any, family_ids: set[str]) -> None:
        for family_id in sorted(family_ids):
            row = _single(tx.run(
                "MERGE (l:FounderGraphAssertionFamilyLock {owner_id: $owner_id, family_key: $family_key}) "
                "SET l._dots_relation_write_lock = $lock_token REMOVE l._dots_relation_write_lock "
                "RETURN l.family_key AS family_key",
                owner_id=self.owner_id, family_key=family_id, lock_token=uuid4().hex,
            ))
            if row is None:
                raise GraphWriteError("relation assertion family could not be locked")

    def _save_relation_assertion_tx(
        self, tx: Any, assertion: RelationAssertion, expected_family_revision: int | None,
        key: str, actor: str, fingerprint: str,
    ) -> WriteReceipt:
        replay = self._relation_assertion_receipt(self._relation_assertion_audit_tx(tx, key), assertion, key, fingerprint)
        if replay is not None:
            return replay

        endpoint_ids = (assertion.source_id, assertion.target_id)
        endpoint_rows: dict[str, Any] = {}
        for endpoint_id in dict.fromkeys(endpoint_ids):
            rows = _rows(tx.run(
                "MATCH (n {id: $id}) RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
                "n.status AS status, n.egress_policy AS egress_policy, n.payload_json AS payload_json, n.revision AS revision",
                id=endpoint_id,
            ))
            if not rows:
                raise GraphWriteNotFoundError("relation assertion endpoint does not exist")
            if len(rows) != 1:
                raise GraphWriteError("relation assertion endpoint identity is ambiguous")
            endpoint_rows[endpoint_id] = rows[0]

        declared = {assertion.source_id: assertion.source_kind, assertion.target_id: assertion.target_kind}
        idea_roots = set()
        for endpoint_id, row in endpoint_rows.items():
            if _record_value(row, "owner_id") != self.owner_id:
                raise GraphWriteError("relation assertion endpoints must belong to the local owner")
            if _record_value(row, "node_type") != declared[endpoint_id].value:
                raise GraphWriteError("relation assertion endpoint type does not match its declaration")
            if declared[endpoint_id] is NodeType.IDEA:
                idea_roots.add(self._idea_root_for_tx(tx, endpoint_id))
        for root_id in sorted(idea_roots):
            self._lock_idea_tx(tx, root_id)
        for idea_id in sorted(endpoint_id for endpoint_id, kind in declared.items() if kind is NodeType.IDEA):
            self._lock_idea_tx(tx, idea_id)

        prior_hint = None
        if assertion.supersedes_id is not None:
            prior_hint = self._relation_assertion_record_tx(tx, assertion.supersedes_id)
            prior_decoded_hint = self._decode_relation_assertion_record(prior_hint)
            family_ids = {assertion.assertion_family_id, prior_decoded_hint.assertion_family_id}
        else:
            prior_decoded_hint = None
            family_ids = {assertion.assertion_family_id}
        self._lock_assertion_families_tx(tx, family_ids)
        replay = self._relation_assertion_receipt(self._relation_assertion_audit_tx(tx, key), assertion, key, fingerprint)
        if replay is not None:
            return replay

        collision = _single(tx.run(
            "MATCH (n {id: $id}) RETURN n.owner_id AS owner_id, n.node_type AS node_type",
            id=assertion.id,
        ))
        if collision is not None:
            raise NodeAlreadyExistsError("relation assertion id is already registered")

        resolved_ideas = []
        for endpoint_id, row in endpoint_rows.items():
            try:
                kind = NodeType(_record_value(row, "node_type"))
            except (TypeError, ValueError):
                raise GraphWriteError("relation assertion endpoint type is invalid") from None
            status_text = _record_value(row, "status")
            inactive = {
                Status.ARCHIVED.value, Status.SUPERSEDED.value, Status.RETRACTED.value,
                Status.EXPIRED.value, Status.CANCELLED.value, Status.REVOKED.value, Status.FAILED.value,
            }
            if status_text in inactive:
                raise GraphWriteError("relation assertion endpoint is not current and active")
            if assertion.egress_policy is EgressPolicy.SHAREABLE and _record_value(
                row, "egress_policy"
            ) != EgressPolicy.SHAREABLE.value:
                raise GraphWriteError("shareable relation assertion requires shareable endpoints")
            if kind is NodeType.IDEA:
                root_id = next(root for root in idea_roots if endpoint_id == root or self._idea_root_for_tx(tx, endpoint_id) == root)
                chain = self._idea_chain_tx(tx, root_id)
                endpoint = next((idea for idea in chain if idea.id == endpoint_id), None)
                if endpoint is None or chain[-1].id != endpoint_id:
                    raise GraphWriteError("relation assertion must reference the current Idea revision")
                resolved_ideas.append(endpoint)
            else:
                successors = _rows(tx.run(
                    "MATCH (n {owner_id: $owner_id, supersedes_id: $node_id}) RETURN n.id AS id",
                    owner_id=self.owner_id, node_id=endpoint_id,
                ))
                if successors:
                    raise GraphWriteError("relation assertion endpoint has a superseding revision")

        if not assertion.evidence_ids:
            raise GraphWriteError("formal relation assertion requires Evidence")
        for evidence_id in assertion.evidence_ids:
            evidence = _single(tx.run(
                "MATCH (e:Evidence {id: $id}) RETURN e.owner_id AS owner_id, e.node_type AS node_type, "
                "e.status AS status, e.egress_policy AS egress_policy",
                id=evidence_id,
            ))
            if evidence is None or _record_value(evidence, "owner_id") != self.owner_id:
                raise GraphWriteNotFoundError("relation assertion Evidence does not exist")
            if _record_value(evidence, "node_type") != NodeType.EVIDENCE.value:
                raise GraphWriteError("relation assertion Evidence has an invalid type")
            if _record_value(evidence, "status") != Status.ACTIVE.value:
                raise GraphWriteError("relation assertion Evidence must be active")
            if assertion.egress_policy is EgressPolicy.SHAREABLE and _record_value(
                evidence, "egress_policy"
            ) != EgressPolicy.SHAREABLE.value:
                raise GraphWriteError("shareable relation assertion requires shareable Evidence")

        primary_idea = next((idea for idea in resolved_ideas if idea.id == assertion.source_id), None)
        if primary_idea is None and resolved_ideas:
            primary_idea = next(idea for idea in resolved_ideas if idea.id == assertion.target_id)
        if primary_idea is not None:
            if assertion.based_on_brief_id is None:
                raise GraphWriteError("Idea relation requires the exact latest researched Brief")
            self._validate_latest_researched_brief_tx(
                tx, primary_idea_id=primary_idea.id, owner_id=self.owner_id,
                brief_id=assertion.based_on_brief_id,
                section_index=assertion.based_on_brief_section_index,
                evidence_ids=assertion.evidence_ids,
                locked_ideas=tuple(resolved_ideas),
            )
        elif assertion.based_on_brief_id is not None:
            raise GraphWriteError("non-Idea relation cannot claim an Idea Brief reference")

        family_rows = _rows(tx.run(
            "MATCH (n:RelationAssertion {owner_id: $owner_id, assertion_family_id: $family_key}) "
            "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, n.revision AS revision, "
            "n.status AS status, n.assertion_family_id AS assertion_family_id, n.supersedes_id AS supersedes_id, "
            "n.payload_json AS payload_json ORDER BY n.revision ASC",
            owner_id=self.owner_id, family_key=assertion.assertion_family_id,
        ))
        family = tuple(self._decode_relation_assertion_record(row) for row in family_rows)
        revisions = tuple(item.revision for item in family)
        if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
            raise GraphWriteError("relation assertion family history is ambiguous")
        actual_revision = revisions[-1] if revisions else None
        if expected_family_revision != actual_revision:
            raise RevisionConflictError("expected relation assertion family revision is stale")

        predecessor = None
        if assertion.supersedes_id is None:
            if family or assertion.revision != 1:
                raise RevisionConflictError("new relation family must start at revision one")
        else:
            predecessor = self._decode_relation_assertion_record(
                self._relation_assertion_record_tx(tx, assertion.supersedes_id)
            )
            if prior_decoded_hint is None or predecessor.assertion_family_id != prior_decoded_hint.assertion_family_id:
                raise RevisionConflictError("relation assertion predecessor changed during write")
            successors = _rows(tx.run(
                "MATCH (n:RelationAssertion {owner_id: $owner_id, supersedes_id: $predecessor_id}) RETURN n.id AS id",
                owner_id=self.owner_id, predecessor_id=predecessor.id,
            ))
            if successors:
                raise GraphWriteError("relation assertion predecessor already has a successor")
            if predecessor.assertion_family_id == assertion.assertion_family_id:
                if predecessor.revision != actual_revision or assertion.revision != predecessor.revision + 1:
                    raise RevisionConflictError("same-family correction must extend the exact latest revision")
                if (predecessor.source_id, predecessor.predicate, predecessor.target_id) != (
                    assertion.source_id, assertion.predicate, assertion.target_id
                ):
                    raise GraphWriteError("same-family correction cannot change endpoints or predicate")
            elif family or assertion.revision != 1:
                raise RevisionConflictError("changed relation family must start at revision one")
            elif (predecessor.source_id, predecessor.predicate, predecessor.target_id) == (
                assertion.source_id, assertion.predicate, assertion.target_id
            ):
                raise GraphWriteError("unchanged relation must remain in its existing family")

        try:
            structural_edges = relation_assertion_structural_edges(assertion)
        except DomainValidationError as error:
            raise GraphWriteError(str(error)) from error
        tx.run("CREATE (n:RelationAssertion) SET n = $properties", properties=_node_properties(assertion))
        for source_id, edge_type, target_id in structural_edges:
            if edge_type not in {value.value for value in RelationAssertionEdgeType}:
                raise GraphWriteError("relation assertion structural edge is not allowlisted")
            created = _single(tx.run(
                f"MATCH (a:RelationAssertion {{id: $assertion_id, owner_id: $owner_id}}), "
                "(b {id: $target_id, owner_id: $owner_id}) "
                f"CREATE (a)-[r:{edge_type} {{owner_id: $owner_id}}]->(b) RETURN a.id AS id",
                assertion_id=assertion.id, source_id=source_id, target_id=target_id,
                owner_id=self.owner_id, edge_type=edge_type,
            ))
            if created is None:
                raise GraphWriteNotFoundError("relation assertion structural reference does not exist")
        if predecessor is not None and predecessor.status is not RelationshipStatus.REJECTED:
            updated = replace(predecessor, status=RelationshipStatus.SUPERSEDED)
            properties = _node_properties(updated)
            tx.run(
                "MATCH (n:RelationAssertion {id: $id, owner_id: $owner_id}) "
                "SET n += $properties RETURN n.id AS id",
                id=predecessor.id, owner_id=self.owner_id,
                properties=properties,
            )
        receipt = WriteReceipt(
            "save_relation_assertion", assertion.id, NodeType.RELATION_ASSERTION.value,
            assertion.revision, key,
        )
        tx.run(
            "CREATE (a:FounderGraphAudit {id: $audit_id, owner_id: $owner_id, actor: $actor, "
            "operation: $operation, target_id: $target_id, target_type: $target_type, revision: $revision, "
            "idempotency_key: $idempotency_key, payload_fingerprint: $payload_fingerprint})",
            audit_id=f"audit_{sha256(f'{self.owner_id}:{key}'.encode()).hexdigest()[:32]}",
            owner_id=self.owner_id, actor=actor, operation=receipt.operation,
            target_id=receipt.target_id, target_type=receipt.target_type, revision=receipt.revision,
            idempotency_key=key, payload_fingerprint=fingerprint,
        )
        return receipt

    def _link_tx(self, tx: Any, relationship: Relationship, relation_type: str, idempotency_key: str, actor: str, fingerprint: str) -> WriteReceipt:
        replay = _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $idempotency_key}) "
            "RETURN a.payload_fingerprint AS payload_fingerprint, a.target_id AS target_id",
            owner_id=self.owner_id, idempotency_key=idempotency_key,
        ))
        if replay is not None:
            prior = replay.get("payload_fingerprint") if isinstance(replay, Mapping) else replay["payload_fingerprint"]
            if prior != fingerprint:
                raise IdempotencyConflictError("idempotency key was reused with a different payload")
            target = replay.get("target_id") if isinstance(replay, Mapping) else replay["target_id"]
            return WriteReceipt("link_entities", target, "relationship", 0, idempotency_key, replayed=True)
        endpoints = _single(tx.run(
            "MATCH (a {id: $source_id}), (b {id: $target_id}) "
            "RETURN a.owner_id AS source_owner, b.owner_id AS target_owner, "
            "a.node_type AS source_type, b.node_type AS target_type",
            source_id=relationship.source_id, target_id=relationship.target_id,
        ))
        if endpoints is None:
            raise GraphWriteNotFoundError("relationship endpoints must already exist")
        source_owner = endpoints.get("source_owner") if isinstance(endpoints, Mapping) else endpoints["source_owner"]
        target_owner = endpoints.get("target_owner") if isinstance(endpoints, Mapping) else endpoints["target_owner"]
        if source_owner != self.owner_id or target_owner != self.owner_id:
            raise GraphWriteError("relationship endpoints must belong to the local owner")
        source_type = endpoints.get("source_type") if isinstance(endpoints, Mapping) else endpoints["source_type"]
        target_type = endpoints.get("target_type") if isinstance(endpoints, Mapping) else endpoints["target_type"]
        if (NodeType(source_type), NodeType(target_type)) not in _ALLOWED_RELATION_ENDPOINTS[relationship.relation]:
            raise GraphWriteError("relationship endpoint types are not allowlisted")
        relation_id = fingerprint
        tx.run(
            f"MATCH (a {{id: $source_id, owner_id: $owner_id}}), (b {{id: $target_id, owner_id: $owner_id}}) "
            f"CREATE (a)-[r:{relation_type} {{id: $relation_id, owner_id: $owner_id, "
            "status: $status, confidence: $confidence, evidence_ids_json: $evidence_ids_json}}]->(b)",
            source_id=relationship.source_id,
            target_id=relationship.target_id,
            owner_id=self.owner_id,
            relation_id=relation_id,
            status=relationship.status.value,
            confidence=relationship.confidence,
            evidence_ids_json=json.dumps(list(relationship.evidence_ids), ensure_ascii=False),
        )
        tx.run(
            "CREATE (a:FounderGraphAudit {id: $audit_id, owner_id: $owner_id, actor: $actor, "
            "operation: 'link_entities', target_id: $target_id, target_type: 'relationship', "
            "revision: 0, idempotency_key: $idempotency_key, payload_fingerprint: $payload_fingerprint})",
            audit_id=f"audit_{sha256(f'{self.owner_id}:{idempotency_key}'.encode()).hexdigest()[:32]}",
            owner_id=self.owner_id, actor=actor, target_id=relation_id,
            idempotency_key=idempotency_key, payload_fingerprint=fingerprint,
        )
        return WriteReceipt("link_entities", relation_id, "relationship", 0, idempotency_key)


__all__ = [
    "Neo4jGatewayError",
    "Neo4jGraphGateway",
    "Neo4jQueryContractError",
    "Neo4jUnavailableError",
]
