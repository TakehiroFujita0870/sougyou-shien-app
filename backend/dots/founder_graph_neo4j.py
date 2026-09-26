"""Parameterized Neo4j gateway for the local Founder Graph.

The gateway intentionally exposes typed write methods only.  It accepts a
driver-like object so contract tests do not need a running database; the real
``neo4j.Driver`` is injected by the application composition root later.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Iterator, Mapping

from .founder_graph import (
    ContentChunk,
    NodeType,
    ReportVersion,
    Relationship,
    RelationType,
    Source,
    SourceRevision,
    build_content_chunks,
    validate_source_revision_history,
    _ALLOWED_RELATION_ENDPOINTS,
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
)
from .founder_graph_schema import SCHEMA_VERSION, migration_queries, rollback_queries
from .founder_graph_read import _FIELD_ALLOWLIST


class Neo4jGatewayError(GraphWriteError):
    """Base class for recoverable gateway failures."""


class Neo4jUnavailableError(Neo4jGatewayError):
    """The injected driver could not open or complete a session."""


class Neo4jQueryContractError(Neo4jGatewayError):
    """A gateway operation would require a query outside the static contract."""


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
    elif node_type is NodeType.SOURCE_REVISION:
        properties["source_id"] = str(node.source_id)
        supersedes_id = getattr(node, "supersedes_id", None)
        if supersedes_id is not None:
            properties["supersedes_id"] = str(supersedes_id)
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
                    "n.revision AS revision, n.payload_json AS payload_json LIMIT 1",
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
        replay = _single(tx.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner_id, idempotency_key: $idempotency_key}) "
            "RETURN a.payload_fingerprint AS payload_fingerprint, a.target_id AS target_id, "
            "a.target_type AS target_type, a.revision AS revision",
            owner_id=self.owner_id,
            idempotency_key=idempotency_key,
        ))
        if replay is not None:
            prior = replay.get("payload_fingerprint") if isinstance(replay, Mapping) else replay["payload_fingerprint"]
            if prior != fingerprint:
                raise IdempotencyConflictError("idempotency key was reused with a different payload")
            target_id = replay.get("target_id") if isinstance(replay, Mapping) else replay["target_id"]
            target_type = replay.get("target_type") if isinstance(replay, Mapping) else replay["target_type"]
            revision = replay.get("revision", 0) if isinstance(replay, Mapping) else replay.get("revision", 0)
            return WriteReceipt(operation, target_id, target_type, revision, idempotency_key, replayed=True)

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
