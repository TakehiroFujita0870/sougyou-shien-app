from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import (
    Claim,
    DomainValidationError,
    EgressPolicy,
    Evidence,
    Idea,
    NodeType,
    Provenance,
    RelationAssertion,
    RelationAssertionEdgeType,
    RelationType,
    Relationship,
    RelationshipStatus,
    ResearchCampaign,
    ResearchRun,
    Status,
    relation_assertion_structural_edges,
)
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.founder_graph_write import (
    GraphWriteError,
    IdempotencyConflictError,
    InMemoryGraphWriteService,
    RevisionConflictError,
)


def _setup():
    now = datetime.now(timezone.utc)
    writes = InMemoryGraphWriteService("owner-memory")
    idea = Idea(id="idea-relation", owner_id=writes.owner_id, title="Synthetic target")
    claim = Claim(
        id="claim-relation", owner_id=writes.owner_id, text="Synthetic claim", confidence=0.8,
        evidence_ids=("evidence-relation",), egress_policy=EgressPolicy.SHAREABLE,
    )
    evidence = Evidence(
        id="evidence-relation", owner_id=writes.owner_id, material_id="material-relation",
        claim_id=claim.id, egress_policy=EgressPolicy.SHAREABLE,
    )
    for node in (idea, claim, evidence):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")

    created = now - timedelta(minutes=10)
    campaign = ResearchCampaign(
        id="campaign-relation", owner_id=writes.owner_id, purpose="Synthetic bounded research",
        target_idea_id=idea.id, allowed_categories=("idea.summary",), trial_budget=1,
        expires_at=now + timedelta(hours=1), egress_policy=EgressPolicy.SHAREABLE,
        created_at=created, provenance=Provenance(
            actor="synthetic-test", operation="seed", target_id="campaign-relation", occurred_at=created,
        ),
    )
    writes.put_node(campaign, idempotency_key="seed-campaign")
    approved = campaign.approve(approved_at=now - timedelta(minutes=5), provenance=Provenance(
        actor="synthetic-test", operation="approve", target_id=campaign.id,
        occurred_at=now - timedelta(minutes=5),
    ))
    writes.put_node(approved, expected_revision=campaign.aggregate_revision, idempotency_key="approve-campaign")
    run = ResearchRun(
        id="run-relation", owner_id=writes.owner_id, campaign_id=campaign.id,
        input_snapshot={"query": "synthetic"}, model_snapshot="synthetic-model@1",
        sources=("synthetic-source",), evidence_ids=(evidence.id,), results={"summary": "synthetic"},
        status=Status.COMPLETED, egress_policy=EgressPolicy.SHAREABLE,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision,
        started_at=now - timedelta(minutes=3), finished_at=now - timedelta(minutes=2),
        provenance=Provenance(actor="synthetic-test", operation="record_research_run", target_id="run-relation"),
    )
    writes.record_research_run(run, expected_campaign_revision=approved.aggregate_revision, idempotency_key="record-run")
    brief = IdeaBriefVersion(
        id="brief-relation", owner_id=writes.owner_id, idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id, research_run_ids=(run.id,),
        sections=tuple(IdeaBriefSection(index=i, content=f"Synthetic section {i}", evidence_ids=(evidence.id,)) for i in range(8)),
    )
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="save-brief")
    assertion = RelationAssertion(
        id="assertion-relation", owner_id=writes.owner_id, source_id=idea.id, source_kind=NodeType.IDEA,
        target_id=claim.id, target_kind=NodeType.CLAIM, predicate=RelationType.ADDRESSES,
        assertion_family_id="family-relation", status=RelationshipStatus.CONFIRMED,
        evidence_ids=(evidence.id,), based_on_brief_id=brief.id, based_on_brief_section_index=1,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    return writes, idea, claim, evidence, brief, assertion


def test_domain_helper_returns_only_canonical_typed_edges():
    _, _, _, _, _, assertion = _setup()
    assert relation_assertion_structural_edges(assertion) == (
        (assertion.id, RelationAssertionEdgeType.ASSERTS_FROM.value, assertion.source_id),
        (assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, assertion.target_id),
        (assertion.id, RelationAssertionEdgeType.EVIDENCED_BY.value, assertion.evidence_ids[0]),
    )
    successor = replace(assertion, id="assertion-successor", revision=2, supersedes_id=assertion.id)
    assert relation_assertion_structural_edges(successor)[-1] == (
        successor.id, RelationAssertionEdgeType.SUPERSEDES.value, assertion.id,
    )


def test_save_assertion_checks_researched_brief_and_replays_without_repair():
    writes, idea, _, evidence, brief, assertion = _setup()
    campaign = writes.get_node("campaign-relation")
    revoked_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    revoked = campaign.change_scope(
        {"target_ids": [idea.id], "question": "later synthetic scope"},
        at=revoked_at,
        provenance=Provenance(
            actor="synthetic-test", operation="scope_change", target_id=campaign.id,
            occurred_at=revoked_at,
        ),
    )
    writes.put_node(
        revoked, expected_revision=campaign.aggregate_revision, idempotency_key="revoke-after-brief",
    )
    receipt = writes.save_relation_assertion(
        assertion, expected_family_revision=None, idempotency_key="assertion-write",
    )
    assert (receipt.target_id, receipt.target_type, receipt.revision, receipt.replayed) == (
        assertion.id, NodeType.RELATION_ASSERTION.value, 1, False,
    )
    assert writes.get_node(assertion.id) is assertion
    assert writes.node_history(assertion.id) == (assertion,)
    assert writes.structural_edges()[-3:] == relation_assertion_structural_edges(assertion)
    audit_count = len(writes.audit_events())

    # Mutable state has moved on; exact replay must be receipt-only and never repair edges.
    writes._nodes[idea.id] = replace(idea, status=Status.ARCHIVED)
    writes._structural_edges.remove((assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, assertion.target_id))
    replay = writes.save_relation_assertion(
        replace(assertion, valid_from=assertion.valid_from + timedelta(seconds=1)),
        expected_family_revision=None, idempotency_key="assertion-write",
    )
    assert replay.replayed is True and replay.target_id == assertion.id
    assert len(writes.audit_events()) == audit_count
    assert (assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, assertion.target_id) not in writes.structural_edges()
    assert writes.get_latest_idea_brief(idea.id) is brief
    assert writes.get_node(evidence.id) is evidence


@pytest.mark.parametrize(
    "case",
    ["wrong_kind", "foreign_endpoint", "archived_endpoint", "superseded_endpoint", "inactive_evidence", "foreign_evidence", "missing_brief",
     "wrong_section_evidence", "empty_runs", "latest_brief", "missing_run_receipt"],
)
def test_invalid_assertion_provenance_fails_without_mutation(case: str):
    writes, idea, claim, evidence, brief, assertion = _setup()
    if case == "wrong_kind":
        writes._nodes[claim.id] = Idea(id=claim.id, owner_id=writes.owner_id, title="Wrong actual endpoint type")
    elif case == "foreign_endpoint":
        writes._nodes[claim.id] = replace(claim, owner_id="owner-foreign")
    elif case == "archived_endpoint":
        writes._nodes[idea.id] = replace(idea, status=Status.ARCHIVED)
    elif case == "superseded_endpoint":
        writes.put_node(claim.revise(text="Superseding claim"), idempotency_key="seed-claim-successor")
    elif case == "inactive_evidence":
        writes._nodes[evidence.id] = replace(evidence, status=Status.RETRACTED)
    elif case == "foreign_evidence":
        writes._nodes[evidence.id] = replace(evidence, owner_id="owner-foreign")
    elif case == "missing_brief":
        assertion = replace(assertion, based_on_brief_id="brief-missing")
    elif case == "wrong_section_evidence":
        section = replace(brief.sections[1], evidence_ids=())
        bad_brief = replace(brief, sections=(brief.sections[0], section, *brief.sections[2:]))
        writes._idea_briefs[brief.id] = bad_brief
    elif case == "empty_runs":
        empty_brief = replace(brief, research_run_ids=())
        writes._idea_briefs[brief.id] = empty_brief
    elif case == "latest_brief":
        newer_brief = brief.revise(change_reason="synthetic newer brief")
        writes.save_idea_brief(newer_brief, expected_latest_revision=1, idempotency_key="save-newer-brief")
    elif case == "missing_run_receipt":
        writes._idempotency.pop("record-run")
    before_nodes = writes.nodes()
    before_history = {node.id: writes.node_history(node.id) for node in before_nodes}
    before_edges = writes.structural_edges()
    before_audit = writes.audit_events()
    before_receipts = dict(writes._idempotency)
    before_latest_brief = writes.get_latest_idea_brief(idea.id)
    with pytest.raises(GraphWriteError):
        writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key=f"invalid-{case}")
    assert writes.nodes() == before_nodes
    assert {node.id: writes.node_history(node.id) for node in before_nodes} == before_history
    assert writes.structural_edges() == before_edges
    assert writes.audit_events() == before_audit
    assert writes._idempotency == before_receipts
    assert writes.get_latest_idea_brief(idea.id) is before_latest_brief
    assert writes.get_node(assertion.id) is None
    assert writes._idempotency.get(f"invalid-{case}") is None
    assert writes.get_node(idea.id) is not None and writes.get_node(claim.id) is not None


def test_generic_put_node_cannot_bypass_structural_assertion_edges():
    writes, _, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="canonical-assertion")
    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())
    with pytest.raises(GraphWriteError, match="save_relation_assertion"):
        writes.put_node(assertion, idempotency_key="raw-assertion")
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before
    assert writes._idempotency.get("raw-assertion") is None
    for label in ("ASSERTS_FROM", "ASSERTS_TO", "EVIDENCED_BY"):
        assert label not in RelationType.__members__
        with pytest.raises(DomainValidationError):
            Relationship(
                owner_id=writes.owner_id, source_id=assertion.id, source_kind=NodeType.RELATION_ASSERTION,
                source_owner_id=writes.owner_id, relation=label, target_id=assertion.target_id,
                target_kind=assertion.target_kind, target_owner_id=writes.owner_id,
            )
    successor = replace(assertion, id="assertion-unchecked-successor", revision=2, supersedes_id=assertion.id)
    with pytest.raises(GraphWriteError, match="save_relation_assertion"):
        writes.link_entities(
            Relationship(
                owner_id=writes.owner_id, source_id=successor.id, source_kind=NodeType.RELATION_ASSERTION,
                source_owner_id=writes.owner_id, relation=RelationType.SUPERSEDES,
                target_id=assertion.id, target_kind=NodeType.RELATION_ASSERTION,
                target_owner_id=writes.owner_id,
            ),
            idempotency_key="unchecked-supersedes",
        )
    other = replace(assertion, id="assertion-other-family", assertion_family_id="family-other")
    writes.save_relation_assertion(other, expected_family_revision=None, idempotency_key="other-family")
    before_forged = (writes.nodes(), writes.structural_edges(), writes.audit_events(), dict(writes._idempotency))
    with pytest.raises(GraphWriteError, match="save_relation_assertion"):
        writes.link_entities(
            Relationship(
                owner_id=writes.owner_id, source_id=other.id, source_kind=NodeType.IDEA,
                source_owner_id=writes.owner_id, relation=RelationType.SUPERSEDES,
                target_id=assertion.id, target_kind=NodeType.IDEA,
                target_owner_id=writes.owner_id,
            ),
            idempotency_key="forged-kind-supersedes",
        )
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events(), writes._idempotency) == before_forged
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before_forged[:3]


def test_assertion_cannot_be_created_already_superseded():
    writes, _, _, _, _, assertion = _setup()
    with pytest.raises(GraphWriteError, match="cannot start in superseded"):
        writes.save_relation_assertion(
            replace(assertion, status=RelationshipStatus.SUPERSEDED),
            expected_family_revision=None, idempotency_key="already-superseded",
        )
    assert writes.get_node(assertion.id) is None


def test_same_family_correction_and_changed_target_family_use_cas_and_one_successor():
    writes, _, claim, _, _, first = _setup()
    writes.save_relation_assertion(first, expected_family_revision=None, idempotency_key="first")
    other_claim = Claim(id="claim-other", owner_id=writes.owner_id, text="Other target", confidence=0.7)
    writes.put_node(other_claim, idempotency_key="seed-other-claim")
    changed_same_family = replace(first, id="same-family-bad-target", target_id=other_claim.id, revision=2,
                                  supersedes_id=first.id)
    with pytest.raises(GraphWriteError, match="cannot change endpoints"):
        writes.save_relation_assertion(
            changed_same_family, expected_family_revision=1, idempotency_key="same-family-bad-target",
        )
    same_family = replace(first, id="assertion-revision-2", revision=2, supersedes_id=first.id)
    writes.save_relation_assertion(same_family, expected_family_revision=1, idempotency_key="second")
    changed_family = replace(
        same_family, id="assertion-new-family", target_id=other_claim.id,
        assertion_family_id="family-new-target", revision=1, supersedes_id=same_family.id,
    )
    writes.save_relation_assertion(changed_family, expected_family_revision=None, idempotency_key="third")
    assert (changed_family.id, RelationAssertionEdgeType.SUPERSEDES.value, same_family.id) in writes.structural_edges()

    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())
    competitor = replace(same_family, id="assertion-competitor")
    with pytest.raises(GraphWriteError):
        writes.save_relation_assertion(competitor, expected_family_revision=1, idempotency_key="competitor")
    stale = replace(same_family, id="assertion-stale", revision=3)
    with pytest.raises(RevisionConflictError):
        writes.save_relation_assertion(stale, expected_family_revision=1, idempotency_key="stale")
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before
    assert writes.get_node(claim.id) is not None
    before_replay = (writes.nodes(), writes.structural_edges(), writes.audit_events())
    replay = writes.save_relation_assertion(first, expected_family_revision=None, idempotency_key="first")
    assert replay.replayed is True
    assert writes.get_node(first.id).status is RelationshipStatus.SUPERSEDED
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before_replay


def test_append_then_raise_audit_rolls_back_all_assertion_state_and_retry_succeeds(monkeypatch):
    writes, _, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="initial")
    successor = replace(assertion, id="assertion-retry", revision=2, supersedes_id=assertion.id)
    before_nodes = writes.nodes()
    before_edges = writes.structural_edges()
    before_audit = writes.audit_events()
    before_receipts = dict(writes._idempotency)
    before_history = {node.id: writes.node_history(node.id) for node in before_nodes}
    append_audit = writes._append_audit

    def append_then_fail(*args, **kwargs):
        append_audit(*args, **kwargs)
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(writes, "_append_audit", append_then_fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        writes.save_relation_assertion(successor, expected_family_revision=1, idempotency_key="retry-after-fault")
    assert writes.nodes() == before_nodes
    assert {node.id: writes.node_history(node.id) for node in before_nodes} == before_history
    assert writes.structural_edges() == before_edges
    assert writes.audit_events() == before_audit
    assert writes._idempotency == before_receipts
    assert writes.get_node(assertion.id) is assertion
    assert writes.node_history(assertion.id) == (assertion,)

    monkeypatch.setattr(writes, "_append_audit", append_audit)
    receipt = writes.save_relation_assertion(
        successor, expected_family_revision=1, idempotency_key="retry-after-fault",
    )
    assert receipt.replayed is False and writes.get_node(successor.id) is successor
    assert writes.get_node(assertion.id).status is RelationshipStatus.SUPERSEDED


def test_same_key_with_changed_intent_conflicts_without_mutation():
    writes, _, _, _, _, assertion = _setup()
    writes.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="same-key")
    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())
    with pytest.raises(IdempotencyConflictError):
        writes.save_relation_assertion(
            replace(assertion, confidence=0.3), expected_family_revision=None, idempotency_key="same-key",
        )
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before
