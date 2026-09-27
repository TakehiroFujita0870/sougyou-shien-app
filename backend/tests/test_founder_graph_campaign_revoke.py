from __future__ import annotations

from datetime import timedelta

import pytest

from dots.founder_graph import DomainValidationError, ResearchCampaign, Status, utc_now


def test_revoke_creates_unauthorized_campaign_revision_and_is_retry_safe() -> None:
    approved_at = utc_now() + timedelta(seconds=1)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        purpose="Validate a bounded research question",
        trial_budget=2,
        expires_at=approved_at + timedelta(days=1),
    ).approve(approved_at=approved_at)

    revoked = campaign.revoke(at=approved_at + timedelta(seconds=1))

    assert revoked.status is Status.REVOKED
    assert revoked.authorized is False
    assert revoked.approved_at is None
    assert revoked.authorization_revision == campaign.authorization_revision + 1
    assert revoked.aggregate_revision == campaign.aggregate_revision + 1
    assert revoked.prior_authorization_snapshot_id == campaign.authorization_snapshot_id
    assert revoked.revoke() is revoked


def test_cancelled_campaign_cannot_be_revoked() -> None:
    campaign = ResearchCampaign(
        owner_id="owner-1",
        purpose="Cancelled campaign",
        status=Status.CANCELLED,
    )

    with pytest.raises(DomainValidationError, match="cancelled campaign cannot be revoked"):
        campaign.revoke()
