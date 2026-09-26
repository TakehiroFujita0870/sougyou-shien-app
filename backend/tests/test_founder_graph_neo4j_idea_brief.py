from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json

import pytest

from dots.founder_graph_neo4j_idea_brief import (
    _decode_persisted_idea_brief,
    _serialize_persisted_idea_brief,
)
from dots.idea_brief import IdeaBriefSection, IdeaBriefValidationError, IdeaBriefVersion


def brief_fixture() -> IdeaBriefVersion:
    return IdeaBriefVersion(
        owner_id="owner-brief",
        idea_lineage_root_id="idea-root",
        based_on_idea_id="idea-rev-2",
        id="brief-rev-2",
        revision=2,
        supersedes_id="brief-rev-1",
        change_reason="synthetic revision",
        egress_policy="shareable",
        created_at=datetime(2026, 9, 26, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=9))),
        research_run_ids=("run-one", "run-two"),
        sections=tuple(
            IdeaBriefSection(
                index=index,
                content=f"section {index}",
                facts=(f"fact {index}",),
                inferences=(f"inference {index}",),
                unconfirmed=(f"unknown {index}",),
                owner_decisions=(f"decision {index}",),
                claim_ids=(f"claim-{index}",),
                evidence_ids=(f"evidence-{index}",),
            )
            for index in range(8)
        ),
    )


def record_for(brief: IdeaBriefVersion) -> dict[str, object]:
    return _serialize_persisted_idea_brief(brief)


def test_idea_brief_serializer_roundtrips_all_fields_eight_sections_and_created_at_exactly():
    brief = brief_fixture()

    record = record_for(brief)
    decoded = _decode_persisted_idea_brief(record, owner_id=brief.owner_id)

    assert decoded == brief
    assert len(decoded.sections) == 8
    assert decoded.created_at == brief.created_at
    assert json.loads(record["payload_json"])["created_at"] == brief.created_at.isoformat()


@pytest.mark.parametrize(
    "corruption",
    [
        "malformed_json", "missing_created_at", "extra_payload_key", "missing_section_key",
        "wrong_section_type", "wrong_research_run_ids_type", "naive_created_at",
        "payload_record_revision", "payload_owner", "record_id", "record_owner", "record_type", "record_root", "record_supersedes",
        "payload_id_whitespace", "payload_root_whitespace", "based_on_idea_whitespace",
        "run_reference_whitespace", "evidence_reference_whitespace",
    ],
)
def test_idea_brief_decoder_fails_closed_without_filling_defaults(corruption: str):
    record = record_for(brief_fixture())
    corrupted = deepcopy(record)
    if corruption == "malformed_json":
        corrupted["payload_json"] = "{invalid-json"
    elif corruption == "missing_created_at":
        payload = json.loads(corrupted["payload_json"])
        del payload["created_at"]
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "extra_payload_key":
        payload = json.loads(corrupted["payload_json"])
        payload["unrecognized"] = "value"
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "missing_section_key":
        payload = json.loads(corrupted["payload_json"])
        del payload["sections"][0]["facts"]
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "wrong_section_type":
        payload = json.loads(corrupted["payload_json"])
        payload["sections"][0]["index"] = True
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "wrong_research_run_ids_type":
        payload = json.loads(corrupted["payload_json"])
        payload["research_run_ids"] = "run-one"
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "naive_created_at":
        payload = json.loads(corrupted["payload_json"])
        payload["created_at"] = "2026-09-26T12:34:56"
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "payload_record_revision":
        payload = json.loads(corrupted["payload_json"])
        payload["revision"] = 3
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "payload_owner":
        payload = json.loads(corrupted["payload_json"])
        payload["owner_id"] = "other-owner"
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "record_id":
        corrupted["id"] = "different-id"
    elif corruption == "record_owner":
        corrupted["owner_id"] = "other-owner"
    elif corruption == "record_type":
        corrupted["node_type"] = "research_run"
    elif corruption == "record_root":
        corrupted["idea_lineage_root_id"] = "other-root"
    elif corruption == "record_supersedes":
        corrupted["supersedes_id"] = "other-brief"
    elif corruption == "payload_id_whitespace":
        payload = json.loads(corrupted["payload_json"])
        payload["id"] = " brief-rev-2 "
        corrupted["id"] = payload["id"]
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "payload_root_whitespace":
        payload = json.loads(corrupted["payload_json"])
        payload["idea_lineage_root_id"] = " idea-root "
        corrupted["idea_lineage_root_id"] = payload["idea_lineage_root_id"]
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "based_on_idea_whitespace":
        payload = json.loads(corrupted["payload_json"])
        payload["based_on_idea_id"] = " idea-rev-2 "
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "run_reference_whitespace":
        payload = json.loads(corrupted["payload_json"])
        payload["research_run_ids"][0] = " run-one "
        corrupted["payload_json"] = json.dumps(payload)
    elif corruption == "evidence_reference_whitespace":
        payload = json.loads(corrupted["payload_json"])
        payload["sections"][0]["evidence_ids"][0] = " evidence-0 "
        corrupted["payload_json"] = json.dumps(payload)

    with pytest.raises((IdeaBriefValidationError, ValueError)):
        _decode_persisted_idea_brief(corrupted, owner_id="owner-brief")


def test_idea_brief_decoder_rejects_foreign_owner_and_wrong_node_type_without_echoing_payload():
    record = record_for(brief_fixture())

    with pytest.raises(ValueError):
        _decode_persisted_idea_brief(record, owner_id="different-owner")


def test_empty_section_draft_roundtrips_as_eight_unchanged_empty_sections():
    draft = IdeaBriefVersion(
        owner_id="owner-brief",
        idea_lineage_root_id="idea-root",
        based_on_idea_id="idea-root",
        id="empty-draft",
        created_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )

    decoded = _decode_persisted_idea_brief(record_for(draft), owner_id=draft.owner_id)

    assert decoded == draft
    assert len(decoded.sections) == 8
    assert all(not section.content and not section.evidence_ids for section in decoded.sections)


def test_schema_v3_adds_non_searchable_idea_brief_label_and_non_destructive_rollback():
    from dots.founder_graph_schema import (
        SCHEMA_VERSION,
        migration_queries,
        rollback_queries,
        schema_manifest,
    )

    upgrade = migration_queries(2, 3)
    rollback = rollback_queries(3, 2)

    assert SCHEMA_VERSION == 3
    assert schema_manifest()["version"] == 3
    assert any("IdeaBriefVersion" in query and "REQUIRE node.id IS UNIQUE" in query for query in upgrade)
    assert any("IdeaBriefVersion" in query and "ON (node.owner_id)" in query for query in upgrade)
    assert not any("IdeaBriefVersion" in query and "search_text" in query for query in upgrade)
    assert rollback and all(query.startswith("DROP ") and "ideabriefversion" in query for query in rollback)
    assert not any("DELETE" in query or "DETACH" in query for query in rollback)
