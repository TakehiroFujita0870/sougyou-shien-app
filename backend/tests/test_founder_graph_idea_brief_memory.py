from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import EgressPolicy, Idea, Provenance, ResearchCampaign, ResearchRun, Status
from dots.founder_graph_write import (
    GraphWriteError,
    IdempotencyConflictError,
    InMemoryGraphWriteService,
    NodeAlreadyExistsError,
    RevisionConflictError,
)
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion


def _brief(idea: Idea, *, revision: int = 1, supersedes_id: str | None = None, runs: tuple[str, ...] = ()) -> IdeaBriefVersion:
    return IdeaBriefVersion(
        owner_id=idea.owner_id,
        idea_lineage_root_id=idea.id if idea.supersedes_id is None else "idea-root",
        based_on_idea_id=idea.id,
        revision=revision,
        supersedes_id=supersedes_id,
        research_run_ids=runs,
    )


def _seed_idea(writes: InMemoryGraphWriteService, idea: Idea) -> None:
    writes.put_node(idea, idempotency_key=f"seed-{idea.id}")


def test_idea_brief_save_requires_expected_latest_and_returns_authoritative_immutable_history():
    writes = InMemoryGraphWriteService("owner-memory")
    idea = Idea(id="idea-memory", owner_id=writes.owner_id, title="Synthetic idea")
    _seed_idea(writes, idea)
    first = _brief(idea)

    with pytest.raises(RevisionConflictError):
        writes.save_idea_brief(first, expected_latest_revision=True, idempotency_key="brief-bool-cas")
    receipt = writes.save_idea_brief(
        first, expected_latest_revision=None, idempotency_key="brief-first", actor="synthetic-test"
    )
    replay = writes.save_idea_brief(
        first, expected_latest_revision=None, idempotency_key="brief-first", actor="synthetic-test"
    )

    assert receipt.operation == "save_idea_brief"
    assert receipt.target_id == first.id and receipt.target_type == "idea_brief_version"
    assert receipt.revision == 1 and receipt.replayed is False
    assert replay.replayed is True
    assert writes.get_idea_brief(first.id) is first
    assert writes.get_latest_idea_brief(idea.id) is first
    assert len(writes.audit_events()) == 2  # Idea seed and one brief save.
    with pytest.raises(NodeAlreadyExistsError):
        writes.put_node(
            Idea(id=first.id, owner_id=idea.owner_id, title="Synthetic ID collision"),
            idempotency_key="brief-node-id-collision",
        )
    with pytest.raises((AttributeError, TypeError)):
        first.sections[0].content = "mutated"  # type: ignore[misc]
    with pytest.raises(IdempotencyConflictError):
        writes.save_idea_brief(
            replace(first, created_at=first.created_at + timedelta(seconds=1)),
            expected_latest_revision=None,
            idempotency_key="brief-first",
        )

    second = first.revise(change_reason="synthetic revision")
    with pytest.raises(RevisionConflictError):
        writes.save_idea_brief(second, expected_latest_revision=None, idempotency_key="brief-stale-cas")
    second_receipt = writes.save_idea_brief(
        second, expected_latest_revision=1, idempotency_key="brief-second", actor="synthetic-test"
    )
    assert second_receipt.revision == 2
    assert writes.get_idea_brief(first.id) is first
    assert writes.get_latest_idea_brief(idea.id) is second
    assert len(writes.audit_events()) == 3

    later_idea = idea.revise(title="Synthetic later Idea revision")
    writes.put_node(later_idea, idempotency_key="seed-later-idea")
    receipt_only_replay = writes.save_idea_brief(
        first, expected_latest_revision=None, idempotency_key="brief-first", actor="synthetic-test"
    )
    assert receipt_only_replay.replayed is True
    assert writes.get_latest_idea_brief(idea.id) is second
    assert len(writes.audit_events()) == 4  # New Idea only; replay wrote no audit.

    with pytest.raises(IdempotencyConflictError):
        writes.save_idea_brief(
            second, expected_latest_revision=1, idempotency_key="brief-first", actor="synthetic-test"
        )


@pytest.mark.parametrize(
    "invalid",
    [
        "foreign_owner", "wrong_root", "old_idea", "forked_lineage", "bad_idea_revision",
        "bad_brief_chain", "brief_id_collision",
    ],
)
def test_brief_lineage_and_current_idea_are_checked_before_mutation(invalid: str):
    writes = InMemoryGraphWriteService("owner-memory")
    root = Idea(id="idea-root", owner_id=writes.owner_id, title="Synthetic root")
    _seed_idea(writes, root)
    idea = root
    if invalid in {"old_idea", "forked_lineage", "bad_idea_revision"}:
        idea = root.revise(title="Synthetic current")
        if invalid == "bad_idea_revision":
            idea = replace(idea, revision=3)
        writes.put_node(idea, idempotency_key="seed-current-idea")
    brief = _brief(idea)
    if invalid == "foreign_owner":
        brief = IdeaBriefVersion(
            owner_id="owner-foreign", idea_lineage_root_id=root.id, based_on_idea_id=idea.id
        )
    elif invalid == "wrong_root":
        brief = IdeaBriefVersion(
            owner_id=writes.owner_id, idea_lineage_root_id="idea-not-root", based_on_idea_id=idea.id
        )
    elif invalid == "old_idea":
        brief = _brief(root)
    elif invalid == "forked_lineage":
        sibling = root.revise(title="Synthetic competing current")
        writes.put_node(sibling, idempotency_key="seed-sibling-idea")
    elif invalid == "bad_brief_chain":
        brief = IdeaBriefVersion(
            owner_id=writes.owner_id,
            idea_lineage_root_id=root.id,
            based_on_idea_id=idea.id,
            revision=3,
            supersedes_id="missing-brief",
        )
    elif invalid == "brief_id_collision":
        brief = IdeaBriefVersion(
            owner_id=writes.owner_id,
            idea_lineage_root_id=root.id,
            based_on_idea_id=idea.id,
            id=root.id,
        )

    before_audit = writes.audit_events()
    with pytest.raises(GraphWriteError):
        writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key=f"invalid-{invalid}")
    assert writes.get_idea_brief(brief.id) is None
    assert writes.get_latest_idea_brief(root.id) is None
    assert writes.audit_events() == before_audit


def _researched_setup():
    now = datetime.now(timezone.utc)
    idea = Idea(id="idea-researched", owner_id="owner-memory", title="Synthetic research target")
    writes = InMemoryGraphWriteService(idea.owner_id)
    _seed_idea(writes, idea)
    campaign_created = now - timedelta(minutes=10)
    campaign_draft = ResearchCampaign(
        id="campaign-researched",
        owner_id=idea.owner_id,
        purpose="Synthetic bounded research",
        target_idea_id=idea.id,
        allowed_categories=("idea.summary",),
        trial_budget=1,
        expires_at=now + timedelta(hours=1),
        egress_policy=EgressPolicy.SHAREABLE,
        created_at=campaign_created,
        provenance=Provenance(
            actor="synthetic-test", operation="seed", target_id="campaign-researched", occurred_at=campaign_created
        ),
    )
    writes.put_node(campaign_draft, idempotency_key="seed-campaign")
    campaign = campaign_draft.approve(
        approved_at=now - timedelta(minutes=5),
        provenance=Provenance(
            actor="synthetic-test", operation="approve", target_id="campaign-researched",
            occurred_at=now - timedelta(minutes=5),
        ),
    )
    writes.put_node(
        campaign,
        expected_revision=campaign_draft.aggregate_revision,
        idempotency_key="approve-campaign",
        actor="synthetic-test",
    )
    run = ResearchRun(
        id="run-researched",
        owner_id=idea.owner_id,
        campaign_id=campaign.id,
        input_snapshot={"query": "synthetic"},
        model_snapshot="synthetic-model@1",
        sources=("synthetic-source",),
        evidence_ids=("synthetic-evidence",),
        results={"summary": "synthetic result"},
        status=Status.COMPLETED,
        egress_policy=EgressPolicy.SHAREABLE,
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
        started_at=now - timedelta(minutes=3),
        finished_at=now - timedelta(minutes=2),
        provenance=Provenance(actor="synthetic-test", operation="record_research_run", target_id="run-researched"),
    )
    writes.record_research_run(
        run,
        expected_campaign_revision=campaign.aggregate_revision,
        idempotency_key="record-run",
        actor="synthetic-test",
    )
    researched = IdeaBriefVersion(
        owner_id=idea.owner_id,
        idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id,
        sections=tuple(IdeaBriefSection(index=index, content=f"Synthetic section {index}") for index in range(8)),
        research_run_ids=(run.id,),
    )
    return writes, idea, run, researched


def test_researched_brief_requires_stored_run_edge_receipt_audit_and_campaign_history():
    writes, idea, run, researched = _researched_setup()
    campaign = writes.get_node(run.campaign_id)
    revoked_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    changed_scope = campaign.change_scope(
        {"target_ids": [idea.id], "question": "later synthetic scope"},
        at=revoked_at,
        provenance=Provenance(
            actor="synthetic-test",
            operation="scope_change",
            target_id=campaign.id,
            occurred_at=revoked_at,
        ),
    )
    writes.put_node(
        changed_scope,
        expected_revision=campaign.aggregate_revision,
        idempotency_key="revoke-run-authorization-later",
        actor="synthetic-test",
    )
    before_audit = writes.audit_events()
    with pytest.raises(GraphWriteError):
        writes.save_idea_brief(
            IdeaBriefVersion(
                owner_id=idea.owner_id,
                idea_lineage_root_id=idea.id,
                based_on_idea_id=idea.id,
                sections=researched.sections,
                research_run_ids=("caller-claimed-run",),
            ),
            expected_latest_revision=None,
            idempotency_key="brief-unregistered-run",
        )
    assert writes.get_latest_idea_brief(idea.id) is None
    assert writes.audit_events() == before_audit

    receipt = writes.save_idea_brief(
        researched, expected_latest_revision=None, idempotency_key="brief-researched", actor="synthetic-test"
    )
    assert receipt.target_id == researched.id
    assert writes.get_latest_idea_brief(idea.id) is researched
    assert writes.get_node(run.id) == run


@pytest.mark.parametrize(
    "missing_record", ["edge", "receipt", "corrupt_receipt", "audit", "corrupt_audit", "history"]
)
def test_researched_brief_fails_closed_when_registered_run_proof_is_incomplete(missing_record: str):
    writes, idea, run, researched = _researched_setup()
    if missing_record == "edge":
        writes._structural_edges.remove((run.campaign_id, "HAS_RUN", run.id))
    elif missing_record == "receipt":
        writes._idempotency.pop("record-run")
    elif missing_record == "corrupt_receipt":
        fingerprint, receipt = writes._idempotency["record-run"]
        writes._idempotency["record-run"] = (fingerprint, replace(receipt, target_id="foreign-run"))
    elif missing_record == "audit":
        writes._audit[:] = [event for event in writes._audit if event.idempotency_key != "record-run"]
    elif missing_record == "corrupt_audit":
        writes._audit[:] = [
            replace(event, payload_fingerprint="tampered") if event.idempotency_key == "record-run" else event
            for event in writes._audit
        ]
    else:
        writes._node_history[run.campaign_id].pop(0)

    before_audit = writes.audit_events()
    with pytest.raises(GraphWriteError):
        writes.save_idea_brief(
            researched, expected_latest_revision=None, idempotency_key=f"brief-missing-{missing_record}"
        )
    assert writes.get_latest_idea_brief(idea.id) is None
    assert writes.audit_events() == before_audit


def test_brief_audit_failure_rolls_back_version_latest_receipt_and_audit(monkeypatch):
    writes = InMemoryGraphWriteService("owner-memory")
    idea = Idea(id="idea-rollback", owner_id=writes.owner_id, title="Synthetic idea")
    _seed_idea(writes, idea)
    brief = _brief(idea)
    before_audit = writes.audit_events()

    append_audit = writes._append_audit

    def append_then_fail(*args, **kwargs):
        append_audit(*args, **kwargs)
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(writes, "_append_audit", append_then_fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="brief-rollback")

    assert writes.get_idea_brief(brief.id) is None
    assert writes.get_latest_idea_brief(idea.id) is None
    assert "brief-rollback" not in writes._idempotency
    assert writes.audit_events() == before_audit
    monkeypatch.setattr(writes, "_append_audit", append_audit)
    receipt = writes.save_idea_brief(
        brief, expected_latest_revision=None, idempotency_key="brief-rollback", actor="synthetic-test"
    )
    assert receipt.replayed is False
    assert writes.get_latest_idea_brief(idea.id) is brief
    assert len(writes.audit_events()) == len(before_audit) + 1
