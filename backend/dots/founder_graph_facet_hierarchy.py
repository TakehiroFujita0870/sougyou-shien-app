"""Pure owner-scoped Facet hierarchy validation and region projection.

Storage adapters should map persisted Facet, RelationAssertion, and anchor
records to these small values. This module has no database or UI dependencies.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .founder_graph import NodeType, RelationAssertion, RelationType


_RELATION_STATUSES = frozenset({"proposed", "inferred", "confirmed"})
_TRAVERSABLE_STATUSES = frozenset({"inferred", "confirmed"})
_REGION_ENTITY_KINDS = frozenset({"idea", "asset"})


class FacetHierarchyError(ValueError):
    """The proposed Facet graph violates owner, evidence, or cycle rules."""


@dataclass(frozen=True, slots=True)
class FacetNode:
    owner_id: str
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class FacetTaxonomyRelation:
    """A broader-to-narrower Facet relation (the adapter maps its predicate)."""

    owner_id: str
    broader_facet_id: str
    narrower_facet_id: str
    status: str = "proposed"
    evidence_ids: tuple[str, ...] = ()


    assertion_family_id: str | None = None
    revision: int = 1
@dataclass(frozen=True, slots=True)
class RegionEntity:
    owner_id: str
    id: str
    kind: str
    title: str


@dataclass(frozen=True, slots=True)
class FacetClassification:
    owner_id: str
    entity_id: str
    facet_id: str
    status: str = "proposed"
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FacetRegionHit:
    entity: RegionEntity
    root_facet_id: str
    matched_facet_id: str
    facet_depth: int
    classification_status: str
    classification_evidence_ids: tuple[str, ...]
    taxonomy_status_path: tuple[str, ...]
    taxonomy_evidence_path: tuple[tuple[str, ...], ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        """Evidence that supports both the region path and entity assignment."""

        return tuple(dict.fromkeys(
            evidence_id
            for edge_evidence in (*self.taxonomy_evidence_path, self.classification_evidence_ids)
            for evidence_id in edge_evidence
        ))


def _validate_status_and_evidence(status: str, evidence_ids: tuple[str, ...]) -> None:
    if status not in _RELATION_STATUSES:
        raise FacetHierarchyError("Facet relation status is invalid")
    if status in _TRAVERSABLE_STATUSES and not evidence_ids:
        raise FacetHierarchyError("inferred and confirmed Facet relations require evidence")
    if any(not isinstance(item, str) or not item.strip() for item in evidence_ids):
        raise FacetHierarchyError("Facet evidence identifiers must be non-empty strings")


def validate_facet_hierarchy(
    facets: Iterable[FacetNode],
    taxonomy_relations: Iterable[FacetTaxonomyRelation],
    *,
    owner_id: str,
) -> None:
    """Validate one owner's broader-to-narrower taxonomy, rejecting all cycles.

    Proposed edges participate in cycle detection even though they are not
    traversable for region retrieval. This prevents an accepted proposal from
    completing a cycle later.
    """

    if not isinstance(owner_id, str) or not owner_id.strip():
        raise FacetHierarchyError("owner_id is required")
    facet_by_id: dict[str, FacetNode] = {}
    for facet in facets:
        if facet.owner_id != owner_id:
            raise FacetHierarchyError("Facet hierarchy cannot include a foreign owner facet")
        if not facet.id or facet.id in facet_by_id:
            raise FacetHierarchyError("Facet identifiers must be unique and non-empty")
        facet_by_id[facet.id] = facet

    adjacency: dict[str, list[str]] = {facet_id: [] for facet_id in facet_by_id}
    seen_edges: set[tuple[str, str]] = set()
    for relation in taxonomy_relations:
        if relation.owner_id != owner_id:
            raise FacetHierarchyError("Facet taxonomy relation belongs to another owner")
        _validate_status_and_evidence(relation.status, relation.evidence_ids)
        edge = (relation.broader_facet_id, relation.narrower_facet_id)
        if edge in seen_edges:
            raise FacetHierarchyError("duplicate Facet taxonomy relation")
        if edge[0] not in facet_by_id or edge[1] not in facet_by_id:
            raise FacetHierarchyError("Facet taxonomy endpoints must belong to the same owner")
        seen_edges.add(edge)
        adjacency[edge[0]].append(edge[1])

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(facet_id: str) -> None:
        if facet_id in visiting:
            raise FacetHierarchyError("Facet taxonomy cycle detected")
        if facet_id in visited:
            return
        visiting.add(facet_id)
        for child_id in adjacency[facet_id]:
            visit(child_id)
        visiting.remove(facet_id)
        visited.add(facet_id)

    for facet_id in sorted(facet_by_id):
        visit(facet_id)


def project_facet_region(
    facets: Iterable[FacetNode],
    taxonomy_relations: Iterable[FacetTaxonomyRelation],
    entities: Iterable[RegionEntity],
    classifications: Iterable[FacetClassification],
    *,
    owner_id: str,
    root_facet_id: str,
    max_facet_depth: int = 0,
) -> tuple[FacetRegionHit, ...]:
    """Return grounded Idea/Asset records in a selected Facet region.

    Depth zero includes only records classified directly into the selected
    Facet. Each additional level follows one evidence-backed inferred or
    confirmed broader-to-narrower taxonomy edge. Proposed facts stay out of
    retrieval while their status remains available to callers/storage.
    """

    if not isinstance(max_facet_depth, int) or isinstance(max_facet_depth, bool) or max_facet_depth < 0:
        raise FacetHierarchyError("max_facet_depth must be a non-negative integer")
    facets = tuple(facets)
    taxonomy_relations = tuple(taxonomy_relations)
    entities = tuple(entities)
    classifications = tuple(classifications)
    validate_facet_hierarchy(facets, taxonomy_relations, owner_id=owner_id)
    facet_by_id = {facet.id: facet for facet in facets}
    if root_facet_id not in facet_by_id:
        raise FacetHierarchyError("selected root Facet does not belong to this owner")

    children: dict[str, list[FacetTaxonomyRelation]] = {}
    for relation in taxonomy_relations:
        if relation.status in _TRAVERSABLE_STATUSES:
            children.setdefault(relation.broader_facet_id, []).append(relation)
    for relations in children.values():
        relations.sort(key=lambda relation: (relation.narrower_facet_id, relation.status, relation.evidence_ids))

    # A DAG may contain more than one route to the same Facet. Keep the
    # shallowest deterministic route so depth and evidence remain stable.
    paths: dict[str, tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {root_facet_id: ((), ())}
    queue = deque([root_facet_id])
    while queue:
        parent_id = queue.popleft()
        statuses, evidence_path = paths[parent_id]
        if len(statuses) >= max_facet_depth:
            continue
        for relation in children.get(parent_id, ()):
            child_id = relation.narrower_facet_id
            if child_id in paths:
                continue
            paths[child_id] = (
                (*statuses, relation.status),
                (*evidence_path, relation.evidence_ids),
            )
            queue.append(child_id)

    entity_by_id = {
        entity.id: entity
        for entity in entities
        if entity.owner_id == owner_id and entity.kind in _REGION_ENTITY_KINDS
    }
    best_hit_by_entity: dict[str, FacetRegionHit] = {}
    for classification in classifications:
        # Records from other owners are intentionally ignored at this boundary.
        if classification.owner_id != owner_id:
            continue
        if classification.facet_id not in facet_by_id:
            raise FacetHierarchyError("classification Facet must belong to this owner")
        _validate_status_and_evidence(classification.status, classification.evidence_ids)
        entity = entity_by_id.get(classification.entity_id)
        if entity is None or classification.facet_id not in paths:
            continue
        if classification.status not in _TRAVERSABLE_STATUSES:
            continue
        taxonomy_statuses, taxonomy_evidence = paths[classification.facet_id]
        hit = FacetRegionHit(
            entity=entity,
            root_facet_id=root_facet_id,
            matched_facet_id=classification.facet_id,
            facet_depth=len(taxonomy_statuses),
            classification_status=classification.status,
            classification_evidence_ids=classification.evidence_ids,
            taxonomy_status_path=taxonomy_statuses,
            taxonomy_evidence_path=taxonomy_evidence,
        )
        previous = best_hit_by_entity.get(entity.id)
        if previous is None or (hit.facet_depth, hit.matched_facet_id) < (previous.facet_depth, previous.matched_facet_id):
            best_hit_by_entity[entity.id] = hit

    return tuple(sorted(best_hit_by_entity.values(), key=lambda hit: (hit.entity.id, hit.facet_depth)))


def facet_taxonomy_relation_from_assertion(
    assertion: RelationAssertion,
) -> FacetTaxonomyRelation | None:
    """Map a Facet→Facet CLASSIFIED_AS assertion to the broader→narrower contract."""

    if (
        assertion.predicate is not RelationType.CLASSIFIED_AS
        or assertion.source_kind is not NodeType.FACET
        or assertion.target_kind is not NodeType.FACET
    ):
        return None
    return FacetTaxonomyRelation(
        owner_id=assertion.owner_id,
        broader_facet_id=assertion.source_id,
        narrower_facet_id=assertion.target_id,
        status=assertion.status.value,
        evidence_ids=assertion.evidence_ids,
        assertion_family_id=assertion.assertion_family_id,
        revision=assertion.revision,
    )


def validate_facet_taxonomy_candidate(
    facets: Iterable[FacetNode],
    existing_relations: Iterable[FacetTaxonomyRelation],
    candidate: FacetTaxonomyRelation,
    *,
    owner_id: str,
) -> None:
    """Validate the latest taxonomy revisions plus one candidate atomically."""

    relations = [*existing_relations, candidate]
    latest_by_family: dict[str, FacetTaxonomyRelation] = {}
    unversioned: list[FacetTaxonomyRelation] = []
    for relation in relations:
        if relation.owner_id != owner_id:
            continue
        family_id = relation.assertion_family_id
        if family_id is None:
            unversioned.append(relation)
            continue
        previous = latest_by_family.get(family_id)
        if previous is None or relation.revision > previous.revision:
            latest_by_family[family_id] = relation
        elif relation.revision == previous.revision and (
            relation.broader_facet_id != previous.broader_facet_id
            or relation.narrower_facet_id != previous.narrower_facet_id
            or relation.status != previous.status
        ):
            raise FacetHierarchyError("Facet assertion family revision is inconsistent")

    current = [
        relation
        for relation in (*latest_by_family.values(), *unversioned)
        if relation.status in _RELATION_STATUSES
    ]
    validate_facet_hierarchy(facets, current, owner_id=owner_id)


__all__ = [
    "facet_taxonomy_relation_from_assertion",
    "FacetClassification",
    "FacetHierarchyError",
    "FacetNode",
    "FacetRegionHit",
    "FacetTaxonomyRelation",
    "RegionEntity",
    "project_facet_region",
    "validate_facet_taxonomy_candidate",
    "validate_facet_hierarchy",
]
