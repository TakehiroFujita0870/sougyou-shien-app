"""Fail-closed decoding for persisted ResearchCampaign values."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
import json
from typing import Any, Mapping

from .founder_graph import DomainValidationError, NodeType, Provenance, ResearchCampaign


class CampaignDecodeError(ValueError):
    """Persisted Campaign data is not safe to use as authorization state."""


def _record_value(record: Any, key: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(key)
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return None


def _timestamp(value: Any, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CampaignDecodeError("persisted campaign timestamp is invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CampaignDecodeError("persisted campaign timestamp is invalid") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise CampaignDecodeError("persisted campaign timestamp must include a timezone")
    return result


def decode_persisted_research_campaign(record: Any, *, owner_id: str) -> ResearchCampaign:
    """Decode a whitelisted Campaign payload, rejecting corrupt authority data."""

    if _record_value(record, "owner_id") != owner_id:
        raise CampaignDecodeError("persisted campaign owner does not match")
    if _record_value(record, "node_type") != NodeType.RESEARCH_CAMPAIGN.value:
        raise CampaignDecodeError("persisted node is not a research campaign")
    revision = _record_value(record, "revision")
    if type(revision) is not int or revision < 0:
        raise CampaignDecodeError("persisted campaign revision is invalid")

    raw_payload = _record_value(record, "payload_json")
    if not isinstance(raw_payload, str):
        raise CampaignDecodeError("persisted campaign payload is invalid")
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        raise CampaignDecodeError("persisted campaign payload is invalid") from None
    if not isinstance(payload, Mapping):
        raise CampaignDecodeError("persisted campaign payload must be an object")

    campaign_fields = {item.name for item in fields(ResearchCampaign)} - {"_internal_transition"}
    if set(payload).difference(campaign_fields | {"_internal_transition"}):
        raise CampaignDecodeError("persisted campaign has unsupported fields")
    if campaign_fields.difference(payload):
        raise CampaignDecodeError("persisted campaign is missing required fields")
    if "_internal_transition" in payload and payload["_internal_transition"] is not False:
        raise CampaignDecodeError("persisted campaign transition guard is invalid")
    if type(payload.get("authorized")) is not bool:
        raise CampaignDecodeError("persisted campaign authorization flag is invalid")
    if type(payload.get("authorization_revision")) is not int:
        raise CampaignDecodeError("persisted campaign authorization revision is invalid")
    if payload.get("id") != _record_value(record, "id") or payload.get("owner_id") != owner_id:
        raise CampaignDecodeError("persisted campaign identity does not match")
    if type(payload.get("aggregate_revision")) is not int or payload["aggregate_revision"] != revision:
        raise CampaignDecodeError("persisted campaign revision does not match its record")

    values = {name: payload[name] for name in campaign_fields if name in payload}
    for name in ("approved_at", "created_at", "expires_at"):
        values[name] = _timestamp(payload.get(name), nullable=name != "created_at")
    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        raise CampaignDecodeError("persisted campaign provenance is invalid")
    provenance_fields = {item.name for item in fields(Provenance)}
    if set(provenance).difference(provenance_fields):
        raise CampaignDecodeError("persisted campaign provenance is invalid")
    if provenance_fields.difference(provenance):
        raise CampaignDecodeError("persisted campaign provenance is missing required fields")
    provenance_values = dict(provenance)
    provenance_values["occurred_at"] = _timestamp(provenance.get("occurred_at"))

    try:
        values["provenance"] = Provenance(**provenance_values)
        # The model intentionally restricts authorized construction to approve().
        # Hydration is trusted only after the record metadata and payload agree.
        values["_internal_transition"] = True
        campaign = ResearchCampaign(**values)
        object.__setattr__(campaign, "_internal_transition", False)
    except (DomainValidationError, TypeError, ValueError):
        raise CampaignDecodeError("persisted campaign is invalid") from None
    if campaign.aggregate_revision != revision:
        raise CampaignDecodeError("persisted campaign revision does not match its record")
    return campaign
