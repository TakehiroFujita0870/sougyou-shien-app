from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import EgressPolicy, Provenance, ResearchCampaign, ResearchRun, Status
from dots.founder_graph_write import (
    GraphWriteError,
    IdempotencyConflictError,
    InMemoryGraphWriteService,
    NodeAlreadyExistsError,
    RevisionConflictError,
)


def make_campaign(*, budget: int = 2, expired: bool = False) -> ResearchCampaign:
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(days=4)
    expires_at = now - timedelta(days=1) if expired else now + timedelta(days=1)
    campaign = ResearchCampaign(
        owner_id="owner-1", id="campaign-1", purpose="Synthetic public-source review",
        scope={"target_ids": ["idea-1"], "question": "synthetic question"}, target_idea_id="idea-1",
        allowed_categories=("idea.summary",), trial_budget=budget, expires_at=expires_at,
        egress_policy=EgressPolicy.SHAREABLE, created_at=created_at,
        provenance=Provenance(occurred_at=created_at),
    )
    approval_time = now - timedelta(days=2) if expired else now - timedelta(minutes=5)
    return campaign.approve(approved_at=approval_time)


def make_run(
    campaign: ResearchCampaign,
    *,
    run_id: str = "run-1",
    owner_id: str = "owner-1",
    status: Status = Status.COMPLETED,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> ResearchRun:
    now = datetime.now(timezone.utc)
    return ResearchRun(
        id=run_id, owner_id=owner_id, campaign_id=campaign.id,
        input_snapshot={"question": "synthetic question"}, model_snapshot="synthetic-model@1",
        sources=("source-synthetic",), evidence_ids=("evidence-synthetic",),
        results={"summary": "synthetic result"}, status=status, egress_policy=EgressPolicy.SHAREABLE,
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
        started_at=started_at if started_at is not None else now - timedelta(minutes=2),
        finished_at=finished_at if finished_at is not None else now - timedelta(minutes=1),
        provenance=Provenance(actor="chatgpt", operation="record_research_run", target_id=run_id,
                              occurred_at=now, idempotency_key=f"run:{run_id}"),
    )


def seeded_memory(*, budget: int = 2, expired: bool = False):
    campaign = make_campaign(budget=budget, expired=expired)
    writes = InMemoryGraphWriteService("owner-1")
    writes.put_node(campaign, idempotency_key="seed-campaign")
    return writes, campaign


def assert_run_write_absent(writes: InMemoryGraphWriteService, campaign: ResearchCampaign, run_id: str) -> None:
    assert writes.get_node(campaign.id) == campaign
    assert writes.node_history(campaign.id) == (campaign,)
    assert writes.get_node(run_id) is None
    assert writes.node_history(run_id) == ()
    assert writes.structural_edges() == ()
    assert len(writes.audit_events()) == 1  # The initial campaign seed only.


def test_valid_terminal_run_advances_campaign_once_and_replay_ignores_transport_times() -> None:
    writes, campaign = seeded_memory()
    run = make_run(campaign)

    def record(value: ResearchRun):
        return writes.record_research_run(
            value, expected_campaign_revision=campaign.aggregate_revision, idempotency_key="record-run-1"
        )

    receipt = record(run)
    replay_run = replace(
        run,
        started_at=run.started_at + timedelta(seconds=2),
        finished_at=run.finished_at + timedelta(seconds=2),
        provenance=replace(run.provenance, occurred_at=run.provenance.occurred_at + timedelta(seconds=2)),
    )
    replay = record(replay_run)

    current = writes.get_node(campaign.id)
    assert receipt.operation == "record_research_run"
    assert receipt.target_id == run.id
    assert receipt.revision == 0
    assert replay.replayed is True
    assert writes.get_node(run.id) == run
    assert current.run_count == 1
    assert current.aggregate_revision == campaign.aggregate_revision + 1
    assert writes.node_history(campaign.id) == (campaign, current)
    assert writes.node_history(run.id) == (run,)
    assert writes.structural_edges() == ((campaign.id, "HAS_RUN", run.id),)
    assert len(writes.audit_events()) == 2

    for changed in (
        replace(run, results={"summary": "changed synthetic result"}),
        replace(run, status=Status.PARTIAL),
        replace(run, evidence_ids=("different-evidence",)),
        replace(run, provenance=replace(run.provenance, idempotency_key="different-provenance-key")),
    ):
        with pytest.raises(IdempotencyConflictError):
            record(changed)
    assert writes.get_node(run.id) == run
    assert writes.get_node(campaign.id) == current
    assert len(writes.audit_events()) == 2

    changed_scope = current.change_scope({"target_ids": ["idea-2"], "question": "later synthetic scope"},
                                         at=datetime.now(timezone.utc))
    writes.put_node(changed_scope, expected_revision=current.aggregate_revision, idempotency_key="later-scope-change")
    replay_after_scope_change = record(replay_run)
    assert replay_after_scope_change.replayed is True
    assert writes.get_node(run.id) == run
    assert writes.get_node(campaign.id) == changed_scope
    assert len(writes.audit_events()) == 3


def test_two_terminal_runs_use_budget_once_each_and_reject_third() -> None:
    writes, campaign = seeded_memory(budget=2)
    first = make_run(campaign, run_id="run-1", status=Status.PARTIAL)
    first_receipt = writes.record_research_run(
        first,
        expected_campaign_revision=campaign.aggregate_revision,
        idempotency_key="record-run-1",
    )
    second_campaign = writes.get_node(campaign.id)
    second = make_run(second_campaign, run_id="run-2")
    second_receipt = writes.record_research_run(
        second,
        expected_campaign_revision=second_campaign.aggregate_revision,
        idempotency_key="record-run-2",
    )
    exhausted = writes.get_node(campaign.id)

    assert writes.get_node(first.id) == first and not first_receipt.replayed and not second_receipt.replayed
    assert exhausted.run_count == 2
    assert exhausted.aggregate_revision == campaign.aggregate_revision + 2
    assert writes.structural_edges() == (
        (campaign.id, "HAS_RUN", first.id),
        (campaign.id, "HAS_RUN", second.id),
    )
    with pytest.raises(GraphWriteError):
        writes.record_research_run(
            make_run(exhausted, run_id="run-3"),
            expected_campaign_revision=exhausted.aggregate_revision,
            idempotency_key="record-run-3",
        )
    assert writes.get_node("run-3") is None
    assert writes.get_node(campaign.id) == exhausted
    assert len(writes.audit_events()) == 3


@pytest.mark.parametrize(
    "case",
    [
        "stale_revision",
        "wrong_owner",
        "expired_campaign",
        "stale_snapshot",
        "boolean_auth_revision",
        "expiry_boundary",
        "not_terminal",
        "missing_start",
        "before_approval",
        "finish_before_start",
        "future_finish",
    ],
)
def test_invalid_run_or_authorization_is_rejected_without_mutation(case: str) -> None:
    writes, campaign = seeded_memory(expired=case in {"expired_campaign", "expiry_boundary"})
    expected_revision = campaign.aggregate_revision
    run = make_run(campaign)

    if case == "wrong_owner":
        run = replace(run, owner_id="owner-2")
    elif case == "stale_snapshot":
        run = replace(run, authorization_snapshot_id="old-snapshot")
    elif case == "expiry_boundary":
        run = make_run(
            campaign,
            started_at=campaign.approved_at + timedelta(minutes=1),
            finished_at=campaign.expires_at,
        )
    elif case == "boolean_auth_revision":
        run = replace(run, authorization_revision=True)
    elif case == "not_terminal":
        run = make_run(campaign, status=Status.RUNNING, finished_at=None)
    elif case == "missing_start":
        run = replace(run, started_at=None)
    elif case == "before_approval":
        run = replace(run, started_at=campaign.approved_at - timedelta(seconds=1))
    elif case == "finish_before_start":
        run = replace(run, started_at=run.finished_at + timedelta(seconds=1))
    elif case == "future_finish":
        run = replace(
            run,
            started_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            finished_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
    elif case == "stale_revision":
        expected_revision += 1

    with pytest.raises(GraphWriteError):
        writes.record_research_run(
            run,
            expected_campaign_revision=expected_revision,
            idempotency_key=f"invalid-{case}",
        )
    assert_run_write_absent(writes, campaign, run.id)


@pytest.mark.parametrize("change", ["scope", "revoked"])
def test_current_campaign_change_invalidates_old_authorization_before_run_is_recorded(change: str) -> None:
    writes, campaign = seeded_memory()
    changed = (
        campaign.change_scope({"target_ids": ["idea-2"], "question": "changed synthetic question"},
                              at=datetime.now(timezone.utc))
        if change == "scope"
        else campaign._transition(status=Status.REVOKED, authorized=False, approved_at=None,
                                  authorization_revision=campaign.authorization_revision + 1,
                                  aggregate_revision=campaign.aggregate_revision + 1)
    )
    writes.put_node(
        changed,
        expected_revision=campaign.aggregate_revision,
        idempotency_key="change-campaign-scope",
    )
    run = make_run(campaign)

    with pytest.raises(GraphWriteError):
        writes.record_research_run(
            run,
            expected_campaign_revision=changed.aggregate_revision,
            idempotency_key="stale-authorization-run",
        )
    assert writes.get_node(campaign.id) == changed
    assert writes.node_history(campaign.id) == (campaign, changed)
    assert writes.get_node(run.id) is None
    assert writes.node_history(run.id) == ()
    assert writes.structural_edges() == ()
    assert len(writes.audit_events()) == 2


def test_existing_run_id_is_rejected_without_consuming_campaign_budget() -> None:
    writes, campaign = seeded_memory()
    existing_run = make_run(campaign)
    writes.put_node(existing_run, idempotency_key="seed-existing-run")
    audits_before = writes.audit_events()

    with pytest.raises(NodeAlreadyExistsError):
        writes.record_research_run(
            existing_run,
            expected_campaign_revision=campaign.aggregate_revision,
            idempotency_key="duplicate-run-registration",
        )

    assert writes.get_node(campaign.id) == campaign
    assert writes.node_history(campaign.id) == (campaign,)
    assert writes.get_node(existing_run.id) == existing_run
    assert writes.node_history(existing_run.id) == (existing_run,)
    assert writes.structural_edges() == ()
    assert writes.audit_events() == audits_before


def test_audit_failure_rolls_back_campaign_run_edge_history_and_retry_state(monkeypatch) -> None:
    writes, campaign = seeded_memory()
    run = make_run(campaign)

    append_audit = writes._append_audit

    def fail_audit(*args, **kwargs):
        append_audit(*args, **kwargs)
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(writes, "_append_audit", fail_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        writes.record_research_run(
            run,
            expected_campaign_revision=campaign.aggregate_revision,
            idempotency_key="rollback-run",
        )
    assert_run_write_absent(writes, campaign, run.id)

    monkeypatch.undo()
    retried = writes.record_research_run(
        run,
        expected_campaign_revision=campaign.aggregate_revision,
        idempotency_key="rollback-run",
    )
    assert retried.replayed is False
    assert writes.get_node(campaign.id).run_count == 1
    assert writes.get_node(run.id) == run
