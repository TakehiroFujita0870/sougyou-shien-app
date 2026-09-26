from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import Idea, Provenance, ResearchCampaign, ResearchRun, Status
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.founder_graph_historical_brief import (
    HistoricalResearchValidationError,
    validate_historical_researched_brief,
)


UTC = timezone.utc
APPROVED_AT = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
RUN_START = APPROVED_AT + timedelta(minutes=10)
RUN_FINISH = RUN_START + timedelta(minutes=20)
EXPIRES_AT = APPROVED_AT + timedelta(hours=2)


def _provenance(target_id: str, operation: str, occurred_at: datetime) -> Provenance:
    return Provenance(
        actor="synthetic-test",
        operation=operation,
        target_id=target_id,
        occurred_at=occurred_at,
        idempotency_key=f"{operation}-{target_id}-{occurred_at.isoformat()}",
    )


def _fixture(*, campaign_target_id: str | None = None):
    idea = Idea(owner_id="owner-synthetic", id="idea-synthetic", title="Synthetic idea")
    campaign_id = "campaign-synthetic"
    draft = ResearchCampaign(
        owner_id=idea.owner_id,
        id=campaign_id,
        purpose="Synthetic bounded research",
        target_idea_id=idea.id if campaign_target_id is None else campaign_target_id,
        trial_budget=2,
        expires_at=EXPIRES_AT,
        created_at=APPROVED_AT - timedelta(hours=1),
        provenance=_provenance(campaign_id, "create", APPROVED_AT - timedelta(hours=1)),
    )
    approved = draft.approve(
        approved_at=APPROVED_AT,
        provenance=_provenance(campaign_id, "approve", APPROVED_AT),
    )
    registered = approved.register_run(
        at=RUN_START - timedelta(minutes=1),
        provenance=_provenance(campaign_id, "register_run", RUN_START - timedelta(minutes=1)),
    )
    run_id = "run-synthetic"
    run = ResearchRun(
        owner_id=idea.owner_id,
        id=run_id,
        campaign_id=campaign_id,
        authorization_snapshot_id=registered.authorization_snapshot_id,
        authorization_revision=registered.authorization_revision,
        input_snapshot={"query": "synthetic"},
        model_snapshot="synthetic-model",
        status=Status.COMPLETED,
        started_at=RUN_START,
        finished_at=RUN_FINISH,
        provenance=_provenance(run_id, "complete_run", RUN_FINISH),
    )
    brief = IdeaBriefVersion(
        owner_id=idea.owner_id,
        idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id,
        sections=tuple(IdeaBriefSection(index=index, content=f"Synthetic section {index}") for index in range(8)),
        research_run_ids=(run_id,),
        created_at=RUN_FINISH + timedelta(minutes=5),
    )
    return brief, idea, run, (draft, approved, registered)


def test_historical_brief_accepts_completed_run_even_after_later_scope_change_and_expiry():
    brief, idea, run, history = _fixture()
    accepted_snapshot = history[-1]
    later_change = accepted_snapshot.change_scope(
        {"target_ids": ["idea-other"]},
        at=EXPIRES_AT + timedelta(days=1),
        provenance=_provenance(accepted_snapshot.id, "scope_change", EXPIRES_AT + timedelta(days=1)),
    )

    assert validate_historical_researched_brief(brief, idea, (run,), history + (later_change,)) is None


def test_historical_brief_rejects_run_started_after_scope_change_revoked_its_snapshot():
    brief, idea, run, history = _fixture()
    revoked_at = RUN_FINISH + timedelta(minutes=2)
    changed = history[-1].change_scope(
        {"target_ids": ["idea-other"]},
        at=revoked_at,
        provenance=_provenance(history[-1].id, "scope_change", revoked_at),
    )
    after_revoke = replace(
        run,
        started_at=revoked_at + timedelta(minutes=1),
        finished_at=revoked_at + timedelta(minutes=2),
    )
    later_brief = replace(brief, created_at=revoked_at + timedelta(minutes=3))

    with pytest.raises(HistoricalResearchValidationError):
        validate_historical_researched_brief(later_brief, idea, (after_revoke,), history + (changed,))


@pytest.mark.parametrize(
    "run_values,history,brief_changes,idea_changes",
    [
        ((), None, {}, {}),
        ("duplicate", None, {}, {}),
        (None, "missing", {}, {}),
        (None, "foreign", {}, {}),
        ("unfinished", None, {}, {}),
        ("snapshot", None, {}, {}),
        ("early", None, {}, {}),
        ("late", None, {}, {}),
        ("after_brief", None, {}, {}),
        (None, None, {"blank_section": True}, {}),
        (None, None, {"owner_id": "owner-other"}, {}),
        (None, None, {}, {"id": "idea-other"}),
    ],
)
def test_historical_brief_fails_closed_for_missing_or_mismatched_proof(
    run_values, history, brief_changes, idea_changes
):
    brief, idea, run, campaigns = _fixture()
    selected_runs = (run,)
    selected_history = campaigns
    if run_values == ():
        selected_runs = ()
    elif run_values == "duplicate":
        selected_runs = (run, replace(run, results={"different": "value"}))
    elif run_values == "unfinished":
        selected_runs = (replace(run, status=Status.PARTIAL),)
    elif run_values == "snapshot":
        selected_runs = (replace(run, authorization_snapshot_id="authorization-other"),)
    elif run_values == "early":
        selected_runs = (replace(run, started_at=APPROVED_AT - timedelta(seconds=1)),)
    elif run_values == "late":
        selected_runs = (replace(run, finished_at=EXPIRES_AT),)
    elif run_values == "after_brief":
        brief = replace(brief, created_at=RUN_FINISH - timedelta(seconds=1))
    if history == "missing":
        selected_history = (campaigns[0], campaigns[-1])
    elif history == "foreign":
        foreign = tuple(item._transition(owner_id="owner-other") for item in campaigns)
        selected_history = foreign
    if brief_changes.get("blank_section"):
        brief = replace(
            brief,
            sections=tuple(
                IdeaBriefSection(index=index, content="" if index == 3 else f"Synthetic section {index}")
                for index in range(8)
            ),
        )
    if "owner_id" in brief_changes:
        brief = replace(brief, owner_id=brief_changes["owner_id"])
    if idea_changes:
        idea = replace(idea, **idea_changes)

    with pytest.raises(HistoricalResearchValidationError):
        validate_historical_researched_brief(brief, idea, selected_runs, selected_history)


def test_historical_brief_rejects_ambiguous_campaign_revision_and_wrong_idea_scope():
    brief, idea, run, history = _fixture()
    conflicting_same_revision = history[-1]._transition(target_idea_id="idea-other")
    conflicting_snapshot = history[-1]._transition(
        aggregate_revision=3,
        allowed_categories=("different-category",),
    )
    wrong_scope = tuple(item._transition(target_idea_id="idea-other") for item in history)

    with pytest.raises(HistoricalResearchValidationError):
        validate_historical_researched_brief(brief, idea, (run,), history + (conflicting_same_revision,))
    with pytest.raises(HistoricalResearchValidationError):
        validate_historical_researched_brief(brief, idea, (run,), history + (conflicting_snapshot,))
    with pytest.raises(HistoricalResearchValidationError):
        validate_historical_researched_brief(brief, idea, (run,), wrong_scope)


def test_historical_brief_does_not_return_run_payload_in_errors():
    brief, idea, run, history = _fixture()
    private_run = replace(run, owner_id="owner-other", results={"private": "synthetic secret"})

    with pytest.raises(HistoricalResearchValidationError) as error:
        validate_historical_researched_brief(brief, idea, (private_run,), history)

    assert "synthetic secret" not in str(error.value)
