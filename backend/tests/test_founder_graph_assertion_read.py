from __future__ import annotations

from dataclasses import replace
from threading import Event, Thread

import pytest

from dots.founder_graph import (
    Idea,
    NodeType,
    RelationAssertionEdgeType,
    RelationType,
    RelationshipStatus,
    Status,
)
from dots.founder_graph_read import GraphReadService
from test_founder_graph_relation_assertion_write import _setup


def _assertion_hit(reads: GraphReadService, query: str):
    page = reads.search(query, owner_id="owner-memory")
    return next(hit for hit in page.hits if hit.node.id == "claim-relation")


def test_search_projects_exact_formal_assertion_path_with_brief_and_evidence():
    writes, _, _, _, brief, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")

    hit = _assertion_hit(GraphReadService(writes), "Synthetic target")

    assert hit.path == (assertion.source_id, assertion.predicate.value, assertion.target_id)
    assert len(hit.relation_path) == 1
    step = hit.relation_path[0]
    assert step.relation_assertion_id == assertion.id
    assert step.evidence_ids == assertion.evidence_ids
    assert step.based_on_brief_id == brief.id
    assert step.based_on_brief_section_index == assertion.based_on_brief_section_index


@pytest.mark.parametrize("successor_status", [RelationshipStatus.REJECTED, RelationshipStatus.EXPIRED])
def test_same_owner_successor_suppresses_old_assertion_even_when_not_current(successor_status):
    writes, _, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
    successor = replace(
        assertion, id="assertion-noncurrent-successor", revision=2,
        status=successor_status, supersedes_id=assertion.id,
    )
    writes._nodes[successor.id] = successor
    writes._structural_edges.append((successor.id, RelationAssertionEdgeType.SUPERSEDES.value, assertion.id))

    page = GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id)

    assert not any(step.relation_assertion_id == assertion.id for hit in page.hits for step in hit.relation_path)


def test_foreign_successor_does_not_suppress_owner_assertion():
    writes, _, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
    foreign = replace(assertion, id="foreign-successor", owner_id="other-owner", revision=2, supersedes_id=assertion.id)
    writes._nodes[foreign.id] = foreign

    hit = _assertion_hit(GraphReadService(writes), "Synthetic target")

    assert hit.relation_path[0].relation_assertion_id == assertion.id


def test_payload_only_malformed_successor_suppresses_predecessor_but_is_not_a_path():
    writes, _, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
    successor = replace(assertion, id="payload-only-successor", revision=2, supersedes_id=assertion.id)
    writes._nodes[successor.id] = successor

    page = GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id)

    assert not any(step.relation_assertion_id in {assertion.id, successor.id} for hit in page.hits for step in hit.relation_path)


def test_ambiguous_successors_suppress_predecessor_and_all_successor_paths():
    writes, _, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
    for successor_id in ("successor-one", "successor-two"):
        successor = replace(assertion, id=successor_id, revision=2, supersedes_id=assertion.id)
        writes._nodes[successor_id] = successor
        writes._structural_edges.extend(
            relation_edge for relation_edge in (
                (successor_id, RelationAssertionEdgeType.ASSERTS_FROM.value, assertion.source_id),
                (successor_id, RelationAssertionEdgeType.ASSERTS_TO.value, assertion.target_id),
                (successor_id, RelationAssertionEdgeType.EVIDENCED_BY.value, assertion.evidence_ids[0]),
                (successor_id, RelationAssertionEdgeType.SUPERSEDES.value, assertion.id),
            )
        )

    page = GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id)

    visible_ids = {step.relation_assertion_id for hit in page.hits for step in hit.relation_path}
    assert "assertion-relation" not in visible_ids
    assert "successor-one" not in visible_ids
    assert "successor-two" not in visible_ids


def test_idea_endpoints_both_current_but_only_primary_idea_requires_brief():
    writes, _, _, _, brief, assertion = _setup()
    second_idea = Idea(id="idea-second", owner_id=writes.owner_id, title="Second idea")
    writes.put_node(second_idea, idempotency_key="second-idea")
    both_ideas = replace(
        assertion,
        id="assertion-two-ideas",
        target_id=second_idea.id,
        target_kind=NodeType.IDEA,
        predicate=RelationType.DERIVED_FROM,
    )
    assert both_ideas.based_on_brief_id == brief.id
    writes.save_relation_assertion(both_ideas, expected_family_revision=None, idempotency_key="both-ideas")
    page = GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id)
    hit = next(hit for hit in page.hits if hit.node.id == second_idea.id)
    assert hit.relation_path[0].based_on_brief_id == brief.id

    writes._nodes[second_idea.id] = replace(second_idea, status=Status.SUPERSEDED)
    page_after_target_stale = GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id)
    assert not any(
        step.relation_assertion_id == both_ideas.id
        for hit in page_after_target_stale.hits
        for step in hit.relation_path
    )


def test_missing_or_disagreeing_canonical_refs_never_fall_back_to_payload():
    for edge_case in ("missing", "duplicate", "wrong_target"):
        writes, _, _, _, _, assertion = _setup()
        writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
        edge = (assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, assertion.target_id)
        writes._structural_edges.remove(edge)
        if edge_case == "duplicate":
            writes._structural_edges.extend((edge, edge))
        elif edge_case == "wrong_target":
            writes._structural_edges.append((assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, "missing-node"))

        page = GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id)

        assert not any(step.relation_assertion_id == assertion.id for hit in page.hits for step in hit.relation_path)


def test_newer_brief_hides_old_formal_path_without_erasing_history():
    writes, _, _, _, brief, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
    newer = brief.revise(change_reason="newer synthetic research", research_run_ids=brief.research_run_ids)
    writes.save_idea_brief(newer, expected_latest_revision=1, idempotency_key="newer-brief")

    page = GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id)

    assert not any(step.relation_assertion_id == assertion.id for hit in page.hits for step in hit.relation_path)
    assert writes.get_node(assertion.id) is assertion


def test_empty_selected_brief_section_hides_formal_path():
    writes, _, _, _, brief, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
    writes._idea_briefs[brief.id] = replace(brief, sections=tuple(replace(s, content=" ") if s.index == assertion.based_on_brief_section_index else s for s in brief.sections))
    assert all(step.relation_assertion_id != assertion.id for step in _assertion_hit(GraphReadService(writes), "Synthetic target").relation_path)


def test_reader_waits_for_atomic_write_and_uses_one_lock_held_snapshot():
    writes, _, _, _, _, assertion = _setup()
    entered_audit = Event()
    release_write = Event()
    reader_started = Event()
    reader_done = Event()
    result = []
    append_audit = writes._append_audit

    def pause_before_audit(receipt, actor, fingerprint):
        entered_audit.set()
        assert release_write.wait(2)
        append_audit(receipt, actor, fingerprint)

    writes._append_audit = pause_before_audit
    writer = Thread(target=lambda: writes.save_relation_assertion(
        assertion, expected_family_revision=None, idempotency_key="formal-read",
    ))
    writer.start()
    assert entered_audit.wait(2)

    def search():
        reader_started.set()
        result.append(_assertion_hit(GraphReadService(writes), "Synthetic target"))
        reader_done.set()

    reader = Thread(target=search)
    reader.start()
    assert reader_started.wait(2)
    assert not reader_done.wait(0.05)
    release_write.set()
    writer.join(2)
    reader.join(2)
    assert not writer.is_alive() and not reader.is_alive()
    assert result[0].relation_path[0].relation_assertion_id == assertion.id

    snapshot = writes.read_snapshot()
    assert snapshot.nodes
    assert isinstance(snapshot.nodes, tuple)
    assert isinstance(snapshot.relations, tuple)
    assert isinstance(snapshot.structural_edges, tuple)
    assert isinstance(snapshot.idea_briefs, tuple)


def test_later_campaign_revocation_does_not_revalidate_accepted_brief_at_read_time():
    writes, idea, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="formal-read")
    campaign = writes.get_node("campaign-relation")
    revoked_at = campaign.expires_at
    revoked = campaign.change_scope(
        {"target_ids": [idea.id], "question": "later synthetic scope"},
        at=revoked_at,
    )
    writes.put_node(
        revoked, expected_revision=campaign.aggregate_revision, idempotency_key="later-revocation",
    )

    hit = _assertion_hit(GraphReadService(writes), "Synthetic target")

    assert hit.relation_path[0].relation_assertion_id == assertion.id
