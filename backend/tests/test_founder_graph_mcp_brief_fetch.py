from __future__ import annotations

import json

from fastapi.testclient import TestClient

from dots.founder_graph import EgressPolicy, Idea
from dots.founder_graph_mcp import McpReadSurface
from dots.founder_graph_mcp_stdio import FounderGraphStdioServer
from dots.founder_graph_mcp_write import McpWriteSurface
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.main import create_app


def _seed_brief_surface() -> tuple[InMemoryGraphWriteService, str]:
    writes = InMemoryGraphWriteService("owner-brief")
    idea = Idea(owner_id=writes.owner_id, id="api-brief-idea", title="Safe idea", egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(idea, idempotency_key="api-brief-idea")
    brief = IdeaBriefVersion(
        owner_id=writes.owner_id,
        id="api-brief-version",
        idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id,
        sections=tuple(IdeaBriefSection(index=index, content=f"section {index}") for index in range(8)),
        egress_policy="shareable",
    )
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="api-brief-save")
    return writes, idea.id


def test_api_and_stdio_catalogs_and_results_match_for_idea_brief_fetch() -> None:
    writes, idea_id = _seed_brief_surface()
    read_surface = McpReadSurface(GraphReadService(writes))
    headers = {"X-Local-Owner-Id": writes.owner_id}
    api = TestClient(create_app(
        founder_graph_write_service=writes,
        founder_graph_read_service=GraphReadService(writes),
        founder_graph_owner_id=writes.owner_id,
    ))
    stdio = FounderGraphStdioServer(read_surface, McpWriteSurface(writes), writes.owner_id)

    api_catalog = api.get("/v1/founder-graph/mcp/tools", headers=headers).json()["read"]
    stdio_catalog = stdio.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})["result"]["tools"]
    api_tool = next(item for item in api_catalog if item["name"] == "fetch_idea_brief")
    stdio_tool = next(item for item in stdio_catalog if item["name"] == "fetch_idea_brief")
    api_result = api.post(
        "/v1/founder-graph/mcp/read/fetch_idea_brief",
        headers=headers,
        json={"idea_id": idea_id},
    )
    stdio_result = stdio.handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "fetch_idea_brief", "arguments": {"idea_id": idea_id}},
    })

    assert api_result.status_code == 200
    assert "fetch_idea_brief" in {item["name"] for item in api_catalog}
    assert "fetch_idea_brief" in {item["name"] for item in stdio_catalog}
    assert api_tool["readOnly"] is True
    assert api_tool["inputSchema"] == stdio_tool["inputSchema"]
    assert api_tool["annotations"] == stdio_tool["annotations"]
    assert api_result.json() == stdio_result["result"]["structuredContent"]
    assert json.loads(stdio_result["result"]["content"][0]["text"]) == api_result.json()
