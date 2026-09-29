from __future__ import annotations

from dots import founder_graph, founder_graph_types


def test_domain_enums_are_reexported_without_changing_identity() -> None:
    enum_names = (
        "Status", "ReportStatus", "AssetKind", "AssetHomeCategory", "MaterialKind", "EgressPolicy",
        "ProvenanceOrigin", "ClaimType", "EvidencePolarity", "RelationshipStatus",
        "RelationType", "RelationAssertionEdgeType", "EvidenceEdgeType", "NodeType",
    )

    for name in enum_names:
        assert getattr(founder_graph, name) is getattr(founder_graph_types, name)

    assert founder_graph.Status.ACTIVE.value == "active"
    assert founder_graph.NodeType.IDEA.value == "idea"
    assert founder_graph.AssetHomeCategory.CRITERION.value == "criterion"
    assert founder_graph.RelationType.SUPERSEDES.value == "SUPERSEDES"


def test_domain_vocabulary_aliases_still_point_to_the_original_enum_types() -> None:
    aliases = (
        "EntityStatus", "IdeaStatus", "AssetStatus", "CampaignStatus", "RunStatus",
        "ClaimStatus", "ResearchMaterialKind", "DataPolicy", "ProvenanceKind",
        "ClaimKind", "RelationStatus", "RelationshipType",
    )

    for name in aliases:
        assert getattr(founder_graph, name) is getattr(founder_graph_types, name)
