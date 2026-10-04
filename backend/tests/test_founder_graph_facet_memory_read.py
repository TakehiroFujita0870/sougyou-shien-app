from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from nebula.founder_graph import Asset, EgressPolicy, Facet, Idea, NodeType, Provenance, RelationAssertion, RelationType, RelationshipStatus, Status
from nebula.founder_graph_facet_memory_read import facet_region_from_snapshot
from nebula.founder_graph_write import GraphReadSnapshot


def _relation(source: str, source_kind: NodeType, target: str, target_kind: NodeType, family: str, evidence: str) -> RelationAssertion:
    return RelationAssertion(
        owner_id="owner-1", source_id=source, source_kind=source_kind,
        target_id=target, target_kind=target_kind,
        predicate=RelationType.CLASSIFIED_AS, assertion_family_id=family,
        status=RelationshipStatus.CONFIRMED, evidence_ids=(evidence,),
        egress_policy=EgressPolicy.SHAREABLE,
    )


def test_memory_region_returns_only_current_shareable_grounded_memberships() -> None:
    root = Facet(owner_id="owner-1", id="facet-root", namespace="domain", value="Business", egress_policy=EgressPolicy.SHAREABLE)
    child = Facet(owner_id="owner-1", id="facet-child", namespace="domain", value="Bakery", egress_policy=EgressPolicy.SHAREABLE)
    private = Facet(owner_id="owner-1", id="facet-private", namespace="domain", value="Private")
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    private_idea = Idea(owner_id="owner-1", id="idea-private", title="Private", status=Status.ACTIVE)
    evidence = tuple(
        SimpleNamespace(id=item, owner_id="owner-1", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
        for item in ("ev-taxonomy", "ev-classification")
    )
    taxonomy = _relation("facet-root", NodeType.FACET, "facet-child", NodeType.FACET, "tax", "ev-taxonomy")
    classified = _relation("idea-1", NodeType.IDEA, "facet-child", NodeType.FACET, "idea", "ev-classification")
    private_classification = _relation("idea-private", NodeType.IDEA, "facet-root", NodeType.FACET, "private", "ev-classification")
    snapshot = GraphReadSnapshot(
        nodes=(root, child, private, idea, private_idea, *evidence, taxonomy, classified, private_classification),
        relations=(), structural_edges=(), idea_briefs=(), latest_idea_briefs=(),
    )

    hits = facet_region_from_snapshot(snapshot, "facet-root", owner_id="owner-1", max_facet_depth=1)

    assert [(hit.entity.id, hit.matched_facet_id, hit.facet_depth) for hit in hits] == [
        ("idea-1", "facet-child", 1),
    ]
    assert hits[0].evidence_ids == ("ev-taxonomy", "ev-classification")
    assert [item.label for item in hits[0].facet_path] == ["domain: Business", "domain: Bakery"]


def test_memory_region_uses_retracted_family_tip_and_keeps_other_axes() -> None:
    root = Facet(owner_id="owner-1", id="facet-root", namespace="domain", value="Root", egress_policy=EgressPolicy.SHAREABLE)
    child = Facet(owner_id="owner-1", id="facet-child", namespace="domain", value="Child", egress_policy=EgressPolicy.SHAREABLE)
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    old = _relation("facet-root", NodeType.FACET, "facet-child", NodeType.FACET, "tax", "ev")
    retracted = RelationAssertion(
        owner_id="owner-1", id="tax-retracted", source_id=old.source_id, source_kind=old.source_kind,
        target_id=old.target_id, target_kind=old.target_kind, predicate=old.predicate,
        assertion_family_id=old.assertion_family_id, revision=2, status=RelationshipStatus.RETRACTED,
        supersedes_id=old.id, egress_policy=EgressPolicy.SHAREABLE,
    )
    evidence = SimpleNamespace(id="ev", owner_id="owner-1", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    direct = _relation("idea-1", NodeType.IDEA, "facet-root", NodeType.FACET, "idea-root", "ev")
    child_classification = _relation("idea-1", NodeType.IDEA, "facet-child", NodeType.FACET, "idea-child", "ev")
    snapshot = GraphReadSnapshot(
        nodes=(root, child, idea, evidence, old, retracted, direct, child_classification),
        relations=(), structural_edges=(), idea_briefs=(), latest_idea_briefs=(),
    )

    hits = facet_region_from_snapshot(snapshot, "facet-root", owner_id="owner-1", max_facet_depth=1)

    assert [(hit.matched_facet_id, hit.facet_depth) for hit in hits] == [("facet-root", 0)]


def test_memory_region_omits_membership_when_any_evidence_is_private() -> None:
    facet = Facet(owner_id="owner-1", id="facet-root", namespace="domain", value="Root", egress_policy=EgressPolicy.SHAREABLE)
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    private_evidence = SimpleNamespace(id="ev-private", owner_id="owner-1", status=Status.ACTIVE, egress_policy=EgressPolicy.LOCAL_ONLY)
    assertion = _relation("idea-1", NodeType.IDEA, "facet-root", NodeType.FACET, "idea-facet", "ev-private")
    snapshot = GraphReadSnapshot(
        nodes=(facet, idea, private_evidence, assertion),
        relations=(), structural_edges=(), idea_briefs=(), latest_idea_briefs=(),
    )

    assert facet_region_from_snapshot(snapshot, "facet-root", owner_id="owner-1", max_facet_depth=1) == ()


def test_memory_region_keeps_distinct_facet_memberships_for_one_entity() -> None:
    root = Facet(owner_id="owner-1", id="root", namespace="domain", value="Root", egress_policy=EgressPolicy.SHAREABLE)
    left = Facet(owner_id="owner-1", id="left", namespace="domain", value="Left", egress_policy=EgressPolicy.SHAREABLE)
    right = Facet(owner_id="owner-1", id="right", namespace="domain", value="Right", egress_policy=EgressPolicy.SHAREABLE)
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    evidence = SimpleNamespace(id="ev", owner_id="owner-1", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    left_edge = _relation("root", NodeType.FACET, "left", NodeType.FACET, "tax-left", "ev")
    right_edge = _relation("root", NodeType.FACET, "right", NodeType.FACET, "tax-right", "ev")
    left_membership = _relation("idea-1", NodeType.IDEA, "left", NodeType.FACET, "idea-left", "ev")
    right_membership = _relation("idea-1", NodeType.IDEA, "right", NodeType.FACET, "idea-right", "ev")
    snapshot = GraphReadSnapshot(
        nodes=(root, left, right, idea, evidence, left_edge, right_edge, left_membership, right_membership),
        relations=(), structural_edges=(), idea_briefs=(), latest_idea_briefs=(),
    )

    hits = facet_region_from_snapshot(snapshot, "root", owner_id="owner-1", max_facet_depth=1)

    assert [(hit.entity.id, hit.matched_facet_id) for hit in hits] == [
        ("idea-1", "left"), ("idea-1", "right"),
    ]


def test_memory_region_fails_closed_on_tied_latest_family_revisions() -> None:
    root = Facet(owner_id="owner-1", id="root", namespace="domain", value="Root", egress_policy=EgressPolicy.SHAREABLE)
    child_a = Facet(owner_id="owner-1", id="child-a", namespace="domain", value="A", egress_policy=EgressPolicy.SHAREABLE)
    child_b = Facet(owner_id="owner-1", id="child-b", namespace="domain", value="B", egress_policy=EgressPolicy.SHAREABLE)
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    evidence = SimpleNamespace(id="ev", owner_id="owner-1", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    first = _relation("idea-1", NodeType.IDEA, "child-a", NodeType.FACET, "classification-family", "ev")
    second = replace(first, id="classification-fork", target_id="child-b")
    taxonomy_a = _relation("root", NodeType.FACET, "child-a", NodeType.FACET, "tax-a", "ev")
    taxonomy_b = _relation("root", NodeType.FACET, "child-b", NodeType.FACET, "tax-b", "ev")
    snapshot = GraphReadSnapshot(
        nodes=(root, child_a, child_b, idea, evidence, first, second, taxonomy_a, taxonomy_b),
        relations=(), structural_edges=(), idea_briefs=(), latest_idea_briefs=(),
    )

    assert facet_region_from_snapshot(snapshot, "root", owner_id="owner-1", max_facet_depth=1) == ()


def test_memory_region_restores_idea_and_asset_classifications_only_across_lifecycle_chain() -> None:
    facet = Facet(owner_id="owner-1", id="facet", namespace="domain", value="Founder", egress_policy=EgressPolicy.SHAREABLE)
    evidence = SimpleNamespace(id="ev", owner_id="owner-1", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    idea0 = Idea(owner_id="owner-1", id="idea-0", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    idea1 = replace(
        idea0, id="idea-1", revision=1, supersedes_id=idea0.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="owner", operation="archive_idea", target_id="idea-1", source_id=idea0.id),
    )
    idea2 = replace(
        idea1, id="idea-2", revision=2, supersedes_id=idea1.id, status=Status.ACTIVE,
        provenance=Provenance(actor="owner", operation="restore_idea", target_id="idea-2", source_id=idea1.id),
    )
    asset0 = Asset(owner_id="owner-1", id="asset-0", name="Asset", egress_policy=EgressPolicy.SHAREABLE)
    asset1 = replace(
        asset0, id="asset-1", revision=2, supersedes_id=asset0.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="owner", operation="archive_asset", target_id="asset-1", source_id=asset0.id),
    )
    asset2 = replace(
        asset1, id="asset-2", revision=3, supersedes_id=asset1.id, status=Status.ACTIVE,
        provenance=Provenance(actor="owner", operation="restore_asset", target_id="asset-2", source_id=asset1.id),
    )
    idea_classification = _relation("idea-0", NodeType.IDEA, "facet", NodeType.FACET, "idea-class", "ev")
    asset_classification = _relation("asset-0", NodeType.ASSET, "facet", NodeType.FACET, "asset-class", "ev")
    snapshot = GraphReadSnapshot(
        nodes=(facet, evidence, idea0, idea1, idea2, asset0, asset1, asset2, idea_classification, asset_classification),
        relations=(), structural_edges=(), idea_briefs=(), latest_idea_briefs=(),
    )

    hits = facet_region_from_snapshot(snapshot, "facet", owner_id="owner-1")

    assert [hit.entity.id for hit in hits] == ["asset-2", "idea-2"]
    assert {hit.entity.kind for hit in hits} == {"asset", "idea"}


def test_memory_region_does_not_restore_classification_after_normal_revision() -> None:
    facet = Facet(owner_id="owner-1", id="facet", namespace="domain", value="Founder", egress_policy=EgressPolicy.SHAREABLE)
    evidence = SimpleNamespace(id="ev", owner_id="owner-1", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    idea0 = Idea(owner_id="owner-1", id="idea-0", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    idea1 = replace(
        idea0, id="idea-1", revision=1, supersedes_id=idea0.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="owner", operation="archive_idea", target_id="idea-1", source_id=idea0.id),
    )
    idea2 = replace(
        idea1, id="idea-2", revision=2, supersedes_id=idea1.id, status=Status.ACTIVE,
        provenance=Provenance(actor="owner", operation="restore_idea", target_id="idea-2", source_id=idea1.id),
    )
    edited = replace(
        idea2, id="idea-3", revision=3, supersedes_id=idea2.id, title="Edited",
        provenance=Provenance(actor="owner", operation="revise_idea", target_id="idea-3", source_id=idea2.id),
    )
    assertion = _relation("idea-0", NodeType.IDEA, "facet", NodeType.FACET, "idea-class", "ev")
    snapshot = GraphReadSnapshot(
        nodes=(facet, evidence, idea0, idea1, idea2, edited, assertion),
        relations=(), structural_edges=(), idea_briefs=(), latest_idea_briefs=(),
    )

    assert facet_region_from_snapshot(snapshot, "facet", owner_id="owner-1") == ()
