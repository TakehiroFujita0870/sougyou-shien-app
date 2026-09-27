from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import Claim, EgressPolicy, Idea, MaterialKind, Source, SourceRevision
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_write import InMemoryGraphWriteService


def test_research_and_brief_tools_use_existing_memory_store_and_enforce_approval() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-research")
    writes.put_node(Idea(owner_id=writes.owner_id, id="idea-mcp", title="Synthetic idea"), idempotency_key="idea-seed")
    surface = McpWriteSurface(writes)
    tools = {item["name"]: item for item in surface.tool_definitions()}
    assert {
        "create_research_campaign", "approve_research_campaign", "revoke_research_campaign",
        "record_research_run", "save_idea_brief", "save_researched_idea_brief",
    } <= tools.keys()
    assert "未許諾Campaign" in tools["create_research_campaign"]["description"]
    assert tools["approve_research_campaign"]["annotations"]["destructiveHint"] is True
    assert all(item["annotations"]["openWorldHint"] is False for item in tools.values())

    created = surface.call("create_research_campaign", {
        "purpose": "Synthetic market check", "scope": {"target_ids": ["idea-mcp"]},
        "target_idea_id": "idea-mcp", "trial_budget": 1,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "idempotency_key": "mcp-campaign", "expected_revision": 0,
    }, owner_id=writes.owner_id)
    assert created.campaign_proposal["authorized"] is False
    try:
        surface.call("record_research_run", {}, owner_id=writes.owner_id)
    except McpWriteError as error:
        assert error.code == "invalid_input"
    else:  # pragma: no cover
        raise AssertionError("malformed run requests must fail closed")

    approved = surface.call("approve_research_campaign", {
        "campaign_id": created.target_id, "expected_revision": 0,
        "confirmation": "approved", "idempotency_key": "mcp-approve",
    }, owner_id=writes.owner_id)
    now = datetime.now(timezone.utc).isoformat()
    run = surface.call("record_research_run", {
        "campaign_id": created.target_id,
        "expected_campaign_revision": approved.revision,
        "authorization_snapshot_id": approved.campaign_proposal["authorization_snapshot_id"],
        "authorization_revision": approved.campaign_proposal["authorization_revision"],
        "input_snapshot": {"question": "synthetic"}, "model_snapshot": "synthetic-test",
        "status": "completed", "results": {"summary": "synthetic"},
        "started_at": now, "finished_at": now, "idempotency_key": "mcp-run",
    }, owner_id=writes.owner_id)
    assert run.target_type == "research_run"

    claim = Claim(owner_id=writes.owner_id, id="claim-mcp", text="Synthetic cited claim", egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(claim, idempotency_key="claim-seed")
    revision = SourceRevision(
        owner_id=writes.owner_id, id="revision-mcp", source_id="source-mcp", content="Synthetic public source",
        locator="https://example.test/source?id=1#section", egress_policy=EgressPolicy.SHAREABLE,
    )
    source = Source(
        owner_id=writes.owner_id, id="source-mcp", title="Synthetic public source",
        locator="https://example.test/source?id=1#section", current_revision_id=revision.id,
        revision=1, egress_policy=EgressPolicy.SHAREABLE, kind=MaterialKind.WEB,
    )
    captured = writes.capture_source(source, revision, idempotency_key="source-seed")
    evidence = writes.capture_evidence(
        claim.id, captured.content_chunk_ids[0], egress_policy=EgressPolicy.SHAREABLE,
        idempotency_key="evidence-seed",
    )
    sections = [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)]
    sections[0]["evidence_ids"] = [evidence.target_id]
    brief = surface.call("save_researched_idea_brief", {
        "idea_id": "idea-mcp", "expected_revision": 0, "sections": sections,
        "research_run_ids": [run.target_id], "idempotency_key": "mcp-brief",
    }, owner_id=writes.owner_id)
    assert brief.target_type == "idea_brief_version"
    saved = writes.get_idea_brief(brief.target_id)
    assert saved is not None and saved.research_run_ids == (run.target_id,)

    with pytest.raises(McpWriteError, match="current, shareable Evidence citation"):
        surface.call("save_researched_idea_brief", {
            "idea_id": "idea-mcp", "expected_revision": 1,
            "sections": [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)],
            "research_run_ids": ["run-with-no-evidence"], "idempotency_key": "mcp-empty-brief",
        }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief("idea-mcp").id == brief.target_id


def test_researched_brief_rejects_wrong_owner_without_writing() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-research")
    writes.put_node(Idea(owner_id=writes.owner_id, id="idea-mcp", title="Synthetic idea"), idempotency_key="idea-seed")
    surface = McpWriteSurface(writes)
    try:
        surface.call("save_researched_idea_brief", {
            "idea_id": "idea-mcp", "expected_revision": 0,
            "sections": [{"index": index, "content": f"Section {index}"} for index in range(8)],
            "research_run_ids": ["missing-run"], "idempotency_key": "wrong-owner-brief",
        }, owner_id="owner-other")
    except McpWriteError as error:
        assert error.code == "owner_mismatch"
    else:  # pragma: no cover
        raise AssertionError("wrong-owner writes must be rejected")
    assert writes.get_latest_idea_brief("idea-mcp") is None


def test_regular_idea_brief_reuses_memory_writer_and_replays_same_key() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-brief")
    writes.put_node(Idea(owner_id=writes.owner_id, id="idea-brief", title="Synthetic idea"), idempotency_key="idea-seed")
    surface = McpWriteSurface(writes)
    args = {
        "idea_id": "idea-brief", "expected_revision": 0,
        "sections": [{"index": 0, "content": "A bounded synthetic note"}],
        "idempotency_key": "regular-brief",
    }
    first = surface.call("save_idea_brief", args, owner_id=writes.owner_id)
    replay = surface.call("save_idea_brief", args, owner_id=writes.owner_id)
    assert first.target_type == "idea_brief_version"
    assert replay.target_id == first.target_id
    assert replay.replayed is True
