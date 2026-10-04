from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from nebula.founder_graph import Claim, EgressPolicy, Idea, MaterialKind, Source, SourceRevision
from nebula.founder_graph_mcp import McpReadSurface
from nebula.founder_graph_candidate_job_processor import CandidateManifestConflictError
from nebula.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from nebula.founder_graph_job_store import FounderGraphJobStore
from nebula.founder_graph_read import GraphReadService
from nebula.founder_graph_write import GraphWriteError, InMemoryGraphWriteService
from nebula.idea_brief import SECTION_TITLES, IdeaBriefSection, IdeaBriefVersion


class _CandidateProcessorStub:
    def __init__(self, *, raises: bool = False, state: str = "failed", error_code: str | None = None) -> None:
        self.raises = raises
        self.state = state
        self.error_code = error_code
        self.calls: list[tuple[str, object]] = []

    def process_specific(self, job_id: str, *, raw_manifest: object) -> object:
        self.calls.append((job_id, raw_manifest))
        if self.raises:
            raise CandidateManifestConflictError() if self.error_code == "candidate_manifest_conflict" else RuntimeError("synthetic processor failure")
        error_code = "candidate_rejected" if self.state == "failed" else None
        return SimpleNamespace(state=self.state, last_error_code=error_code)


def _candidate_manifest(idea_id: str, target_id: str, quote: str) -> dict[str, object]:
    return {
        "version": 1, "idea_id": idea_id, "candidates": [{
            "source_id": idea_id, "target_id": target_id, "predicate": "RELATES_TO",
            "basis": "brief_hypothesis", "support": {"quote": quote}, "evidence_ids": [],
        }],
    }


def test_research_and_brief_tools_use_existing_memory_store_and_enforce_approval() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-research")
    writes.put_node(Idea(owner_id=writes.owner_id, id="idea-mcp", title="Synthetic idea", egress_policy=EgressPolicy.SHAREABLE), idempotency_key="idea-seed")
    processor = _CandidateProcessorStub()
    surface = McpWriteSurface(writes, candidate_processor=processor)
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
    sections = [{"index": index} for index in range(8)]
    sections[0]["evidence_ids"] = [evidence.target_id]
    researched_tool = tools["save_researched_idea_brief"]
    assert "report_markdown" in researched_tool["inputSchema"]["required"]
    assert "content" not in researched_tool["inputSchema"]["properties"]["sections"]["items"]["required"]
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
        "relation_candidate_manifest": _candidate_manifest("idea-mcp", claim.id, "Synthetic section 0."),
        "idempotency_key": "mcp-brief",
    }, owner_id=writes.owner_id)
    assert brief.candidate_processing == {"state": "failed", "error_code": "candidate_rejected"}
    assert processor.calls[0][0] == FounderGraphJobStore.job_id_for(writes.owner_id, brief.target_id)
    assert brief.target_type == "idea_brief_version"
    saved = writes.get_idea_brief(brief.target_id)
    assert saved is not None and saved.research_run_ids == (run.target_id,)
    assert all(not section.content for section in saved.sections)
    assert saved.origin is None
    assert saved.report_markdown == report_markdown
    fetched = McpReadSurface(GraphReadService(writes)).call(
        "fetch_idea_brief", {"idea_id": "idea-mcp"}, owner_id=writes.owner_id,
    )
    assert fetched["brief_id"] == brief.target_id
    assert fetched["report_markdown"] == report_markdown
    assert fetched["sections"][0]["content"] == "Synthetic section 0."
    assert fetched["sections"][0]["evidence_ids"] == [evidence.target_id]
    assert fetched["brief_citations"][0][0]["evidence_id"] == evidence.target_id
    assert fetched["report_projection"]["links"] == [{
        "url": "https://example.test/source?id=1#section",
        "label": None,
        "offset": report_markdown.index("https://example.test/source?id=1#section"),
        "section_index": 7,
        "verification_status": "url_only",
        "evidence_ids": [],
    }]
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
    processor = _CandidateProcessorStub()
    surface = McpWriteSurface(writes, candidate_processor=processor)
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
        "relation_candidate_manifest": _candidate_manifest(idea.id, "claim-append-stub", "The first synthetic finding."),
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
    assert first.candidate_processing == {"state": "failed", "error_code": "candidate_rejected"}
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


def test_markdown_only_research_draft_accepts_brief_hypothesis_without_evidence_or_section() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-markdown-hypothesis")
    idea = Idea(
        owner_id=writes.owner_id, id="idea-markdown-hypothesis", title="Synthetic idea",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    claim = Claim(
        owner_id=writes.owner_id, id="claim-markdown-hypothesis", text="Synthetic proposition",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    for node in (idea, claim):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    surface = McpWriteSurface(writes)
    saved = surface.call("append_research_finding", {
        "idea_id": idea.id, "expected_revision": 0,
        "finding": "A synthetic external observation for the draft.",
        "source_url": "https://example.test/finding",
        "egress_policy": "shareable", "idempotency_key": "append-markdown-hypothesis",
    }, owner_id=writes.owner_id)
    brief = writes.get_idea_brief(saved.target_id)
    assert brief is not None and brief.sections and all(not section.content for section in brief.sections)
    assert brief.report_markdown and "A synthetic external observation" in brief.report_markdown

    relation = surface.call("link_entities", {
        "source_id": idea.id, "target_id": claim.id, "relation": "ADDRESSES",
        "basis": "brief_hypothesis", "status": "proposed", "egress_policy": "shareable",
        "based_on_brief_id": brief.id, "idempotency_key": "link-markdown-hypothesis",
    }, owner_id=writes.owner_id)

    assertion = writes.get_node(relation.target_id)
    assert assertion.status.value == "proposed"
    assert assertion.basis.value == "brief_hypothesis"
    assert assertion.based_on_brief_id == brief.id
    assert assertion.based_on_brief_section_index is None
    assert assertion.evidence_ids == ()


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
    processor = _CandidateProcessorStub()
    surface = McpWriteSurface(writes, candidate_processor=processor)
    args = {
        "idea_id": "idea-brief", "expected_revision": 0,
        "sections": [{"index": 0, "content": "A bounded synthetic note"}],
        "report_markdown": "## 概要\n\n| 対象 | 課題 |\n| --- | --- |\n| 店舗 | 発注 |",
        "relation_candidate_manifest": _candidate_manifest("idea-brief", "claim-brief-stub", "A bounded synthetic note"),
        "idempotency_key": "regular-brief",
    }
    first = surface.call("save_idea_brief", args, owner_id=writes.owner_id)
    replay = surface.call("save_idea_brief", args, owner_id=writes.owner_id)
    assert first.target_type == "idea_brief_version"
    assert first.candidate_processing == {"state": "failed", "error_code": "candidate_rejected"}
    assert replay.target_id == first.target_id
    assert replay.replayed is True
    assert writes.get_idea_brief(first.target_id).report_markdown == args["report_markdown"]
    with pytest.raises(McpWriteError) as changed:
        surface.call("save_idea_brief", {**args, "report_markdown": "## 別の本文"}, owner_id=writes.owner_id)
    assert changed.value.code == "idempotency_conflict"
    save_brief = next(item for item in surface.tool_definitions() if item["name"] == "save_idea_brief")
    assert save_brief["inputSchema"]["properties"]["origin"]["enum"] == ["prior_research_import"]
    assert save_brief["inputSchema"]["properties"]["report_markdown"]["maxLength"] == 60000


@pytest.mark.parametrize("send_empty_content", (False, True), ids=("content-omitted", "content-empty"))
def test_regular_idea_brief_accepts_markdown_only_h1_draft_with_candidate_manifest(send_empty_content: bool) -> None:
    writes = InMemoryGraphWriteService("owner-mcp-markdown-only-brief")
    idea = Idea(
        owner_id=writes.owner_id, id="idea-markdown-only-brief", title="Synthetic idea",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(idea, idempotency_key="markdown-only-brief-idea")
    processor = _CandidateProcessorStub()
    surface = McpWriteSurface(writes, candidate_processor=processor)
    report_markdown = "\n\n".join(
        f"# {title}\n\nSynthetic chapter {index}."
        for index, title in enumerate(SECTION_TITLES)
    )
    sections = [
        {"index": index, **({"content": ""} if send_empty_content else {})}
        for index in range(8)
    ]
    arguments = {
        "idea_id": idea.id,
        "expected_revision": 0,
        "sections": sections,
        "report_markdown": report_markdown,
        "egress_policy": EgressPolicy.SHAREABLE.value,
        "relation_candidate_manifest": _candidate_manifest(idea.id, "claim-markdown-only", "Synthetic chapter 0."),
        "idempotency_key": f"markdown-only-brief-{send_empty_content}",
    }

    receipt = surface.call("save_idea_brief", arguments, owner_id=writes.owner_id)

    saved = writes.get_idea_brief(receipt.target_id)
    assert saved is not None and saved.report_markdown == report_markdown
    assert all(not section.content for section in saved.sections)
    assert receipt.candidate_processing == {"state": "failed", "error_code": "candidate_rejected"}
    assert processor.calls == [(
        FounderGraphJobStore.job_id_for(writes.owner_id, receipt.target_id),
        arguments["relation_candidate_manifest"],
    )]
    replay = surface.call("save_idea_brief", arguments, owner_id=writes.owner_id)
    assert replay.target_id == receipt.target_id and replay.replayed
    fetched = McpReadSurface(GraphReadService(writes)).call(
        "fetch_idea_brief", {"idea_id": idea.id}, owner_id=writes.owner_id,
    )
    assert [section["content"] for section in fetched["sections"]] == [
        f"Synthetic chapter {index}." for index in range(8)
    ]
    section_schema = next(
        item for item in surface.tool_definitions() if item["name"] == "save_idea_brief"
    )["inputSchema"]["properties"]["sections"]
    assert "content" not in section_schema["items"]["required"]


@pytest.mark.parametrize("section", ({"index": 0}, {"index": 0, "content": ""}), ids=("omitted", "empty"))
def test_regular_idea_brief_still_requires_content_for_first_draft_without_markdown(section: dict[str, object]) -> None:
    writes = InMemoryGraphWriteService("owner-mcp-empty-brief-rejected")
    idea = Idea(owner_id=writes.owner_id, id="idea-empty-brief-rejected", title="Synthetic idea")
    writes.put_node(idea, idempotency_key="empty-brief-rejected-idea")

    with pytest.raises(McpWriteError, match="at least one viewpoint needs content"):
        McpWriteSurface(writes).call("save_idea_brief", {
            "idea_id": idea.id,
            "expected_revision": 0,
            "sections": [section],
            "idempotency_key": f"empty-first-draft-{bool(section.get('content'))}",
        }, owner_id=writes.owner_id)

    assert writes.get_latest_idea_brief(idea.id) is None


def test_regular_idea_brief_allows_content_free_revision_when_previous_markdown_exists() -> None:
    writes = InMemoryGraphWriteService("owner-mcp-brief-metadata-only")
    idea = Idea(
        owner_id=writes.owner_id, id="idea-brief-metadata-only", title="Synthetic idea",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(idea, idempotency_key="brief-metadata-only-idea")
    surface = McpWriteSurface(writes)
    report_markdown = "\n\n".join(
        f"# {title}\n\nSynthetic chapter {index}."
        for index, title in enumerate(SECTION_TITLES)
    )
    original = surface.call("save_idea_brief", {
        "idea_id": idea.id, "expected_revision": 0,
        "sections": [{"index": 0, "content": "Old parallel body"}],
        "report_markdown": report_markdown,
        "egress_policy": EgressPolicy.SHAREABLE.value,
        "idempotency_key": "brief-metadata-only-original",
    }, owner_id=writes.owner_id)
    with pytest.raises(McpWriteError, match="report_markdown"):
        surface.call("save_idea_brief", {
            "idea_id": idea.id,
            "expected_revision": 1,
            "sections": [{"index": 0}],
            "report_markdown": "   ",
            "idempotency_key": "brief-metadata-only-empty-markdown",
        }, owner_id=writes.owner_id)
    assert writes.get_latest_idea_brief(idea.id).id == original.target_id

    update_args = {
        "idea_id": idea.id,
        "expected_revision": 1,
        "sections": [{"index": 0, "facts": ["fact-metadata-only"]}],
        "egress_policy": EgressPolicy.SHAREABLE.value,
        "idempotency_key": "brief-metadata-only-update",
    }
    updated = surface.call("save_idea_brief", update_args, owner_id=writes.owner_id)
    replay = surface.call("save_idea_brief", update_args, owner_id=writes.owner_id)

    latest = writes.get_latest_idea_brief(idea.id)
    assert latest is not None and latest.id == updated.target_id
    assert latest.report_markdown == report_markdown
    assert latest.sections[0].content == "" and latest.sections[0].facts == ("fact-metadata-only",)
    assert writes.get_idea_brief(original.target_id).sections[0].content == "Old parallel body"
    assert replay.target_id == updated.target_id and replay.replayed
    fetched = McpReadSurface(GraphReadService(writes)).call(
        "fetch_idea_brief", {"idea_id": idea.id}, owner_id=writes.owner_id,
    )
    assert [section["content"] for section in fetched["sections"]] == [
        f"Synthetic chapter {index}." for index in range(8)
    ]


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


def test_all_brief_save_tools_expose_optional_bounded_candidate_manifest():
    writes = InMemoryGraphWriteService("owner-mcp-candidate-schema")
    surface = McpWriteSurface(writes)
    tools = {tool["name"]: tool for tool in surface.tool_definitions()}
    manifest_names = {"save_idea_brief", "append_research_finding", "save_researched_idea_brief"}

    for tool_name in manifest_names:
        schema = tools[tool_name]["inputSchema"]
        manifest = schema["properties"]["relation_candidate_manifest"]
        assert "candidate_processing" in tools[tool_name]["outputSchema"]["required"]
        assert manifest["type"] == "object" and "relation_candidate_manifest" not in schema["required"]
        assert manifest["additionalProperties"] is False
        assert manifest["properties"]["version"]["const"] == 1
        assert manifest["properties"]["idea_id"]["maxLength"] == 200
        assert manifest["properties"]["candidates"]["minItems"] == 0
        assert manifest["properties"]["candidates"]["maxItems"] == 64
        description = tools[tool_name]["description"]
        assert "同じ保存呼出し" in description and "本文保存後にNebula" in description
        assert "candidate_processing.state" in description
        assert "candidates: []" in description
        assert "調査前の下書きも" in description
        assert "link_entities" not in description and "classify_entity" not in description

    support_schema = tools["save_idea_brief"]["inputSchema"]["properties"][
        "relation_candidate_manifest"
    ]["properties"]["candidates"]["items"]["properties"]["support"]
    assert len(support_schema["oneOf"]) == 2
    quote_schema = support_schema["oneOf"][0]["properties"]["quote"]
    assert quote_schema["maxLength"] == 1200
    assert support_schema["oneOf"][1]["properties"]["section_index"]["maximum"] == 7


def test_markdown_brief_tools_document_heading_levels_and_text_edit_contract():
    writes = InMemoryGraphWriteService("owner-mcp-markdown-heading-contract")
    tools = {tool["name"]: tool for tool in McpWriteSurface(writes).tool_definitions()}

    for tool_name in ("save_idea_brief", "save_researched_idea_brief"):
        tool = tools[tool_name]
        description = tool["description"]
        report_description = tool["inputSchema"]["properties"]["report_markdown"]["description"]
        section_description = tool["inputSchema"]["properties"]["sections"]["items"]["properties"]["content"]["description"]
        for text in (description, report_description):
            assert "H1（例: `# エグゼクティブサマリー`）" in text
            assert "H2（例: `## エグゼクティブサマリー`）" in text
            assert "sections[].contentだけでは既存Markdownの章本文は編集されません" in text
        assert "sections[].contentだけでは既存Markdownの章本文は編集されません" in section_description
        assert "H3以上" in description
        if tool_name == "save_idea_brief":
            assert "Markdownなしの初回下書きでは少なくとも一観点の本文が必要" in description
            assert "Markdownなしの初回下書きでは少なくとも一観点の本文が必要" in section_description


@pytest.mark.parametrize("tool_name,base_args", [
    ("save_idea_brief", {
        "expected_revision": 0, "sections": [{"index": 0, "content": "A short note"}],
        "idempotency_key": "candidate-mismatch-brief",
    }),
    ("append_research_finding", {
        "expected_revision": 0, "finding": "A short finding.",
        "source_url": "https://example.test/source", "idempotency_key": "candidate-mismatch-append",
    }),
    ("save_researched_idea_brief", {
        "expected_revision": 0, "sections": [{"index": index} for index in range(8)],
        "research_run_ids": ["run-placeholder"], "report_markdown": "## A report\n\nA body.",
        "idempotency_key": "candidate-mismatch-researched",
    }),
])
def test_brief_save_tools_reject_wrong_idea_and_oversized_candidate_manifests(tool_name, base_args):
    writes = InMemoryGraphWriteService(f"owner-mcp-candidate-{tool_name}")
    idea = Idea(owner_id=writes.owner_id, id="idea-candidate-entry", title="Synthetic idea")
    writes.put_node(idea, idempotency_key=f"seed-{tool_name}")
    surface = McpWriteSurface(writes)
    arguments = {"idea_id": idea.id, **base_args}

    for manifest, expected_message in (
        ({"version": 1, "idea_id": "another-idea", "candidates": [{}]}, "idea_id"),
        ({"version": 1, "idea_id": idea.id, "candidates": [{}], "extra": True}, "fields"),
        ({"version": True, "idea_id": idea.id, "candidates": [{}]}, "version"),
        ({"version": 1, "idea_id": idea.id, "candidates": [{"support": {"quote": "x" * 70_000}}]}, "64 KiB"),
        ({"version": 1, "idea_id": idea.id, "candidates": [{} for _ in range(65)]}, "64"),
    ):
        with pytest.raises(McpWriteError, match=expected_message):
            surface.call(
                tool_name,
                {**arguments, "relation_candidate_manifest": manifest},
                owner_id=writes.owner_id,
            )
    assert writes.get_latest_idea_brief(idea.id) is None


def test_candidate_review_distinguishes_omitted_empty_and_processor_failure():
    writes = InMemoryGraphWriteService("owner-mcp-candidate-omitted")
    idea = Idea(owner_id=writes.owner_id, id="idea-candidate-omitted", title="Synthetic idea")
    writes.put_node(idea, idempotency_key="candidate-omitted-idea")
    processor = _CandidateProcessorStub(state="pending")
    surface = McpWriteSurface(writes, candidate_processor=processor)

    def save(revision: int, key: str, note: str, manifest: dict[str, object] | None = None):
        args = {
            "idea_id": idea.id, "expected_revision": revision,
            "sections": [{"index": 0, "content": note}],
            "report_markdown": f"## 概要\n\n{note}", "idempotency_key": key,
        }
        if manifest is not None:
            args["relation_candidate_manifest"] = manifest
        return surface.call("save_idea_brief", args, owner_id=writes.owner_id)

    result = save(0, "candidate-omitted-brief", "Not reviewed for relations.")

    assert result.candidate_processing == {"state": "pending", "error_code": None}
    assert writes.get_idea_brief(result.target_id) is not None
    assert processor.calls[0] == (FounderGraphJobStore.job_id_for(writes.owner_id, result.target_id), None)

    processor.state = "succeeded"
    empty_manifest = {"version": 1, "idea_id": idea.id, "candidates": []}
    reviewed = save(1, "candidate-empty-brief", "No relations proposed.", empty_manifest)
    assert reviewed.candidate_processing == {"state": "succeeded", "error_code": None}
    assert processor.calls[1][1] == empty_manifest

    processor.state = "failed"
    invalid_manifest = {"version": 1, "idea_id": idea.id, "candidates": [{
        "source_id": "missing-source", "target_id": "missing-target",
        "predicate": "REQUIRES_CAPABILITY", "basis": "brief_hypothesis",
        "support": {"quote": "Not in the saved Brief"}, "evidence_ids": [],
    }]}
    failed = save(2, "candidate-processing-failed-brief", "Saved despite invalid candidates.", invalid_manifest)
    assert failed.candidate_processing == {"state": "failed", "error_code": "candidate_rejected"}
    assert writes.get_idea_brief(failed.target_id).report_markdown == "## 概要\n\nSaved despite invalid candidates."
    assert processor.calls[2][1] == invalid_manifest

    processor.raises = True
    processor.error_code = None
    failed_processor = save(3, "candidate-processing-error-brief", "Saved despite processor error.", empty_manifest)
    assert failed_processor.candidate_processing == {"state": "unavailable", "error_code": "processing_unavailable"}
    assert writes.get_idea_brief(failed_processor.target_id) is not None

    processor.error_code = "candidate_manifest_conflict"
    conflict = save(4, "candidate-processing-conflict-brief", "Saved despite candidate conflict.", empty_manifest)
    assert conflict.candidate_processing == {
        "state": "unavailable", "error_code": "candidate_manifest_conflict",
    }
    assert writes.get_idea_brief(conflict.target_id) is not None
