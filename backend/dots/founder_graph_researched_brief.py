"""Pure validation for a complete Idea brief backed by current research."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .founder_graph import (
    CampaignAuthorizationRegistry,
    DomainValidationError,
    Idea,
    ResearchRun,
    Status,
    validate_campaign_idea_reference,
    validate_run_campaign_reference,
)
from .idea_brief import IdeaBriefSection, IdeaBriefVersion


class ResearchedBriefValidationError(ValueError):
    """A brief is not fully backed by current owner-authorized research."""


_ACTIVE_CAMPAIGN_STATUSES = frozenset({Status.APPROVED, Status.RUNNING, Status.PARTIAL, Status.FAILED})


def validate_researched_brief(
    brief: IdeaBriefVersion,
    idea: Idea,
    runs: Sequence[ResearchRun],
    authorization_registry: CampaignAuthorizationRegistry,
    *,
    at: datetime | None = None,
) -> None:
    """Validate a candidate brief at its acceptance/save boundary.

    The function returns no Run values or payload. Callers must resolve its
    arguments from their authoritative owner-scoped store before calling it.
    Do not rerun it to classify previously accepted briefs during reads; their
    historical researched status does not disappear when Campaigns expire.
    """

    now = datetime.now(timezone.utc) if at is None else at
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ResearchedBriefValidationError("validation time must include a timezone")
    now = now.astimezone(timezone.utc)
    if not isinstance(brief, IdeaBriefVersion) or not isinstance(idea, Idea):
        raise ResearchedBriefValidationError("brief and Idea values are required")
    if brief.owner_id != idea.owner_id or brief.based_on_idea_id != idea.id:
        raise ResearchedBriefValidationError("brief must reference the same owner and Idea")
    if len(brief.sections) != 8 or not all(isinstance(section, IdeaBriefSection) and section.content.strip() for section in brief.sections):
        raise ResearchedBriefValidationError("all eight brief sections must contain text")
    if not brief.research_run_ids:
        raise ResearchedBriefValidationError("a researched brief requires at least one Run")
    if not isinstance(authorization_registry, CampaignAuthorizationRegistry):
        raise ResearchedBriefValidationError("current campaign authorization registry is required")
    if not isinstance(runs, (tuple, list)) or not all(isinstance(run, ResearchRun) for run in runs):
        raise ResearchedBriefValidationError("Run references must resolve to ResearchRun values")

    run_by_id = {run.id: run for run in runs}
    if len(run_by_id) != len(runs) or set(run_by_id) != set(brief.research_run_ids):
        raise ResearchedBriefValidationError("Run references must resolve uniquely to the brief")
    referenced_count_by_campaign: dict[str, int] = {}
    for run in runs:
        referenced_count_by_campaign[run.campaign_id] = referenced_count_by_campaign.get(run.campaign_id, 0) + 1

    try:
        for run_id in brief.research_run_ids:
            run = run_by_id[run_id]
            if run.owner_id != brief.owner_id or run.status is not Status.COMPLETED:
                raise ResearchedBriefValidationError("each Run must be completed and owned by the brief owner")
            if type(run.authorization_revision) is not int or run.authorization_revision < 1:
                raise ResearchedBriefValidationError("each Run must reference an integer authorization revision")
            if run.started_at is None or run.finished_at is None:
                raise ResearchedBriefValidationError("each completed Run must have start and finish times")

            campaign, snapshot = authorization_registry.resolve_current(run.campaign_id)
            if campaign.owner_id != brief.owner_id or campaign.status not in _ACTIVE_CAMPAIGN_STATUSES:
                raise ResearchedBriefValidationError("each Run must have a current authorized Campaign")
            if (
                campaign.run_count < referenced_count_by_campaign[campaign.id]
                or campaign.run_count > campaign.trial_budget
            ):
                raise ResearchedBriefValidationError("Campaign run count must be within its authorized budget")
            validate_campaign_idea_reference(campaign, idea)
            snapshot.validate(owner_id=brief.owner_id, target_id=idea.id, categories=(), at=now)
            validate_run_campaign_reference(
                run,
                campaign,
                snapshot,
                authorization_registry=authorization_registry,
                at=now,
            )
            if campaign.approved_at is None or campaign.expires_at is None:
                raise ResearchedBriefValidationError("Campaign authorization requires approval and expiry times")
            if run.started_at < campaign.approved_at:
                raise ResearchedBriefValidationError("Run cannot start before Campaign approval")
            if run.finished_at < run.started_at or run.finished_at > now:
                raise ResearchedBriefValidationError("Run finish time is outside its valid interval")
            if run.finished_at >= snapshot.expires_at:
                raise ResearchedBriefValidationError("Run must finish before Campaign authorization expires")
    except DomainValidationError:
        raise ResearchedBriefValidationError("Run authorization or Idea reference is invalid") from None


__all__ = ["ResearchedBriefValidationError", "validate_researched_brief"]
