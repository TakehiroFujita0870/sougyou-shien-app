from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from dots.founder_graph import Idea, Provenance, Status
from dots.founder_graph_neo4j import _node_properties
from dots.founder_graph_neo4j_idea import IdeaDecodeError, decode_persisted_idea


def fixture_record():
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    idea = Idea(
        id="idea-strict", owner_id="owner-strict", title="synthetic",
        status=Status.ACTIVE, revision=0, tags=("synthetic",),
        provenance=Provenance(actor="synthetic", operation="create", target_id="idea-strict",
                              occurred_at=now, idempotency_key="idea-strict-key"),
    )
    properties = _node_properties(idea)
    return idea, {key: properties[key] for key in ("id", "owner_id", "node_type", "revision", "payload_json")}


def test_strict_idea_decoder_roundtrips_complete_payload_without_generated_values():
    idea, record = fixture_record()
    assert decode_persisted_idea(record, owner_id=idea.owner_id, expected_id=idea.id) == idea


@pytest.mark.parametrize("case", [
    "missing_payload_field", "extra_payload_field", "owner", "type", "record_id",
    "bool_revision", "whitespace_id", "missing_provenance", "wrong_nullable_type",
    "duplicate_top_key", "duplicate_nested_key", "nonfinite_number", "naive_timestamp",
    "tags_not_list", "tag_not_string", "description_not_string", "provenance_not_object",
    "record_revision_mismatch", "invalid_enum", "extra_record_field",
])
def test_strict_idea_decoder_rejects_malformed_or_noncanonical_persisted_values(case):
    idea, record = fixture_record()
    if case == "duplicate_top_key":
        record["payload_json"] = record["payload_json"].replace('"title":"synthetic"', '"title":"synthetic","title":"other"')
    elif case == "duplicate_nested_key":
        record["payload_json"] = record["payload_json"].replace('"actor":"synthetic"', '"actor":"synthetic","actor":"other"')
    elif case == "nonfinite_number":
        record["payload_json"] = record["payload_json"].replace('"revision":0', '"revision":NaN')
    else:
        payload = json.loads(record["payload_json"])
        if case == "missing_payload_field":
            del payload["tags"]
        elif case == "extra_payload_field":
            payload["unexpected"] = True
        elif case == "owner":
            payload["owner_id"] = "other-owner"
        elif case == "type":
            record["node_type"] = "claim"
        elif case == "record_id":
            record["id"] = "other-id"
        elif case == "bool_revision":
            payload["revision"] = True
            record["revision"] = True
        elif case == "whitespace_id":
            payload["id"] = " idea-strict "
            record["id"] = payload["id"]
        elif case == "missing_provenance":
            del payload["provenance"]["idempotency_key"]
        elif case == "wrong_nullable_type":
            payload["provenance"]["source_id"] = 12
        elif case == "naive_timestamp":
            payload["created_at"] = "2026-09-26T00:00:00"
        elif case == "tags_not_list":
            payload["tags"] = "synthetic"
        elif case == "tag_not_string":
            payload["tags"] = [False]
        elif case == "description_not_string":
            payload["description"] = 10
        elif case == "provenance_not_object":
            payload["provenance"] = []
        elif case == "record_revision_mismatch":
            record["revision"] = 2
        elif case == "invalid_enum":
            payload["status"] = "not-a-status"
        record["payload_json"] = json.dumps(payload)
        if case == "extra_record_field":
            record["unexpected"] = True
    expected_id = " idea-strict " if case == "whitespace_id" else idea.id
    with pytest.raises(IdeaDecodeError) as error:
        decode_persisted_idea(record, owner_id=idea.owner_id, expected_id=expected_id)
    if case == "whitespace_id":
        assert "would change during hydration" in str(error.value)
