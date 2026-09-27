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
    SearchHit,
    SearchPage,
    _tokens,
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
        "n.search_text AS search_text, n.egress_policy AS egress_policy ORDER BY n.id"
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
        # Region paths are shareable projections: excluding private intermediate
        # Facets and taxonomy assertions here prevents leaking their existence
        # through descendant membership or reported path depth.
        if _row_value(row, "egress_policy") != "shareable":
            continue
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
        evidence_values = payload.get("evidence_ids", ())
        if not isinstance(evidence_values, (tuple, list)) or not all(
            isinstance(item, str) and item for item in evidence_values
        ):
            raise GraphReadError("Facet relation evidence is invalid")
        evidence = tuple(evidence_values)
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
        "AND e.egress_policy = 'shareable' AND NOT coalesce(e.status, '') IN $non_current RETURN e.id AS id"
    )
    with reads._read_session() as session:
        evidence_rows = gateway._execute_read(session, lambda tx: tuple(_rows(tx.run(
            evidence_query,
            owner_id=owner,
            evidence_ids=sorted(evidence_ids),
            non_current=sorted(_NON_CURRENT),
        ))))
    active_evidence = {str(_row_value(row, "id")) for row in evidence_rows}
    # A relationship is traversable only when every referenced Evidence is
    # current, owner-scoped and shareable. Never downgrade to a partial proof.
    taxonomy = [
        FacetTaxonomyRelation(
            item.owner_id, item.broader_facet_id, item.narrower_facet_id,
            item.status, item.evidence_ids,
        )
        for item in taxonomy
        if all(evidence_id in active_evidence for evidence_id in item.evidence_ids)
    ]
    classifications = [
        FacetClassification(
            item.owner_id, item.entity_id, item.facet_id,
            item.status, item.evidence_ids,
        )
        for item in classifications
        if all(evidence_id in active_evidence for evidence_id in item.evidence_ids)
    ]
    shareable_facet_ids = {item.id for item in facets}
    shareable_entity_ids = {item.id for item in entities}
    taxonomy = [
        item for item in taxonomy
        if item.broader_facet_id in shareable_facet_ids
        and item.narrower_facet_id in shareable_facet_ids
    ]
    classifications = [
        item for item in classifications
        if item.entity_id in shareable_entity_ids and item.facet_id in shareable_facet_ids
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


def search_facet_nodes(
    reads: Any,
    query: str,
    *,
    owner_id: str,
    limit: int = 20,
    cursor: str | None = None,
) -> SearchPage:
    """Search only current shareable Facet nodes before applying page limits."""

    owner = _required_owner(owner_id)
    if owner != reads._gateway.owner_id:
        raise GraphReadNotFoundError("Facet search was not found")
    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise GraphReadError("query must be a non-empty string of at most 512 characters")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise GraphReadError("limit must be between 1 and 50")
    if cursor is None:
        offset = 0
    elif isinstance(cursor, str) and cursor.isdecimal():
        offset = int(cursor)
    else:
        raise GraphReadError("cursor is invalid")

    query_text = (
        "MATCH (n:Facet {owner_id: $owner_id}) "
        "WHERE n.egress_policy = 'shareable' AND coalesce(n.status, 'active') = 'active' "
        "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type, "
        "n.status AS status, n.revision AS revision, n.payload_json AS payload_json, "
        "n.search_text AS search_text ORDER BY n.id"
    )
    with reads._read_session() as session:
        rows = reads._gateway._execute_read(session, lambda tx: tuple(_rows(tx.run(query_text, owner_id=owner))))
    tokens = _tokens(query)
    ranked: list[tuple[float, str, Any]] = []
    for row in rows:
        view = _view_from_row(row, owner_id=owner)
        if view is None or view.node_type != "facet" or view.fields.get("egress_policy") != "shareable":
            continue
        stored_search_text = _row_value(row, "search_text")
        haystack = json.dumps(dict(view.fields), ensure_ascii=False, sort_keys=True)
        if isinstance(stored_search_text, str):
            haystack += " " + stored_search_text
        haystack = haystack.casefold()
        matched = sum(1 for token in tokens if token in haystack)
        if matched:
            score = matched / len(tokens) + (0.25 if query.casefold() in haystack else 0.0)
            ranked.append((score, view.id, view))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    page = ranked[offset : offset + limit]
    end = offset + limit
    next_cursor = str(end) if end < len(ranked) else None
    return SearchPage(tuple(SearchHit(view, score) for score, _identifier, view in page), next_cursor)
