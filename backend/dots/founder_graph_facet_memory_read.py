"""Memory adapter for safe owner-scoped Facet-region reads."""

from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Any

from .founder_graph import Asset, EgressPolicy, Facet, Idea, RelationAssertion, RelationshipStatus, Status
from .founder_graph_read import SearchHit, SearchPage, _node_view, _tokens
from .founder_graph_facet_hierarchy import (
    FacetClassification,
    FacetNode,
    RegionEntity,
    facet_taxonomy_relation_from_assertion,
    project_facet_region,
)


_TRAVERSABLE = {RelationshipStatus.INFERRED, RelationshipStatus.CONFIRMED}
_CURRENT = {RelationshipStatus.PROPOSED, *_TRAVERSABLE}
_NON_CURRENT_STATUSES = {
    Status.ARCHIVED, Status.SUPERSEDED, Status.RETRACTED, Status.EXPIRED,
    Status.CANCELLED, Status.REVOKED, Status.FAILED,
}


def facet_region_from_snapshot(
    snapshot: Any,
    root_facet_id: str,
    *,
    owner_id: str,
    max_facet_depth: int = 0,
):
    """Project current, shareable taxonomy and memberships from one snapshot.

    The snapshot is produced while the memory store lock is held. Local-only
    Facets, entities, assertions, and Evidence are intentionally not exposed.
    """

    nodes = tuple(getattr(snapshot, "nodes", ()))
    owner_nodes = tuple(node for node in nodes if getattr(node, "owner_id", None) == owner_id)
    shareable = lambda node: getattr(node, "egress_policy", None) is EgressPolicy.SHAREABLE
    visible = lambda node: getattr(node, "status", None) not in _NON_CURRENT_STATUSES and shareable(node)
    evidence_is_visible = lambda evidence_id: any(
        getattr(node, "id", None) == evidence_id
        and getattr(node, "status", None) is Status.ACTIVE
        and shareable(node)
        for node in owner_nodes
    )

    superseded_ids = {
        node.supersedes_id
        for node in owner_nodes
        if isinstance(node, (Idea, Asset)) and node.supersedes_id is not None
    }
    facets = tuple(
        FacetNode(owner_id, node.id, f"{node.namespace}: {node.value}")
        for node in owner_nodes
        if isinstance(node, Facet) and node.status is Status.ACTIVE and visible(node) and node.id not in superseded_ids
    )
    entities = tuple(
        RegionEntity(
            owner_id,
            node.id,
            "idea" if isinstance(node, Idea) else "asset",
            node.title if isinstance(node, Idea) else node.name,
        )
        for node in owner_nodes
        if isinstance(node, (Idea, Asset)) and visible(node) and node.id not in superseded_ids
    )
    assertions = tuple(
        node
        for node in owner_nodes
        if isinstance(node, RelationAssertion)
        and node.predicate.value == "CLASSIFIED_AS"
        and node.egress_policy is EgressPolicy.SHAREABLE
    )
    assertions_by_family: dict[str, list[RelationAssertion]] = {}
    for assertion in assertions:
        assertions_by_family.setdefault(assertion.assertion_family_id, []).append(assertion)
    latest_by_family: list[RelationAssertion] = []
    for family_assertions in assertions_by_family.values():
        highest_revision = max(assertion.revision for assertion in family_assertions)
        latest = [assertion for assertion in family_assertions if assertion.revision == highest_revision]
        # Conflicting tips are malformed history. Do not choose one based on
        # snapshot order, because that would make membership output unstable.
        if len(latest) == 1:
            latest_by_family.append(latest[0])
    current_tips = tuple(
        assertion for assertion in latest_by_family
        if assertion.status in _CURRENT
    )
    facet_ids = {facet.id for facet in facets}
    entity_ids = {entity.id for entity in entities}
    taxonomy = tuple(
        relation for assertion in current_tips
        if (relation := facet_taxonomy_relation_from_assertion(assertion)) is not None
        and assertion.source_id in facet_ids
        and assertion.target_id in facet_ids
        and all(evidence_is_visible(evidence_id) for evidence_id in assertion.evidence_ids)
    )
    classifications = tuple(
        FacetClassification(
            owner_id=owner_id,
            entity_id=assertion.source_id,
            facet_id=assertion.target_id,
            status=assertion.status.value,
            evidence_ids=assertion.evidence_ids,
        )
        for assertion in current_tips
        if assertion.source_id in entity_ids
        and assertion.target_id in facet_ids
        and assertion.source_kind.value != "facet"
        and assertion.status in _TRAVERSABLE
        and all(evidence_is_visible(evidence_id) for evidence_id in assertion.evidence_ids)
    )
    return project_facet_region(
        facets,
        taxonomy,
        entities,
        classifications,
        owner_id=owner_id,
        root_facet_id=root_facet_id,
        max_facet_depth=max_facet_depth,
    )


def facet_search_from_snapshot(
    snapshot: Any,
    query: str,
    *,
    owner_id: str,
    limit: int = 20,
    cursor: str | None = None,
) -> SearchPage:
    """Search only active shareable Facets before applying pagination."""

    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise ValueError("query must be a non-empty string of at most 512 characters")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if cursor is None:
        offset = 0
    elif isinstance(cursor, str) and cursor.isdecimal():
        offset = int(cursor)
    else:
        raise ValueError("cursor is invalid")

    tokens = _tokens(query)
    ranked: list[tuple[float, str, Any]] = []
    for facet in getattr(snapshot, "nodes", ()):
        if (
            not isinstance(facet, Facet)
            or facet.owner_id != owner_id
            or facet.status is not Status.ACTIVE
            or facet.egress_policy is not EgressPolicy.SHAREABLE
        ):
            continue
        view = _node_view(facet)
        haystack = json.dumps(dict(view.fields), ensure_ascii=False, sort_keys=True).casefold()
        matched = sum(1 for token in tokens if token in haystack)
        if matched:
            score = matched / len(tokens) + (0.25 if query.casefold() in haystack else 0.0)
            ranked.append((score, facet.id, view))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    page = ranked[offset : offset + limit]
    end = offset + limit
    next_cursor = str(end) if end < len(ranked) else None
    return SearchPage(
        tuple(SearchHit(view, score) for score, _identifier, view in page),
        next_cursor,
    )


__all__ = ["facet_region_from_snapshot", "facet_search_from_snapshot"]
