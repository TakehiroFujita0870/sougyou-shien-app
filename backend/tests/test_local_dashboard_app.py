from __future__ import annotations

import json

from fastapi.testclient import TestClient

from dots.local_dashboard_app import (
    LOCAL_DASHBOARD_HOST,
    LOCAL_DASHBOARD_ORIGIN,
    LOCAL_DASHBOARD_START_ORDER,
    LOCAL_DASHBOARD_STOP_ORDER,
    create_local_dashboard_app,
)
from dots.local_graph_proxy import LocalGraphSearchProxy, ProxyResponse
from dots.local_overview import StoredOverviewNode
from dots.founder_graph_facet_hierarchy import FacetRegionHit, RegionEntity


class FakeService:
    def __init__(self, name: str, state: str, events: list[str]) -> None:
        self.name = name
        self.state = state
        self.events = events

    def status(self) -> str:
        return self.state

    def start(self) -> None:
        self.events.append(f"{self.name}:start")
        self.state = "running"

    def stop(self) -> None:
        self.events.append(f"{self.name}:stop")
        self.state = "stopped"


class FakeOverviewStore:
    def __init__(self, nodes=()) -> None:
        self.nodes = tuple(nodes)
        self.owners: list[str] = []

    def read_overview(self, owner_id: str):
        self.owners.append(owner_id)
        return self.nodes


def _node(identity: str, payload: dict[str, object]) -> StoredOverviewNode:
    return StoredOverviewNode(
        id=identity,
        owner_id="owner-a",
        node_type="idea",
        status="active",
        revision=1,
        payload_json=json.dumps({"id": identity, "owner_id": "owner-a", **payload}),
    )


def _make_app(tmp_path, *, database_state="stopped", overview_store=None, home_store=None, graph_view_store=None, self_intro_writer=None, graph_proxy=None):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>Dots Dashboard</main>", encoding="utf-8")
    (assets / "app.js").write_text("window.appReady = true;", encoding="utf-8")
    events: list[str] = []
    services = {
        name: FakeService(name, state, events)
        for name, state in {
            "database": database_state,
            "intent": "running",
            "api": "running",
            "tunnel": "running",
        }.items()
    }
    store = overview_store or FakeOverviewStore()
    app = create_local_dashboard_app(
        database_adapter=services["database"],
        intent_adapter=services["intent"],
        api_adapter=services["api"],
        tunnel_adapter=services["tunnel"],
        overview_store=store,
        home_store=home_store,
        graph_view_store=graph_view_store,
        self_intro_writer=self_intro_writer,
        overview_owner_id="owner-a",
        dist_dir=dist,
        graph_proxy=graph_proxy,
    )
    client = TestClient(
        app,
        base_url=f"http://{LOCAL_DASHBOARD_HOST}",
        client=("127.0.0.1", 50000),
    )
    return client, events, services, store


def test_home_projection_is_local_only_and_uses_real_owner_scoped_records(tmp_path):
    class HomeStore:
        def __init__(self):
            self.owners = []

        def read_home(self, owner_id):
            self.owners.append(owner_id)
            return [{
                "id": "idea-1", "owner_id": owner_id, "node_type": "idea", "status": "draft",
                "payload_json": json.dumps({
                    "id": "idea-1", "owner_id": owner_id, "title": "新しい事業",
                    "summary": "顧客の課題", "source_text": "private raw text",
                    "created_at": "2026-09-25T00:00:00Z",
                }),
            }]

    store = HomeStore()
    client, _, _, _ = _make_app(tmp_path, database_state="running", home_store=store)
    response = client.get("/api/home")
    assert response.status_code == 200
    assert response.json()["ideas"][0]["title"] == "新しい事業"
    assert "private raw text" not in response.text
    assert store.owners == ["owner-a"]
    assert client.get("/api/home", headers={"host": "malicious.example"}).status_code == 403


def test_graph_projection_is_local_only_and_does_not_expose_private_payload(tmp_path):
    class GraphStore:
        def read_nodes(self, owner_id):
            assert owner_id == "owner-a"
            return [{"id": "idea-1", "owner_id": owner_id, "node_type": "idea", "status": "active",
                     "payload_json": json.dumps({"id": "idea-1", "owner_id": owner_id, "title": "良い案", "private_note": "PRIVATE"})}]

        def read_edges(self, owner_id, ids):
            assert owner_id == "owner-a" and ids == ["idea-1"]
            return []

    client, _, _, _ = _make_app(tmp_path, database_state="running", graph_view_store=GraphStore())
    response = client.get("/api/graph")
    assert response.status_code == 200
    assert response.json()["nodes"] == [{"id": "idea-1", "kind": "idea", "label": "良い案"}]
    assert "PRIVATE" not in response.text
    assert client.get("/api/graph", headers={"host": "malicious.example"}).status_code == 403


def test_facet_region_api_is_loopback_owner_scoped_and_returns_grounded_fields(tmp_path):
    class GraphStore:
        def read_nodes(self, owner_id):
            return []

        def read_edges(self, owner_id, ids):
            return []

        def read_facet_region(self, owner_id, facet_id, depth):
            assert (owner_id, facet_id, depth) == ("owner-a", "facet-root", 1)
            return (FacetRegionHit(
                entity=RegionEntity(owner_id, "idea-1", "idea", "事業案"),
                root_facet_id=facet_id,
                matched_facet_id="facet-child",
                facet_depth=1,
                classification_status="inferred",
                classification_evidence_ids=("ev-class",),
                taxonomy_status_path=("confirmed",),
                taxonomy_evidence_path=(("ev-tax",),),
            ),)

    client, _, _, _ = _make_app(tmp_path, database_state="running", graph_view_store=GraphStore())
    response = client.get("/api/graph/facet-region?facet_id=facet-root&depth=1")
    assert response.status_code == 200
    assert response.json()["hits"][0]["classification_status"] == "inferred"
    assert response.json()["hits"][0]["evidence_ids"] == ["ev-tax", "ev-class"]
    assert "本文" not in response.text
    assert client.get("/api/graph/facet-region?facet_id=facet-root&depth=4").status_code == 503
    assert client.get("/api/graph/facet-region?facet_id=facet-root&depth=1", headers={"host": "malicious.example"}).status_code == 403


def test_self_intro_write_requires_local_origin_csrf_and_explicit_text(tmp_path):
    class Writer:
        def __init__(self):
            self.calls = []

        def save(self, *args):
            self.calls.append(args)
            return "asset-new"

    writer = Writer()
    client, _, _, _ = _make_app(tmp_path, database_state="running", self_intro_writer=writer)
    csrf = client.get("/api/status").json()["csrf_token"]
    payload = {"text": "自己紹介の補足", "expected_id": None}
    assert client.post("/api/self-introduction", json=payload).status_code == 403
    headers = {"Origin": LOCAL_DASHBOARD_ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": "edit-1"}
    response = client.post("/api/self-introduction", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"id": "asset-new"}
    assert writer.calls == [("owner-a", "自己紹介の補足", None, "edit-1")]


def test_factory_serves_built_page_status_and_stopped_overview_without_database_calls(tmp_path):
    client, _, _, store = _make_app(tmp_path)

    page = client.get("/")
    status = client.get("/api/status")
    overview = client.get("/api/overview")

    assert page.status_code == 200
    assert "Dots Dashboard" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert status.status_code == 200
    assert status.json()["services"] == {
        "database": "stopped",
        "intent": "running",
        "api": "running",
        "tunnel": "running",
    }
    assert overview.status_code == 200
    assert overview.json()["status"] == "stopped"
    assert store.owners == []


def test_factory_uses_fixed_start_and_stop_orders_with_intent_internal(tmp_path):
    client, events, _, _ = _make_app(tmp_path, database_state="running")
    status = client.get("/api/status").json()
    csrf = status["csrf_token"]
    headers = {"Origin": LOCAL_DASHBOARD_ORIGIN, "X-CSRF-Token": csrf}

    stopped = client.post(
        "/api/control/stop",
        json={"action": "stop"},
        headers={**headers, "Idempotency-Key": "stop-1"},
    )
    started = client.post(
        "/api/control/start",
        json={"action": "start"},
        headers={**headers, "Idempotency-Key": "start-1"},
    )

    assert stopped.status_code == started.status_code == 200
    assert events == [
        "intent:stop",
        "tunnel:stop",
        "api:stop",
        "database:stop",
        "database:start",
        "intent:start",
        "api:start",
        "tunnel:start",
    ]
    assert stopped.json()["stages"][0]["service"] == "intent"
    assert started.json()["stages"][-1]["service"] == "tunnel"
    assert LOCAL_DASHBOARD_START_ORDER == ("database", "intent", "api", "tunnel")
    assert LOCAL_DASHBOARD_STOP_ORDER == ("intent", "tunnel", "api", "database")
    assert "intent" in started.json()["services"]


def test_factory_returns_safe_overview_and_never_exposes_private_payload(tmp_path):
    store = FakeOverviewStore([
        _node(
            "idea-1",
            {
                "title": "Safe idea",
                "created_at": "2026-09-25T00:00:00Z",
                "private_notes": "keep this private",
            },
        ),
    ])
    client, _, _, _ = _make_app(tmp_path, database_state="running", overview_store=store)

    response = client.get("/api/overview")

    assert response.status_code == 200
    assert response.json()["count_basis"] == "stored_active_records"
    assert response.json()["counts"]["idea_records"] == 1
    assert response.json()["recent"][0]["title"] == "Safe idea"
    assert "keep this private" not in response.text
    assert store.owners == ["owner-a"]


def test_graph_proxy_is_optional_and_routes_only_fixed_search_path(tmp_path):
    calls = []

    def transport(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        return ProxyResponse(200, {"results": [{"id": "idea-1"}]})

    client, _, _, _ = _make_app(
        tmp_path,
        graph_proxy=LocalGraphSearchProxy(transport=transport),
    )
    response = client.post(
        "/v1/founder-graph/mcp/read/search",
        json={"query": "idea", "limit": 3},
        headers={"Origin": LOCAL_DASHBOARD_ORIGIN},
    )

    assert response.status_code == 200
    assert response.json() == {"results": [{"id": "idea-1"}]}
    assert len(calls) == 1
    assert calls[0][2] == {"query": "idea", "limit": 3}
