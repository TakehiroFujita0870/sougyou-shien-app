from __future__ import annotations

import pytest

from nebula.founder_graph_facet_hierarchy import (
    FacetClassification,
    FacetHierarchyError,
    FacetNode,
    FacetTaxonomyRelation,
    RegionEntity,
    project_facet_region,
    validate_facet_hierarchy,
)


def test_taxonomy_rejects_cycles_even_when_edge_is_only_proposed() -> None:
    facets = (FacetNode("owner-1", "business", "Business"), FacetNode("owner-1", "startup", "Startup"))
    relations = (
        FacetTaxonomyRelation("owner-1", "business", "startup", status="proposed"),
        FacetTaxonomyRelation("owner-1", "startup", "business", status="proposed"),
    )
    with pytest.raises(FacetHierarchyError, match="cycle"):
        validate_facet_hierarchy(facets, relations, owner_id="owner-1")


def test_taxonomy_rejects_cross_owner_facets_and_relations() -> None:
    facets = (FacetNode("owner-1", "business", "Business"), FacetNode("owner-2", "startup", "Startup"))
    relation = FacetTaxonomyRelation("owner-1", "business", "startup", status="proposed")
    with pytest.raises(FacetHierarchyError, match="owner"):
        validate_facet_hierarchy(facets, (relation,), owner_id="owner-1")


@pytest.mark.parametrize("status", ["inferred", "confirmed"])
def test_inferred_and_confirmed_relations_require_evidence(status: str) -> None:
    facets = (FacetNode("owner-1", "business", "Business"),)
    relation = FacetTaxonomyRelation("owner-1", "business", "business", status=status)
    with pytest.raises(FacetHierarchyError, match="evidence"):
        validate_facet_hierarchy(facets, (relation,), owner_id="owner-1")


def test_region_projection_is_owner_scoped_grounded_and_depth_limited() -> None:
    facets = (
        FacetNode("owner-1", "business", "Business"),
        FacetNode("owner-1", "startup", "Startup"),
        FacetNode("owner-1", "marketplace", "Marketplace"),
        FacetNode("owner-1", "unrelated", "Unrelated"),
    )
    taxonomy = (
        FacetTaxonomyRelation("owner-1", "business", "startup", status="confirmed", evidence_ids=("ev-1",)),
        FacetTaxonomyRelation("owner-1", "startup", "marketplace", status="inferred", evidence_ids=("ev-2",)),
        FacetTaxonomyRelation("owner-1", "business", "unrelated", status="proposed"),
    )
    entities = (
        RegionEntity("owner-1", "idea-1", "idea", "Business concept"),
        RegionEntity("owner-1", "asset-1", "asset", "Market research"),
        RegionEntity("owner-1", "idea-2", "idea", "Unproven idea"),
        RegionEntity("owner-2", "asset-private", "asset", "Foreign owner"),
    )
    classifications = (
        FacetClassification("owner-1", "idea-1", "business", status="confirmed", evidence_ids=("ev-3",)),
        FacetClassification("owner-1", "asset-1", "marketplace", status="inferred", evidence_ids=("ev-4",)),
        FacetClassification("owner-1", "idea-2", "business", status="proposed"),
        FacetClassification("owner-2", "asset-private", "business", status="confirmed", evidence_ids=("ev-5",)),
    )
    shallow = project_facet_region(facets, taxonomy, entities, classifications, owner_id="owner-1", root_facet_id="business", max_facet_depth=0)
    deep = project_facet_region(facets, taxonomy, entities, classifications, owner_id="owner-1", root_facet_id="business", max_facet_depth=2)
    assert [(hit.entity.id, hit.facet_depth, hit.classification_status) for hit in shallow] == [("idea-1", 0, "confirmed")]
    assert [(hit.entity.id, hit.facet_depth, hit.classification_status) for hit in deep] == [("asset-1", 2, "inferred"), ("idea-1", 0, "confirmed")]
    assert deep[0].taxonomy_status_path == ("confirmed", "inferred")
    assert deep[0].evidence_ids == ("ev-1", "ev-2", "ev-4")
    assert [(item.facet_id, item.label, item.depth) for item in deep[0].facet_path] == [
        ("business", "Business", 0), ("startup", "Startup", 1),
        ("marketplace", "Marketplace", 2),
    ]


def test_region_projection_rejects_ungrounded_results_and_invalid_depth() -> None:
    facets = (FacetNode("owner-1", "business", "Business"),)
    entities = (RegionEntity("owner-1", "idea-1", "idea", "Idea"),)
    classification = FacetClassification("owner-1", "idea-1", "business", status="confirmed")
    with pytest.raises(FacetHierarchyError, match="evidence"):
        project_facet_region(facets, (), entities, (classification,), owner_id="owner-1", root_facet_id="business")
    with pytest.raises(FacetHierarchyError, match="depth"):
        project_facet_region(facets, (), entities, (), owner_id="owner-1", root_facet_id="business", max_facet_depth=-1)
    with pytest.raises(FacetHierarchyError, match="classification Facet"):
        project_facet_region(
            facets, (), entities, (FacetClassification("owner-1", "idea-1", "foreign", status="proposed"),),
            owner_id="owner-1", root_facet_id="business",
        )


def test_region_projection_keeps_distinct_memberships_but_one_best_path_per_membership() -> None:
    facets = tuple(FacetNode("owner-1", key, key) for key in ("root", "left", "right", "leaf"))
    taxonomy = (
        FacetTaxonomyRelation("owner-1", "root", "left", "confirmed", ("ev-left",)),
        FacetTaxonomyRelation("owner-1", "root", "right", "confirmed", ("ev-right",)),
        FacetTaxonomyRelation("owner-1", "left", "leaf", "confirmed", ("ev-leaf",)),
        FacetTaxonomyRelation("owner-1", "right", "leaf", "inferred", ("ev-leaf2",)),
        FacetTaxonomyRelation("owner-1", "root", "leaf", "confirmed", ("ev-direct",)),
    )
    entities = (RegionEntity("owner-1", "idea-1", "idea", "Idea"),)
    classifications = (
        FacetClassification("owner-1", "idea-1", "left", "confirmed", ("ev-class-left",)),
        FacetClassification("owner-1", "idea-1", "leaf", "confirmed", ("ev-class-leaf",)),
        FacetClassification("owner-1", "idea-1", "right", "inferred", ("ev-class-right",)),
    )

    hits = project_facet_region(
        facets, taxonomy, entities, classifications,
        owner_id="owner-1", root_facet_id="root", max_facet_depth=3,
    )

    assert {(hit.entity.id, hit.matched_facet_id, hit.facet_depth) for hit in hits} == {
        ("idea-1", "left", 1), ("idea-1", "right", 1), ("idea-1", "leaf", 1),
    }
    leaf = next(hit for hit in hits if hit.matched_facet_id == "leaf")
    assert [item.facet_id for item in leaf.facet_path] == ["root", "leaf"]
