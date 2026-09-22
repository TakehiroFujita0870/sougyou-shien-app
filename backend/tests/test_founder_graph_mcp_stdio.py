from __future__ import annotations

from io import StringIO
import json

from dots.founder_graph_mcp_stdio import FounderGraphStdioServer, create_stdio_server, run_stdio
from dots.founder_graph_mcp_write import McpWriteError


def request(method: str, request_id: int, params: dict | None = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def test_initialize_and_tools_list_expose_only_ten_tools() -> None:
    server = create_stdio_server("owner-a")
    initialized = server.handle(request("initialize", 1, {"protocolVersion": "2025-06-18", "clientInfo": {}}))
    listed = server.handle(request("tools/list", 2, {}))
    ping = server.handle(request("ping", 8, {}))

    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert ping["result"] == {}
    tools = listed["result"]["tools"]
    assert len(tools) == 10
    assert {tool["name"] for tool in tools} == {
        "search", "fetch", "capture_idea", "capture_person", "capture_organization", "append_claim",
        "link_entities", "save_research_report", "record_decision", "record_correction",
    }
    assert all("inputSchema" in tool and "readOnlyHint" in tool["annotations"] for tool in tools)


def test_tools_call_delegates_read_and_idempotent_write() -> None:
    server = create_stdio_server("owner-a")
    write = server.handle(request("tools/call", 3, {"name": "capture_idea", "arguments": {"title": "MCP idea", "idempotency_key": "idea-1"}}))
    replay = server.handle(request("tools/call", 4, {"name": "capture_idea", "arguments": {"title": "MCP idea", "idempotency_key": "idea-1"}}))
    search = server.handle(request("tools/call", 5, {"name": "search", "arguments": {"query": "MCP"}}))

    assert json.loads(write["result"]["content"][0]["text"])["target_type"] == "idea"
    assert json.loads(replay["result"]["content"][0]["text"])["replayed"] is True
    assert search["result"]["structuredContent"]["results"] == []


def test_errors_notifications_and_malformed_lines_are_safe() -> None:
    server = create_stdio_server("owner-a")
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    unknown = server.handle(request("missing", 6, {}))
    unknown_tool = server.handle(request("tools/call", 9, {"name": "not_a_tool", "arguments": {}}))
    malformed = server.handle({"jsonrpc": "1.0", "id": 7, "method": "tools/list"})
    assert unknown["error"]["code"] == -32601
    assert unknown_tool["error"]["data"]["code"] == "unknown_tool"
    assert malformed["error"]["code"] == -32600

    output = StringIO()
    run_stdio(StringIO("not-json\n"), output, server=server)
    line = json.loads(output.getvalue())
    assert line["error"]["code"] == -32700
    assert "Traceback" not in output.getvalue()


def test_write_owner_error_is_converted_to_safe_json_rpc_error() -> None:
    server = create_stdio_server("owner-a")

    class RejectingWriteSurface:
        def tool_definitions(self):
            return ({"name": "capture_idea", "description": "", "readOnly": False, "inputSchema": {"type": "object"}},)

        def call(self, tool_name, arguments, *, owner_id):
            raise McpWriteError("owner_mismatch", "The request owner is not the local owner.")

    guarded = FounderGraphStdioServer(server.reads, RejectingWriteSurface(), "owner-a")
    response = guarded.handle(request("tools/call", 10, {"name": "capture_idea", "arguments": {"title": "x"}}))

    assert response["error"]["code"] == -32000
    assert response["error"]["data"] == {"code": "owner_mismatch"}
    assert "local owner" in response["error"]["message"]
