from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from dots.founder_graph_campaign_read import (
    CampaignComparisonInputError,
    load_campaign_comparison,
)
from dots.founder_graph_read import GraphReadNotFoundError, GraphReadTimeoutError, NodeView, SearchHit, SearchPage


@dataclass
class FakeReadPort:
    nodes: dict[str, NodeView]
    search_hits: tuple[SearchHit, ...]
    owner_id: str = "owner-a"
    fetch_calls: list[str] | None = None

    def __post_init__(self) -> None:
        self.fetch_calls = []

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        assert owner_id == self.owner_id
        self.fetch_calls.append(node_id)
        node = self.nodes.get(node_id)
        if node is None:
            raise GraphReadNotFoundError("node was not found")
        return node

    def search(self, query: str, *, owner_id: str, limit: int = 20, cursor: str | None = None, timeout_ms: int = 1000) -> SearchPage:
        assert query == "campaign-1"
        assert owner_id == self.owner_id
        assert limit == 50
        return SearchPage(self.search_hits, None)


def node(node_id: str, node_type: str, fields: dict[str, Any], *, owner_id: str = "owner-a") -> NodeView:
    return NodeView(node_id, node_type, owner_id, node_id, node_id, "active", 0, fields)


def report(node_id: str, *, owner_id: str = "owner-a") -> NodeView:
    return node(
        node_id,
        "report_version",
        {"status": "final", "sections": [{"id": 0, "content": "summary"}], "run_ids": ["run-1"]},
        owner_id=owner_id,
    )


def test_load_campaign_comparison_is_bounded_and_safe() -> None:
    campaign = node("campaign-1", "research_campaign", {"purpose": "検証", "status": "approved", "trial_budget": 2})
    run = node("run-1", "research_run", {"campaign_id": "campaign-1", "status": "completed", "model_snapshot": "luna@v1", "input_snapshot": {"secret": "drop"}})
    duplicate = node("run-1", "research_run", {"campaign_id": "campaign-1", "status": "duplicate", "model_snapshot": "drop"})
    unrelated = node("run-2", "research_run", {"campaign_id": "campaign-2", "status": "wrong"})
    port = FakeReadPort({"campaign-1": campaign, "report-1": report("report-1"), "report-2": report("report-2")}, tuple(SearchHit(item, 1.0) for item in (run, duplicate, unrelated)))

    result = load_campaign_comparison(port, "campaign-1", owner_id="owner-a", previous_report_id="report-1", current_report_id="report-2", limit=50)

    assert result.campaign == {"id": "campaign-1", "purpose": "検証", "status": "approved", "trial_budget": "2"}
    assert result.runs == ({"id": "run-1", "status": "completed", "model_snapshot": "luna@v1"},)
    assert result.previous_report.id == "report-1"
    assert result.current_report.id == "report-2"
    assert port.fetch_calls == ["campaign-1", "report-1", "report-2"]
    assert "secret" not in str(result.as_dict())


def test_owner_and_bounds_fail_before_read() -> None:
    port = FakeReadPort({}, ())
    with pytest.raises(CampaignComparisonInputError, match="owner_id"):
        load_campaign_comparison(port, "campaign-1", owner_id="owner-b")
    with pytest.raises(CampaignComparisonInputError, match="limit"):
        load_campaign_comparison(port, "campaign-1", owner_id="owner-a", limit=51)
    assert port.fetch_calls == []


def test_read_errors_propagate_without_partial_projection() -> None:
    class StoppedPort(FakeReadPort):
        def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
            raise GraphReadTimeoutError("timed out")

    with pytest.raises(GraphReadTimeoutError):
        load_campaign_comparison(StoppedPort({}, ()), "campaign-1", owner_id="owner-a")
