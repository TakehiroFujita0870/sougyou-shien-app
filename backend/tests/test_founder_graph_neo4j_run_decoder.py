from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from dots.founder_graph import (
    EgressPolicy,
    NodeType,
    Provenance,
    ProvenanceOrigin,
    ResearchRun,
    Status,
    TransportRetry,
)
from dots.founder_graph_neo4j import _node_properties
from dots.founder_graph_neo4j_run import ResearchRunDecodeError, decode_persisted_research_run


OWNER_ID = "owner-run-decode-synthetic"
RUN_ID = "run-decode-synthetic"
CAMPAIGN_ID = "campaign-decode-synthetic"


def persisted_run_record() -> tuple[ResearchRun, dict[str, object]]:
    now = datetime(2026, 9, 26, 9, 30, tzinfo=timezone.utc)
    run = ResearchRun(
        id=RUN_ID,
        owner_id=OWNER_ID,
        campaign_id=CAMPAIGN_ID,
        input_snapshot={"query": "synthetic", "flags": [True, 2], "filters": {"region": "sample"}},
        model_snapshot="model-synthetic-v1",
        sources=("source-synthetic",),
        evidence_ids=("evidence-synthetic",),
        results={"items": [{"count": 3, "ok": True}], "metadata": {"origin": "fixture"}},
        failures=(),
        status=Status.COMPLETED,
        egress_policy=EgressPolicy.SHAREABLE,
        authorization_snapshot_id="authorization-synthetic",
        authorization_revision=4,
        parent_run_id="run-parent-synthetic",
        supersedes_id=None,
        started_at=now - timedelta(minutes=3),
        finished_at=now - timedelta(minutes=1),
        transport_retries=(TransportRetry(attempted_at=now - timedelta(minutes=2), error="synthetic retry"),),
        provenance=Provenance(
            actor="synthetic-actor",
            operation="complete_run",
            origin=ProvenanceOrigin.GENERATED,
            target_id=RUN_ID,
            source_id=CAMPAIGN_ID,
            model_snapshot="model-synthetic-v1",
            prompt_version="prompt-synthetic-v1",
            occurred_at=now,
            idempotency_key="idem-run-synthetic",
        ),
    )
    properties = _node_properties(run)
    return run, {
        "id": properties["id"],
        "owner_id": properties["owner_id"],
        "node_type": properties["node_type"],
        "revision": properties["revision"],
        "payload_json": properties["payload_json"],
    }


def _payload(record: dict[str, object]) -> dict[str, object]:
    return json.loads(str(record["payload_json"]))


def _store_payload(record: dict[str, object], payload: dict[str, object]) -> None:
    record["payload_json"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def test_decoder_roundtrips_every_research_run_field_without_defaults():
    original, record = persisted_run_record()

    decoded = decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)

    assert decoded == original
    assert decoded.input_snapshot == original.input_snapshot
    assert decoded.results == original.results
    assert decoded.transport_retries == original.transport_retries
    assert decoded.provenance == original.provenance


def test_decoder_accepts_semantically_equivalent_timezone_representation():
    original, record = persisted_run_record()
    payload = _payload(record)
    payload["finished_at"] = original.finished_at.isoformat().replace("+00:00", "Z")
    payload["provenance"]["occurred_at"] = original.provenance.occurred_at.isoformat().replace("+00:00", "Z")
    payload["transport_retries"][0]["attempted_at"] = (
        original.transport_retries[0].attempted_at.isoformat().replace("+00:00", "Z")
    )
    _store_payload(record, payload)

    decoded = decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)

    assert decoded == original


def test_decoder_preserves_nullable_timestamps_without_generating_values():
    original, _record = persisted_run_record()
    run = ResearchRun(
        id=original.id,
        owner_id=original.owner_id,
        campaign_id=original.campaign_id,
        input_snapshot=original.input_snapshot,
        model_snapshot=original.model_snapshot,
        status=Status.PENDING,
        started_at=None,
        finished_at=None,
        provenance=original.provenance,
    )
    properties = _node_properties(run)
    record = {
        "id": properties["id"],
        "owner_id": properties["owner_id"],
        "node_type": properties["node_type"],
        "revision": properties["revision"],
        "payload_json": properties["payload_json"],
    }

    decoded = decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)

    assert decoded == run
    assert decoded.started_at is None
    assert decoded.finished_at is None


@pytest.mark.parametrize(
    ("record_change", "owner_id", "expected_id"),
    [
        (lambda record: record.update(id="run-other"), OWNER_ID, RUN_ID),
        (lambda record: record.update(owner_id="owner-other"), OWNER_ID, RUN_ID),
        (lambda record: record.update(node_type=NodeType.CLAIM.value), OWNER_ID, RUN_ID),
        (lambda record: record.update(revision=True), OWNER_ID, RUN_ID),
        (lambda record: record.update(revision=1), OWNER_ID, RUN_ID),
        (lambda record: None, "owner-other", RUN_ID),
        (lambda record: None, OWNER_ID, "run-other"),
    ],
)
def test_decoder_rejects_inconsistent_outer_metadata(record_change, owner_id, expected_id):
    _run, record = persisted_run_record()
    record_change(record)

    with pytest.raises(ResearchRunDecodeError):
        decode_persisted_research_run(record, owner_id=owner_id, expected_id=expected_id)


@pytest.mark.parametrize(
    ("payload_change",),
    [
        (lambda payload: payload.pop("sources"),),
        (lambda payload: payload.pop("started_at"),),
        (lambda payload: payload.pop("id"),),
        (lambda payload: payload.update(unknown_field="not-accepted"),),
        (lambda payload: payload.update(owner_id="owner-other"),),
        (lambda payload: payload.update(id="run-other"),),
        (lambda payload: payload.update(campaign_id=f" {CAMPAIGN_ID} "),),
        (lambda payload: payload.update(sources="source-synthetic"),),
        (lambda payload: payload.update(input_snapshot=[]),),
        (lambda payload: payload.update(authorization_revision=True),),
        (lambda payload: payload.update(status="unknown-status"),),
        (lambda payload: payload.update(egress_policy="research_allowed"),),
        (lambda payload: payload["provenance"].pop("idempotency_key"),),
        (lambda payload: payload["provenance"].update(origin="unknown-origin"),),
        (lambda payload: payload["transport_retries"][0].pop("attempted_at"),),
        (lambda payload: payload["transport_retries"][0].update(attempted_at="2026-09-26T09:28:00"),),
        (lambda payload: payload.update(finished_at="2026-09-26T09:29:00"),),
        (lambda payload: payload.update(finished_at="2026-09-26T09:00:00+00:00"),),
    ],
)
def test_decoder_rejects_missing_unknown_or_noncanonical_payload_values(payload_change):
    _run, record = persisted_run_record()
    payload = _payload(record)
    payload_change(payload)
    _store_payload(record, payload)

    with pytest.raises(ResearchRunDecodeError):
        decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)


def test_decoder_rejects_whitespace_ids_even_when_record_and_payload_match():
    _run, record = persisted_run_record()
    payload = _payload(record)
    payload["id"] = f" {RUN_ID} "
    record["id"] = payload["id"]
    _store_payload(record, payload)

    with pytest.raises(ResearchRunDecodeError, match="values would change during hydration"):
        decode_persisted_research_run(
            record, owner_id=OWNER_ID, expected_id=f" {RUN_ID} "
        )


@pytest.mark.parametrize(
    "payload_json",
    ["not-json", "[]"],
)
def test_decoder_rejects_nonobject_or_invalid_json(payload_json):
    _run, record = persisted_run_record()
    record["payload_json"] = payload_json

    with pytest.raises(ResearchRunDecodeError):
        decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)


def test_decoder_rejects_duplicate_object_keys_at_any_depth():
    _run, record = persisted_run_record()
    raw = str(record["payload_json"])
    duplicate_top_level = raw.replace(
        f'"campaign_id":"{CAMPAIGN_ID}"',
        f'"campaign_id":"{CAMPAIGN_ID}","campaign_id":"{CAMPAIGN_ID}"',
        1,
    )
    record["payload_json"] = duplicate_top_level
    with pytest.raises(ResearchRunDecodeError, match="duplicate keys"):
        decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)

    _run, record = persisted_run_record()
    raw = str(record["payload_json"])
    duplicate_nested = raw.replace(
        '"region":"sample"', '"region":"sample","region":"other"', 1,
    )
    record["payload_json"] = duplicate_nested
    with pytest.raises(ResearchRunDecodeError, match="duplicate keys"):
        decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)


@pytest.mark.parametrize("field", ["input_snapshot", "results"])
def test_decoder_rejects_nonfinite_json_values(field):
    _run, record = persisted_run_record()
    payload_json = str(record["payload_json"])
    payload_json = payload_json.replace('"query":"synthetic"', '"query":NaN') if field == "input_snapshot" else payload_json.replace('"count":3', '"count":Infinity')
    record["payload_json"] = payload_json

    with pytest.raises(ResearchRunDecodeError):
        decode_persisted_research_run(record, owner_id=OWNER_ID, expected_id=RUN_ID)
