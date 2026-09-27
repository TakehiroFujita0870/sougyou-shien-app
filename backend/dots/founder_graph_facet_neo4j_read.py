"""Owner-scoped Neo4j adapter for semantic Facet-region projections."""

from __future__ import annotations

import json
from typing import Any

from .founder_graph_facet_hierarchy import (
    FacetClassification,
    FacetNode,
    FacetTaxonomyRelation,
    RegionEntity,
    project_facet_region,
)
from .founder_graph import RelationshipStatus
from .founder_graph_read import (
    GraphReadError,
    GraphReadNotFoundError,
)
from .founder_graph_neo4j_read import (
    _NON_CURRENT,
    _required_node_id,
    _required_owner,
    _row_value,
    _rows,
    _view_from_row,
)

_ACTIVE_RELATION_STATUSES = frozenset({
    RelationshipStatus.PROPOSED.value,
    RelationshipStatus.INFERRED.value,
    RelationshipStatus.CONFIRMED.value,
})


def read_facet_region(reads: Any, root_facet_id: str, *, owner_id: str, max_facet_depth: int = 0):
    """Load one owner's bounded Facet region and project grounded results."""

    owner = _required_owner(owner_id)
    root_id = _required_node_id(root_facet_id)
    gateway = reads._gateway
    if owner != gateway.owner_id:
        raise GraphReadNotFoundError("selected Facet was not found")

    node_query = (
        "MATCH (n) WHERE n.owner_id = $owner_id AND n.node_type IN $node_types "
        "AND NOT EXISTS { MATCH (successor:RelationAssertion {owner_id: $owner_id})-[:SUPERSEDES]->(n) } "
        "AND NOT coalesce(n.status, '') IN $non_current "
        "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
        "n.status AS status, n.revision AS revision, n.payload_json AS payload_json, "
        "n.search_text AS search_text ORDER BY n.id"
    )
    with reads._read_session() as session:
        rows = gateway._execute_read(session, lambda tx: tuple(_rows(tx.run(
            node_query,
            owner_id=owner,
            node_types=["facet", "idea", "asset", "relation_assertion"],
            non_current=sorted(_NON_CURRENT),
        ))))

    facets: list[FacetNode] = []
    entities: list[RegionEntity] = []
    taxonomy: list[FacetTaxonomyRelation] = []
    classifications: list[FacetClassification] = []
    evidence_ids: set[str] = set()
    for row in rows:
        view = _view_from_row(row, owner_id=owner)
        if view is None:
            continue
        payload_json = _row_value(row, "payload_json")
        try:
            payload = json.loads(payload_json) if isinstance(payload_json, str) else None
        except (TypeError, ValueError) as error:
            raise GraphReadError("Facet region record payload is invalid") from error
        if not isinstance(payload, dict):
            raise GraphReadError("Facet region record payload is invalid")
        if view.node_type == "facet":
            facets.append(FacetNode(owner, view.id, f"{payload.get('namespace', '')}: {payload.get('value', '')}"))
            continue
        if view.node_type in {"idea", "asset"}:
            entities.append(RegionEntity(owner, view.id, view.node_type, view.title))
            continue
        if view.node_type != "relation_assertion":
            continue
        if payload.get("predicate") != "CLASSIFIED_AS" or payload.get("status") not in _ACTIVE_RELATION_STATUSES:
            continue
        evidence = tuple(item for item in payload.get("evidence_ids", ()) if isinstance(item, str) and item)
        evidence_ids.update(evidence)
        source_id, target_id = payload.get("source_id"), payload.get("target_id")
        source_kind, target_kind = payload.get("source_kind"), payload.get("target_kind")
        status = payload["status"]
        if not all(isinstance(item, str) and item for item in (source_id, target_id)):
            raise GraphReadError("Facet relation endpoint is invalid")
        if source_kind == "facet" and target_kind == "facet":
            taxonomy.append(FacetTaxonomyRelation(owner, source_id, target_id, status, evidence))
        elif source_kind in {"idea", "asset"} and target_kind == "facet":
            classifications.append(FacetClassification(owner, source_id, target_id, status, evidence))

    evidence_query = (
        "MATCH (e:Evidence) WHERE e.owner_id = $owner_id AND e.id IN $evidence_ids "
        "AND NOT coalesce(e.status, '') IN $non_current RETURN e.id AS id"
    )
    with reads._read_session() as session:
        evidence_rows = gateway._execute_read(session, lambda tx: tuple(_rows(tx.run(
            evidence_query,
            owner_id=owner,
            evidence_ids=sorted(evidence_ids),
            non_current=sorted(_NON_CURRENT),
        ))))
    active_evidence = {str(_row_value(row, "id")) for row in evidence_rows}
    taxonomy = [
        FacetTaxonomyRelation(
            item.owner_id, item.broader_facet_id, item.narrower_facet_id,
            item.status, tuple(e for e in item.evidence_ids if e in active_evidence),
        )
        for item in taxonomy
    ]
    classifications = [
        FacetClassification(
            item.owner_id, item.entity_id, item.facet_id,
            item.status, tuple(e for e in item.evidence_ids if e in active_evidence),
        )
        for item in classifications
    ]
    if root_id not in {facet.id for facet in facets}:
        raise GraphReadNotFoundError("selected Facet was not found")
    try:
        return project_facet_region(
            facets,
            taxonomy,
            entities,
            classifications,
            owner_id=owner,
            root_facet_id=root_id,
            max_facet_depth=max_facet_depth,
        )
    except ValueError as error:
        raise GraphReadError(str(error)) from error
