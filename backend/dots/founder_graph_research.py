"""Small pure helpers for existing research state transitions."""

from __future__ import annotations

from datetime import datetime

from .founder_graph import Provenance, ResearchCampaign
from .founder_graph_research_run import validate_research_run_timing


def revoke_research_campaign(
    campaign: ResearchCampaign,
    *,
    at: datetime | None = None,
    provenance: Provenance | None = None,
) -> ResearchCampaign:
    """Delegate revocation to the canonical immutable campaign transition."""
    if not isinstance(campaign, ResearchCampaign):
        raise TypeError("campaign must be a ResearchCampaign")
    return campaign.revoke(at=at, provenance=provenance)


__all__ = ["revoke_research_campaign", "validate_research_run_timing"]
