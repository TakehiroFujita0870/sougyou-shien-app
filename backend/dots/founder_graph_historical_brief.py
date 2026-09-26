"""Pure historical proof checks for already accepted, researched Idea briefs.

Unlike the save-time research validator, this module never resolves current
authorization and never consults the current clock. Callers must provide
authoritative typed history and verify that referenced Runs were registered.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .founder_graph import (
    DomainValidationError,
    Idea,
    ResearchCampaign,
    ResearchRun,
    Status,
    validate_campaign_idea_reference,
)
from .idea_brief import IdeaBriefSection, IdeaBriefVersion


class HistoricalResearchValidationError(ValueError):
    """Historical Run authorization cannot be proven for a brief."""


_AUTHORIZED_RUN_STATUSES = frozenset({Status.APPROVED, Status.RUNNING, Status.PARTIAL, Status.FAILED})


def _campaign_history_by_id(campaigns: Sequence[ResearchCampaign]) -> dict[str, tuple[ResearchCampaign, ...]]:
    if not isinstance(campaigns, (tuple, list)) or not campaigns:
        raise HistoricalResearchValidationError("authoritative Campaign history is required")
    if not all(isinstance(item, ResearchCampaign) for item in campaigns):
        raise HistoricalResearchValidationError("Campaign history must contain typed Campaign values")

    grouped: dict[str, list[ResearchCampaign]] = {}
    for campaign in campaigns:
        grouped.setdefault(campaign.id, []).append(campaign)
    result: dict[str, tuple[ResearchCampaign, ...]] = {}
    for campaign_id, history in grouped.items():
        revisions: dict[int, ResearchCampaign] = {}
        for campaign in history:
            previous = revisions.get(campaign.aggregate_revision)
            if previous is not None:
                raise HistoricalResearchValidationError("Campaign history contains a duplicate or ambiguous revision")
            revisions[campaign.aggregate_revision] = campaign
        if set(revisions) != set(range(max(revisions) + 1)):
            raise HistoricalResearchValidationError("Campaign history is incomplete")
        owners = {campaign.owner_id for campaign in history}
        if len(owners) != 1:
            raise HistoricalResearchValidationError("Campaign history owner is inconsistent")
        result[campaign_id] = tuple(revisions[index] for index in sorted(revisions))
    return result


def _authorization_key(campaign: ResearchCampaign) -> tuple[object, ...]:
    """Fields defining the authorization itself, excluding mutable run state."""
    if not campaign.authorized:
        raise HistoricalResearchValidationError("Run does not resolve to an authorized historical Campaign")
    try:
        snapshot = campaign.authorization_snapshot
    except DomainValidationError:
        raise HistoricalResearchValidationError("historical Campaign authorization is incomplete") from None
    def freeze(value: object) -> object:
        if isinstance(value, Mapping):
            return tuple((key, freeze(item)) for key, item in sorted(value.items()))
        if isinstance(value, (tuple, list)):
            return tuple(freeze(item) for item in value)
        return value

    return (
        campaign.id,
        campaign.owner_id,
        campaign.purpose,
        campaign.target_idea_id,
        freeze(campaign.scope),
        campaign.questions,
        campaign.allowed_categories,
        campaign.external_sources,
        campaign.trial_budget,
        campaign.egress_policy,
        campaign.approved_at,
        snapshot.id,
        snapshot.revision,
        snapshot.scope_target_ids,
        snapshot.expires_at,
    )


def validate_historical_researched_brief(
    brief: IdeaBriefVersion,
    idea: Idea,
    runs: Sequence[ResearchRun],
    campaigns: Sequence[ResearchCampaign],
) -> None:
    """Prove a complete brief using its Runs' historical authorization only.

    `runs` and `campaigns` must come from an authoritative owner-scoped store;
    callers additionally verify Run registration/receipt and exact brief
    lineage. This function intentionally accepts no `at` argument, never
    reads Campaign current state, and never calls the save-time validator.
    """
    if not isinstance(brief, IdeaBriefVersion) or not isinstance(idea, Idea):
        raise HistoricalResearchValidationError("typed brief and Idea values are required")
    if brief.owner_id != idea.owner_id or brief.based_on_idea_id != idea.id:
        raise HistoricalResearchValidationError("brief must reference the same owner and Idea")
    if len(brief.sections) != 8 or not all(
        isinstance(section, IdeaBriefSection) and section.content.strip()
        for section in brief.sections
    ):
        raise HistoricalResearchValidationError("all eight brief sections must contain text")
    if not brief.research_run_ids:
        raise HistoricalResearchValidationError("a researched brief requires at least one Run")
    if not isinstance(runs, (tuple, list)) or not all(isinstance(run, ResearchRun) for run in runs):
        raise HistoricalResearchValidationError("Run references must resolve to typed Run values")
    run_by_id = {run.id: run for run in runs}
    if len(run_by_id) != len(runs) or set(run_by_id) != set(brief.research_run_ids):
        raise HistoricalResearchValidationError("Run references must resolve uniquely to the brief")

    histories = _campaign_history_by_id(campaigns)
    if any(campaign.owner_id != brief.owner_id for history in histories.values() for campaign in history):
        raise HistoricalResearchValidationError("Campaign history must belong to the brief owner")
    count_by_campaign: dict[str, int] = {}
    for run in runs:
        count_by_campaign[run.campaign_id] = count_by_campaign.get(run.campaign_id, 0) + 1

    try:
        for run_id in brief.research_run_ids:
            run = run_by_id[run_id]
            if run.owner_id != brief.owner_id or run.status is not Status.COMPLETED:
                raise HistoricalResearchValidationError("each Run must be completed and owned by the brief owner")
            if type(run.authorization_revision) is not int or run.authorization_revision < 1:
                raise HistoricalResearchValidationError("Run must reference a valid authorization revision")
            if run.started_at is None or run.finished_at is None:
                raise HistoricalResearchValidationError("completed Run must have start and finish times")
            history = histories.get(run.campaign_id, ())
            matching = tuple(
                campaign for campaign in history
                if campaign.authorized
                and campaign.authorization_snapshot_id == run.authorization_snapshot_id
                and campaign.authorization_revision == run.authorization_revision
            )
            if not matching:
                raise HistoricalResearchValidationError("Run authorization snapshot is absent from Campaign history")
            authorization_keys = {_authorization_key(campaign) for campaign in matching}
            if len(authorization_keys) != 1:
                raise HistoricalResearchValidationError("Run authorization snapshot history is ambiguous")
            campaign = matching[0]
            if campaign.owner_id != brief.owner_id or campaign.status not in _AUTHORIZED_RUN_STATUSES:
                raise HistoricalResearchValidationError("Run Campaign was not authorized for this owner")
            if run.egress_policy is not campaign.egress_policy:
                raise HistoricalResearchValidationError("Run egress policy does not match its authorization")
            validate_campaign_idea_reference(campaign, idea)
            snapshot = campaign.authorization_snapshot
            if idea.id not in snapshot.scope_target_ids:
                raise HistoricalResearchValidationError("Run authorization did not include the Idea scope")
            if campaign.approved_at is None or campaign.expires_at is None:
                raise HistoricalResearchValidationError("historical authorization requires approval and expiry")
            if run.started_at < campaign.approved_at:
                raise HistoricalResearchValidationError("Run started before historical approval")
            epoch_history = history[campaign.aggregate_revision:]
            epoch_records: list[ResearchCampaign] = []
            revoked_at = None
            expected_key = _authorization_key(campaign)
            for historical in epoch_history:
                if (
                    not historical.authorized
                    or historical.status not in _AUTHORIZED_RUN_STATUSES
                    or historical.authorization_snapshot_id != snapshot.id
                    or historical.authorization_revision != snapshot.revision
                ):
                    revoked_at = historical.provenance.occurred_at
                    break
                if _authorization_key(historical) != expected_key:
                    revoked_at = historical.provenance.occurred_at
                    break
                epoch_records.append(historical)
            if not epoch_records:
                raise HistoricalResearchValidationError("Run authorization history is incomplete")
            if run.finished_at < run.started_at or run.finished_at >= snapshot.expires_at:
                raise HistoricalResearchValidationError("Run finished outside its historical authorization interval")
            if revoked_at is not None and run.finished_at >= revoked_at:
                raise HistoricalResearchValidationError("Run finished after its authorization was revoked")
            if run.finished_at > brief.created_at:
                raise HistoricalResearchValidationError("Run finished after the brief was created")
            latest_for_snapshot = epoch_records[-1]
            if count_by_campaign[run.campaign_id] > latest_for_snapshot.run_count:
                raise HistoricalResearchValidationError("Campaign history does not register all referenced Runs")
            if latest_for_snapshot.run_count > latest_for_snapshot.trial_budget:
                raise HistoricalResearchValidationError("Campaign run count exceeds its authorized budget")
    except DomainValidationError:
        raise HistoricalResearchValidationError("historical Run authorization or Idea scope is invalid") from None


__all__ = ["HistoricalResearchValidationError", "validate_historical_researched_brief"]
