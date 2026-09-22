"""Minimal stdio JSON-RPC transport for the local Founder Graph MCP surface.

The transport is intentionally dependency-free and delegates all policy to the
existing read/write adapters.  It writes only JSON-RPC responses to stdout so
it can be started by a private Secure MCP Tunnel stdio profile.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, IO, Mapping

from .founder_graph_mcp import McpReadError, McpReadSurface
from .founder_graph_mcp_write import McpWriteError, McpWriteSurface
from .founder_graph_read import GraphReadService
from .founder_graph_write import InMemoryGraphWriteService
from .founder_graph_runtime import create_neo4j_graph_composition


JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "dots-founder-graph"
SERVER_VERSION = "0.1.0"


def _json_value(value: Any) -> Any:
    if hasattr(value, "value") and not isinstance(value, (str, bytes, bytearray)):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": _json_value(result)}


def _error(request_id: Any, code: int, message: str, *, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}
    if data:
        payload["error"]["data"] = _json_value(data)
    return payload


def _tool_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Convert the internal definition to the MCP tool shape."""

    return {
        "name": str(definition.get("name", "")),
        "description": str(definition.get("description", "")),
        "inputSchema": _json_value(definition.get("inputSchema", {"type": "object"})),
        "annotations": {"readOnlyHint": bool(definition.get("readOnly", False))},
    }


@dataclass(slots=True)
class FounderGraphStdioServer:
    reads: McpReadSurface
    writes: McpWriteSurface
    owner_id: str

    def handle(self, request: object) -> dict[str, Any] | None:
        if not isinstance(request, Mapping) or request.get("jsonrpc") != JSONRPC_VERSION or not isinstance(request.get("method"), str):
            return _error(request.get("id") if isinstance(request, Mapping) else None, -32600, "Invalid JSON-RPC request.")
        request_id = request.get("id")
        method = request["method"]
        params = request.get("params", {})
        if request_id is None and method.startswith("notifications/"):
            return None
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            if not isinstance(params, Mapping):
                return _error(request_id, -32602, "Initialize parameters must be an object.")
            return _response(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method == "ping":
            if params is not None and not isinstance(params, Mapping):
                return _error(request_id, -32602, "Ping parameters must be an object.")
            return _response(request_id, {})
        if method == "tools/list":
            if params is not None and not isinstance(params, Mapping):
                return _error(request_id, -32602, "Tool list parameters must be an object.")
            definitions = tuple(self.reads.tool_definitions()) + tuple(self.writes.tool_definitions())
            return _response(request_id, {"tools": [_tool_definition(item) for item in definitions]})
        if method == "tools/call":
            return self._call_tool(request_id, params)
        return _error(request_id, -32601, "Method not found.")

    def _call_tool(self, request_id: Any, params: object) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            return _error(request_id, -32602, "Tool call parameters must be an object.")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name.strip() or not isinstance(arguments, Mapping):
            return _error(request_id, -32602, "Tool name and object arguments are required.")
        try:
            if name in {item["name"] for item in self.reads.tool_definitions()}:
                result = self.reads.call(name, arguments, owner_id=self.owner_id)
            else:
                receipt = self.writes.call(name, arguments, owner_id=self.owner_id)
                result = asdict(receipt)
        except (McpReadError, McpWriteError) as exc:
            return _error(request_id, -32000, exc.message, data={"code": exc.code})
        text = json.dumps(_json_value(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return _response(request_id, {"content": [{"type": "text", "text": text}], "structuredContent": _json_value(result)})


def create_stdio_server(owner_id: str | None = None) -> FounderGraphStdioServer:
    resolved_owner = (owner_id or os.environ.get("DOTS_LOCAL_OWNER_ID") or "local-owner").strip()
    if not resolved_owner:
        raise ValueError("DOTS_LOCAL_OWNER_ID must be non-empty")
    writes = InMemoryGraphWriteService(resolved_owner)
    reads = GraphReadService(writes)
    return FounderGraphStdioServer(McpReadSurface(reads), McpWriteSurface(writes), resolved_owner)


def create_neo4j_stdio_server(driver: Any, owner_id: str, *, database: str = "neo4j") -> FounderGraphStdioServer:
    """Create a stdio server with explicitly injected persistent ports.

    This helper never discovers a driver, opens a network connection, or runs
    migrations.  The caller owns those lifecycle decisions.
    """

    composition = create_neo4j_graph_composition(driver, owner_id, database=database)
    return FounderGraphStdioServer(
        McpReadSurface(composition.reads),
        McpWriteSurface(composition.writes),
        composition.gateway.owner_id,
    )


def run_stdio(
    input_stream: IO[str] | None = None,
    output_stream: IO[str] | None = None,
    *,
    server: FounderGraphStdioServer | None = None,
) -> None:
    """Process newline-delimited JSON-RPC requests without logging to stdout."""

    source = input_stream or sys.stdin
    target = output_stream or sys.stdout
    active_server = server or create_stdio_server()
    for line in source:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "Parse error.")
        else:
            response = active_server.handle(request)
        if response is not None:
            target.write(json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            target.flush()


def main() -> int:
    run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
