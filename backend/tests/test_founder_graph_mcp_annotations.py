from __future__ import annotations

from fastapi.testclient import TestClient

from dots.founder_graph_mcp_stdio import create_stdio_server
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.main import create_app


EXPECTED_DESTRUCTIVE_HINTS = {
    "record_correction": True,
    "confirm_person_merge": True,
}
EXPECTED_READ_TOOLS = {"search", "fetch"}
EXPECTED_WRITE_TOOLS = {
    "capture_idea",
    "capture_source",
    "capture_person",
    "capture_organization",
    "append_claim",
    "capture_evidence",
    "link_entities",
    "save_research_report",
    "record_decision",
    "record_correction",
    "confirm_person_merge",
}


def _stdio_catalog() -> dict[str, dict]:
    response = create_stdio_server("owner-a").handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    assert response is not None
    return {tool["name"]: tool for tool in response["result"]["tools"]}


def _api_catalog() -> dict[str, dict]:
    client = TestClient(
        create_app(
            founder_graph_write_service=InMemoryGraphWriteService("owner-a"),
            founder_graph_owner_id="owner-a",
        )
    )
    response = client.get(
        "/v1/founder-graph/mcp/tools",
        headers={"X-Local-Owner-Id": "owner-a"},
    )
    assert response.status_code == 200
    catalog = response.json()
    return {
        tool["name"]: tool
        for group in ("read", "write")
        for tool in catalog[group]
    }


def test_stdio_and_fastapi_catalogs_publish_matching_truthful_annotations() -> None:
    stdio_tools = _stdio_catalog()
    api_tools = _api_catalog()
    assert set(stdio_tools) == set(api_tools)
    assert set(api_tools) == EXPECTED_READ_TOOLS | EXPECTED_WRITE_TOOLS
    assert set(EXPECTED_DESTRUCTIVE_HINTS) <= set(api_tools)
    for name, stdio_tool in stdio_tools.items():
        expected = {
            "readOnlyHint": name in EXPECTED_READ_TOOLS,
            "destructiveHint": EXPECTED_DESTRUCTIVE_HINTS.get(name, False),
            "openWorldHint": False,
        }
        assert stdio_tool["annotations"] == expected
        assert api_tools[name]["annotations"] == expected
        assert all(type(value) is bool for value in stdio_tool["annotations"].values())
        assert api_tools[name]["readOnly"] is expected["readOnlyHint"]


def test_capture_source_is_a_local_write_not_a_destructive_or_open_world_action() -> None:
    stdio_source = _stdio_catalog()["capture_source"]
    api_source = _api_catalog()["capture_source"]

    expected = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
    }
    assert stdio_source["annotations"] == api_source["annotations"] == expected
    assert stdio_source["inputSchema"] == api_source["inputSchema"]
    assert stdio_source["inputSchema"]["additionalProperties"] is False
    assert set(stdio_source["inputSchema"]["required"]) == {
        "url", "title", "summary", "idempotency_key",
    }
    schema_description = stdio_source["inputSchema"]["description"]
    assert "ページ取得や調査の許可にはなりません" in schema_description
    assert "ページ本文は取得しません" in stdio_source["inputSchema"]["properties"]["url"]["description"]
