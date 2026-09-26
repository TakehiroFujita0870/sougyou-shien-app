"""Synthetic conversation-to-MCP dispatch acceptance through real stdio."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
import json
import os
import threading
import time
from typing import Mapping
from uuid import uuid4

import pytest

from dots.founder_graph_conversation_dispatch import ConversationToolDispatcher, ToolCall
from dots.founder_graph_mcp_stdio import create_neo4j_stdio_server, run_stdio
from dots.founder_graph_neo4j import Neo4jGraphGateway
from neo4j_disposable_harness import DisposableNeo4j, fixed_docker, is_opted_in


DISPATCH_OPT_IN = "DOTS_P5_CONVERSATION_DISPATCH_REAL"


class SyntheticConversationFixtures(ConversationToolDispatcher):
    """Deterministic intent-to-tool seam; only opaque fixture IDs enter traces."""

    def dispatch(self, fixture_id: str, *, context: Mapping[str, str] | None = None) -> tuple[ToolCall, ...]:
        context = context or {}
        if fixture_id == "P5-01-A":
            return (ToolCall("capture_idea", {
                "title": "Synthetic pilot concept A",
                "summary": "P5Aneedle synthetic workflow concept",
                "egress_policy": "shareable",
                "idempotency_key": "p5-01-a-idea",
            }),)
        if fixture_id == "P5-01-B":
            return (
                ToolCall("capture_source", {
                    "url": "https://example.invalid/p5-b",
                    "title": "Synthetic local reference B",
                    "summary": "P5Bsourceneedle authored synthetic summary",
                    "idempotency_key": "p5-01-b-source",
                }),
                ToolCall("capture_asset", {
                    "name": "Synthetic asset B",
                    "kind": "artifact",
                    "summary": "P5Bassetneedle metadata only",
                    "egress_policy": "shareable",
                    "idempotency_key": "p5-01-b-asset",
                }),
            )
        if fixture_id == "P5-01-C":
            return (
                ToolCall("capture_person", {
                    "name": "Synthetic local collaborator C",
                    "idempotency_key": "p5-01-c-person",
                }),
                ToolCall("capture_organization", {
                    "name": "Synthetic cooperative C",
                    "description": "P5Corgneedle synthetic shareable organization",
                    "egress_policy": "shareable",
                    "idempotency_key": "p5-01-c-organization",
                }),
            )
        if fixture_id == "P5-01-D":
            previous_id = context.get("previous_id")
            if previous_id is None:
                return (ToolCall("capture_idea", {
                    "title": "Synthetic draft D",
                    "summary": "P5Doldneedle initial synthetic summary",
                    "egress_policy": "shareable",
                    "idempotency_key": "p5-01-d-seed",
                }),)
            return (ToolCall("record_correction", {
                "previous_id": previous_id,
                "title": "Synthetic revised D",
                "summary": "P5Dnewneedle corrected synthetic summary",
                "idempotency_key": "p5-01-d-correction",
            }),)
        if fixture_id == "P5-01-E":
            return ()
        raise KeyError("unknown synthetic conversation fixture")


def _tool_call_request(request_id: int, tool: ToolCall) -> dict[str, object]:
    return {
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": tool.name, "arguments": dict(tool.arguments)},
    }


def _stdio_exchange(driver, owner_id: str, requests: list[dict[str, object]]) -> list[dict[str, object]]:
    server = create_neo4j_stdio_server(driver, owner_id)
    source = StringIO("".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in requests))
    output = StringIO()
    run_stdio(source, output, server=server)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def _open_driver(port: int):
    from neo4j import GraphDatabase

    return GraphDatabase.driver(f"bolt://127.0.0.1:{port}", auth=None)


def _exchange_reopened(port: int, owner_id: str, requests: list[dict[str, object]]) -> list[dict[str, object]]:
    driver = _open_driver(port)
    try:
        driver.verify_connectivity()
        return _stdio_exchange(driver, owner_id, requests)
    finally:
        driver.close()


def _structured(response: dict[str, object]) -> dict[str, object]:
    result = response.get("result")
    assert isinstance(result, dict), response
    if "error" in result:
        raise AssertionError("synthetic stdio tool call returned an MCP error")
    structured = result.get("structuredContent")
    assert isinstance(structured, dict), response
    return structured


def _fingerprint(tool: ToolCall) -> str:
    canonical = json.dumps(
        {"name": tool.name, "arguments": dict(tool.arguments)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _store_marker(driver, run_id: str) -> str:
    marker = sha256(f"p5-store:{run_id}".encode()).hexdigest()
    with driver.session(database="neo4j") as session:
        session.run(
            "CREATE (:P5ConversationDispatchMarker {run_id:$run_id, marker:$marker})",
            run_id=run_id, marker=marker,
        ).consume()
    return marker


def _assert_reopened_marker(driver, run_id: str, marker: str) -> None:
    with driver.session(database="neo4j") as session:
        row = session.run(
            "MATCH (m:P5ConversationDispatchMarker {run_id:$run_id}) RETURN m.marker AS marker",
            run_id=run_id,
        ).single()
    assert row is not None and row["marker"] == marker


def _assert_no_campaigns_or_runs(driver) -> tuple[int, int]:
    with driver.session(database="neo4j") as session:
        campaigns = session.run("MATCH (n:ResearchCampaign) RETURN count(n) AS count").single()["count"]
        runs = session.run("MATCH (n:ResearchRun) RETURN count(n) AS count").single()["count"]
    assert (campaigns, runs) == (0, 0)
    return campaigns, runs


def _node_payload(port: int, node_id: str, owner_id: str) -> dict[str, object]:
    driver = _open_driver(port)
    try:
        record = Neo4jGraphGateway(driver, owner_id).fetch_node_record(node_id)
        assert record is not None and record["owner_id"] == owner_id
        payload = json.loads(record["payload_json"])
        assert isinstance(payload, dict)
        return payload
    finally:
        driver.close()


def _dispatch_write(port: int, owner_id: str, fixture_id: str, tool: ToolCall, request_id: int) -> dict[str, object]:
    assert tool.name in {"capture_idea", "capture_source", "capture_asset", "capture_person", "capture_organization", "record_correction"}
    response = _exchange_reopened(port, owner_id, [_tool_call_request(request_id, tool)])[0]
    receipt = _structured(response)
    return {
        "fixture_id": fixture_id,
        "input_fingerprint": _fingerprint(tool),
        "operation": receipt["operation"],
        "target_id": receipt["target_id"],
        "target_type": receipt["target_type"],
        "replayed": receipt["replayed"],
    }


def test_deterministic_synthetic_dispatch_seam_covers_cases_a_to_e() -> None:
    dispatcher = SyntheticConversationFixtures()
    assert [item.name for item in dispatcher.dispatch("P5-01-A")] == ["capture_idea"]
    assert [item.name for item in dispatcher.dispatch("P5-01-B")] == ["capture_source", "capture_asset"]
    assert [item.name for item in dispatcher.dispatch("P5-01-C")] == ["capture_person", "capture_organization"]
    assert [item.name for item in dispatcher.dispatch("P5-01-D")] == ["capture_idea"]
    assert [item.name for item in dispatcher.dispatch("P5-01-D", context={"previous_id": "synthetic-id"})] == ["record_correction"]
    assert dispatcher.dispatch("P5-01-E") == ()


@pytest.mark.skipif(not is_opted_in(os.environ, DISPATCH_OPT_IN), reason="set the explicit disposable Neo4j opt-in")
def test_five_synthetic_conversation_dispatches_cross_stdio_and_reopen_persistent_neo4j() -> None:
    docker = fixed_docker()
    if docker is None:
        pytest.skip("the documented Docker Desktop CLI is unavailable")
    run_id = uuid4().hex
    owner_id = f"owner-p5-{run_id[:12]}"
    disposable = DisposableNeo4j(docker, run_id, role="p5-conversation-dispatch", name_prefix="dots-p5dispatch")
    driver = None
    trace: list[dict[str, object]] = []
    private_values: list[str] = []
    try:
        port = disposable.start(auth="none")
        driver = _open_driver(port)
        deadline = time.monotonic() + 90
        while True:
            try:
                driver.verify_connectivity()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise AssertionError("disposable Neo4j did not become ready")
                threading.Event().wait(0.2)
        gateway = Neo4jGraphGateway(driver, owner_id)
        gateway.migrate()
        marker = _store_marker(driver, run_id)
        _assert_no_campaigns_or_runs(driver)
        driver.close()
        driver = None
        tool_list = _exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}])[0]
        tool_names = {tool["name"] for tool in tool_list["result"]["tools"]}
        dispatcher = SyntheticConversationFixtures()

        for case_id in ("P5-01-A", "P5-01-B", "P5-01-C", "P5-01-D", "P5-01-E"):
            case_trace: dict[str, object] = {"fixture_id": case_id, "writes": [], "search_counts": {}, "fetch_ids": []}
            calls = dispatcher.dispatch(case_id)
            assert all(call.name in tool_names for call in calls)
            if case_id == "P5-01-D":
                seed = calls[0]
                seed_trace = _dispatch_write(port, owner_id, case_id, seed, 10)
                seed_receipt = _structured(_exchange_reopened(port, owner_id, [_tool_call_request(11, seed)])[0])
                assert seed_receipt["replayed"] is True and seed_receipt["target_id"] == seed_trace["target_id"]
                previous_id = str(seed_receipt["target_id"])
                correction = dispatcher.dispatch(case_id, context={"previous_id": previous_id})[0]
                correction_trace = _dispatch_write(port, owner_id, case_id, correction, 12)
                correction_replay = _structured(_exchange_reopened(port, owner_id, [_tool_call_request(13, correction)])[0])
                assert correction_replay["replayed"] is True and correction_replay["target_id"] == correction_trace["target_id"]
                correction_trace["replayed"] = correction_replay["replayed"]
                correction_trace["replay_target_id"] = correction_replay["target_id"]
                case_trace["writes"] = [seed_trace, correction_trace]
                private_values.extend([str(seed.arguments["summary"]), str(correction.arguments["summary"]), str(seed.arguments["idempotency_key"]), str(correction.arguments["idempotency_key"])])
                current_id = str(correction_trace["target_id"])
                old_payload = _node_payload(port, previous_id, owner_id)
                current_payload = _node_payload(port, current_id, owner_id)
                assert old_payload["status"] == "draft"
                assert current_payload["supersedes_id"] == previous_id
                assert current_payload["provenance"]["target_id"] == current_id
                case_trace["provenance"] = {"target_id": current_id, "source_id": current_payload["provenance"].get("source_id"), "operation": current_payload["provenance"]["operation"], "supersedes_id": previous_id}
                query = "P5Dnewneedle"
                search = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 14, "method": "tools/call", "params": {"name": "search", "arguments": {"query": query}}}])[0])
                case_trace["search_counts"]["current_idea"] = len(search["results"])
                assert len(search["results"]) == 1 and search["results"][0]["id"] == current_id
                fetched = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 15, "method": "tools/call", "params": {"name": "fetch", "arguments": {"id": current_id}}}])[0])
                assert fetched["id"] == current_id and "supersedes_id" not in fetched["fields"]
                case_trace["fetch_ids"] = [fetched["id"]]
            elif case_id == "P5-01-B":
                source_call, asset_call = calls
                source_trace = _dispatch_write(port, owner_id, case_id, source_call, 20)
                source_replay = _structured(_exchange_reopened(port, owner_id, [_tool_call_request(21, source_call)])[0])
                assert source_replay["replayed"] is True and source_replay["target_id"] == source_trace["target_id"]
                source_trace["replayed"] = source_replay["replayed"]
                source_trace["replay_target_id"] = source_replay["target_id"]
                source_receipt = source_replay
                asset_trace = _dispatch_write(port, owner_id, case_id, asset_call, 22)
                asset_replay = _structured(_exchange_reopened(port, owner_id, [_tool_call_request(23, asset_call)])[0])
                assert asset_replay["replayed"] is True and asset_replay["target_id"] == asset_trace["target_id"]
                asset_trace["replayed"] = asset_replay["replayed"]
                asset_trace["replay_target_id"] = asset_replay["target_id"]
                case_trace["writes"] = [source_trace, asset_trace]
                private_values.extend([str(source_call.arguments["summary"]), str(asset_call.arguments["summary"]), str(source_call.arguments["idempotency_key"]), str(asset_call.arguments["idempotency_key"])])
                source_id, revision_id = str(source_receipt["target_id"]), str(source_receipt["source_revision_id"])
                chunk_ids = tuple(source_receipt["content_chunk_ids"])
                source_payload = _node_payload(port, source_id, owner_id)
                revision_payload = _node_payload(port, revision_id, owner_id)
                assert source_payload["egress_policy"] == "local_only"
                assert source_payload["provenance"]["target_id"] == source_id
                assert revision_payload["source_id"] == source_id
                assert revision_payload["provenance"]["target_id"] == revision_id
                for chunk_id in chunk_ids:
                    assert _node_payload(port, str(chunk_id), owner_id)["provenance"]["target_id"] == chunk_id
                case_trace["source_chain_ids"] = [source_id, revision_id, *chunk_ids]
                source_search = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 24, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "P5Bsourceneedle"}}}])[0])
                asset_search = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 25, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "P5Bassetneedle"}}}])[0])
                case_trace["search_counts"] = {"source": len(source_search["results"]), "asset": len(asset_search["results"])}
                assert case_trace["search_counts"] == {"source": 0, "asset": 1}
                source_fetch = _exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 26, "method": "tools/call", "params": {"name": "fetch", "arguments": {"id": source_id}}}])[0]
                assert "error" in source_fetch
                asset_id = str(asset_trace["target_id"])
                asset_fetch = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 27, "method": "tools/call", "params": {"name": "fetch", "arguments": {"id": asset_id}}}])[0])
                assert set(asset_fetch["fields"]) == {"name", "kind", "description", "status"}
                case_trace["fetch_ids"] = [asset_fetch["id"]]
                case_trace["provenance"] = {"source_id": source_id, "revision_id": revision_id, "asset_id": asset_id}
            elif case_id == "P5-01-C":
                person_call, organization_call = calls
                person_trace = _dispatch_write(port, owner_id, case_id, person_call, 30)
                person_replay = _structured(_exchange_reopened(port, owner_id, [_tool_call_request(31, person_call)])[0])
                assert person_replay["replayed"] is True and person_replay["target_id"] == person_trace["target_id"]
                person_trace["replayed"] = person_replay["replayed"]
                organization_trace = _dispatch_write(port, owner_id, case_id, organization_call, 32)
                organization_replay = _structured(_exchange_reopened(port, owner_id, [_tool_call_request(33, organization_call)])[0])
                assert organization_replay["replayed"] is True and organization_replay["target_id"] == organization_trace["target_id"]
                organization_trace["replayed"] = organization_replay["replayed"]
                case_trace["writes"] = [person_trace, organization_trace]
                person_id, organization_id = str(person_trace["target_id"]), str(organization_trace["target_id"])
                org_search = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 34, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "P5Corgneedle"}}}])[0])
                person_search = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 35, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "Synthetic local collaborator C"}}}])[0])
                person_hits = [result for result in person_search["results"] if result["id"] == person_id]
                case_trace["search_counts"] = {"organization": len(org_search["results"]), "person_match": len(person_hits)}
                assert len(org_search["results"]) == 1
                assert person_hits == []
                assert all(result.get("name") != person_call.arguments["name"] for result in person_search["results"])
                organization_payload = _node_payload(port, organization_id, owner_id)
                assert organization_payload["egress_policy"] == "shareable"
                assert organization_payload["provenance"]["operation"] == "capture_organization"
                assert organization_payload["provenance"]["target_id"] == organization_id
                person_fetch = _exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 36, "method": "tools/call", "params": {"name": "fetch", "arguments": {"id": person_id}}}])[0]
                assert "error" in person_fetch
                organization_fetch = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 37, "method": "tools/call", "params": {"name": "fetch", "arguments": {"id": organization_id}}}])[0])
                assert set(organization_fetch["fields"]) == {"name", "description", "status"}
                assert "provenance" not in str(organization_fetch)
                assert not {"contact", "private_notes", "owner_id", "egress_policy"} & set(organization_fetch["fields"])
                case_trace["fetch_ids"] = [organization_fetch["id"]]
                case_trace["provenance"] = {"organization_target_id": organization_payload["provenance"]["target_id"]}
                private_values.extend([str(person_call.arguments["idempotency_key"]), str(organization_call.arguments["idempotency_key"])])
            elif case_id == "P5-01-A":
                tool = calls[0]
                first_trace = _dispatch_write(port, owner_id, case_id, tool, 40)
                replay = _structured(_exchange_reopened(port, owner_id, [_tool_call_request(41, tool)])[0])
                assert replay["replayed"] is True and replay["target_id"] == first_trace["target_id"]
                first_trace["replayed"] = replay["replayed"]
                first_trace["replay_target_id"] = replay["target_id"]
                case_trace["writes"] = [first_trace]
                idea_id = str(first_trace["target_id"])
                query = "P5Aneedle"
                search = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": {"name": "search", "arguments": {"query": query}}}])[0])
                case_trace["search_counts"]["idea"] = len(search["results"])
                assert len(search["results"]) == 1 and search["results"][0]["id"] == idea_id
                fetched = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 43, "method": "tools/call", "params": {"name": "fetch", "arguments": {"id": idea_id}}}])[0])
                payload = _node_payload(port, idea_id, owner_id)
                source_revision_id = str(replay["source_revision_id"])
                revision_payload = _node_payload(port, source_revision_id, owner_id)
                source_id = str(revision_payload["source_id"])
                source_payload = _node_payload(port, source_id, owner_id)
                assert payload["provenance"]["target_id"] == idea_id
                assert payload["provenance"]["source_id"] == source_revision_id
                assert revision_payload["provenance"]["target_id"] == source_revision_id
                assert revision_payload["provenance"]["source_id"] == source_revision_id
                assert source_payload["current_revision_id"] == source_revision_id
                assert source_payload["provenance"]["target_id"] == source_id
                assert "provenance" not in fetched["fields"]
                case_trace["fetch_ids"] = [fetched["id"]]
                case_trace["provenance"] = {"idea_target_id": payload["provenance"]["target_id"], "source_id": source_id, "source_revision_id": source_revision_id}
                private_values.extend([str(tool.arguments["summary"]), str(tool.arguments["idempotency_key"])])
            else:
                assert case_id == "P5-01-E" and calls == ()
                query = "P5Enoneedle"
                search = _structured(_exchange_reopened(port, owner_id, [{"jsonrpc": "2.0", "id": 50, "method": "tools/call", "params": {"name": "search", "arguments": {"query": query}}}])[0])
                assert search["results"] == []
                case_trace["search_counts"]["fixture"] = 0
                case_trace["fixture_fingerprint"] = sha256(f"synthetic:{case_id}".encode()).hexdigest()
                case_trace["write_count"] = 0
                case_trace["fetch_ids"] = []

            driver = _open_driver(port)
            try:
                _assert_reopened_marker(driver, run_id, marker)
                campaigns, runs = _assert_no_campaigns_or_runs(driver)
            finally:
                driver.close()
                driver = None
            case_trace["research_campaign_count"] = campaigns
            case_trace["research_run_count"] = runs
            trace.append(case_trace)

        redacted_trace = json.dumps(trace, ensure_ascii=False, sort_keys=True)
        assert all(value not in redacted_trace for value in private_values)
        assert all("arguments" not in event and "conversation" not in event for event in trace)
    finally:
        if driver is not None:
            driver.close()
        disposable.close()
