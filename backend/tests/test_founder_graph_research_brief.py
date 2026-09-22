from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import pytest

from dots.founder_graph_read import (
    GraphReadError,
    GraphReadTimeoutError,
    GraphReadUnavailableError,
    NodeView,
    SearchHit,
    SearchPage,
)
from dots.founder_graph_research_brief import build_research_brief


@dataclass
class _ReadStub:
    page: SearchPage
    calls: list[dict[str, object]]

    @property
    def owner_id(self) -> str:
        return "owner-1"

    def search(self, query: str, *, owner_id: str, limit: int = 20, cursor: str | None = None, timeout_ms: int = 1_000) -> SearchPage:
        self.calls.append({"query": query, "owner_id": owner_id, "limit": limit, "cursor": cursor, "timeout_ms": timeout_ms})
        return self.page

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        raise AssertionError("ResearchBrief must use the bounded search contract only")


def _view(node_id: str, node_type: str, title: str, *, policy: str, **fields: object) -> NodeView:
    values = {"egress_policy": policy, "title": title, **fields}
    return NodeView(
        id=node_id,
        node_type=node_type,
        owner_id="owner-1",
        title=title,
        snippet=title,
        status="active",
        revision=0,
        fields=MappingProxyType(values),
    )


def test_build_research_brief_combines_safe_ideas_assets_and_sources() -> None:
    page = SearchPage(
        hits=(
            SearchHit(
                _view(
                    "idea-1",
                    "idea",
                    "Founder Graph",
                    policy="shareable",
                    summary="A graph for founder decisions",
                    source_text="private conversation text",
                ),
                1.0,
                ("idea-1", "REUSES", "asset-1"),
            ),
            SearchHit(
                _view("asset-1", "asset", "Graph knowledge", policy="shareable", description="Reusable knowledge"),
                0.8,
            ),
            SearchHit(
                _view("source-1", "source", "Public source", policy="shareable", locator="https://example.test/source"),
                0.7,
            ),
            SearchHit(
                _view(
                    "idea-private",
                    "idea",
                    "Private idea",
                    policy="local_only",
                    source_text="must not leave the graph",
                ),
                0.9,
            ),
            SearchHit(
                _view(
                    "person-1",
                    "person",
                    "Private person",
                    policy="shareable",
                    contact={"email": "private@example.test"},
                    private_notes="private note",
                ),
                0.6,
            ),
        ),
        next_cursor="5",
    )
    reads = _ReadStub(page, [])

    brief = build_research_brief(reads, "founder graph", owner_id="owner-1", limit=50)

    assert [item.id for item in brief.items] == ["idea-1", "asset-1", "source-1"]
    assert [item.category for item in brief.items] == ["ideas", "assets", "sources"]
    assert brief.items[0].relation_path == ("idea-1", "REUSES", "asset-1")
    assert brief.items[0].canonical_url == "dots://node/idea-1"
    assert brief.items[0].fields["summary"] == "A graph for founder decisions"
    assert "source_text" not in brief.items[0].fields
    assert brief.items[0].egress_policy == "shareable"
    assert brief.next_cursor == "5"
    assert brief.as_dict()["items"][0]["canonical_url"] == "dots://node/idea-1"
    assert "owner_id" not in brief.as_dict()

    assert reads.calls == [{"query": "founder graph", "owner_id": "owner-1", "limit": 50, "cursor": None, "timeout_ms": 1_000}]


def test_build_research_brief_preserves_safe_source_text_as_text_only() -> None:
    reads = _ReadStub(
        SearchPage(
            hits=(
                SearchHit(
                    _view(
                        "source-revision-1",
                        "source_revision",
                        "Revision",
                        policy="shareable",
                        content="A public excerpt",
                        source_id="source-1",
                    ),
                    0.5,
                ),
            ),
            next_cursor=None,
        ),
        [],
    )

    item = build_research_brief(reads, "public", owner_id="owner-1").items[0]

    assert item.category == "sources"
    assert item.fields["text"] == "A public excerpt"
    assert "content" not in item.fields


@pytest.mark.parametrize("failure", [GraphReadTimeoutError("bounded timeout"), GraphReadUnavailableError("stopped")])
def test_build_research_brief_propagates_recoverable_read_failure_without_partial_output(failure: Exception) -> None:
    class _Failure(_ReadStub):
        def search(self, *args, **kwargs):
            raise failure

    reads = _Failure(SearchPage((), None), [])

    with pytest.raises(type(failure), match=str(failure)):
        build_research_brief(reads, "founder", owner_id="owner-1")


@pytest.mark.parametrize("query", ["", "   "])
def test_build_research_brief_rejects_empty_query_before_read(query: str) -> None:
    reads = _ReadStub(SearchPage((), None), [])

    with pytest.raises(GraphReadError, match="query"):
        build_research_brief(reads, query, owner_id="owner-1")

    assert reads.calls == []
