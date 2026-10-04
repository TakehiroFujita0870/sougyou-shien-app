from __future__ import annotations

from dataclasses import replace

import pytest

from nebula.founder_graph import NodeType, RelationAssertion, RelationType, RelationshipStatus
from nebula.founder_graph_facet_hierarchy import FacetHierarchyError, FacetNode
from nebula.founder_graph_facet_write_guard import validate_facet_taxonomy_write


def _assertion(
    source: str,
    target: str,
    family: str,
    *,
    revision: int = 1,
    status: RelationshipStatus = RelationshipStatus.PROPOSED,
    supersedes: str | None = None,
) -> RelationAssertion:
    return RelationAssertion(
        owner_id="owner-1",
        id=f"assertion-{family}-{revision}",
        source_id=source,
        source_kind=NodeType.FACET,
        target_id=target,
        target_kind=NodeType.FACET,
        predicate=RelationType.CLASSIFIED_AS,
        assertion_family_id=family,
        revision=revision,
        status=status,
        supersedes_id=supersedes,
    )


def test_taxonomy_write_rejects_cycle_using_current_family_tips() -> None:
    facets = tuple(FacetNode("owner-1", item, item) for item in ("a", "b", "c"))
    existing = (
        _assertion("a", "b", "family-ab"),
        _assertion("b", "c", "family-bc"),
    )
    with pytest.raises(FacetHierarchyError, match="cycle"):
        validate_facet_taxonomy_write(
            owner_id="owner-1", assertion=_assertion("c", "a", "family-ca"),
            facets=facets, assertions=existing,
        )


def test_taxonomy_correction_replaces_old_edge_and_retraction_removes_tip() -> None:
    facets = tuple(FacetNode("owner-1", item, item) for item in ("a", "b", "c"))
    predecessor = _assertion("a", "b", "family-ab")
    correction = _assertion("a", "c", "family-ab", revision=2, supersedes=predecessor.id)
    validate_facet_taxonomy_write(
        owner_id="owner-1", assertion=correction,
        facets=facets, assertions=(predecessor,),
    )
    retract = replace(
        correction,
        id="assertion-family-ab-3",
        revision=3,
        status=RelationshipStatus.RETRACTED,
        supersedes_id=correction.id,
    )
    validate_facet_taxonomy_write(
        owner_id="owner-1", assertion=retract,
        facets=facets, assertions=(predecessor, correction),
    )


def test_taxonomy_guard_ignores_unrelated_relation_assertions() -> None:
    facets = (FacetNode("owner-1", "a", "A"), FacetNode("owner-1", "b", "B"))
    unrelated = RelationAssertion(
        owner_id="owner-1", source_id="idea", source_kind=NodeType.IDEA,
        target_id="a", target_kind=NodeType.FACET,
        predicate=RelationType.CLASSIFIED_AS, assertion_family_id="idea-a",
    )
    validate_facet_taxonomy_write(
        owner_id="owner-1", assertion=_assertion("a", "b", "facet-ab"),
        facets=facets, assertions=(unrelated,),
    )
