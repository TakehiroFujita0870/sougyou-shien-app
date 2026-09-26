from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import (
    CampaignAuthorizationRegistry,
    Idea,
    Provenance,
    ResearchCampaign,
    ResearchRun,
    Status,
)
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.founder_graph_researched_brief import ResearchedBriefValidationError, validate_researched_brief


UTC = timezone.utc
AT = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


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
    campaign = ResearchCampaign(
        owner_id=idea.owner_id,
        id=campaign_id,
        purpose="Synthetic bounded research",
        target_idea_id=idea.id if campaign_target_id is None else campaign_target_id,
        trial_budget=2,
        expires_at=AT + timedelta(hours=2),
        created_at=AT - timedelta(hours=4),
        provenance=_provenance(campaign_id, "create", AT - timedelta(hours=4)),
    )
    approved = campaign.approve(
        approved_at=AT - timedelta(hours=2),
        provenance=_provenance(campaign_id, "approve", AT - timedelta(hours=2)),
    )
    current = approved.register_run(
        at=AT - timedelta(hours=1),
        provenance=_provenance(campaign_id, "register_run", AT - timedelta(hours=1)),
    )
    run_id = "run-synthetic"
    run = ResearchRun(
        owner_id=idea.owner_id,
        id=run_id,
        campaign_id=campaign_id,
        authorization_snapshot_id=current.authorization_snapshot_id,
        authorization_revision=current.authorization_revision,
        input_snapshot={"query": "Synthetic private input"},
        model_snapshot="Synthetic model",
        results={"summary": "Synthetic private result"},
        status=Status.COMPLETED,
        started_at=AT - timedelta(minutes=50),
        finished_at=AT - timedelta(minutes=40),
        provenance=_provenance(run_id, "complete_run", AT - timedelta(minutes=40)),
    )
    brief = IdeaBriefVersion(
        owner_id=idea.owner_id,
        idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id,
        sections=tuple(IdeaBriefSection(index=index, content=f"Synthetic section {index}") for index in range(8)),
        research_run_ids=(run_id,),
    )
    registry = CampaignAuthorizationRegistry(campaigns=(approved, current))
    return brief, idea, run, current, registry


def test_researched_brief_accepts_eight_sections_and_current_completed_run_without_returning_run_data():
    brief, idea, run, _, registry = _fixture()

    result = validate_researched_brief(brief, idea, (run,), registry, at=AT)

    assert result is None


def test_researched_brief_accepts_multiple_completed_runs_within_campaign_budget():
    brief, idea, first_run, campaign, registry = _fixture()
    second_id = "run-synthetic-two"
    second_campaign = campaign.register_run(
        at=AT - timedelta(minutes=30),
        provenance=_provenance(campaign.id, "register_run", AT - timedelta(minutes=30)),
    )
    second_run = ResearchRun(
        owner_id=idea.owner_id,
        id=second_id,
        campaign_id=campaign.id,
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
        input_snapshot={"query": "Synthetic second query"},
        model_snapshot="Synthetic model",
        results={"summary": "Synthetic second result"},
        status=Status.COMPLETED,
        started_at=AT - timedelta(minutes=25),
        finished_at=AT - timedelta(minutes=20),
        provenance=_provenance(second_id, "complete_run", AT - timedelta(minutes=20)),
    )
    multi_run_brief = replace(brief, research_run_ids=(first_run.id, second_id))
    history = registry.campaigns + (second_campaign,)
    current_registry = CampaignAuthorizationRegistry(campaigns=history)

    assert validate_researched_brief(multi_run_brief, idea, (first_run, second_run), current_registry, at=AT) is None


def test_researched_brief_rejects_missing_referenced_run_with_safe_error():
    brief, idea, _, _, registry = _fixture()

    with pytest.raises(ResearchedBriefValidationError) as error:
        validate_researched_brief(brief, idea, (), registry, at=AT)

    assert "Synthetic private" not in str(error.value)


def test_researched_brief_rejects_empty_research_run_references():
    brief, idea, run, _, registry = _fixture()
    empty = replace(brief, research_run_ids=())

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(empty, idea, (run,), registry, at=AT)


@pytest.mark.parametrize("section_index", range(8))
def test_researched_brief_requires_content_in_every_section(section_index):
    brief, idea, run, _, registry = _fixture()
    sections = tuple(
        IdeaBriefSection(index=index, content="" if index == section_index else f"Synthetic section {index}")
        for index in range(8)
    )
    incomplete = replace(brief, sections=sections)

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(incomplete, idea, (run,), registry, at=AT)


def test_researched_brief_rejects_wrong_idea_or_owner():
    brief, idea, run, _, registry = _fixture()

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, replace(idea, id="idea-other"), (run,), registry, at=AT)
    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(replace(brief, owner_id="owner-other"), idea, (run,), registry, at=AT)


@pytest.mark.parametrize("status", [Status.PENDING, Status.RUNNING, Status.PARTIAL, Status.FAILED])
def test_researched_brief_requires_completed_runs(status):
    brief, idea, run, _, registry = _fixture()
    unfinished = replace(run, status=status)

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (unfinished,), registry, at=AT)


def test_researched_brief_rejects_duplicate_run_values_and_wrong_run_owner():
    brief, idea, run, _, registry = _fixture()

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (run, replace(run, results={"other": "synthetic"})), registry, at=AT)
    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (replace(run, owner_id="owner-other"),), registry, at=AT)


def test_researched_brief_rejects_boolean_authorization_revision():
    brief, idea, run, _, registry = _fixture()

    with pytest.raises(ResearchedBriefValidationError) as error:
        validate_researched_brief(brief, idea, (replace(run, authorization_revision=True),), registry, at=AT)

    assert str(error.value) == "each Run must reference an integer authorization revision"


def test_researched_brief_rejects_more_referenced_runs_than_campaign_registered():
    brief, idea, run, _, registry = _fixture()
    second_id = "run-synthetic-two"
    second_run = replace(
        run,
        id=second_id,
        provenance=_provenance(second_id, "complete_run", AT - timedelta(minutes=35)),
    )
    two_run_brief = replace(brief, research_run_ids=(run.id, second_id))

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(two_run_brief, idea, (run, second_run), registry, at=AT)


def test_researched_brief_error_does_not_return_run_payload():
    brief, idea, run, _, registry = _fixture()
    run_with_private_payload = replace(run, status=Status.PARTIAL)

    with pytest.raises(ResearchedBriefValidationError) as error:
        validate_researched_brief(brief, idea, (run_with_private_payload,), registry, at=AT)

    assert "Synthetic private input" not in str(error.value)
    assert "Synthetic private result" not in str(error.value)


def test_researched_brief_rejects_campaign_for_another_idea():
    brief, idea, run, _, other_registry = _fixture(campaign_target_id="idea-other")

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (run,), other_registry, at=AT)


def test_researched_brief_rejects_old_campaign_authorization_snapshot():
    brief, idea, run, current, _ = _fixture()
    changed = current.change_scope({"target_ids": [idea.id]}, at=AT - timedelta(minutes=20))
    reapproved = changed.approve(approved_at=AT - timedelta(minutes=10))
    registry = CampaignAuthorizationRegistry(campaigns=(current, changed, reapproved))

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (run,), registry, at=AT)


def test_researched_brief_rejects_campaign_pending_after_scope_change():
    brief, idea, run, current, _ = _fixture()
    pending = current.change_scope({"target_ids": [idea.id]}, at=AT - timedelta(minutes=20))
    registry = CampaignAuthorizationRegistry(campaigns=(current, pending))

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (run,), registry, at=AT)


def test_researched_brief_rejects_expired_authorization_and_run_after_expiry():
    brief, idea, run, current, registry = _fixture()
    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (run,), registry, at=current.expires_at)

    late_run = replace(run, finished_at=current.expires_at + timedelta(seconds=1))
    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (late_run,), registry, at=AT)


@pytest.mark.parametrize(
    "changes",
    [
        {"started_at": None},
        {"started_at": AT - timedelta(hours=3)},
        {"started_at": AT - timedelta(minutes=30), "finished_at": AT - timedelta(minutes=40)},
        {"finished_at": AT + timedelta(seconds=1)},
    ],
)
def test_researched_brief_rejects_missing_or_out_of_bounds_run_times(changes):
    brief, idea, run, _, registry = _fixture()
    invalid_run = replace(run, **changes)

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (invalid_run,), registry, at=AT)


@pytest.mark.parametrize("invalid_at", [False, datetime(2026, 9, 26, 12, 0)])
def test_researched_brief_rejects_invalid_validation_clock(invalid_at):
    brief, idea, run, _, registry = _fixture()

    with pytest.raises(ResearchedBriefValidationError):
        validate_researched_brief(brief, idea, (run,), registry, at=invalid_at)  # type: ignore[arg-type]
