"""Shared authorization-time checks for terminal research runs."""

from __future__ import annotations

from datetime import datetime, timezone

from .founder_graph import DomainValidationError, ResearchCampaign, ResearchRun


def validate_research_run_timing(
    run: ResearchRun,
    campaign: ResearchCampaign,
    *,
    at: datetime | None = None,
) -> None:
    """Check that a persisted Run fits within its Campaign authorization."""

    now = datetime.now(timezone.utc) if at is None else at
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise DomainValidationError("research run validation time must include a timezone")
    now = now.astimezone(timezone.utc)
    if not isinstance(run, ResearchRun) or not isinstance(campaign, ResearchCampaign):
        raise DomainValidationError("research run timing requires a Run and Campaign")
    if campaign.approved_at is None or campaign.expires_at is None:
        raise DomainValidationError("research campaign must have approval and expiry times")
    if run.started_at is None or run.finished_at is None:
        raise DomainValidationError("terminal research run requires start and finish times")
    if run.started_at < campaign.approved_at:
        raise DomainValidationError("research run cannot start before campaign approval")
    if run.finished_at < run.started_at:
        raise DomainValidationError("research run finish cannot precede its start")
    if run.finished_at > now:
        raise DomainValidationError("research run cannot finish in the future")
    if run.finished_at >= campaign.expires_at:
        raise DomainValidationError("research run must finish before campaign expiry")
