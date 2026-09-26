from __future__ import annotations

from io import StringIO
import json

from dots.founder_graph_mcp_stdio import FounderGraphStdioServer, create_stdio_server, run_stdio
from dots.founder_graph_mcp_write import McpWriteError
import dots.founder_graph_mcp_stdio as stdio_module


def request(method: str, request_id: int, params: dict | None = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def test_initialize_and_tools_list_expose_confirmed_person_merge_tool() -> None:
    server = create_stdio_server("owner-a")
    initialized = server.handle(request("initialize", 1, {"protocolVersion": "2025-06-18", "clientInfo": {}}))
    listed = server.handle(request("tools/list", 2, {}))
    ping = server.handle(request("ping", 8, {}))

    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert ping["result"] == {}
    tools = listed["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "search", "fetch", "capture_idea", "capture_source", "capture_person", "capture_organization", "capture_asset", "append_claim",
        "capture_evidence",
        "link_entities", "save_research_report", "record_decision", "record_correction", "confirm_person_merge",
    }
    assert len(tools) == len({tool["name"] for tool in tools})
    assert all("inputSchema" in tool and "readOnlyHint" in tool["annotations"] for tool in tools)


def test_write_tools_publish_actionable_input_contracts() -> None:
    server = create_stdio_server("owner-a")
    tools = {tool["name"]: tool for tool in server.handle(request("tools/list", 20, {}))["result"]["tools"]}

    assert tools["capture_idea"]["inputSchema"]["required"] == ["title", "idempotency_key"]
    assert "egress_policy" in tools["capture_idea"]["inputSchema"]["properties"]
    assert tools["link_entities"]["inputSchema"]["properties"]["relation"]["enum"]
    assert tools["save_research_report"]["inputSchema"]["properties"]["sections"]["items"]["properties"]["content"]
    assert tools["record_correction"]["inputSchema"]["required"] == ["previous_id", "idempotency_key"]
    assert tools["confirm_person_merge"]["inputSchema"]["required"] == ["winner_person_id", "loser_person_id", "confirmation", "evidence_ids", "idempotency_key"]
    assert tools["capture_evidence"]["inputSchema"]["required"] == ["claim_id", "content_chunk_id", "idempotency_key"]
    assert "excerpt" not in tools["capture_evidence"]["inputSchema"]["properties"]


def test_tools_call_delegates_read_and_idempotent_write() -> None:
    server = create_stdio_server("owner-a")
    write = server.handle(request("tools/call", 3, {"name": "capture_idea", "arguments": {"title": "MCP idea", "idempotency_key": "idea-1"}}))
    replay = server.handle(request("tools/call", 4, {"name": "capture_idea", "arguments": {"title": "MCP idea", "idempotency_key": "idea-1"}}))
    search = server.handle(request("tools/call", 5, {"name": "search", "arguments": {"query": "MCP"}}))

    assert json.loads(write["result"]["content"][0]["text"])["target_type"] == "idea"
    assert json.loads(replay["result"]["content"][0]["text"])["replayed"] is True
    assert search["result"]["structuredContent"]["results"] == []


def test_capture_asset_is_discoverable_and_callable_over_stdio() -> None:
    server = create_stdio_server("owner-asset")
    tool = next(item for item in server.handle(request("tools/list", 90, {}))["result"]["tools"] if item["name"] == "capture_asset")
    assert tool["inputSchema"]["required"] == ["name", "kind", "idempotency_key"]
    assert tool["inputSchema"]["additionalProperties"] is False
    captured = server.handle(request("tools/call", 91, {"name": "capture_asset", "arguments": {
        "name": "Synthetic asset", "kind": "artifact", "summary": "Short metadata", "idempotency_key": "asset-stdio",
    }}))
    assert captured["result"]["structuredContent"]["target_type"] == "asset"


def test_stdio_source_grounded_evidence_returns_common_receipt_only() -> None:
    server = create_stdio_server("owner-evidence")
    source = server.handle(request("tools/call", 31, {"name": "capture_source", "arguments": {
        "url": "https://example.test/stdio", "title": "Synthetic", "summary": "Private source phrase.",
        "idempotency_key": "stdio-source",
    }}))
    claim = server.handle(request("tools/call", 32, {"name": "append_claim", "arguments": {
        "text": "A synthetic claim", "idempotency_key": "stdio-claim",
    }}))
    source_receipt = source["result"]["structuredContent"]
    claim_receipt = claim["result"]["structuredContent"]
    captured = server.handle(request("tools/call", 33, {"name": "capture_evidence", "arguments": {
        "claim_id": claim_receipt["target_id"], "content_chunk_id": source_receipt["content_chunk_ids"][0],
        "idempotency_key": "stdio-evidence",
    }}))
    projection = captured["result"]["structuredContent"]
    assert projection["target_type"] == "evidence"
    assert set(projection) == {"operation", "target_id", "target_type", "revision", "idempotency_key", "replayed", "source_revision_id", "content_chunk_ids"}
    serialized = captured["result"]["content"][0]["text"]
    assert "Private source phrase." not in serialized
    assert "claim_id" not in serialized and source_receipt["content_chunk_ids"][0] not in serialized


def test_tools_call_capture_receipt_exposes_opaque_chunk_ids_without_source_text() -> None:
    server = create_stdio_server("owner-a")
    source_text = "Private source text must remain local to the Founder Graph."
    captured = server.handle(
        request(
            "tools/call",
            10,
            {
                "name": "capture_idea",
                "arguments": {
                    "title": "MCP captured idea",
                    "source_text": source_text,
                    "idempotency_key": "stdio-capture-1",
                },
            },
        )
    )

    result = captured["result"]
    receipt_text = result["content"][0]["text"]
    receipt = result["structuredContent"]

    assert receipt["target_type"] == "idea"
    assert receipt["source_revision_id"].startswith("source-revision_")
    assert len(receipt["content_chunk_ids"]) == 1
    assert receipt["content_chunk_ids"][0].startswith("content-chunk_")
    assert source_text not in receipt_text
    assert source_text not in json.dumps(receipt, ensure_ascii=False)
    assert "source_text" not in receipt
    assert "content" not in receipt


def test_tools_call_captures_and_reads_a_shareable_idea_without_source_text() -> None:
    """Exercise the three P5 synthetic MCP tools through one stdio session."""

    server = create_stdio_server("owner-a")
    captured = server.handle(
        request(
            "tools/call",
            11,
            {
                "name": "capture_idea",
                "arguments": {
                    "title": "Shareable card-network idea",
                    "summary": "A synthetic business idea.",
                    "source_text": "This private conversation text must not leave Dots.",
                    "egress_policy": "shareable",
                    "idempotency_key": "shareable-idea-1",
                },
            },
        )
    )
    idea_id = json.loads(captured["result"]["content"][0]["text"])["target_id"]

    searched = server.handle(request("tools/call", 12, {"name": "search", "arguments": {"query": "card-network"}}))
    fetched = server.handle(request("tools/call", 13, {"name": "fetch", "arguments": {"id": idea_id}}))

    assert [result["id"] for result in searched["result"]["structuredContent"]["results"]] == [idea_id]
    projection = fetched["result"]["structuredContent"]
    assert projection["id"] == idea_id
    assert projection["fields"]["title"] == "Shareable card-network idea"
    assert "private conversation" not in json.dumps(projection, ensure_ascii=False)


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


def test_neo4j_backend_is_explicit_and_uses_environment_configuration(monkeypatch) -> None:
    fake_driver = object()
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")
    monkeypatch.setattr(stdio_module, "create_neo4j_driver_from_env", lambda: fake_driver)

    server = create_stdio_server("owner-persistent")

    assert server.owner_id == "owner-persistent"
    assert server.reads.reads.owner_id == "owner-persistent"


def test_unknown_backend_does_not_silently_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "unknown")

    try:
        create_stdio_server("owner-a")
    except ValueError as error:
        assert "memory or neo4j" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("unknown backend must fail closed")
