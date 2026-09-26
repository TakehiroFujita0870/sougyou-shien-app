from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dots.founder_graph import Claim, EgressPolicy
from dots.founder_graph_mcp import McpReadError, McpReadSurface
from dots.founder_graph_mcp_stdio import FounderGraphStdioServer
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.main import create_app


def test_append_claim_is_private_by_default_and_only_explicit_shareable_claims_are_readable() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    reader = McpReadSurface(GraphReadService(writes))

    private_receipt = writer.call("append_claim", {
        "text": "Synthetic private claim", "idempotency_key": "claim-private-default",
    }, owner_id="owner-1")
    private_claim = writes.get_node(private_receipt.target_id)
    assert isinstance(private_claim, Claim)
    assert private_claim.egress_policy is EgressPolicy.LOCAL_ONLY
    assert reader.call("search", {"query": "Synthetic private claim"}, owner_id="owner-1")["results"] == []
    with pytest.raises(McpReadError) as private_fetch:
        reader.call("fetch", {"id": private_receipt.target_id}, owner_id="owner-1")
    assert private_fetch.value.code == "not_found"

    public_receipt = writer.call("append_claim", {
        "text": "Synthetic explicitly shareable claim", "egress_policy": "shareable",
        "idempotency_key": "claim-shareable-explicit",
    }, owner_id="owner-1")
    public_claim = writes.get_node(public_receipt.target_id)
    assert isinstance(public_claim, Claim)
    assert public_claim.egress_policy is EgressPolicy.SHAREABLE
    projection = reader.call("fetch", {"id": public_receipt.target_id}, owner_id="owner-1")
    assert projection["fields"]["text"] == "Synthetic explicitly shareable claim"
    assert "owner_id" not in projection


def test_append_claim_rejects_implicit_upgrade_invalid_policy_unknown_input_and_other_owner() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    private_receipt = writer.call("append_claim", {
        "text": "Synthetic private claim", "idempotency_key": "claim-stable-key",
    }, owner_id="owner-1")

    before_nodes = writes.nodes()
    before_audit = writes.audit_events()
    with pytest.raises(McpWriteError) as upgrade:
        writer.call("append_claim", {
            "text": "Synthetic private claim", "egress_policy": "shareable",
            "idempotency_key": "claim-stable-key",
        }, owner_id="owner-1")
    assert upgrade.value.code == "idempotency_conflict"
    assert writes.get_node(private_receipt.target_id).egress_policy is EgressPolicy.LOCAL_ONLY
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit

    invalid_inputs = (
        {"egress_policy": "research_allowed"},
        {"egress_policy": "unknown"},
        {"research_allowed": True},
    )
    for extra in invalid_inputs:
        with pytest.raises(McpWriteError) as invalid:
            writer.call("append_claim", {
                "text": "Synthetic invalid claim", **extra,
                "idempotency_key": f"invalid-{len(writes.nodes())}-{len(writes.audit_events())}",
            }, owner_id="owner-1")
        assert invalid.value.code == "invalid_input"
        assert writes.nodes() == before_nodes
        assert writes.audit_events() == before_audit

    with pytest.raises(McpWriteError) as wrong_owner:
        writer.call("append_claim", {
            "text": "Synthetic other-owner claim", "egress_policy": "shareable",
            "idempotency_key": "other-owner-claim",
        }, owner_id="owner-2")
    assert wrong_owner.value.code == "owner_mismatch"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


def test_append_claim_schema_matches_api_and_stdio_with_closed_egress_enum() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    reads = McpReadSurface(GraphReadService(writes))
    writer = McpWriteSurface(writes)
    api = TestClient(create_app(
        founder_graph_write_service=writes,
        founder_graph_owner_id="owner-1",
    )).get("/v1/founder-graph/mcp/tools", headers={"X-Local-Owner-Id": "owner-1"})
    assert api.status_code == 200
    api_schema = next(
        item for item in api.json()["write"] if item["name"] == "append_claim"
    )["inputSchema"]

    stdio = FounderGraphStdioServer(reads, writer, "owner-1")
    listed = stdio.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert listed is not None and "result" in listed
    stdio_schema = next(
        item for item in listed["result"]["tools"] if item["name"] == "append_claim"
    )["inputSchema"]
    surface_schema = next(
        item for item in writer.tool_definitions() if item["name"] == "append_claim"
    )["inputSchema"]

    assert api_schema == stdio_schema == surface_schema
    assert api_schema["properties"]["egress_policy"]["enum"] == ["local_only", "shareable"]
    assert api_schema["additionalProperties"] is False
