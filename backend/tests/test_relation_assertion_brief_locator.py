from __future__ import annotations

from dataclasses import fields, replace
import json

import pytest

from dots.founder_graph import DomainValidationError, EgressPolicy
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_read import _decode_assertion
from dots.founder_graph_mcp import McpReadSurface
from dots.founder_graph_read import GraphReadService
from test_founder_graph_relation_assertion_write import _setup


def _with_quote(assertion, markdown: str, quote: str, revision: int):
    start = markdown.index(quote)
    return replace(
        assertion,
        based_on_brief_revision=revision,
        based_on_brief_quote_start=start,
        based_on_brief_quote_end=start + len(quote),
    ), start


def test_relation_assertion_stores_unicode_quote_offsets_without_quote_text() -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()
    markdown = "## 事業概要\n\n創業支援の構想を記録する"
    quote = "創業支援の構想"
    located, quote_start = _with_quote(assertion, markdown, quote, revision=1)
    quote_end = quote_start + len(quote)

    payload = json.loads(_node_properties(located)["payload_json"])

    assert payload["based_on_brief_id"] == "brief-relation"
    assert payload["based_on_brief_section_index"] == 1
    assert payload["based_on_brief_revision"] == 1
    assert payload["based_on_brief_quote_start"] == quote_start
    assert payload["based_on_brief_quote_end"] == quote_end
    assert not {"quote", "support_quote", "excerpt"}.intersection(payload)
    assert not {"quote", "support_quote", "excerpt"}.intersection(
        field.name for field in fields(located)
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"based_on_brief_quote_start": 1},
        {"based_on_brief_quote_start": True, "based_on_brief_quote_end": 3},
        {"based_on_brief_quote_start": -1, "based_on_brief_quote_end": 3},
        {"based_on_brief_quote_start": 3, "based_on_brief_quote_end": 3},
        {"based_on_brief_revision": True},
        {"based_on_brief_revision": 0},
    ],
)
def test_relation_assertion_rejects_malformed_brief_locators(changes: dict[str, object]) -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()

    with pytest.raises(DomainValidationError):
        replace(assertion, **changes)


def test_section_locator_can_include_revision_without_quote_offsets() -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()

    located = replace(assertion, based_on_brief_revision=1)

    assert located.based_on_brief_revision == 1
    assert located.based_on_brief_quote_start is None
    assert located.based_on_brief_quote_end is None


def test_old_relation_assertion_payloads_decode_without_locator_fields() -> None:
    _writes, _idea, _claim, _evidence, _brief, assertion = _setup()
    payload = json.loads(_node_properties(assertion)["payload_json"])
    for field_name in (
        "based_on_brief_revision",
        "based_on_brief_quote_start",
        "based_on_brief_quote_end",
    ):
        payload.pop(field_name, None)
    encoded = json.dumps(payload, ensure_ascii=False)
    read_row = {
        "assertion_payload_json": encoded,
        "assertion_id": assertion.id,
        "assertion_owner_id": assertion.owner_id,
        "assertion_node_type": "relation_assertion",
        "assertion_revision": assertion.revision,
        "assertion_status": assertion.status.value,
        "assertion_egress_policy": assertion.egress_policy.value,
    }
    write_record = {
        "id": assertion.id,
        "owner_id": assertion.owner_id,
        "node_type": "relation_assertion",
        "revision": assertion.revision,
        "status": assertion.status.value,
        "assertion_family_id": assertion.assertion_family_id,
        "supersedes_id": assertion.supersedes_id,
        "payload_json": encoded,
    }

    read_decoded = _decode_assertion(read_row, owner_id=assertion.owner_id)
    write_decoded = Neo4jGraphGateway(object(), assertion.owner_id)._decode_relation_assertion_record(write_record)

    for decoded in (read_decoded, write_decoded):
        assert decoded.id == assertion.id
        assert decoded.based_on_brief_id == assertion.based_on_brief_id
        assert decoded.based_on_brief_section_index == assertion.based_on_brief_section_index
        assert decoded.based_on_brief_revision is None
        assert decoded.based_on_brief_quote_start is None
        assert decoded.based_on_brief_quote_end is None


def test_memory_search_projects_quote_from_current_shareable_brief_only() -> None:
    writes, _idea, claim, _evidence, brief, assertion = _setup()
    quote = "創業支援の構想"
    markdown = brief.report_markdown.replace("Markdown section 1", quote)
    located, quote_start = _with_quote(assertion, markdown, quote, revision=brief.revision)
    writes.save_relation_assertion(
        located, expected_family_revision=None, idempotency_key="save-brief-quote-locator",
    )
    writes._idea_briefs[brief.id] = replace(brief, report_markdown=markdown)

    reads = GraphReadService(writes)
    hit = next(item for item in reads.search("Synthetic target", owner_id=writes.owner_id).hits if item.node.id == claim.id)
    step = hit.relation_path[0]
    assert step.based_on_brief_revision == brief.revision
    assert (step.based_on_brief_quote_start, step.based_on_brief_quote_end) == (
        quote_start, quote_start + len(quote),
    )
    assert step.support_quote == quote

    response = McpReadSurface(reads).call("search", {"query": "Synthetic target"}, owner_id=writes.owner_id)
    projected = next(item for item in response["results"] if item["id"] == claim.id)["semantic_relation_path"][0]
    assert projected["based_on_brief_revision"] == brief.revision
    assert projected["based_on_brief_quote_start"] == quote_start
    assert projected["based_on_brief_quote_end"] == quote_start + len(quote)
    assert projected["support_quote"] == quote
    assert "report_markdown" not in projected
    fetched = McpReadSurface(reads).call("fetch", {"id": located.id}, owner_id=writes.owner_id)
    assert fetched["based_on_brief_revision"] == brief.revision
    assert fetched["based_on_brief_quote_start"] == quote_start
    assert fetched["based_on_brief_quote_end"] == quote_start + len(quote)
    assert fetched["support_quote"] == quote


def test_memory_search_keeps_legacy_and_section_only_reads_without_inventing_quotes() -> None:
    for revision in (None, 1):
        writes, _idea, claim, _evidence, _brief, assertion = _setup()
        located = replace(assertion, based_on_brief_revision=revision)
        writes.save_relation_assertion(
            located, expected_family_revision=None, idempotency_key=f"save-section-locator-{revision}",
        )
        reads = GraphReadService(writes)

        hit = next(
            item for item in reads.search("Synthetic target", owner_id=writes.owner_id).hits
            if item.node.id == claim.id
        )
        step = hit.relation_path[0]
        assert step.based_on_brief_revision == revision
        assert step.support_quote is None
        response = McpReadSurface(reads).call(
            "search", {"query": "Synthetic target"}, owner_id=writes.owner_id,
        )
        semantic = next(item for item in response["results"] if item["id"] == claim.id)["semantic_relation_path"][0]
        assert "support_quote" not in semantic
        assert "based_on_brief_quote_start" not in semantic
        assert "based_on_brief_quote_end" not in semantic


@pytest.mark.parametrize(
    ("brief_change", "assertion_revision"),
    [
        ({"egress_policy": EgressPolicy.LOCAL_ONLY}, 1),
        ({"owner_id": "other-owner"}, 1),
        ({"based_on_idea_id": "other-idea"}, 1),
        ({}, 2),
    ],
)
def test_memory_search_hides_revisioned_locator_for_noncurrent_brief(
    brief_change: dict[str, object], assertion_revision: int,
) -> None:
    writes, _idea, claim, _evidence, brief, assertion = _setup()
    quote = "Markdown section 1"
    located, quote_start = _with_quote(assertion, brief.report_markdown, quote, revision=assertion_revision)
    writes.save_relation_assertion(
        located, expected_family_revision=None, idempotency_key=f"save-unsafe-brief-{assertion_revision}",
    )
    writes._idea_briefs[brief.id] = replace(brief, **brief_change)

    hit = next(
        item for item in GraphReadService(writes).search("Synthetic target", owner_id=writes.owner_id).hits
        if item.node.id == claim.id
    )

    assert all(step.relation_assertion_id != located.id for step in hit.relation_path)
