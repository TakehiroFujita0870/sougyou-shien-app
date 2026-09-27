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
