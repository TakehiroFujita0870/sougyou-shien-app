from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import Claim, EgressPolicy, Idea, MaterialKind, Source, SourceRevision
from dots.founder_graph_mcp import McpReadSurface
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_write import GraphWriteError, InMemoryGraphWriteService
from dots.idea_brief import SECTION_TITLES, IdeaBriefSection, IdeaBriefVersion


def test_research_and_brief_tools_use_existing_memory_store_and_enforce_approval() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-research")
    writes.put_node(Idea(owner_id=writes.owner_id, id="idea-mcp", title="Synthetic idea", egress_policy=EgressPolicy.SHAREABLE), idempotency_key="idea-seed")
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
    researched_tool = tools["save_researched_idea_brief"]
    assert "report_markdown" in researched_tool["inputSchema"]["required"]
    assert "egress_policy=shareable" in researched_tool["description"]
    report_markdown = "\n\n".join(
        f"## {title}\n\nSynthetic section {index}."
        for index, title in enumerate(SECTION_TITLES)
    ) + "\n\n| 対象 | 課題 |\n| --- | --- |\n| 店舗 | 発注 |\n\n出典: https://example.test/source?id=1#section"
    for missing_report in ({}, {"report_markdown": "  "}):
        with pytest.raises(McpWriteError, match="report_markdown"):
            surface.call("save_researched_idea_brief", {
                "idea_id": "idea-mcp", "expected_revision": 0, "sections": sections,
                "research_run_ids": [run.target_id], "idempotency_key": "mcp-brief-invalid",
                **missing_report,
            }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief("idea-mcp") is None
    brief = surface.call("save_researched_idea_brief", {
        "idea_id": "idea-mcp", "expected_revision": 0, "sections": sections,
        "research_run_ids": [run.target_id], "report_markdown": report_markdown,
        "egress_policy": "shareable",
        "idempotency_key": "mcp-brief",
    }, owner_id=writes.owner_id)
    assert brief.target_type == "idea_brief_version"
    saved = writes.get_idea_brief(brief.target_id)
    assert saved is not None and saved.research_run_ids == (run.target_id,)
    assert saved.origin is None
    assert saved.report_markdown == report_markdown
    fetched = McpReadSurface(GraphReadService(writes)).call(
        "fetch_idea_brief", {"idea_id": "idea-mcp"}, owner_id=writes.owner_id,
    )
    assert fetched["brief_id"] == brief.target_id
    assert fetched["report_markdown"] == report_markdown
    assert fetched["sections"][0]["evidence_ids"] == [evidence.target_id]
    link = surface.call("link_entities", {
        "source_id": "idea-mcp", "target_id": claim.id, "relation": "ADDRESSES",
        "evidence_ids": [evidence.target_id], "based_on_brief_id": fetched["brief_id"],
        "based_on_brief_section_index": 0, "egress_policy": "shareable",
        "idempotency_key": "mcp-report-graph-link",
    }, owner_id=writes.owner_id)
    linked = McpReadSurface(GraphReadService(writes)).call(
        "fetch", {"id": link.target_id}, owner_id=writes.owner_id,
    )
    assert linked["id"] == link.target_id

    invalid_reports = (
        "## 概要\n\nIncomplete report",
        "\n\n".join(f"## {title}" for title in reversed(SECTION_TITLES)),
    )
    for index, invalid_report in enumerate(invalid_reports):
        with pytest.raises(McpWriteError, match="canonical eight headings"):
            surface.call("save_researched_idea_brief", {
                "idea_id": "idea-mcp", "expected_revision": 1, "sections": sections,
                "research_run_ids": [run.target_id], "report_markdown": invalid_report,
                "idempotency_key": f"mcp-brief-incomplete-report-{index}",
            }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief("idea-mcp").id == brief.target_id

    with pytest.raises(McpWriteError, match="current, shareable Evidence citation"):
        surface.call("save_researched_idea_brief", {
            "idea_id": "idea-mcp", "expected_revision": 1,
            "sections": [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)],
            "research_run_ids": ["run-with-no-evidence"], "report_markdown": report_markdown,
            "idempotency_key": "mcp-empty-brief",
        }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief("idea-mcp").id == brief.target_id


def test_append_research_finding_writes_only_markdown_and_replays_idempotently() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-research-append")
    idea = Idea(
        owner_id=writes.owner_id, id="idea-research-append", title="Synthetic idea",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(idea, idempotency_key="idea-research-append-seed")
    surface = McpWriteSurface(writes)
    tools = {item["name"]: item for item in surface.tool_definitions()}

    assert "append_research_finding" in tools
    append_tool = tools["append_research_finding"]
    assert set(append_tool["inputSchema"]["required"]) == {
        "idea_id", "expected_revision", "finding", "source_url", "idempotency_key",
    }
    assert "sections" not in append_tool["inputSchema"]["required"]

    first_args = {
        "idea_id": idea.id, "expected_revision": 0,
        "finding": "The first synthetic finding.",
        "source_url": "https://example.test/first?tab=public",
        "egress_policy": "shareable", "idempotency_key": "append-finding-first",
    }
    first = surface.call("append_research_finding", first_args, owner_id=writes.owner_id)
    second = surface.call("append_research_finding", {
        "idea_id": idea.id, "expected_revision": first.revision,
        "finding": "The second synthetic finding.",
        "source_url": "https://example.test/second",
        "egress_policy": "shareable", "idempotency_key": "append-finding-second",
    }, owner_id=writes.owner_id)
    third = surface.call("append_research_finding", {
        "idea_id": idea.id, "expected_revision": second.revision,
        "finding": "The third synthetic finding.",
        "source_url": "https://example.test/third",
        "egress_policy": "shareable", "idempotency_key": "append-finding-third",
    }, owner_id=writes.owner_id)
    replay = surface.call("append_research_finding", first_args, owner_id=writes.owner_id)

    assert first.target_type == "idea_brief_version"
    assert first.revision == 1
    assert second.revision == 2
    assert third.revision == 3
    assert replay.target_id == first.target_id
    assert replay.revision == first.revision
    assert replay.replayed is True
    saved = writes.get_latest_idea_brief(idea.id)
    assert saved is not None
    assert saved.sections and all(not section.content for section in saved.sections)
    assert saved.research_run_ids == ()
    assert saved.report_markdown is not None
    assert saved.report_markdown.index("The first synthetic finding.") < saved.report_markdown.index("The second synthetic finding.")
    assert saved.report_markdown.index("The second synthetic finding.") < saved.report_markdown.index("The third synthetic finding.")
    assert "<https://example.test/first?tab=public>" in saved.report_markdown
    assert "<https://example.test/second>" in saved.report_markdown
    assert "<https://example.test/third>" in saved.report_markdown

    fetched = McpReadSurface(GraphReadService(writes)).call(
        "fetch_idea_brief", {"idea_id": idea.id}, owner_id=writes.owner_id,
    )
    assert fetched["report_markdown"] == saved.report_markdown

    with pytest.raises(McpWriteError) as changed_retry:
        surface.call("append_research_finding", {
            **first_args, "finding": "A different synthetic finding.",
        }, owner_id=writes.owner_id)
    assert changed_retry.value.code == "idempotency_conflict"

    with pytest.raises(McpWriteError) as stale_revision:
        surface.call("append_research_finding", {
            "idea_id": idea.id, "expected_revision": 1,
            "finding": "A stale synthetic finding.", "source_url": "https://example.test/stale",
            "idempotency_key": "append-finding-stale",
        }, owner_id=writes.owner_id)
    assert stale_revision.value.code == "revision_conflict"


@pytest.mark.parametrize("source_url", [
    "javascript:alert(1)",
    "https://user:password@example.test/source",
    "https://example.test/source?access_token=private",
    "https://example.test/source with spaces",
])
def test_append_research_finding_rejects_non_public_markdown_urls(source_url: str) -> None:
    writes = InMemoryGraphWriteService("owner-mcp-invalid-source-url")
    idea = Idea(owner_id=writes.owner_id, id="idea-invalid-source-url", title="Synthetic idea")
    writes.put_node(idea, idempotency_key="idea-invalid-source-url-seed")
    surface = McpWriteSurface(writes)

    with pytest.raises(McpWriteError, match=r"public HTTP\(S\) URL"):
        surface.call("append_research_finding", {
            "idea_id": idea.id, "expected_revision": 0,
            "finding": "A synthetic finding.", "source_url": source_url,
            "idempotency_key": "append-invalid-source-url",
        }, owner_id=writes.owner_id)

    assert writes.get_latest_idea_brief(idea.id) is None


def test_markdown_append_remains_a_draft_after_a_structured_brief() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-research-append-draft")
    idea = Idea(owner_id=writes.owner_id, id="idea-append-draft", title="Synthetic idea")
    writes.put_node(idea, idempotency_key="idea-append-draft-seed")
    original = IdeaBriefVersion(
        owner_id=writes.owner_id,
        idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id,
        sections=tuple(IdeaBriefSection(index=index, content=f"prior section {index}") for index in range(8)),
        report_markdown="## Prior draft",
        change_reason="prior structured brief",
    )
    writes.save_idea_brief(original, expected_latest_revision=None, idempotency_key="prior-structured-brief")

    surface = McpWriteSurface(writes)
    appended = surface.call("append_research_finding", {
        "idea_id": idea.id, "expected_revision": 1,
        "finding": "A new unverified finding.", "source_url": "https://example.test/new-finding",
        "idempotency_key": "append-after-structured-brief",
    }, owner_id=writes.owner_id)

    latest = writes.get_latest_idea_brief(idea.id)
    assert latest is not None and latest.id == appended.target_id
    assert latest.research_run_ids == ()
    assert all(not section.content and not section.evidence_ids for section in latest.sections)
    assert writes.get_idea_brief(original.id).sections[0].content == "prior section 0"


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
        "report_markdown": "## 概要\n\n| 対象 | 課題 |\n| --- | --- |\n| 店舗 | 発注 |",
        "idempotency_key": "regular-brief",
    }
    first = surface.call("save_idea_brief", args, owner_id=writes.owner_id)
    replay = surface.call("save_idea_brief", args, owner_id=writes.owner_id)
    assert first.target_type == "idea_brief_version"
    assert replay.target_id == first.target_id
    assert replay.replayed is True
    assert writes.get_idea_brief(first.target_id).report_markdown == args["report_markdown"]
    with pytest.raises(McpWriteError) as changed:
        surface.call("save_idea_brief", {**args, "report_markdown": "## 別の本文"}, owner_id=writes.owner_id)
    assert changed.value.code == "idempotency_conflict"
    save_brief = next(item for item in surface.tool_definitions() if item["name"] == "save_idea_brief")
    assert save_brief["inputSchema"]["properties"]["origin"]["enum"] == ["prior_research_import"]
    assert save_brief["inputSchema"]["properties"]["report_markdown"]["maxLength"] == 60000


def test_regular_idea_brief_omission_preserves_markdown_and_string_replaces_it():
    writes = InMemoryGraphWriteService("owner-mcp-brief-preserve")
    idea = Idea(owner_id=writes.owner_id, id="idea-brief-preserve", title="Synthetic idea")
    writes.put_node(idea, idempotency_key="idea-brief-preserve-seed")
    surface = McpWriteSurface(writes)
    original_markdown = "## Synthetic report\n\nOriginal body."
    first = surface.call("save_idea_brief", {
        "idea_id": idea.id, "expected_revision": 0,
        "sections": [{"index": 0, "content": "Original section"}],
        "report_markdown": original_markdown,
        "idempotency_key": "brief-preserve-first",
    }, owner_id=writes.owner_id)
    with pytest.raises(McpWriteError):
        surface.call("save_idea_brief", {
            "idea_id": idea.id, "expected_revision": 1,
            "sections": [{"index": 0, "content": "Null section"}],
            "report_markdown": None,
            "idempotency_key": "brief-preserve-null-markdown",
        }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief(idea.id).report_markdown == original_markdown

    omission_arguments = {
        "idea_id": idea.id, "expected_revision": 1,
        "sections": [{"index": 0, "content": "Updated section"}],
        "idempotency_key": "brief-preserve-omitted-markdown",
    }
    omitted = surface.call("save_idea_brief", omission_arguments, owner_id=writes.owner_id)
    latest_after_omission = writes.get_latest_idea_brief(idea.id)
    assert latest_after_omission is not None
    assert latest_after_omission.report_markdown == original_markdown
    assert writes.get_idea_brief(first.target_id).report_markdown == original_markdown
    replay = surface.call("save_idea_brief", omission_arguments, owner_id=writes.owner_id)
    assert replay.replayed is True
    assert writes.get_latest_idea_brief(idea.id).report_markdown == original_markdown

    replacement_markdown = "## Synthetic replacement\n\nReplacement body."
    replaced = surface.call("save_idea_brief", {
        "idea_id": idea.id, "expected_revision": omitted.revision,
        "sections": [{"index": 0, "content": "Replaced section"}],
        "report_markdown": replacement_markdown,
        "idempotency_key": "brief-preserve-replacement",
    }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief(idea.id).report_markdown == replacement_markdown
    assert writes.get_idea_brief(first.target_id).report_markdown == original_markdown
    assert writes.get_idea_brief(omitted.target_id).report_markdown == original_markdown
    save_brief = next(item for item in surface.tool_definitions() if item["name"] == "save_idea_brief")
    schema = save_brief["inputSchema"]
    assert "report_markdown" not in schema["required"]
    assert "省略時" in schema["properties"]["report_markdown"]["description"]


def test_prior_research_brief_successor_requires_current_public_evidence_and_replays_origin():
    writes = InMemoryGraphWriteService("owner-prior-brief")
    idea = Idea(owner_id=writes.owner_id, id="idea-prior", title="Synthetic idea", egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(idea, idempotency_key="idea-prior-seed")
    surface = McpWriteSurface(writes)
    sections = [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)]
    original = surface.call("save_idea_brief", {
        "idea_id": idea.id, "expected_revision": 0, "sections": sections,
        "idempotency_key": "prior-brief-draft",
    }, owner_id=writes.owner_id)
    claim = Claim(owner_id=writes.owner_id, id="claim-prior-brief", text="Synthetic claim",
                  egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(claim, idempotency_key="claim-prior-brief-seed")
    source = Source(
        owner_id=writes.owner_id, id="source-prior-brief", title="Synthetic public source",
        locator="https://example.test/prior-brief", current_revision_id="revision-prior-brief",
        revision=1, egress_policy=EgressPolicy.SHAREABLE, kind=MaterialKind.WEB,
    )
    revision = SourceRevision(
        owner_id=writes.owner_id, id=source.current_revision_id, source_id=source.id,
        content="Synthetic public source excerpt", locator=source.locator,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    source_receipt = writes.capture_source(source, revision, idempotency_key="prior-brief-source")
    evidence = writes.capture_evidence(
        claim.id, source_receipt.content_chunk_ids[0], egress_policy=EgressPolicy.SHAREABLE,
        idempotency_key="prior-brief-evidence",
    )
    imported_sections = [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)]
    imported_sections[3]["evidence_ids"] = [evidence.target_id]
    arguments = {
        "idea_id": idea.id, "expected_revision": 1, "sections": imported_sections,
        "origin": "prior_research_import", "egress_policy": "shareable",
        "idempotency_key": "prior-brief-import",
    }
    save_started = datetime.now(timezone.utc)

    receipt = surface.call("save_idea_brief", arguments, owner_id=writes.owner_id)
    replay = surface.call("save_idea_brief", arguments, owner_id=writes.owner_id)
    saved = writes.get_idea_brief(receipt.target_id)

    assert saved is not None
    assert saved.origin == "prior_research_import"
    assert saved.research_run_ids == ()
    assert saved.sections[3].evidence_ids == (evidence.target_id,)
    assert saved.created_at >= save_started
    assert replay.target_id == receipt.target_id and replay.replayed
    assert writes.get_idea_brief(original.target_id).origin is None

    append_arguments = {
        "idea_id": idea.id, "expected_revision": 2,
        "finding": "A new unverified finding.", "source_url": "https://example.test/new-finding",
        "idempotency_key": "prior-brief-append",
    }
    appended = surface.call("append_research_finding", append_arguments, owner_id=writes.owner_id)
    append_replay = surface.call("append_research_finding", append_arguments, owner_id=writes.owner_id)
    draft = writes.get_idea_brief(appended.target_id)

    assert draft is not None and draft.origin is None and draft.research_run_ids == ()
    assert all(not section.content and not section.evidence_ids for section in draft.sections)
    assert append_replay.target_id == appended.target_id and append_replay.replayed
    assert writes.get_idea_brief(receipt.target_id) == saved


def test_prior_research_brief_rejects_missing_or_nonpublic_evidence_without_revision():
    writes = InMemoryGraphWriteService("owner-prior-brief-reject")
    idea = Idea(owner_id=writes.owner_id, id="idea-prior-reject", title="Synthetic idea",
                 egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(idea, idempotency_key="idea-prior-reject-seed")
    surface = McpWriteSurface(writes)
    sections = [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)]
    original = surface.call("save_idea_brief", {
        "idea_id": idea.id, "expected_revision": 0, "sections": sections,
        "idempotency_key": "prior-reject-draft",
    }, owner_id=writes.owner_id)
    claim = Claim(owner_id=writes.owner_id, id="claim-prior-reject", text="Synthetic claim",
                  egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(claim, idempotency_key="claim-prior-reject-seed")
    source = Source(
        owner_id=writes.owner_id, id="source-prior-reject", title="Synthetic public source",
        locator="https://example.test/prior-reject", current_revision_id="revision-prior-reject",
        revision=1, egress_policy=EgressPolicy.SHAREABLE, kind=MaterialKind.WEB,
    )
    revision = SourceRevision(
        owner_id=writes.owner_id, id=source.current_revision_id, source_id=source.id,
        content="Synthetic public source excerpt", locator=source.locator,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    source_receipt = writes.capture_source(source, revision, idempotency_key="prior-reject-source")
    private_evidence = writes.capture_evidence(
        claim.id, source_receipt.content_chunk_ids[0], egress_policy=EgressPolicy.LOCAL_ONLY,
        idempotency_key="prior-reject-evidence",
    )
    no_evidence = [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)]
    nonpublic_evidence = [{"index": index, "content": f"Synthetic section {index}"} for index in range(8)]
    nonpublic_evidence[3]["evidence_ids"] = [private_evidence.target_id]

    for content, policy, key in (
        (no_evidence, "shareable", "prior-reject-empty"),
        (nonpublic_evidence, "shareable", "prior-reject-private-evidence"),
        (nonpublic_evidence, "local_only", "prior-reject-private-brief"),
    ):
        with pytest.raises(McpWriteError):
            surface.call("save_idea_brief", {
                "idea_id": idea.id, "expected_revision": 1, "sections": content,
                "origin": "prior_research_import", "egress_policy": policy,
                "idempotency_key": key,
            }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief(idea.id) == writes.get_idea_brief(original.target_id)


def test_memory_store_rejects_unverified_prior_origin_even_without_mcp():
    writes = InMemoryGraphWriteService("owner-prior-direct")
    idea = Idea(owner_id=writes.owner_id, id="idea-prior-direct", title="Synthetic idea",
                 egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(idea, idempotency_key="idea-prior-direct-seed")
    writer = McpWriteSurface(writes)
    saved = writer.call("save_idea_brief", {
        "idea_id": idea.id, "expected_revision": 0,
        "sections": [{"index": index, "content": f"Synthetic {index}"} for index in range(8)],
        "idempotency_key": "prior-direct-draft",
    }, owner_id=writes.owner_id)
    original = writes.get_idea_brief(saved.target_id)
    imported = original.revise(origin="prior_research_import", egress_policy="shareable")

    with pytest.raises(GraphWriteError, match="current Evidence citations"):
        writes.save_idea_brief(imported, expected_latest_revision=1, idempotency_key="prior-direct-import")

    assert writes.get_latest_idea_brief(idea.id) == original
