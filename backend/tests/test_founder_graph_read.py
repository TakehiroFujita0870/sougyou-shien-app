from __future__ import annotations

from datetime import datetime, timezone

import pytest

import nebula.founder_graph_read as read_module
from nebula.founder_graph import Asset, AssetKind, EgressPolicy, Evidence, Idea, NodeType, PersonAsset, RelationType, Relationship, Source, Status
from nebula.founder_graph_mcp import McpReadSurface
from nebula.founder_graph_read import GraphReadNotFoundError, GraphReadService, GraphReadTimeoutError
from nebula.founder_graph_write import InMemoryGraphWriteService


def _fixture() -> tuple[InMemoryGraphWriteService, GraphReadService]:
    writes = InMemoryGraphWriteService("owner-1")
    return writes, GraphReadService(writes)


def _link(person: PersonAsset, idea: Idea, evidence: Evidence) -> Relationship:
    return Relationship(
        owner_id="owner-1",
        source_id=person.id,
        source_kind=NodeType.PERSON,
        source_owner_id="owner-1",
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target_id=idea.id,
        target_kind=NodeType.IDEA,
        target_owner_id="owner-1",
        status="proposed",
        evidence_ids=(evidence.id,),
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )


def test_search_returns_keyword_and_one_hop_graph_hits() -> None:
    writes, reads = _fixture()
    person = PersonAsset(owner_id="owner-1", id="person-1", name="Founder network")
    idea = Idea(owner_id="owner-1", id="idea-1", title="Circular materials")
    evidence = Evidence(owner_id="owner-1", id="evidence-1", material_id="material-1", claim_id="claim-1")
    for node, key in ((person, "person"), (idea, "idea"), (evidence, "evidence")):
        writes.put_node(node, idempotency_key=key)
    writes.link_entities(_link(person, idea, evidence), idempotency_key="link")

    page = reads.search("Founder", owner_id="owner-1")

    assert page.hits[0].node.id == person.id
    idea_hit = next(hit for hit in page.hits if hit.node.id == idea.id)
    assert idea_hit.path == (person.id, RelationType.CAN_CONTRIBUTE_TO.value, idea.id)
    assert len(idea_hit.relation_path) == 1
    step = idea_hit.relation_path[0]
    assert step.from_id == person.id
    assert step.to_id == idea.id
    assert step.source_id == person.id
    assert step.target_id == idea.id
    assert step.predicate == RelationType.CAN_CONTRIBUTE_TO.value
    assert step.traversal_direction == "outgoing"
    assert step.evidence_ids == (evidence.id,)
    assert step.status == "proposed"
    assert step.confidence == 0.8
    assert step.expires_at == "2027-01-01T00:00:00+00:00"
    assert step.relation_assertion_id is None
    assert idea_hit.score < page.hits[0].score

    incoming_page = reads.search("Circular materials", owner_id="owner-1")
    person_hit = next(hit for hit in incoming_page.hits if hit.node.id == person.id)
    incoming_step = person_hit.relation_path[0]
    assert incoming_step.from_id == idea.id
    assert incoming_step.to_id == person.id
    assert incoming_step.source_id == person.id
    assert incoming_step.target_id == idea.id
    assert incoming_step.traversal_direction == "incoming"
    assert incoming_step.relation_assertion_id is None


def test_person_asset_projection_exposes_canonical_revision_metadata() -> None:
    writes, reads = _fixture()
    person = PersonAsset(owner_id="owner-1", id="person-revision", name="Synthetic person")
    writes.put_node(person, idempotency_key="person-revision")

    view = reads.fetch(person.id, owner_id="owner-1")

    assert view.revision == person.revision == 1
    assert "revision" not in view.fields


@pytest.mark.parametrize(
    ("kind", "category"),
    [(AssetKind.KNOWLEDGE, "strength"), (AssetKind.BARRIER, "barrier")],
)
def test_legacy_asset_category_is_resolved_for_search_and_mcp(kind, category) -> None:
    writes, reads = _fixture()
    legacy = Asset(
        owner_id="owner-1", id=f"legacy-{category}", name="Legacy asset",
        kind=kind, egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(legacy, idempotency_key=f"legacy-{category}")
    surface = McpReadSurface(reads)

    page = reads.search("Legacy asset", owner_id="owner-1")
    fetched = surface.call("fetch", {"id": legacy.id}, owner_id="owner-1")
    searched = surface.call("search", {"query": "Legacy asset"}, owner_id="owner-1")

    assert [hit.node.id for hit in page.hits] == [legacy.id]
    assert page.hits[0].node.fields["home_category"] == category
    assert fetched["fields"]["home_category"] == category
    assert [hit["id"] for hit in searched["results"]] == [legacy.id]
    assert searched["results"][0]["fields"]["home_category"] == category


def test_current_asset_lineage_rejects_mixed_asset_subtypes() -> None:
    parent = Asset(
        owner_id="owner-1", id="asset-parent", name="Parent", kind=AssetKind.PERSON,
    )
    child = PersonAsset(
        owner_id="owner-1", id="person-child", name="Child", revision=2,
        supersedes_id=parent.id,
    )
    node_by_id = {parent.id: parent, child.id: child}

    assert not GraphReadService._current_endpoint(parent, "owner-1", node_by_id)
    assert not GraphReadService._current_endpoint(child, "owner-1", node_by_id)


def test_search_expands_to_two_hops_but_not_three() -> None:
    writes, reads = _fixture()
    nodes = tuple(
        Idea(owner_id="owner-1", id=node_id, title=title)
        for node_id, title in (
            ("root", "Founder seed"),
            ("middle", "Bridge idea"),
            ("leaf", "Remote asset"),
            ("far", "Too far"),
        )
    )
    for node, key in zip(nodes, ("root", "middle", "leaf", "far")):
        writes.put_node(node, idempotency_key=key)
    for index, (source, target) in enumerate(zip(nodes, nodes[1:]), start=1):
        writes.link_entities(
            Relationship(
                owner_id="owner-1",
                source_id=source.id,
                source_kind=NodeType.IDEA,
                source_owner_id="owner-1",
                relation=RelationType.DERIVED_FROM,
                target_id=target.id,
                target_kind=NodeType.IDEA,
                target_owner_id="owner-1",
            ),
            idempotency_key=f"link-{index}",
        )

    page = reads.search("Founder", owner_id="owner-1")

    assert [hit.node.id for hit in page.hits] == ["root", "middle", "leaf"]
    assert page.hits[0].path == ()
    assert page.hits[1].path == ("root", RelationType.DERIVED_FROM.value, "middle")
    assert page.hits[2].path == (
        "root",
        RelationType.DERIVED_FROM.value,
        "middle",
        RelationType.DERIVED_FROM.value,
        "leaf",
    )
    assert [step.from_id for step in page.hits[2].relation_path] == ["root", "middle"]
    assert [step.to_id for step in page.hits[2].relation_path] == ["middle", "leaf"]
    assert [step.relation_assertion_id for step in page.hits[2].relation_path] == [None, None]
    assert page.hits[0].score > page.hits[1].score > page.hits[2].score


def test_search_filters_owner_and_non_current_nodes() -> None:
    writes, reads = _fixture()
    writes.put_node(Idea(owner_id="owner-1", id="current", title="Graph current"), idempotency_key="current")
    writes.put_node(Idea(owner_id="owner-1", id="old", title="Graph old", status=Status.SUPERSEDED), idempotency_key="old")
    foreign_writes = InMemoryGraphWriteService("owner-2")
    foreign_writes.put_node(Idea(owner_id="owner-2", id="other", title="Graph other"), idempotency_key="other")

    page = reads.search("Graph", owner_id="owner-1")

    assert [hit.node.id for hit in page.hits] == ["current"]
    assert GraphReadService(foreign_writes).search("Graph", owner_id="owner-1").hits == ()


def test_search_paginates_with_stable_cursor_and_limit() -> None:
    writes, reads = _fixture()
    for index in range(3):
        writes.put_node(Idea(owner_id="owner-1", id=f"idea-{index}", title="Graph seed"), idempotency_key=f"idea-{index}")

    first = reads.search("Graph", owner_id="owner-1", limit=2)
    second = reads.search("Graph", owner_id="owner-1", limit=2, cursor=first.next_cursor)

    assert first.next_cursor == "2"
    assert [hit.node.id for hit in first.hits] == ["idea-0", "idea-1"]
    assert [hit.node.id for hit in second.hits] == ["idea-2"]
    assert second.next_cursor is None


def test_fetch_enforces_owner_boundary() -> None:
    writes, reads = _fixture()
    writes.put_node(Idea(owner_id="owner-1", id="idea-1", title="Private idea"), idempotency_key="idea")

    assert reads.fetch("idea-1", owner_id="owner-1").title == "Private idea"
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch("idea-1", owner_id="owner-2")
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch("missing", owner_id="owner-1")


def test_read_view_has_an_explicit_egress_policy_for_canonical_source() -> None:
    writes, reads = _fixture()
    source = Source(
        owner_id="owner-1",
        id="source-1",
        title="Market source",
        locator="https://example.test/source",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(source, idempotency_key="source")

    view = reads.fetch(source.id, owner_id="owner-1")

    assert view.node_type == NodeType.SOURCE.value
    assert view.fields["egress_policy"] == EgressPolicy.SHAREABLE.value


def test_search_timeout_is_recoverable_and_has_no_partial_success(monkeypatch: pytest.MonkeyPatch) -> None:
    writes, reads = _fixture()
    writes.put_node(Idea(owner_id="owner-1", id="idea-1", title="Graph seed"), idempotency_key="idea")
    clock = iter((0.0, 1.0))
    monkeypatch.setattr(read_module, "monotonic", lambda: next(clock))

    with pytest.raises(GraphReadTimeoutError):
        reads.search("Graph", owner_id="owner-1", timeout_ms=1)
