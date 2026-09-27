"""Bounded, owner-only graph projection for the local visual browser."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from typing import Any, Mapping, Protocol, Sequence

from .founder_graph_lifecycle_resolver import decode_asset_lifecycle_record, lifecycle_reference_aliases
from .founder_graph_neo4j_idea import decode_persisted_idea


MAX_NODES = 200
MAX_EDGES = 400
_EXCLUDED = frozenset({"deleted", "archived", "superseded", "retracted", "expired", "cancelled", "revoked"})
_TITLES = {"idea": "title", "asset": "name", "person": "name", "organization": "name", "owner_profile": "display_name", "source": "title", "research_campaign": "title", "facet": "value"}
_EMPTY = {"status": "empty", "nodes": [], "edges": [], "semantic_edges": [], "truncated": False}
_ACTIVE_ASSERTION_STATUSES = frozenset({"proposed", "inferred", "confirmed"})


class GraphViewStore(Protocol):
    def read_nodes(self, owner_id: str) -> Sequence[Mapping[str, Any]]: ...

    def read_edges(self, owner_id: str, ids: Sequence[str]) -> Sequence[Mapping[str, Any]]: ...

    def read_facet_region(self, owner_id: str, facet_id: str, depth: int) -> Sequence[Any]: ...


class Neo4jGraphViewStore:
    _NODES = (
        "MATCH (n) WHERE n.owner_id = $owner_id AND n.node_type IS NOT NULL "
        "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
        "n.status AS status, n.payload_json AS payload_json, "
        "(EXISTS { MATCH (successor:RelationAssertion {owner_id: $owner_id})-[:SUPERSEDES]->(n) } "
        "OR (n.node_type IN ['idea', 'asset', 'person'] AND EXISTS { MATCH (successor {owner_id: $owner_id, supersedes_id: n.id}) })) "
        "AS has_successor ORDER BY n.id LIMIT 201"
    )
    _EDGES = (
        "MATCH (a)-[r]->(b) WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id "
        "AND a.id IN $ids AND b.id IN $ids "
        "RETURN a.id AS source, b.id AS target, type(r) AS relation, "
        "r.owner_id AS relation_owner ORDER BY source, target, relation LIMIT 401"
    )

    def __init__(self, driver: Any, *, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def read_nodes(self, owner_id: str) -> Sequence[Mapping[str, Any]]:
        with self._driver.session(database=self._database) as session:
            return tuple(dict(row) for row in session.run(self._NODES, owner_id=owner_id))

    def read_edges(self, owner_id: str, ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        with self._driver.session(database=self._database) as session:
            return tuple(dict(row) for row in session.run(self._EDGES, owner_id=owner_id, ids=list(ids)))

    def read_facet_region(self, owner_id: str, facet_id: str, depth: int):
        from dots.founder_graph_neo4j import Neo4jGraphGateway
        from dots.founder_graph_neo4j_read import Neo4jGraphReadService

        reads = Neo4jGraphReadService(Neo4jGraphGateway(self._driver, owner_id, database=self._database))
        return reads.facet_region(facet_id, owner_id=owner_id, max_facet_depth=depth)


def read_local_graph(store: GraphViewStore, *, owner_id: str, storage_status: str = "running") -> dict[str, Any]:
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("owner_id is required")
    if storage_status == "stopped":
        return {**_EMPTY, "status": "stopped"}
    if storage_status != "running":
        return {**_EMPTY, "status": "failed"}
    try:
        raw_nodes = store.read_nodes(owner_id)
        truncated = len(raw_nodes) > MAX_NODES
        nodes = []
        seen = set()
        payloads: dict[str, Mapping[str, Any]] = {}
        node_kinds: dict[str, str] = {}
        node_statuses: dict[str, str] = {}
        globally_superseded_ids = set()
        superseded_asset_ids = set()
        superseded_idea_ids = set()
        for row in raw_nodes[:MAX_NODES]:
            identity, kind = row["id"], row["node_type"]
            if row["owner_id"] != owner_id or not isinstance(identity, str) or not identity or identity in seen or not isinstance(kind, str):
                raise ValueError("unexpected node identity")
            seen.add(identity)
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict) or payload.get("id") != identity or payload.get("owner_id") != owner_id:
                raise ValueError("unexpected payload identity")
            status = str(row.get("status") or "").lower()
            if payload.get("status") is not None and payload.get("status") != row.get("status"):
                raise ValueError("unexpected node status")
            payloads[identity] = payload
            node_kinds[identity] = kind
            node_statuses[identity] = status
            if "has_successor" in row:
                has_successor = row["has_successor"]
                if type(has_successor) is not bool:
                    raise ValueError("unexpected assertion successor status")
                if kind == "relation_assertion" and has_successor:
                    globally_superseded_ids.add(identity)
                if kind == "idea" and has_successor:
                    superseded_idea_ids.add(identity)
                if kind in {"asset", "person"} and has_successor:
                    superseded_asset_ids.add(identity)
            if str(row.get("status") or "").lower() in _EXCLUDED:
                continue
            if identity in superseded_asset_ids or identity in superseded_idea_ids:
                continue
            field = _TITLES.get(kind)
            label = payload.get(field) if field else None
            if not isinstance(label, str) or not label.strip():
                label = kind.replace("_", " ")
            nodes.append({"id": identity, "kind": kind, "label": label.strip()[:100]})
        included = {node["id"] for node in nodes}
        raw_edges = store.read_edges(owner_id, list(included)) if included else ()
        truncated = truncated or len(raw_edges) > MAX_EDGES
        edges = []
        for row in raw_edges[:MAX_EDGES]:
            if row["source"] not in included or row["target"] not in included or row.get("relation_owner") not in (None, owner_id):
                raise ValueError("unexpected relation identity")
            relation = row["relation"]
            if not isinstance(relation, str) or not relation:
                raise ValueError("unexpected relation type")
            edges.append({"source": row["source"], "target": row["target"], "label": relation[:60]})
        lifecycle_aliases = _lifecycle_aliases(owner_id, payloads, node_kinds)
        semantic_edges = _semantic_edges(
            owner_id, payloads, node_kinds, node_statuses, globally_superseded_ids,
            idea_aliases=lifecycle_aliases,
        )
        return {
            "status": "ready" if nodes else "empty",
            "nodes": nodes,
            "edges": edges,
            "semantic_edges": semantic_edges,
            "truncated": truncated,
        }
    except Exception:
        return {**_EMPTY, "status": "failed"}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _semantic_edges(
    owner_id: str,
    payloads: Mapping[str, Mapping[str, Any]],
    node_kinds: Mapping[str, str],
    node_statuses: Mapping[str, str],
    globally_superseded_ids: set[str] | frozenset[str] = frozenset(),
    *,
    at: datetime | None = None,
    idea_aliases: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Project current owner-local RelationAssertions without exposing payloads."""
    now = at or datetime.now(timezone.utc)
    idea_aliases = idea_aliases or {}
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    superseded_ids = {
        payload.get("supersedes_id")
        for identity, payload in payloads.items()
        if node_kinds.get(identity) == "relation_assertion"
        and payload.get("owner_id") == owner_id
        and isinstance(payload.get("supersedes_id"), str)
    }
    superseded_asset_ids = {
        payload.get("supersedes_id")
        for identity, payload in payloads.items()
        if node_kinds.get(identity) in {"asset", "person"}
        and payload.get("owner_id") == owner_id
        and isinstance(payload.get("supersedes_id"), str)
    }
    projected: list[dict[str, Any]] = []
    for identity, assertion in payloads.items():
        if node_kinds.get(identity) != "relation_assertion" or assertion.get("owner_id") != owner_id:
            continue
        status = assertion.get("status")
        if status not in _ACTIVE_ASSERTION_STATUSES or node_statuses.get(identity) != status:
            continue
        if identity in superseded_ids or identity in globally_superseded_ids:
            continue
        valid_from = _timestamp(assertion.get("valid_from"))
        if valid_from is None or valid_from > now:
            continue
        expires_at = assertion.get("expires_at")
        if expires_at is not None:
            expires_at = _timestamp(expires_at)
            if expires_at is None or expires_at <= now:
                continue

        source_id = assertion.get("source_id")
        target_id = assertion.get("target_id")
        source_kind = assertion.get("source_kind")
        target_kind = assertion.get("target_kind")
        predicate = assertion.get("predicate")
        if (
            not all(isinstance(value, str) and value.strip() for value in (source_id, target_id, source_kind, target_kind, predicate))
            or len(predicate) > 60
        ):
            continue
        aliasable_kinds = {"idea", "asset", "person"}
        resolved_source_id = idea_aliases.get(source_id, source_id) if source_kind in aliasable_kinds else source_id
        resolved_target_id = idea_aliases.get(target_id, target_id) if target_kind in aliasable_kinds else target_id
        source = payloads.get(resolved_source_id)
        target = payloads.get(resolved_target_id)
        if (
            source is None
            or target is None
            or resolved_source_id in superseded_asset_ids
            or resolved_target_id in superseded_asset_ids
            or node_statuses.get(resolved_source_id) in _EXCLUDED
            or node_statuses.get(resolved_target_id) in _EXCLUDED
            or node_kinds.get(resolved_source_id) != source_kind
            or node_kinds.get(resolved_target_id) != target_kind
            or source.get("owner_id") != owner_id
            or target.get("owner_id") != owner_id
        ):
            continue

        brief_id = assertion.get("based_on_brief_id")
        section_index = assertion.get("based_on_brief_section_index")
        if (brief_id is None) != (section_index is None):
            continue
        if brief_id is not None and (
            not isinstance(brief_id, str)
            or not brief_id.strip()
            or type(section_index) is not int
            or not 0 <= section_index <= 7
        ):
            continue
        confidence = assertion.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            continue

        raw_evidence_ids = assertion.get("evidence_ids")
        if not isinstance(raw_evidence_ids, (list, tuple)) or any(not isinstance(value, str) for value in raw_evidence_ids):
            continue
        evidence_ids = []
        for evidence_id in raw_evidence_ids:
            evidence = payloads.get(evidence_id)
            if (
                evidence is not None
                and node_kinds.get(evidence_id) == "evidence"
                and node_statuses.get(evidence_id) not in _EXCLUDED
                and evidence.get("owner_id") == owner_id
                and evidence.get("egress_policy") == "shareable"
            ):
                evidence_ids.append(evidence_id)
        if status in {"inferred", "confirmed"} and not evidence_ids:
            continue
        projected.append({
            "id": identity,
            "source_id": resolved_source_id,
            "target_id": resolved_target_id,
            "predicate": predicate,
            "status": status,
            "confidence": confidence,
            "evidence_ids": sorted(set(evidence_ids)),
            "based_on_brief_id": brief_id,
            "based_on_brief_section_index": section_index,
        })
    return sorted(projected, key=lambda edge: edge["id"])


def _lifecycle_aliases(
    owner_id: str,
    payloads: Mapping[str, Mapping[str, Any]],
    node_kinds: Mapping[str, str],
) -> dict[str, str]:
    records = []
    for identity, payload in payloads.items():
        kind = node_kinds.get(identity)
        if kind not in {"idea", "asset", "person"}:
            continue
        try:
            if kind == "idea":
                records.append(decode_persisted_idea({
                    "id": identity,
                    "owner_id": owner_id,
                    "node_type": "idea",
                    "revision": payload.get("revision"),
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                }, owner_id=owner_id, expected_id=identity))
            else:
                records.append(decode_asset_lifecycle_record(
                    payload, owner_id=owner_id, expected_id=identity,
                ))
        except (TypeError, ValueError):
            continue
    return lifecycle_reference_aliases(records)


def read_local_facet_region(
    store: GraphViewStore,
    *,
    owner_id: str,
    facet_id: str,
    depth: int,
    storage_status: str = "running",
) -> dict[str, Any]:
    """Return a strict safe projection of one semantic Facet region."""
    if storage_status == "stopped":
        return {"status": "stopped", "facet_id": facet_id, "depth": depth, "hits": []}
    if storage_status != "running":
        return {"status": "failed", "facet_id": facet_id, "depth": depth, "hits": []}
    try:
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner is required")
        if not isinstance(facet_id, str) or not facet_id.strip():
            raise ValueError("Facet is required")
        if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 3:
            raise ValueError("depth is out of range")
        read = getattr(store, "read_facet_region", None)
        if not callable(read):
            raise ValueError("Facet region read is unavailable")
        hits = read(owner_id.strip(), facet_id.strip(), depth)
        projected = []
        for hit in hits:
            entity = hit.entity
            if entity.owner_id != owner_id or entity.kind not in {"idea", "asset"}:
                raise ValueError("unexpected Facet region entity")
            projected.append({
                "id": entity.id,
                "kind": entity.kind,
                "title": entity.title[:200],
                "root_facet_id": hit.root_facet_id,
                "matched_facet_id": hit.matched_facet_id,
                "depth": hit.facet_depth,
                "classification_status": hit.classification_status,
                "classification_evidence_ids": list(hit.classification_evidence_ids),
                "taxonomy_status_path": list(hit.taxonomy_status_path),
                "taxonomy_evidence_path": [list(item) for item in hit.taxonomy_evidence_path],
                "facet_path": [
                    {"facet_id": item.facet_id, "label": item.label, "depth": item.depth}
                    for item in hit.facet_path
                ],
                "evidence_ids": list(hit.evidence_ids),
            })
        return {"status": "ready" if projected else "empty", "facet_id": facet_id, "depth": depth, "hits": projected}
    except Exception:
        return {"status": "failed", "facet_id": facet_id, "depth": depth, "hits": []}
