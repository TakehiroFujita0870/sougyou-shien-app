"""The local controller's production wiring must remain inert at import time."""

from dots import local_dashboard_runtime as runtime
from dots.local_overview import StoredOverviewNode


def test_runtime_constructs_fixed_localhost_app_without_contacting_services():
    assert runtime.LIVE_OWNER_ID == "owner-mvp"
    assert runtime.LIVE_DOCKER_CLI.startswith("/mnt/c/")
    app = runtime.create_runtime_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/status" in paths
    assert "/api/overview" in paths
    assert "/api/control/{action}" in paths
    assert any(type(route).__name__ == "_IncludedRouter" for route in app.routes)


def test_overview_driver_is_opened_only_for_actual_read(monkeypatch):
    calls = []

    class FakeDriver:
        def close(self):
            calls.append("closed")

    driver = FakeDriver()
    monkeypatch.setattr(runtime, "create_neo4j_driver_from_env", lambda: calls.append("opened") or driver)
    monkeypatch.setattr(
        runtime.Neo4jOverviewStore,
        "read_overview",
        lambda self, owner_id: calls.append(owner_id) or (StoredOverviewNode("i", owner_id, "idea", None, 1, "{}"),),
    )
    store = runtime.OnDemandNeo4jOverviewStore()
    assert calls == []
    assert len(store.read_overview("owner-mvp")) == 1
    assert calls == ["opened", "owner-mvp", "closed"]


def test_home_runtime_forwards_guarded_citations_and_closes_connection(monkeypatch):
    calls = []

    class Driver:
        def close(self):
            calls.append("closed")

    monkeypatch.setattr(runtime, "create_neo4j_driver_from_env", lambda: calls.append("opened") or Driver())
    expected = {"evidence": {"url": "https://example.test/report", "title": "公開資料"}}
    monkeypatch.setattr(runtime.Neo4jHomeStore, "read_citations",
                        lambda self, owner_id, ids: calls.append((owner_id, ids)) or expected)
    store = runtime.OnDemandNeo4jHomeStore()
    assert calls == []
    assert store.read_citations("owner-mvp", ["evidence"]) == expected
    assert calls == ["opened", ("owner-mvp", ["evidence"]), "closed"]


def test_home_runtime_closes_connection_when_citation_projection_fails(monkeypatch):
    import pytest

    closed = []

    class Driver:
        def close(self):
            closed.append(True)

    def fail(*args):
        raise ValueError("invalid citation lineage")

    monkeypatch.setattr(runtime, "create_neo4j_driver_from_env", Driver)
    monkeypatch.setattr(runtime.Neo4jHomeStore, "read_citations", fail)
    with pytest.raises(ValueError, match="invalid citation lineage"):
        runtime.OnDemandNeo4jHomeStore().read_citations("owner-mvp", ["evidence"])
    assert closed == [True]


def test_graph_runtime_forwards_current_citations_and_closes_connection(monkeypatch):
    calls = []

    class Driver:
        def close(self):
            calls.append("closed")

    monkeypatch.setattr(runtime, "create_neo4j_driver_from_env", lambda: calls.append("opened") or Driver())
    expected = ({"idea_id": "idea-1", "source_id": "source-1", "evidence_id": "evidence-1", "url": "https://example.test/source"},)
    monkeypatch.setattr(runtime.Neo4jGraphViewStore, "read_idea_citations",
                        lambda self, owner_id, ids: calls.append((owner_id, ids)) or expected)
    store = runtime.OnDemandNeo4jGraphViewStore()
    assert store.read_idea_citations("owner-mvp", ["idea-1"]) == expected
    assert calls == ["opened", ("owner-mvp", ["idea-1"]), "closed"]
