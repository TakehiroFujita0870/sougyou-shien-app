from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pytest

from dots.founder_graph_read import (
    GraphReadTimeoutError,
    GraphReadUnavailableError,
    NodeView,
    SearchHit,
    SearchPage,
)
from dots.founder_graph_export import (
    FounderGraphExportError,
    FounderGraphExportLimitError,
    FounderGraphExportTooLargeError,
    build_safe_export,
)


def _view(node_id: str, node_type: str = "idea", *, title: str = "Idea", **fields: Any) -> NodeView:
    values = {"egress_policy": "shareable", "title": title, **fields}
    return NodeView(
        id=node_id,
        node_type=node_type,
        owner_id="owner-a",
        title=title,
        snippet=title,
        status="active",
        revision=0,
        fields=MappingProxyType(values),
    )


def test_safe_export_filters_owner_private_policy_and_instruction_path() -> None:
    result = build_safe_export(
        [
            {
                "id": "z-idea",
                "kind": "idea",
                "owner_id": "owner-a",
                "egress_policy": "shareable",
                "provenance_ids": ["prov-z", "prov-z"],
                "provenance": {"id": "prov-z", "idempotency_key": "secret-idempotency"},
                "fields": {
                    "title": "Z idea",
                    "summary": "safe summary",
                    "source_text": "private conversation",
                    "private_notes": "private note",
                    "tags": ["z"],
                    "metadata": {"path": "should not be copied"},
                },
            },
            {
                "id": "a-instruction",
                "kind": "instruction_artifact",
                "owner_id": "owner-a",
                "fields": {
                    "content_hash": "hash-a",
                    "path": "C:/private/AGENTS.md",
                    "instruction_path": "C:/private/SKILL.md",
                    "status": "active",
                },
                "provenance_ids": ["prov-a"],
            },
            {
                "id": "local-person",
                "kind": "person",
                "owner_id": "owner-a",
                "egress_policy": "local_only",
                "fields": {"name": "Local", "contact": {"email": "local@example.test"}},
            },
            {
                "id": "other-owner",
                "kind": "idea",
                "owner_id": "owner-b",
                "fields": {"title": "Other owner"},
            },
        ],
        owner_id="owner-a",
    )

    payload = result.as_dict()
    assert [node["id"] for node in payload["nodes"]] == ["z-idea", "a-instruction"]
    assert payload["schema_version"] == "founder-graph-export-v1"
    assert payload["provenance_ids"] == ["prov-a", "prov-z"]
    assert payload["nodes"][0]["fields"] == {"summary": "safe summary", "tags": ["z"], "title": "Z idea"}
    assert payload["nodes"][1]["fields"] == {"content_hash": "hash-a", "status": "active"}
    serialized = result.json_text + result.markdown
    for forbidden in (
        "owner-b",
        "local@example.test",
        "source_text",
        "private_notes",
        "instruction_path",
        "C:/private/AGENTS.md",
        "secret-idempotency",
    ):
        assert forbidden not in serialized
    assert payload["omitted_count"] == 2


def test_safe_export_is_stable_and_preserves_explicit_provenance_ids() -> None:
    nodes = [
        {"id": "b", "kind": "asset", "fields": {"name": "B", "status": "active"}, "provenance_ids": ["p2"]},
        {"id": "a", "kind": "asset", "fields": {"name": "A", "status": "active"}, "provenance_ids": ["p1"]},
    ]

    first = build_safe_export(nodes, owner_id="owner-a", provenance_ids=("p0",))
    second = build_safe_export(tuple(reversed(nodes)), owner_id="owner-a", provenance_ids=("p0",))

    assert first.json_text == second.json_text
    assert first.markdown == second.markdown
    assert [node["id"] for node in first.as_dict()["nodes"]] == ["a", "b"]
    assert first.as_dict()["provenance_ids"] == ["p0", "p1", "p2"]


def test_safe_export_markdown_escapes_untrusted_display_values() -> None:
    result = build_safe_export(
        [{"id": "idea-1", "kind": "idea", "fields": {"title": "# [unsafe](https://example.test)\n<script>"}}],
        owner_id="owner-a",
    )

    assert "# [unsafe]" not in result.markdown
    assert "](https://example.test)" not in result.markdown
    assert "<script>" not in result.markdown
    assert "\\# \\[unsafe\\]" in result.markdown


@dataclass
class _ReadStub:
    page: SearchPage
    views: dict[str, NodeView]
    calls: list[dict[str, object]]
    failure: Exception | None = None

    @property
    def owner_id(self) -> str:
        return "owner-a"

    def search(
        self,
        query: str,
        *,
        owner_id: str,
        limit: int = 20,
        cursor: str | None = None,
        timeout_ms: int = 1_000,
    ) -> SearchPage:
        self.calls.append({"op": "search", "query": query, "owner_id": owner_id, "limit": limit, "cursor": cursor, "timeout_ms": timeout_ms})
        if self.failure is not None:
            raise self.failure
        return self.page

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        self.calls.append({"op": "fetch", "node_id": node_id, "owner_id": owner_id})
        if self.failure is not None:
            raise self.failure
        return self.views[node_id]


def test_graph_read_search_and_fetch_are_owner_scoped_and_bounded() -> None:
    one = _view("one", title="One")
    two = _view("two", title="Two")
    reads = _ReadStub(SearchPage((SearchHit(two, 0.5), SearchHit(one, 1.0)), "next"), {"one": one, "two": two}, [])

    searched = build_safe_export(reads, owner_id="owner-a", query="founder", limit=2, timeout_ms=250)
    fetched = build_safe_export(reads, owner_id="owner-a", node_ids=("two", "one"), limit=2)

    assert [node["id"] for node in searched.as_dict()["nodes"]] == ["one", "two"]
    assert searched.as_dict()["next_cursor"] == "next"
    assert [node["id"] for node in fetched.as_dict()["nodes"]] == ["one", "two"]
    assert reads.calls == [
        {"op": "search", "query": "founder", "owner_id": "owner-a", "limit": 2, "cursor": None, "timeout_ms": 250},
        {"op": "fetch", "node_id": "two", "owner_id": "owner-a"},
        {"op": "fetch", "node_id": "one", "owner_id": "owner-a"},
    ]


@pytest.mark.parametrize("failure", [GraphReadUnavailableError("stopped"), GraphReadTimeoutError("timed out")])
def test_graph_read_failures_are_propagated_without_partial_export(failure: Exception) -> None:
    reads = _ReadStub(SearchPage((), None), {}, [], failure=failure)

    with pytest.raises(type(failure), match=str(failure)):
        build_safe_export(reads, owner_id="owner-a", query="founder")


def test_export_rejects_owner_mismatch_limits_and_size_before_output() -> None:
    reads = _ReadStub(SearchPage((), None), {}, [])

    with pytest.raises(FounderGraphExportError, match="owner_id"):
        build_safe_export(reads, owner_id="owner-b", query="founder")
    with pytest.raises(FounderGraphExportLimitError, match="limit"):
        build_safe_export([], owner_id="owner-a", limit=0)
    with pytest.raises(FounderGraphExportLimitError, match="node_ids"):
        build_safe_export(reads, owner_id="owner-a", node_ids=("a", "b"), limit=1)
    with pytest.raises(FounderGraphExportTooLargeError, match="max_bytes"):
        build_safe_export(
            [{"id": "idea-1", "kind": "idea", "fields": {"title": "A" * 100}}],
            owner_id="owner-a",
            max_bytes=10,
        )


def test_node_view_and_search_hit_are_accepted_as_safe_inputs() -> None:
    result = build_safe_export(
        [
            SearchHit(
                _view("idea-1", title="Safe", source_text="private source"),
                1.0,
                ("idea-1", "REUSES", "asset-1"),
            )
        ],
        owner_id="owner-a",
    )

    assert result.as_dict()["nodes"][0]["id"] == "idea-1"
    assert "relation_path" not in result.as_dict()["nodes"][0]
    assert "private source" not in result.json_text
