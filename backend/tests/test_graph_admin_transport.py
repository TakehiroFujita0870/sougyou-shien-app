from fastapi.testclient import TestClient

from nebula.founder_graph_mcp_stdio import FounderGraphStdioServer
from nebula.founder_graph_mcp import McpReadSurface
from nebula.founder_graph_mcp_write import McpWriteSurface
from nebula.main import create_app
from test_graph_admin_cleanup import context, manifest, request


def test_http_admin_requires_owner_and_publishes_safe_schema():
    writes, _, surface = context()
    client = TestClient(create_app(founder_graph_write_service=writes, founder_graph_owner_id="owner",
                                  founder_graph_candidate_processor=surface.cleanup.processor))
    path = "/v1/founder-graph/mcp/read/audit_graph"
    assert client.post(path, json={}).status_code == 401
    assert client.post(path, json={}, headers={"X-Local-Owner-Id": "other"}).status_code == 403
    headers = {"X-Local-Owner-Id": "owner"}
    audit = client.post(path, json={}, headers=headers)
    assert audit.status_code == 200 and audit.json()["summary"]["node_count"] == 3
    assert client.post(path, json={"limit": True}, headers=headers).status_code == 422
    result = client.post("/v1/founder-graph/mcp/write/apply_graph_cleanup", headers=headers,
        json=request(surface, [{"action": "archive", "node_id": "idea", "expected_revision": 0}], dry_run=False))
    assert result.status_code == 403


def test_stdio_admin_dry_run_has_no_mutation_and_returns_metadata_only():
    writes, _, surface = context()
    server = FounderGraphStdioServer(McpReadSurface(surface.reads), McpWriteSurface(writes), "owner", admin=surface)
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "audit_graph", "arguments": {}}})
    result = response["result"]["structuredContent"]
    assert result["scope"] == "current_shareable_graph"
    assert all(set(n) == {"id", "kind", "revision", "degree", "in_degree", "out_degree", "degree_by_category"} for n in result["results"])
    candidate = surface.call("propose_graph_cleanup", {"manifests": [manifest()]}, owner_id="owner")["candidates"][0]
    args = request(surface, [{"action": "relation", "manifest": manifest(), "candidate_id": candidate["id"]}])
    dry = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "apply_graph_cleanup", "arguments": args}})
    assert dry["result"]["structuredContent"]["dry_run"] is True
    assert len(writes.nodes()) == 2
