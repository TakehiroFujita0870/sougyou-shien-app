"""Owner-scoped, read-only Neo4j adapter for the Founder Graph.

The write gateway stores each domain value as ``payload_json``.  This adapter
deliberately hydrates only the public read contract (``NodeView`` and
``SearchPage``); it does not reconstruct domain dataclasses or expose Cypher.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
import json
from time import monotonic
from types import MappingProxyType
from typing import Any, Mapping

from .founder_graph import (
    DomainValidationError,
    EgressPolicy,
    Evidence,
    NodeType,
    Provenance,
    RelationAssertion,
    RelationAssertionEdgeType,
    RelationType,
    RelationshipStatus,
    Status,
    relation_assertion_structural_edges,
)
from .founder_graph_neo4j import (
    Neo4jGraphGateway,
    GraphWriteError,
    GraphWriteNotFoundError,
    Neo4jQueryContractError,
    Neo4jUnavailableError,
    _single,
)
from .founder_graph_read import (
    GraphReadError,
    GraphReadNotFoundError,
    GraphReadTimeoutError,
    GraphReadUnavailableError,
    NodeView,
    RelationPathStep,
    SearchHit,
    SearchPage,
    _FIELD_ALLOWLIST,
    _NON_CURRENT,
    _tokens,
)
from .idea_brief import SECTION_TITLES


class Neo4jReadUnavailableError(GraphReadUnavailableError):
    """The injected Neo4j driver could not complete a read operation."""


@dataclass(frozen=True, slots=True)
class GraphRelationView:
    source_id: str
    relation: str
    target_id: str
    source_node_type: str
    target_node_type: str


_FETCH_QUERY = (
    "MATCH (n) WHERE n.id = $node_id AND n.owner_id = $owner_id "
    "AND NOT coalesce(n.status, '') IN $non_current "
    "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
    "n.status AS status, n.revision AS revision, n.payload_json AS payload_json, "
    "n.search_text AS search_text LIMIT 1"
)

_SEARCH_QUERY = (
    "MATCH (n) WHERE n.owner_id = $owner_id AND n.node_type IN $searchable_node_types "
    "AND NOT coalesce(n.status, '') IN $non_current "
    "AND any(token IN $tokens WHERE toLower(coalesce(n.search_text, '')) CONTAINS token) "
    "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
    "n.status AS status, n.revision AS revision, n.payload_json AS payload_json, "
    "n.search_text AS search_text"
)

_SEARCH_RELATIONS_QUERY = (
    "MATCH (a)-[r]->(b) "
    "WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id "
    "AND NOT coalesce(a.status, '') IN $non_current "
    "AND NOT coalesce(b.status, '') IN $non_current "
    "AND a.node_type IN $searchable_node_types AND b.node_type IN $searchable_node_types "
    "AND NOT type(r) IN $assertion_edge_types AND NOT type(r) IN $internal_edge_types "
    "AND (a.id IN $matched_ids OR b.id IN $matched_ids) "
    "RETURN a.id AS source_id, type(r) AS relation, r.evidence_ids_json AS evidence_ids_json, b.id AS target_id, "
    "a.owner_id AS source_owner_id, a.node_type AS source_node_type, "
    "a.status AS source_status, a.revision AS source_revision, "
    "a.payload_json AS source_payload_json, a.search_text AS source_search_text, "
    "b.owner_id AS target_owner_id, b.node_type AS target_node_type, "
    "b.status AS target_status, b.revision AS target_revision, "
    "b.payload_json AS target_payload_json, b.search_text AS target_search_text"
)

_INTERNAL_GRAPH_EDGES = frozenset({
    "HAS_SOURCE_REVISION", "CURRENT_SOURCE_REVISION", "HAS_CHUNK", "EVIDENCE_FROM",
})

_SEARCH_FORMAL_ASSERTIONS_QUERY = (
    "MATCH (a:RelationAssertion {owner_id: $owner_id}) "
    "OPTIONAL MATCH (a)-[r]-(b) "
    "WHERE b.owner_id = $owner_id "
    "RETURN a.id AS assertion_id, a.owner_id AS assertion_owner_id, "
    "a.node_type AS assertion_node_type, a.revision AS assertion_revision, "
    "a.status AS assertion_status, a.egress_policy AS assertion_egress_policy, "
    "a.payload_json AS assertion_payload_json, type(r) AS relation, "
    "startNode(r) = a AS is_outgoing, b.id AS target_id, b.owner_id AS target_owner_id, "
    "b.node_type AS target_node_type, b.revision AS target_revision, b.status AS target_status, "
    "b.egress_policy AS target_egress_policy, b.payload_json AS target_payload_json, "
    "b.search_text AS target_search_text ORDER BY assertion_id, relation, target_id"
)

_EVIDENCE_LINEAGE_QUERY = (
    "MATCH (e:Evidence {id: $evidence_id, owner_id: $owner_id}) "
    "OPTIONAL MATCH (e)-[ef:EVIDENCE_FROM]->(c) "
    "OPTIONAL MATCH (r:SourceRevision)-[hc:HAS_CHUNK]->(c) "
    "OPTIONAL MATCH (s:Source {id: r.source_id, owner_id: $owner_id}) "
    "OPTIONAL MATCH (s)-[sh:HAS_SOURCE_REVISION]->(r) "
    "OPTIONAL MATCH (s)-[sc:CURRENT_SOURCE_REVISION]->(r) "
    "OPTIONAL MATCH (cl:Claim {id: e.claim_id, owner_id: $owner_id}) "
    "RETURN e.owner_id AS evidence_owner_id, e.status AS evidence_status, "
    "e.egress_policy AS evidence_egress_policy, e.payload_json AS evidence_payload_json, "
    "count(DISTINCT ef) AS evidence_edge_count, count(DISTINCT hc) AS revision_edge_count, "
    "count(DISTINCT sh) AS source_history_edge_count, count(DISTINCT sc) AS source_current_edge_count, "
    "size([(s)-[:CURRENT_SOURCE_REVISION]->() | 1]) AS source_current_edge_total, "
    "collect(DISTINCT {chunk_id: c.id, chunk_labels: labels(c), chunk_owner_id: c.owner_id, chunk_status: c.status, "
    "chunk_source_revision_id: c.source_revision_id, chunk_payload_json: c.payload_json, "
    "revision_id: r.id, revision_owner_id: r.owner_id, revision_status: r.status, "
    "revision_payload_json: r.payload_json, source_id: s.id, source_owner_id: s.owner_id, "
    "source_status: s.status, source_payload_json: s.payload_json}) AS lineages, cl.id AS claim_id, "
    "cl.owner_id AS claim_owner_id, cl.status AS claim_status, cl.payload_json AS claim_payload_json"
)

_RELATIONS_QUERY = (
    "MATCH (a)-[r]->(b) "
    "WHERE a.id = $node_id AND a.owner_id = $owner_id AND b.owner_id = $owner_id "
    "AND NOT coalesce(a.status, '') IN $non_current "
    "AND NOT coalesce(b.status, '') IN $non_current "
    "RETURN a.id AS source_id, type(r) AS relation, b.id AS target_id, "
    "a.owner_id AS source_owner_id, b.owner_id AS target_owner_id, "
    "a.node_type AS source_node_type, b.node_type AS target_node_type "
    "ORDER BY source_id, relation, target_id"
)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    getter = getattr(row, "get", None)
    if callable(getter):
        try:
            value = getter(key)
        except (KeyError, TypeError):
            return default
        return default if value is None else value
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _rows(result: Any) -> tuple[Any, ...]:
    if result is None:
        return ()
    try:
        return tuple(result)
    except TypeError:
        row = _single(result)
        return () if row is None else (row,)


def _parse_payload(row: Any, *, prefix: str = "") -> dict[str, Any]:
    raw = _row_value(row, f"{prefix}payload_json")
    if not isinstance(raw, str) or not raw.strip():
        raise GraphReadError("Neo4j node payload is missing")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise GraphReadError("Neo4j node payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise GraphReadError("Neo4j node payload must be a JSON object")
    return payload


def _parse_evidence_ids(row: Any) -> tuple[str, ...]:
    raw = _row_value(row, "evidence_ids_json")
    if raw is None:
        return ()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise GraphReadError("Neo4j relation evidence ids are not valid JSON") from error
    if not isinstance(raw, (list, tuple)):
        raise GraphReadError("Neo4j relation evidence ids must be a list")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise GraphReadError("Neo4j relation evidence id is invalid")
        if item.strip() not in values:
            values.append(item.strip())
    return tuple(values)


def _view_from_row(row: Any, *, owner_id: str, prefix: str = "", strict: bool = True) -> NodeView | None:
    payload = _parse_payload(row, prefix=prefix)
    node_id = _row_value(row, f"{prefix}id", payload.get("id"))
    row_owner = _row_value(row, f"{prefix}owner_id", payload.get("owner_id"))
    if not isinstance(node_id, str) or not node_id or row_owner != owner_id:
        if strict:
            raise GraphReadNotFoundError("node was not found")
        return None
    raw_type = _row_value(row, f"{prefix}node_type", payload.get("node_type"))
    try:
        node_type = raw_type if isinstance(raw_type, NodeType) else NodeType(raw_type)
    except (TypeError, ValueError) as error:
        raise GraphReadError("Neo4j node type is not in the Founder Graph allowlist") from error

    field_names = _FIELD_ALLOWLIST[node_type]
    if node_type is NodeType.EVIDENCE and payload.get("content_chunk_id") is not None:
        field_names = ("polarity", "confidence", "content_hash", "status", "egress_policy")
    values = {
        field_name: payload[field_name]
        for field_name in field_names
        if field_name in payload
    }
    status = values.get("status", _row_value(row, f"{prefix}status"))
    status_value = status.value if hasattr(status, "value") else status
    if status_value in _NON_CURRENT:
        if strict:
            raise GraphReadNotFoundError("node was not found")
        return None
    if status_value is not None and not isinstance(status_value, str):
        status_value = str(status_value)
    values["status"] = status_value
    revision = values.get("revision", _row_value(row, f"{prefix}revision", 0))
    if not isinstance(revision, int) or isinstance(revision, bool):
        revision = 0
    title = next(
        (
            str(values[key])
            for key in ("title", "name", "display_name", "text", "purpose", "path")
            if values.get(key)
        ),
        node_id,
    )
    snippet_source = next(
        (
            str(values[key])
            for key in ("summary", "description", "content", "excerpt", "text", "purpose")
            if values.get(key)
        ),
        title,
    )
    return NodeView(
        id=node_id,
        node_type=node_type.value,
        owner_id=owner_id,
        title=title,
        snippet=snippet_source[:320],
        status=status_value,
        revision=revision,
        fields=MappingProxyType(values),
    )


def _required_owner(owner_id: str) -> str:
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise GraphReadError("owner_id is required")
    return owner_id.strip()


def _required_node_id(node_id: str) -> str:
    if not isinstance(node_id, str) or not node_id.strip():
        raise GraphReadError("node_id is required")
    return node_id.strip()


def _aware_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _decode_assertion(row: Any, *, owner_id: str) -> RelationAssertion:
    payload = _parse_payload(row, prefix="assertion_")
    names = {item.name for item in fields(RelationAssertion)}
    if set(payload) != names:
        raise ValueError("assertion payload fields are incomplete")
    if _row_value(row, "assertion_id") != payload.get("id"):
        raise ValueError("assertion id does not match its payload")
    if _row_value(row, "assertion_owner_id") != owner_id or payload.get("owner_id") != owner_id:
        raise ValueError("assertion owner does not match")
    if _row_value(row, "assertion_node_type") != NodeType.RELATION_ASSERTION.value:
        raise ValueError("assertion node type does not match")
    if not isinstance(payload.get("provenance"), dict):
        raise ValueError("assertion provenance is malformed")
    provenance = dict(payload["provenance"])
    if set(provenance) != {item.name for item in fields(Provenance)}:
        raise ValueError("assertion provenance fields are incomplete")
    provenance["occurred_at"] = _aware_time(provenance.get("occurred_at"))
    payload["provenance"] = Provenance(**provenance)
    payload["valid_from"] = _aware_time(payload.get("valid_from"))
    if payload.get("expires_at") is not None:
        payload["expires_at"] = _aware_time(payload["expires_at"])
    assertion = RelationAssertion(**payload)
    scalar_values = {
        "assertion_revision": assertion.revision,
        "assertion_status": assertion.status.value,
        "assertion_egress_policy": assertion.egress_policy.value,
    }
    if any(_row_value(row, key) != value for key, value in scalar_values.items()):
        raise ValueError("assertion metadata does not match its payload")
    return assertion


def _checked_ref_view(row: Any, *, owner_id: str) -> NodeView:
    payload = _parse_payload(row, prefix="target_")
    expected = {
        "id": _row_value(row, "target_id"),
        "owner_id": _row_value(row, "target_owner_id"),
        "status": _row_value(row, "target_status"),
        "egress_policy": _row_value(row, "target_egress_policy"),
    }
    node_type = _row_value(row, "target_node_type")
    revision = _row_value(row, "target_revision")
    if (
        any(payload.get(key) != value for key, value in expected.items())
        or expected["owner_id"] != owner_id
        or ("node_type" in payload and payload.get("node_type") != node_type)
        or ("revision" in payload and payload.get("revision") != revision)
        or ("revision" not in payload and revision != 0)
    ):
        raise ValueError("assertion endpoint metadata does not match its payload")
    view = _view_from_row(row, owner_id=owner_id, prefix="target_")
    if view is None or view.fields.get("egress_policy") != EgressPolicy.SHAREABLE.value:
        raise ValueError("assertion endpoint is not shareable")
    return view


class Neo4jGraphReadService:
    """Read-only NodeView/SearchPage boundary over an injected gateway."""

    def __init__(self, gateway: Neo4jGraphGateway) -> None:
        if not isinstance(gateway, Neo4jGraphGateway):
            raise GraphReadError("a Neo4jGraphGateway is required")
        self._gateway = gateway

    @property
    def owner_id(self) -> str:
        """Expose the owner bound to the injected Neo4j gateway."""

        return self._gateway.owner_id

    def _formal_adjacency(self, tx: Any, *, owner_id: str, at: datetime, started: float, timeout_ms: int):
        grouped: dict[str, list[Any]] = {}
        rows = _rows(tx.run(_SEARCH_FORMAL_ASSERTIONS_QUERY, owner_id=owner_id))
        for row in rows:
            self._check_timeout(started, timeout_ms)
            assertion_id = _row_value(row, "assertion_id")
            if isinstance(assertion_id, str) and assertion_id:
                grouped.setdefault(assertion_id, []).append(row)

        successors: set[str] = set()
        for assertion_rows in grouped.values():
            try:
                payload = _parse_payload(assertion_rows[0], prefix="assertion_")
            except GraphReadError:
                continue
            predecessor = payload.get("supersedes_id")
            if isinstance(predecessor, str) and predecessor:
                successors.add(predecessor)
            for row in assertion_rows:
                if _row_value(row, "relation") == RelationAssertionEdgeType.SUPERSEDES.value:
                    ref = _row_value(row, "target_id")
                    if _row_value(row, "is_outgoing") is True and isinstance(ref, str):
                        successors.add(ref)

        adjacency: dict[str, list[tuple[str, RelationPathStep]]] = {}
        views: dict[str, NodeView] = {}
        for assertion_rows in grouped.values():
            self._check_timeout(started, timeout_ms)
            try:
                assertion = _decode_assertion(assertion_rows[0], owner_id=owner_id)
                if assertion.id in successors or assertion.status not in {
                    RelationshipStatus.PROPOSED, RelationshipStatus.INFERRED, RelationshipStatus.CONFIRMED,
                } or assertion.egress_policy is not EgressPolicy.SHAREABLE:
                    continue
                if assertion.valid_from > at or (assertion.expires_at is not None and assertion.expires_at <= at):
                    continue
                if assertion.source_id == assertion.target_id:
                    continue
                expected_edges = relation_assertion_structural_edges(assertion)
                actual_edges: list[tuple[str, str, str]] = []
                ref_views: dict[str, NodeView] = {}
                valid = len(assertion_rows) == len(expected_edges)
                for row in assertion_rows:
                    relation = _row_value(row, "relation")
                    target_id = _row_value(row, "target_id")
                    is_outgoing = _row_value(row, "is_outgoing")
                    if relation is None and target_id is None:
                        continue
                    if not isinstance(relation, str) or not isinstance(target_id, str) or is_outgoing is not True:
                        valid = False
                        continue
                    actual_edges.append((assertion.id, relation, target_id))
                    view = _checked_ref_view(row, owner_id=owner_id)
                    prior = ref_views.get(view.id)
                    if prior is not None and prior != view:
                        valid = False
                    ref_views[view.id] = view
                if (
                    not valid
                    or len(actual_edges) != len(set(actual_edges))
                    or set(actual_edges) != set(expected_edges)
                ):
                    continue
                source = ref_views.get(assertion.source_id)
                target = ref_views.get(assertion.target_id)
                if source is None or target is None:
                    continue
                if source.node_type != assertion.source_kind.value or target.node_type != assertion.target_kind.value:
                    continue
                if any(view.status in _NON_CURRENT for view in (source, target)):
                    continue
                idea_ends = [view for view in (source, target) if view.node_type == NodeType.IDEA.value]
                for idea in idea_ends:
                    root_id = self._gateway._idea_root_for_tx(tx, idea.id)
                    chain = self._gateway._idea_chain_tx(tx, root_id)
                    if not chain or chain[-1].id != idea.id:
                        raise ValueError("Idea endpoint is not its current leaf")
                if idea_ends:
                    if assertion.based_on_brief_id is None or assertion.based_on_brief_section_index is None:
                        continue
                    primary = source if source.node_type == NodeType.IDEA.value else target
                    root_id = self._gateway._idea_root_for_tx(tx, primary.id)
                    briefs = self._gateway._idea_briefs_for_root_tx(tx, root_id)
                    if not briefs:
                        continue
                    latest = briefs[-1]
                    section_index = assertion.based_on_brief_section_index
                    if (
                        latest.id != assertion.based_on_brief_id
                        or latest.based_on_idea_id != primary.id
                        or not latest.research_run_ids
                        or type(section_index) is not int
                        or not 0 <= section_index < len(latest.sections)
                    ):
                        continue
                    section = latest.sections[section_index]
                    if (
                        not section.content.strip()
                        or not set(assertion.evidence_ids).issubset(section.evidence_ids)
                    ):
                        continue
                    brief_id, brief_section = latest.id, section_index
                elif assertion.based_on_brief_id is not None or assertion.based_on_brief_section_index is not None:
                    continue
                else:
                    brief_id, brief_section = None, None
                evidence_views = [ref_views.get(item) for item in assertion.evidence_ids]
                if any(
                    not isinstance(view, NodeView)
                    or view.node_type != NodeType.EVIDENCE.value
                    or view.status != Status.ACTIVE.value
                    or view.fields.get("egress_policy") != EgressPolicy.SHAREABLE.value
                    or not self._evidence_lineage_valid(tx, evidence_id=evidence_id, owner_id=owner_id)
                    for evidence_id, view in zip(assertion.evidence_ids, evidence_views, strict=True)
                ):
                    continue
                step = RelationPathStep(
                    from_id=source.id, to_id=target.id, source_id=source.id,
                    predicate=assertion.predicate.value, target_id=target.id,
                    traversal_direction="outgoing", evidence_ids=tuple(assertion.evidence_ids),
                    status=assertion.status.value, confidence=assertion.confidence,
                    valid_from=assertion.valid_from.isoformat(),
                    expires_at=assertion.expires_at.isoformat() if assertion.expires_at else None,
                    relation_assertion_id=assertion.id, based_on_brief_id=brief_id,
                    based_on_brief_section_index=brief_section,
                )
                adjacency.setdefault(source.id, []).append((target.id, step))
                adjacency.setdefault(target.id, []).append((source.id, replace(
                    step, from_id=target.id, to_id=source.id, traversal_direction="incoming",
                )))
                views[source.id] = source
                views[target.id] = target
            except (GraphReadError, GraphWriteError, DomainValidationError, TypeError, ValueError, KeyError):
                continue
        return adjacency, views

    @staticmethod
    def _evidence_lineage_valid(tx: Any, *, evidence_id: str, owner_id: str) -> bool:
        rows = _rows(tx.run(_EVIDENCE_LINEAGE_QUERY, evidence_id=evidence_id, owner_id=owner_id))
        if len(rows) != 1:
            return False
        row = rows[0]
        try:
            evidence = json.loads(_row_value(row, "evidence_payload_json"))
            lineages = _row_value(row, "lineages")
            claim = json.loads(_row_value(row, "claim_payload_json"))
        except (TypeError, ValueError):
            return False
        if (
            not isinstance(evidence, dict)
            or evidence.get("id") != evidence_id
            or evidence.get("owner_id") != owner_id
            or evidence.get("status") != Status.ACTIVE.value
            or evidence.get("egress_policy") != EgressPolicy.SHAREABLE.value
            or evidence.get("claim_id") is None
            or evidence.get("content_chunk_id") is None
            or evidence.get("source_revision_id") is None
            or evidence.get("material_id") is not None
            or evidence.get("excerpt") != ""
            or _row_value(row, "evidence_owner_id") != owner_id
            or _row_value(row, "evidence_status") != Status.ACTIVE.value
            or _row_value(row, "evidence_egress_policy") != EgressPolicy.SHAREABLE.value
            or _row_value(row, "evidence_edge_count") != 1
            or _row_value(row, "revision_edge_count") != 1
            or _row_value(row, "source_history_edge_count") != 1
            or _row_value(row, "source_current_edge_count") != 1
            or _row_value(row, "source_current_edge_total") != 1
            or _row_value(row, "claim_id") != evidence.get("claim_id")
            or _row_value(row, "claim_owner_id") != owner_id
            or _row_value(row, "claim_status") != Status.ACTIVE.value
            or not isinstance(lineages, list)
            or len(lineages) != 1
            or not isinstance(lineages[0], Mapping)
            or not isinstance(claim, dict)
        ):
            return False
        lineage = lineages[0]
        try:
            chunk = json.loads(lineage["chunk_payload_json"])
            revision = json.loads(lineage["revision_payload_json"])
            source = json.loads(lineage["source_payload_json"])
        except (KeyError, TypeError, ValueError):
            return False
        chunk_id = evidence["content_chunk_id"]
        revision_id = evidence["source_revision_id"]
        claim_id = evidence["claim_id"]
        return (
            isinstance(chunk, dict)
            and isinstance(revision, dict)
            and isinstance(source, dict)
            and lineage.get("chunk_id") == chunk_id == chunk.get("id")
            and isinstance(lineage.get("chunk_labels"), (list, tuple))
            and "ContentChunk" in lineage.get("chunk_labels", ())
            and lineage.get("chunk_owner_id") == owner_id == chunk.get("owner_id")
            and lineage.get("chunk_status") == Status.ACTIVE.value == chunk.get("status")
            and (lineage.get("chunk_source_revision_id") is None or lineage.get("chunk_source_revision_id") == revision_id)
            and revision_id == chunk.get("source_revision_id")
            and lineage.get("revision_id") == revision_id == revision.get("id")
            and lineage.get("revision_owner_id") == owner_id == revision.get("owner_id")
            and lineage.get("revision_status") == Status.ACTIVE.value == revision.get("status")
            and lineage.get("source_id") == revision.get("source_id")
            and lineage.get("source_owner_id") == owner_id
            and lineage.get("source_status") == Status.ACTIVE.value
            and claim.get("id") == claim_id
            and claim.get("owner_id") == owner_id
            and claim.get("status") == Status.ACTIVE.value
            and evidence.get("locator") == f"chars:{evidence.get('char_start')}-{evidence.get('char_end')}"
            and evidence.get("content_hash") == chunk.get("text_hash")
            and source.get("id") == lineage.get("source_id")
            and source.get("owner_id") == owner_id
            and source.get("status") == Status.ACTIVE.value
            and source.get("current_revision_id") == revision_id
        )

    @contextmanager
    def _read_session(self):
        try:
            with self._gateway._session() as session:
                yield session
        except Neo4jUnavailableError as error:
            raise Neo4jReadUnavailableError("Neo4j read is unavailable") from error

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        identifier = _required_node_id(node_id)
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            raise GraphReadNotFoundError("node was not found")
        with self._read_session() as session:
            result = self._gateway._execute_read(
                session,
                lambda tx: _rows(tx.run(
                    _FETCH_QUERY,
                    node_id=identifier,
                    owner_id=owner,
                    non_current=sorted(_NON_CURRENT),
                )),
            )
            rows = tuple(result)
        if not rows:
            raise GraphReadNotFoundError("node was not found")
        view = _view_from_row(rows[0], owner_id=owner)
        if view is None:
            raise GraphReadNotFoundError("node was not found")
        return view

    def fetch_idea_brief(self, idea_id: str, *, owner_id: str) -> dict[str, Any]:
        identifier = _required_node_id(idea_id)
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            raise GraphReadNotFoundError("idea brief was not found")

        def read(tx: Any) -> dict[str, Any] | None:
            if self._gateway._idea_record_tx(tx, identifier) is None:
                return None
            try:
                root_id = self._gateway._idea_root_for_tx(tx, identifier)
                chain = self._gateway._idea_chain_tx(tx, root_id)
            except GraphWriteNotFoundError:
                return None
            if not chain or chain[-1].id != identifier:
                return None
            idea = chain[-1]
            if (
                idea.status.value in _NON_CURRENT
                or idea.egress_policy is not EgressPolicy.SHAREABLE
            ):
                return None
            briefs = self._gateway._idea_briefs_for_root_tx(tx, root_id)
            if not briefs:
                return None
            latest = briefs[-1]
            if (
                latest.owner_id != owner
                or latest.idea_lineage_root_id != root_id
                or latest.based_on_idea_id != idea.id
                or latest.egress_policy != EgressPolicy.SHAREABLE.value
            ):
                return None
            sections = []
            for section in latest.sections:
                safe_evidence_ids = [
                    evidence_id for evidence_id in section.evidence_ids
                    if self._evidence_lineage_valid(tx, evidence_id=evidence_id, owner_id=owner)
                ]
                sections.append({
                    "index": section.index,
                    "title": SECTION_TITLES[section.index],
                    "content": section.content,
                    "evidence_ids": safe_evidence_ids,
                })
            return {"brief_id": latest.id, "idea_id": idea.id, "sections": sections}

        with self._read_session() as session:
            projection = self._gateway._execute_read(session, read)
        if projection is None:
            raise GraphReadNotFoundError("idea brief was not found")
        return projection

    def fetch_relation_assertion(self, node_id: str, *, owner_id: str) -> RelationPathStep:
        identifier = _required_node_id(node_id)
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            raise GraphReadNotFoundError("node was not found")
        started = monotonic()
        with self._read_session() as session:
            step = self._gateway._execute_read(
                session,
                lambda tx: next((step for neighbors in self._formal_adjacency(
                    tx, owner_id=owner, at=datetime.now(timezone.utc), started=started, timeout_ms=30_000,
                )[0].values() for _neighbor, step in neighbors
                    if step.relation_assertion_id == identifier and step.traversal_direction == "outgoing"), None),
            )
        if step is None:
            raise GraphReadNotFoundError("node was not found")
        return step

    def search(
        self,
        query: str,
        *,
        owner_id: str,
        limit: int = 20,
        cursor: str | None = None,
        # A restarted Neo4j instance may need to warm its page cache before
        # the first full-text scan. Keep the in-memory contract at 1 second,
        # but give the persistent local database a bounded 5-second budget.
        timeout_ms: int = 5_000,
    ) -> SearchPage:
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise GraphReadError("query must be a non-empty string of at most 512 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise GraphReadError("limit must be between 1 and 50")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= 30_000:
            raise GraphReadError("timeout_ms must be between 1 and 30000")
        offset = self._cursor(cursor)
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            return SearchPage((), None)
        tokens = _tokens(query)
        started = monotonic()
        with self._read_session() as session:
            views, scores, paths, evidence_by_node, relation_paths = self._gateway._execute_read(
                session,
                lambda tx: self._search_tx(tx, query=query, tokens=tokens, owner_id=owner,
                                           started=started, timeout_ms=timeout_ms),
            )

        ordered_ids = sorted(scores, key=lambda node_id: (-scores[node_id], node_id))
        page_ids = ordered_ids[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(ordered_ids) else None
        return SearchPage(
            tuple(
                SearchHit(
                    views[node_id],
                    scores[node_id],
                    paths.get(node_id, ()),
                    evidence_by_node.get(node_id, ()),
                    relation_paths.get(node_id, ()),
                )
                for node_id in page_ids
            ),
            next_cursor,
        )

    def _search_tx(self, tx: Any, *, query: str, tokens: tuple[str, ...], owner_id: str,
                   started: float, timeout_ms: int):
        searchable_types = [node_type.value for node_type in NodeType if node_type is not NodeType.RELATION_ASSERTION]
        views: dict[str, NodeView] = {}
        scores: dict[str, float] = {}
        paths: dict[str, tuple[str, ...]] = {}
        evidence_by_node: dict[str, tuple[str, ...]] = {}
        relation_paths: dict[str, tuple[RelationPathStep, ...]] = {}
        rows = _rows(tx.run(
            _SEARCH_QUERY, owner_id=owner_id, tokens=list(tokens), non_current=sorted(_NON_CURRENT),
            searchable_node_types=searchable_types,
        ))
        for row in rows:
            self._check_timeout(started, timeout_ms)
            view = _view_from_row(row, owner_id=owner_id, strict=False)
            if view is None:
                continue
            views[view.id] = view
            haystack = str(_row_value(row, "search_text", "")).casefold()
            if not haystack:
                haystack = json.dumps(dict(view.fields), ensure_ascii=False, sort_keys=True).casefold()
            matched = sum(1 for token in tokens if token in haystack)
            if matched:
                scores[view.id] = matched / len(tokens) + (0.25 if query.casefold() in haystack else 0.0)

        formal, formal_views = self._formal_adjacency(
            tx, owner_id=owner_id, at=datetime.now(timezone.utc), started=started, timeout_ms=timeout_ms,
        )
        views.update(formal_views)
        frontier = set(scores)
        for _depth in range(1, 3):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for current_id in sorted(frontier):
                current_path = paths.get(current_id, ())
                for neighbor_id, step in sorted(
                    formal.get(current_id, ()),
                    key=lambda item: (item[0], item[1].predicate, item[1].evidence_ids, item[1].relation_assertion_id or ""),
                ):
                    self._check_timeout(started, timeout_ms)
                    if neighbor_id in current_path[0::2]:
                        continue
                    candidate_score = scores[current_id] * 0.5
                    candidate_path = current_path + (step.predicate, neighbor_id) if current_path else (current_id, step.predicate, neighbor_id)
                    if candidate_score <= scores.get(neighbor_id, -1.0):
                        continue
                    prior_steps = relation_paths.get(current_id, ())
                    formal_candidate = not current_path or len(prior_steps) == (len(current_path) - 1) // 2
                    candidate_relation_path = (*prior_steps, step) if formal_candidate else ()
                    candidate_evidence = (
                        tuple(dict.fromkeys(evidence_id for item in candidate_relation_path for evidence_id in item.evidence_ids))
                        if formal_candidate
                        else tuple(dict.fromkeys((*evidence_by_node.get(current_id, ()), *step.evidence_ids)))
                    )
                    scores[neighbor_id] = candidate_score
                    paths[neighbor_id] = candidate_path
                    relation_paths[neighbor_id] = candidate_relation_path
                    evidence_by_node[neighbor_id] = candidate_evidence
                    next_frontier.add(neighbor_id)
            relation_rows = _rows(tx.run(
                _SEARCH_RELATIONS_QUERY, owner_id=owner_id, matched_ids=sorted(frontier),
                non_current=sorted(_NON_CURRENT), searchable_node_types=searchable_types,
                assertion_edge_types=[edge.value for edge in RelationAssertionEdgeType],
                internal_edge_types=sorted(_INTERNAL_GRAPH_EDGES),
            ))
            for row in relation_rows:
                self._check_timeout(started, timeout_ms)
                source = _view_from_row(row, owner_id=owner_id, prefix="source_", strict=False)
                target = _view_from_row(row, owner_id=owner_id, prefix="target_", strict=False)
                if source is None or target is None:
                    continue
                views[source.id] = source
                views[target.id] = target
                relation = _row_value(row, "relation")
                if relation in _INTERNAL_GRAPH_EDGES:
                    continue
                try:
                    relation_name = Neo4jGraphGateway.relation_type_for(relation)
                    edge_evidence = _parse_evidence_ids(row)
                except Neo4jQueryContractError as error:
                    raise GraphReadError("Neo4j relation type is not in the Founder Graph allowlist") from error
                for current, neighbor in ((source, target), (target, source)):
                    if current.id not in frontier:
                        continue
                    current_path = paths.get(current.id, ())
                    if neighbor.id in current_path[0::2]:
                        continue
                    candidate_score = scores[current.id] * 0.5
                    candidate_path = current_path + (relation_name, neighbor.id) if current_path else (current.id, relation_name, neighbor.id)
                    if candidate_score <= scores.get(neighbor.id, -1.0):
                        continue
                    scores[neighbor.id] = candidate_score
                    paths[neighbor.id] = candidate_path
                    relation_paths[neighbor.id] = ()
                    evidence_by_node[neighbor.id] = tuple(dict.fromkeys((*evidence_by_node.get(current.id, ()), *edge_evidence)))
                    next_frontier.add(neighbor.id)
            frontier = next_frontier
        self._check_timeout(started, timeout_ms)
        return views, scores, paths, evidence_by_node, relation_paths

    def relations(self, node_id: str, *, owner_id: str) -> tuple[GraphRelationView, ...]:
        identifier = _required_node_id(node_id)
        owner = _required_owner(owner_id)
        if owner != self._gateway.owner_id:
            raise GraphReadNotFoundError("node was not found")
        self.fetch(identifier, owner_id=owner)
        with self._read_session() as session:
            result = self._gateway._execute_read(
                session,
                lambda tx: _rows(tx.run(
                    _RELATIONS_QUERY,
                    node_id=identifier,
                    owner_id=owner,
                    non_current=sorted(_NON_CURRENT),
                )),
            )
            rows = tuple(result)
        relations: list[GraphRelationView] = []
        for row in rows:
            source_id = _row_value(row, "source_id")
            target_id = _row_value(row, "target_id")
            relation = _row_value(row, "relation")
            source_type = _row_value(row, "source_node_type")
            target_type = _row_value(row, "target_node_type")
            try:
                if (
                    _row_value(row, "source_owner_id") != owner
                    or _row_value(row, "target_owner_id") != owner
                ):
                    raise GraphReadNotFoundError("node was not found")
                source_kind = NodeType(source_type).value
                target_kind = NodeType(target_type).value
                relation_name = Neo4jGraphGateway.relation_type_for(relation)
            except (TypeError, ValueError, GraphReadNotFoundError, Neo4jQueryContractError) as error:
                raise GraphReadError("Neo4j relation row is not in the Founder Graph allowlist") from error
            relations.append(GraphRelationView(str(source_id), relation_name, str(target_id), source_kind, target_kind))
        return tuple(sorted(relations, key=lambda item: (item.source_id, item.relation, item.target_id)))

    @staticmethod
    def _cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        if not isinstance(cursor, str) or not cursor.isdigit():
            raise GraphReadError("cursor must be a non-negative decimal offset")
        return int(cursor)

    @staticmethod
    def _check_timeout(started: float, timeout_ms: int) -> None:
        if (monotonic() - started) * 1000 > timeout_ms:
            raise GraphReadTimeoutError("local graph search timed out; retry with a narrower query")


__all__ = ["GraphRelationView", "Neo4jGraphReadService", "Neo4jReadUnavailableError"]
