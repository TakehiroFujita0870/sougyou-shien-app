"""Atomic-write validation helpers for owner-scoped Facet taxonomy edges."""

from __future__ import annotations

from typing import Iterable

from .founder_graph import NodeType, RelationAssertion, RelationType, RelationshipStatus
from .founder_graph_facet_hierarchy import (
    FacetNode,
    FacetTaxonomyRelation,
    facet_taxonomy_relation_from_assertion,
    validate_facet_taxonomy_candidate,
)


def validate_facet_taxonomy_write(
    *,
    owner_id: str,
    assertion: RelationAssertion,
    facets: Iterable[FacetNode],
    assertions: Iterable[RelationAssertion],
) -> None:
    """Validate a Facet→Facet write against authoritative current family tips.

    Callers must serialize this check with every taxonomy write for ``owner_id``
    and provide a snapshot read in the same transaction/critical section.
    Retraction replaces its family tip but contributes no active graph edge.
    """

    if assertion.owner_id != owner_id:
        raise ValueError("Facet taxonomy assertion belongs to another owner")
    if (
        assertion.predicate is not RelationType.CLASSIFIED_AS
        or assertion.source_kind is not NodeType.FACET
        or assertion.target_kind is not NodeType.FACET
    ):
        raise ValueError("assertion is not a Facet taxonomy relation")

    latest_by_family: dict[str, RelationAssertion] = {}
    for current in assertions:
        if current.owner_id != owner_id:
            continue
        if (
            current.predicate is not RelationType.CLASSIFIED_AS
            or current.source_kind is not NodeType.FACET
            or current.target_kind is not NodeType.FACET
        ):
            continue
        previous = latest_by_family.get(current.assertion_family_id)
        if previous is None or current.revision > previous.revision:
            latest_by_family[current.assertion_family_id] = current
        elif current.revision == previous.revision and current != previous:
            raise ValueError("Facet assertion family revision is inconsistent")

    # The candidate is authoritative for its family even if the caller's
    # snapshot also contains its predecessor/current tip.
    latest_by_family[assertion.assertion_family_id] = assertion
    active_relations: list[FacetTaxonomyRelation] = []
    for tip in latest_by_family.values():
        if tip.status in {RelationshipStatus.SUPERSEDED, RelationshipStatus.RETRACTED}:
            continue
        relation = facet_taxonomy_relation_from_assertion(tip)
        if relation is not None:
            active_relations.append(relation)

    candidate = facet_taxonomy_relation_from_assertion(assertion)
    if candidate is None:
        raise ValueError("assertion is not a Facet taxonomy relation")
    validate_facet_taxonomy_candidate(
        facets,
        active_relations,
        candidate,
        owner_id=owner_id,
    )


__all__ = ["validate_facet_taxonomy_write"]
