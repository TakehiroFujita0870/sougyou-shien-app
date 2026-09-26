from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from dots.founder_graph import EgressPolicy, NodeType, Provenance, ResearchCampaign
from dots.founder_graph_neo4j import _node_properties
from dots.founder_graph_neo4j_campaign import CampaignDecodeError, decode_persisted_research_campaign


def persisted_campaign_record():
    now = datetime.now(timezone.utc)
    campaign = ResearchCampaign(
        id="campaign-decoder-synthetic", owner_id="owner-decoder-synthetic",
        purpose="synthetic payload marker", scope={"target_ids": ["idea-synthetic"]},
        allowed_categories=("idea.summary",), trial_budget=3,
        expires_at=now + timedelta(hours=1), egress_policy=EgressPolicy.SHAREABLE,
        created_at=now - timedelta(hours=1),
        provenance=Provenance(actor="synthetic", operation="create", target_id="campaign-decoder-synthetic",
                              occurred_at=now - timedelta(hours=1), idempotency_key="idem-decoder-synthetic"),
    ).approve(approved_at=now - timedelta(minutes=5))
    properties = _node_properties(campaign)
    return campaign, {
        "id": properties["id"], "owner_id": properties["owner_id"],
        "node_type": properties["node_type"], "revision": properties["revision"],
        "payload_json": properties["payload_json"],
    }


def test_decoder_restores_authoritative_campaign_and_resets_internal_guard():
    original, record = persisted_campaign_record()

    decoded = decode_persisted_research_campaign(record, owner_id=original.owner_id)

    assert decoded == original
    assert decoded.authorized is True
    assert decoded.authorization_snapshot_id == original.authorization_snapshot_id
    assert decoded.scope == original.scope
    assert decoded.aggregate_revision == record["revision"]
    assert decoded._internal_transition is False


@pytest.mark.parametrize(
    ("record_change", "payload_change"),
    [
        (lambda record: record.update(owner_id="owner-other"), None),
        (lambda record: record.update(node_type="relation_assertion"), None),
        (lambda record: record.update(revision=True), None),
        (lambda record: None, lambda payload: payload.update(aggregate_revision=99)),
        (lambda record: None, lambda payload: payload.update(egress_policy="research_allowed")),
        (lambda record: None, lambda payload: payload.update(status="unknown-status")),
        (lambda record: None, lambda payload: payload.update(_internal_transition=True)),
        (lambda record: None, lambda payload: payload.update(expires_at="2026-09-26T09:00:00")),
        (lambda record: None, lambda payload: payload["provenance"].update(origin="unknown-origin")),
    ],
)
def test_decoder_rejects_corrupt_record_or_payload_without_echoing_values(record_change, payload_change):
    _campaign, record = persisted_campaign_record()
    record_change(record)
    if payload_change is not None:
        payload = json.loads(record["payload_json"])
        payload_change(payload)
        record["payload_json"] = json.dumps(payload)

    with pytest.raises(CampaignDecodeError) as error:
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")

    assert "synthetic payload marker" not in str(error.value)
    assert "owner-other" not in str(error.value)


@pytest.mark.parametrize("payload_json", ["not-json", "[]"])
def test_decoder_rejects_malformed_payload_json(payload_json):
    _campaign, record = persisted_campaign_record()
    record["payload_json"] = payload_json

    with pytest.raises(CampaignDecodeError):
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")


def test_decoder_rejects_unknown_payload_fields_and_naive_provenance_time():
    _campaign, record = persisted_campaign_record()
    payload = json.loads(record["payload_json"])
    payload["secret_extension"] = "must-not-leak"
    record["payload_json"] = json.dumps(payload)

    with pytest.raises(CampaignDecodeError) as error:
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")
    assert "must-not-leak" not in str(error.value)

    payload.pop("secret_extension")
    payload["provenance"]["occurred_at"] = "2026-09-26T09:00:00"
    record["payload_json"] = json.dumps(payload)
    with pytest.raises(CampaignDecodeError):
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")


def test_decoder_fails_closed_when_payload_and_record_owner_disagree():
    _campaign, record = persisted_campaign_record()
    payload = json.loads(record["payload_json"])
    payload["owner_id"] = "owner-other"
    record["payload_json"] = json.dumps(payload)

    with pytest.raises(CampaignDecodeError):
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")


@pytest.mark.parametrize("field", ["trial_budget", "scope", "authorization_snapshot_id"])
def test_decoder_rejects_missing_campaign_fields_instead_of_using_model_defaults(field):
    _campaign, record = persisted_campaign_record()
    payload = json.loads(record["payload_json"])
    payload.pop(field)
    record["payload_json"] = json.dumps(payload)

    with pytest.raises(CampaignDecodeError):
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")


def test_decoder_rejects_missing_provenance_fields_instead_of_generating_new_values():
    _campaign, record = persisted_campaign_record()
    payload = json.loads(record["payload_json"])
    payload["provenance"].pop("idempotency_key")
    record["payload_json"] = json.dumps(payload)

    with pytest.raises(CampaignDecodeError):
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")


@pytest.mark.parametrize(
    ("field", "value"),
    [("authorized", "false"), ("authorization_revision", True)],
)
def test_decoder_rejects_wrong_authorization_primitive_types(field, value):
    _campaign, record = persisted_campaign_record()
    payload = json.loads(record["payload_json"])
    payload[field] = value
    record["payload_json"] = json.dumps(payload)

    with pytest.raises(CampaignDecodeError):
        decode_persisted_research_campaign(record, owner_id="owner-decoder-synthetic")
