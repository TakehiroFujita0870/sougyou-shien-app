from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dots.local_control import LocalControl, create_local_control_app
from dots.local_dashboard_host import DashboardBuildMissing, mount_local_dashboard
from dots.local_overview import StoredOverviewNode


class FakeAdapter:
    def __init__(self) -> None:
        self.state = "stopped"
        self.calls: list[str] = []
        self.fail_on: str | None = None

    def status(self) -> str:
        return self.state

    def start(self) -> None:
        self.calls.append("start")
        if self.fail_on == "start":
            raise RuntimeError("synthetic failure")
        self.state = "running"

    def stop(self) -> None:
        self.calls.append("stop")
        if self.fail_on == "stop":
            raise RuntimeError("synthetic failure")
        self.state = "stopped"


class FakeOverviewStore:
    def __init__(self, nodes=(), *, fail: bool = False) -> None:
        self.nodes = tuple(nodes)
        self.fail = fail
        self.owners: list[str] = []

    def read_overview(self, owner_id: str):
        self.owners.append(owner_id)
        if self.fail:
            raise RuntimeError("private storage diagnostic")
        return self.nodes


class FakeGraphProcessingStore:
    def __init__(self, counts=None, *, fail: bool = False) -> None:
        self.counts = counts if counts is not None else {
            "pending": 1, "leased": 0, "succeeded": 2, "failed": 0, "superseded": 0,
        }
        self.fail = fail
        self.owners: list[str] = []

    def read_counts(self, owner_id: str):
        self.owners.append(owner_id)
        if self.fail:
            raise RuntimeError("private graph processing diagnostic")
        return self.counts


def _overview_node(identity: str, kind: str, payload: dict[str, object]) -> StoredOverviewNode:
    return StoredOverviewNode(
        id=identity,
        owner_id="owner-a",
        node_type=kind,
        status="active",
        revision=1,
        payload_json=json.dumps({"id": identity, "owner_id": "owner-a", **payload}),
    )


@pytest.fixture
def setup_control():
    adapters = {name: FakeAdapter() for name in ("tunnel", "api", "database")}
    control = LocalControl(
        adapters,
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database", "api", "tunnel"),
        stop_order=("tunnel", "api", "database"),
    )
    client = TestClient(create_local_control_app(control), base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
    auth: dict[str, str] = {}
    status = client.get("/api/status", headers=auth)
    assert status.status_code == 200
    csrf = status.json()["csrf_token"]
    mutation = {
        **auth,
        "Origin": "http://127.0.0.1:8765",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": "attempt-1",
    }
    return client, adapters, control, auth, mutation


def test_no_secret_mode_allows_status_and_fixed_mutation(setup_control):
    client, adapters, _, _, mutation = setup_control
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert "csrf_token" in status.json()
    assert "local_secret" not in status.json()
    assert client.post("/api/control/start", json={"action": "start"}, headers=mutation).status_code == 200
    assert adapters["database"].state == "running"


def test_configured_bearer_secret_remains_optional_authentication():
    control = LocalControl(
        {"fake": FakeAdapter()},
        local_secret="test-local-secret",
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("fake",),
        stop_order=("fake",),
    )
    client = TestClient(create_local_control_app(control), base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer test-local-secret"}).status_code == 200
    assert client.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_host_origin_and_csrf_are_checked(setup_control):
    client, adapters, _, _, mutation = setup_control
    assert client.get("/api/status", headers={"Host": "attacker.invalid"}).status_code == 403
    for header, value in (("Origin", "http://attacker.invalid"), ("X-CSRF-Token", "wrong")):
        assert client.post("/api/control/start", json={"action": "start"}, headers={**mutation, header: value}).status_code == 403
    assert all(adapter.calls == [] for adapter in adapters.values())


def test_hostile_origin_is_rejected_for_status_and_dns_rebinding_host_is_rejected(setup_control):
    client, _, _, _, _ = setup_control
    hostile_origin = client.get("/api/status", headers={"Origin": "http://attacker.invalid"})
    rebound_host = client.get("/api/status", headers={"Host": "attacker.invalid"})
    assert hostile_origin.status_code == 403
    assert rebound_host.status_code == 403
    assert "access-control-allow-origin" not in hostile_origin.headers


def test_non_loopback_client_is_rejected():
    control = LocalControl(
        {"fake": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("fake",),
        stop_order=("fake",),
    )
    client = TestClient(
        create_local_control_app(control),
        base_url="http://127.0.0.1:8765",
        client=("203.0.113.10", 50000),
    )
    assert client.get("/api/status").status_code == 403


def test_overview_returns_only_safe_owner_scoped_projection():
    control = LocalControl(
        {"database": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database",),
        stop_order=("database",),
    )
    control.adapters["database"].state = "running"
    store = FakeOverviewStore([
        _overview_node(
            "idea-1",
            "idea",
            {
                "title": "Safe title",
                "created_at": "2026-09-25T00:00:00Z",
                "private_notes": "private payload value",
            },
        ),
    ])
    client = TestClient(
        create_local_control_app(control, overview_store=store, overview_owner_id="owner-a"),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/api/overview")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "ready",
        "count_basis": "stored_active_records",
        "counts": {"idea_records": 1, "person_records": 0, "asset_records": 0, "report_version_records": 0},
        "recent": [
            {
                "id": "idea-1",
                "kind": "idea",
                "title": "Safe title",
                "updated_at": "2026-09-25T00:00:00+00:00",
            },
        ],
    }
    assert store.owners == ["owner-a"]
    assert "private payload value" not in response.text


def test_stopped_overview_skips_store_and_stays_under_local_request_guards():
    control = LocalControl(
        {"database": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database",),
        stop_order=("database",),
    )
    store = FakeOverviewStore()
    client = TestClient(
        create_local_control_app(control, overview_store=store, overview_owner_id="owner-a"),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/api/overview")

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert response.json()["counts"] == {
        "idea_records": 0,
        "person_records": 0,
        "asset_records": 0,
        "report_version_records": 0,
    }
    assert store.owners == []
    assert client.get("/api/overview", headers={"Host": "attacker.invalid"}).status_code == 403
    assert client.get("/api/overview", headers={"Origin": "http://attacker.invalid"}).status_code == 403


def test_graph_processing_status_is_owner_scoped_and_keeps_exact_job_states():
    control = LocalControl(
        {"database": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database",),
        stop_order=("database",),
    )
    control.adapters["database"].state = "running"
    store = FakeGraphProcessingStore()
    client = TestClient(
        create_local_control_app(
            control,
            overview_owner_id="owner-a",
            graph_processing_store=store,
        ),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/api/graph-processing")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "ready", "counts": store.counts}
    assert store.owners == ["owner-a"]
    assert client.get("/api/graph-processing", headers={"Host": "attacker.invalid"}).status_code == 403


def test_graph_processing_status_does_not_show_zero_when_storage_stopped_or_read_fails():
    control = LocalControl(
        {"database": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database",),
        stop_order=("database",),
    )
    store = FakeGraphProcessingStore(fail=True)
    client = TestClient(
        create_local_control_app(
            control,
            overview_owner_id="owner-a",
            graph_processing_store=store,
        ),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
    )

    stopped = client.get("/api/graph-processing")
    assert stopped.status_code == 503
    assert stopped.json() == {"status": "unavailable"}
    assert store.owners == []

    control.adapters["database"].state = "running"
    failed = client.get("/api/graph-processing")
    assert failed.status_code == 503
    assert failed.json() == {"status": "failed"}
    assert store.owners == ["owner-a"]
    assert "private graph processing diagnostic" not in failed.text


def test_graph_processing_status_rejects_store_fields_outside_the_count_allowlist():
    control = LocalControl(
        {"database": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database",),
        stop_order=("database",),
    )
    control.adapters["database"].state = "running"
    store = FakeGraphProcessingStore({
        "pending": 0, "leased": 0, "succeeded": 0, "failed": 0, "superseded": 0,
        "report_text": "PRIVATE",
    })
    client = TestClient(
        create_local_control_app(control, overview_owner_id="owner-a", graph_processing_store=store),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/api/graph-processing")

    assert response.status_code == 503
    assert response.json() == {"status": "failed"}
    assert "PRIVATE" not in response.text


def test_overview_read_failure_returns_sanitized_service_unavailable():
    control = LocalControl(
        {"database": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database",),
        stop_order=("database",),
    )
    control.adapters["database"].state = "running"
    store = FakeOverviewStore(fail=True)
    client = TestClient(
        create_local_control_app(control, overview_store=store, overview_owner_id="owner-a"),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/api/overview")

    assert response.status_code == 503
    assert response.json()["status"] == "failed"
    assert response.json()["count_basis"] == "stored_active_records"
    assert "private storage diagnostic" not in response.text


def test_local_processes_are_not_authenticated_by_browser_origin_checks(setup_control):
    """No-secret mode is browser-origin protection, not local process/user auth."""
    client, adapters, _, _, _ = setup_control
    csrf = client.get("/api/status").json()["csrf_token"]
    response = client.post(
        "/api/control/start",
        json={"action": "start"},
        headers={
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "local-process-attempt",
        },
    )
    assert response.status_code == 200
    assert adapters["database"].state == "running"


def test_start_stop_use_only_fixed_order_and_repeat_is_idempotent(setup_control):
    client, adapters, _, _, mutation = setup_control
    first = client.post("/api/control/start", json={"action": "start"}, headers=mutation)
    replay = client.post("/api/control/start", json={"action": "start"}, headers=mutation)
    assert first.status_code == replay.status_code == 200
    assert [stage["service"] for stage in first.json()["stages"]] == ["database", "api", "tunnel"]
    assert replay.json()["replayed"] is True
    assert all(adapter.calls == ["start"] for adapter in adapters.values())
    conflicting_replay = client.post(
        "/api/control/stop",
        json={"action": "stop"},
        headers=mutation,
    )
    assert conflicting_replay.status_code == 409
    assert all(adapter.calls == ["start"] for adapter in adapters.values())

    stop_headers = {**mutation, "Idempotency-Key": "attempt-2"}
    stopped = client.post("/api/control/stop", json={"action": "stop"}, headers=stop_headers)
    assert [stage["service"] for stage in stopped.json()["stages"]] == ["tunnel", "api", "database"]
    assert all(adapter.calls == ["start", "stop"] for adapter in adapters.values())


def test_missing_idempotency_key_or_mismatched_fixed_action_is_rejected(setup_control):
    client, adapters, _, _, mutation = setup_control
    no_key = {key: value for key, value in mutation.items() if key != "Idempotency-Key"}
    assert client.post("/api/control/start", json={"action": "start"}, headers=no_key).status_code == 400
    assert client.post("/api/control/restart", json={"action": "restart"}, headers=mutation).status_code == 404
    assert client.post("/api/control/start", json={"action": "stop"}, headers=mutation).status_code == 404
    assert all(adapter.calls == [] for adapter in adapters.values())


def test_failed_stage_is_reported_and_later_services_are_not_touched(setup_control):
    client, adapters, _, _, mutation = setup_control
    adapters["api"].fail_on = "start"
    response = client.post("/api/control/start", json={"action": "start"}, headers=mutation)
    assert response.status_code == 200
    assert response.json()["status"] == "partial_failure"
    assert response.json()["stages"] == [
        {"service": "database", "status": "completed"},
        {"service": "api", "status": "failed"},
    ]
    assert adapters["tunnel"].calls == []


def test_app_refuses_non_loopback_bind():
    control = LocalControl(
        {"fake": FakeAdapter()},
        local_secret="test",
        expected_host="127.0.0.1:1",
        allowed_origin="http://127.0.0.1:1",
        start_order=("fake",),
        stop_order=("fake",),
    )
    with pytest.raises(ValueError, match="loopback"):
        create_local_control_app(control, bind_host="0.0.0.0")


def test_built_dashboard_and_assets_are_served_on_control_origin_while_database_is_stopped(tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>Dots local dashboard</main>", encoding="utf-8")
    (assets / "app.js").write_text("window.dotsReady = true;", encoding="utf-8")
    control = LocalControl(
        {"database": FakeAdapter()},
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
        start_order=("database",),
        stop_order=("database",),
    )
    store = FakeOverviewStore()
    app = create_local_control_app(control, overview_store=store, overview_owner_id="owner-a")
    mount_local_dashboard(
        app,
        dist_dir=dist,
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))

    page = client.get("/")
    asset = client.get("/assets/app.js")
    overview = client.get("/api/overview")

    assert page.status_code == 200
    assert "Dots local dashboard" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert asset.status_code == 200
    assert asset.text == "window.dotsReady = true;"
    assert asset.headers["cache-control"] == "no-store"
    assert overview.status_code == 200
    assert overview.json()["status"] == "stopped"
    assert store.owners == []


def test_dashboard_host_origin_loopback_and_traversal_guards(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("safe app", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside secret", encoding="utf-8")
    app = create_local_control_app(
        LocalControl(
            {"database": FakeAdapter()},
            expected_host="127.0.0.1:8765",
            allowed_origin="http://127.0.0.1:8765",
            start_order=("database",),
            stop_order=("database",),
        ),
    )
    mount_local_dashboard(
        app,
        dist_dir=dist,
        expected_host="127.0.0.1:8765",
        allowed_origin="http://127.0.0.1:8765",
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))

    assert client.get("/", headers={"Host": "attacker.invalid"}).status_code == 403
    assert client.get("/", headers={"Origin": "http://attacker.invalid"}).status_code == 403
    assert client.get("/assets/app.js", headers={"Host": "attacker.invalid"}).status_code == 403
    assert client.get("/assets/app.js", headers={"Origin": "http://attacker.invalid"}).status_code == 403
    assert client.get("/missing.js").status_code == 404
    assert client.get("/api/not-found").status_code == 404
    traversal = client.get("/%2e%2e/outside.txt")
    assert traversal.status_code == 404
    assert "outside secret" not in traversal.text

    remote_client = TestClient(app, base_url="http://127.0.0.1:8765", client=("203.0.113.10", 50000))
    assert remote_client.get("/").status_code == 403


def test_dashboard_mount_fails_closed_without_built_dist_or_index(tmp_path):
    control_app = create_local_control_app(
        LocalControl(
            {"database": FakeAdapter()},
            expected_host="127.0.0.1:8765",
            allowed_origin="http://127.0.0.1:8765",
            start_order=("database",),
            stop_order=("database",),
        ),
    )
    with pytest.raises(DashboardBuildMissing):
        mount_local_dashboard(
            control_app,
            dist_dir=tmp_path / "not-built",
            expected_host="127.0.0.1:8765",
            allowed_origin="http://127.0.0.1:8765",
        )
    empty_dist = tmp_path / "empty-dist"
    empty_dist.mkdir()
    with pytest.raises(DashboardBuildMissing):
        mount_local_dashboard(
            control_app,
            dist_dir=empty_dist,
            expected_host="127.0.0.1:8765",
            allowed_origin="http://127.0.0.1:8765",
        )
