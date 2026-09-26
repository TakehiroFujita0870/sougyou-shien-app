from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from dots.founder_graph import EgressPolicy, Idea, ResearchMaterial
from dots.founder_graph_read import (
    GraphReadUnavailableError,
    NodeView,
    SearchHit,
    SearchPage,
)
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.main import create_app


class InjectedReadService:
    def __init__(self, owner_id: str = "owner-1") -> None:
        self.owner_id = owner_id
        self.search_calls: list[tuple[str, str]] = []
        self.fetch_calls: list[tuple[str, str]] = []
        self.view = NodeView(
            id="injected-idea",
            node_type="idea",
            owner_id=owner_id,
            title="Injected graph idea",
            snippet="from injected read service",
            status="active",
            revision=0,
            fields={
                "title": "Injected graph idea",
                "summary": "from injected read service",
                "egress_policy": "shareable",
            },
        )

    def search(
        self,
        query: str,
        *,
        owner_id: str,
        limit: int = 20,
        cursor: str | None = None,
        timeout_ms: int = 1_000,
    ) -> SearchPage:
        self.search_calls.append((query, owner_id))
        return SearchPage((SearchHit(self.view, 1.0),), None)

    def fetch(self, node_id: str, *, owner_id: str) -> NodeView:
        self.fetch_calls.append((node_id, owner_id))
        return self.view


class UnavailableReadService(InjectedReadService):
    def search(
        self,
        query: str,
        *,
        owner_id: str,
        limit: int = 20,
        cursor: str | None = None,
        timeout_ms: int = 1_000,
    ) -> SearchPage:
        raise GraphReadUnavailableError("Neo4j read is unavailable")


def test_founder_graph_mcp_tools_and_capture_route_are_local_owner_scoped() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    client = TestClient(create_app(founder_graph_write_service=writes, founder_graph_owner_id="owner-1"))
    headers = {"X-Local-Owner-Id": "owner-1"}

    tools = client.get("/v1/founder-graph/mcp/tools", headers=headers)
    assert tools.status_code == 200
    assert [item["name"] for item in tools.json()["read"]] == ["search", "fetch"]
    write_names = {item["name"] for item in tools.json()["write"]}
    assert write_names == {
        "capture_idea", "capture_source", "capture_person", "capture_organization", "capture_asset", "append_claim",
        "capture_evidence",
        "link_entities", "save_research_report", "record_decision", "record_correction", "confirm_person_merge",
    }

    first = client.post(
        "/v1/founder-graph/mcp/write/capture_idea",
        headers=headers,
        json={"title": "Graph idea", "idempotency_key": "idea-1"},
    )
    replay = client.post(
        "/v1/founder-graph/mcp/write/capture_idea",
        headers=headers,
        json={"title": "Graph idea", "idempotency_key": "idea-1"},
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True

    asset = client.post("/v1/founder-graph/mcp/write/capture_asset", headers=headers,
                        json={"name": "Synthetic asset", "kind": "knowledge", "summary": "A safe description", "idempotency_key": "asset-api"})
    assert asset.status_code == 200
    assert asset.json()["target_type"] == "asset"
    assert client.post("/v1/founder-graph/mcp/write/capture_asset", headers=headers,
                       json={"name": "Synthetic asset", "kind": "knowledge", "details": {"body": "x"}, "idempotency_key": "asset-api"}).status_code == 422

    assert client.get("/v1/founder-graph/mcp/tools", headers={"X-Local-Owner-Id": "owner-2"}).status_code == 403


def test_capture_idea_receipt_returns_opaque_source_refs_on_initial_write_and_replay() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    client = TestClient(create_app(founder_graph_write_service=writes, founder_graph_owner_id="owner-1"))
    headers = {"X-Local-Owner-Id": "owner-1"}
    arguments = {
        "title": "Private conversation idea",
        "source_text": "Private source text: owner@example.test, phone +81-90-1111-2222.",
        "idempotency_key": "idea-source-receipt-1",
    }

    first = client.post("/v1/founder-graph/mcp/write/capture_idea", headers=headers, json=arguments)
    replay = client.post("/v1/founder-graph/mcp/write/capture_idea", headers=headers, json=arguments)

    assert first.status_code == replay.status_code == 200
    initial_receipt = first.json()
    replay_receipt = replay.json()
    expected_fields = {
        "operation",
        "target_id",
        "target_type",
        "revision",
        "idempotency_key",
        "replayed",
        "source_revision_id",
        "content_chunk_ids",
    }
    assert set(initial_receipt) == expected_fields
    assert set(replay_receipt) == expected_fields
    assert initial_receipt["replayed"] is False
    assert replay_receipt["replayed"] is True
    assert initial_receipt["source_revision_id"].startswith("source-revision_")
    assert replay_receipt["source_revision_id"] == initial_receipt["source_revision_id"]
    assert len(initial_receipt["content_chunk_ids"]) == 1
    assert initial_receipt["content_chunk_ids"][0].startswith("content-chunk_")
    assert replay_receipt["content_chunk_ids"] == initial_receipt["content_chunk_ids"]
    for receipt in (initial_receipt, replay_receipt):
        serialized = str(receipt)
        assert "Private source text" not in serialized
        assert "owner@example.test" not in serialized
        assert "+81-90-1111-2222" not in serialized
        assert not {"source_text", "content", "contact", "private_notes", "locator"} & set(receipt)


def test_founder_graph_mcp_read_route_returns_shareable_material_and_safe_errors() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    material = ResearchMaterial(
        owner_id="owner-1",
        id="material-1",
        title="Shareable source",
        content="safe content",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(material, idempotency_key="material")
    client = TestClient(create_app(founder_graph_write_service=writes, founder_graph_owner_id="owner-1"))
    headers = {"X-Local-Owner-Id": "owner-1"}

    response = client.post(
        "/v1/founder-graph/mcp/read/fetch",
        headers=headers,
        json={"id": material.id},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "safe content"

    missing = client.post(
        "/v1/founder-graph/mcp/read/fetch",
        headers=headers,
        json={"id": "missing"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "not_found"


def test_founder_graph_mcp_routes_use_explicitly_injected_read_service() -> None:
    reads = InjectedReadService()
    client = TestClient(
        create_app(
            founder_graph_write_service=InMemoryGraphWriteService("owner-1"),
            founder_graph_read_service=reads,
            founder_graph_owner_id="owner-1",
        )
    )
    headers = {"X-Local-Owner-Id": "owner-1"}

    search = client.post(
        "/v1/founder-graph/mcp/read/search",
        headers=headers,
        json={"query": "injected"},
    )
    fetched = client.post(
        "/v1/founder-graph/mcp/read/fetch",
        headers=headers,
        json={"id": "injected-idea"},
    )

    assert search.status_code == 200
    assert search.json()["results"][0]["id"] == "injected-idea"
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Injected graph idea"
    assert reads.search_calls == [("injected", "owner-1")]
    assert reads.fetch_calls == [("injected-idea", "owner-1")]


def test_founder_graph_mcp_read_route_maps_injected_unavailable_service_to_503() -> None:
    client = TestClient(
        create_app(
            founder_graph_write_service=InMemoryGraphWriteService("owner-1"),
            founder_graph_read_service=UnavailableReadService(),
            founder_graph_owner_id="owner-1",
        )
    )

    response = client.post(
        "/v1/founder-graph/mcp/read/search",
        headers={"X-Local-Owner-Id": "owner-1"},
        json={"query": "injected"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "unavailable"


def test_create_app_rejects_read_service_for_a_different_owner() -> None:
    with pytest.raises(ValueError, match="founder_graph_read_service owner"):
        create_app(
            founder_graph_write_service=InMemoryGraphWriteService("owner-1"),
            founder_graph_read_service=InjectedReadService("owner-2"),
            founder_graph_owner_id="owner-1",
        )


def test_capture_idea_can_explicitly_opt_into_shareable_projection_without_source_text() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    client = TestClient(create_app(founder_graph_write_service=writes, founder_graph_owner_id="owner-1"))
    headers = {"X-Local-Owner-Id": "owner-1"}

    response = client.post(
        "/v1/founder-graph/mcp/write/capture_idea",
        headers=headers,
        json={
            "title": "Shareable idea",
            "summary": "A safe summary",
            "source_text": "private conversational context",
            "egress_policy": "shareable",
            "idempotency_key": "idea-shareable-1",
        },
    )
    assert response.status_code == 200
    idea_id = response.json()["target_id"]

    fetched = client.post(
        "/v1/founder-graph/mcp/read/fetch",
        headers=headers,
        json={"id": idea_id},
    )
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["title"] == "Shareable idea"
    assert body["fields"]["summary"] == "A safe summary"
    assert "source_text" not in body["fields"]
    assert "private conversational context" not in body["snippet"]
    assert isinstance(writes.get_node(idea_id), Idea)


def test_capture_evidence_api_accepts_only_persisted_references_and_returns_common_receipt() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    client = TestClient(create_app(founder_graph_write_service=writes, founder_graph_owner_id="owner-1"))
    headers = {"X-Local-Owner-Id": "owner-1"}
    source = client.post("/v1/founder-graph/mcp/write/capture_source", headers=headers, json={
        "url": "https://example.test/api", "title": "Synthetic", "summary": "Local source text.",
        "idempotency_key": "api-source",
    }).json()
    claim = client.post("/v1/founder-graph/mcp/write/append_claim", headers=headers, json={
        "text": "A synthetic claim", "idempotency_key": "api-claim",
    }).json()
    response = client.post("/v1/founder-graph/mcp/write/capture_evidence", headers=headers, json={
        "claim_id": claim["target_id"], "content_chunk_id": source["content_chunk_ids"][0],
        "idempotency_key": "api-evidence",
    })
    assert response.status_code == 200
    assert response.json()["target_type"] == "evidence"
    assert response.json()["source_revision_id"] is None and response.json()["content_chunk_ids"] == []
    assert not {"claim_id", "locator", "excerpt"} & set(response.json())
    assert source["content_chunk_ids"][0] not in response.text
    rejected = client.post("/v1/founder-graph/mcp/write/capture_evidence", headers=headers, json={
        "claim_id": claim["target_id"], "content_chunk_id": source["content_chunk_ids"][0],
        "excerpt": "caller text", "idempotency_key": "api-evidence-extra",
    })
    assert rejected.status_code == 422
