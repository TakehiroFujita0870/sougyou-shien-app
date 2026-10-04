from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from nebula.founder_graph_neo4j import Neo4jUnavailableError
from nebula.founder_graph_write import RevisionConflictError, WriteReceipt
from nebula.local_control import LocalControl, create_local_control_app
from nebula.local_record_lifecycle import LocalRecordLifecycleWriter


HOST = "127.0.0.1:8765"
ORIGIN = "http://127.0.0.1:8765"
OWNER_ID = "owner-a"


class DatabaseAdapter:
    def __init__(self, state: str = "running", *, fail: bool = False) -> None:
        self.state = state
        self.fail = fail

    def status(self) -> str:
        if self.fail:
            raise RuntimeError("private database diagnostic")
        return self.state

    def start(self) -> None:
        self.state = "running"

    def stop(self) -> None:
        self.state = "stopped"


class RecordingWriter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = []
        self.error = error

    def transition(self, kind, action, record_id, *, expected_revision, idempotency_key):
        self.calls.append((kind, action, record_id, expected_revision, idempotency_key))
        if self.error:
            raise self.error
        return WriteReceipt(
            f"{action}_{kind}", f"{record_id}-successor", kind, expected_revision + 1,
            idempotency_key, replayed=False,
        )


class OwnerBoundWritePort:
    """Minimal write port proving the route uses the injected owner boundary."""

    owner_id = OWNER_ID

    def __init__(self) -> None:
        self.calls = []

    def _receipt(self, operation, record_id, expected_revision, idempotency_key):
        self.calls.append((self.owner_id, operation, record_id, expected_revision, idempotency_key))
        return WriteReceipt(operation, f"{record_id}-archived", "idea", expected_revision + 1, idempotency_key)

    def archive_idea(self, record_id, *, expected_revision, idempotency_key):
        return self._receipt("archive_idea", record_id, expected_revision, idempotency_key)

    def restore_idea(self, record_id, *, expected_revision, idempotency_key):
        return self._receipt("restore_idea", record_id, expected_revision, idempotency_key)

    def archive_asset(self, record_id, *, expected_revision, idempotency_key):
        return self._receipt("archive_asset", record_id, expected_revision, idempotency_key)

    def restore_asset(self, record_id, *, expected_revision, idempotency_key):
        return self._receipt("restore_asset", record_id, expected_revision, idempotency_key)


class HomeStore:
    def __init__(self, rows=(), *, fail: bool = False) -> None:
        self.rows = tuple(rows)
        self.fail = fail
        self.owners = []

    def read_home(self, owner_id):
        self.owners.append(owner_id)
        if self.fail:
            raise RuntimeError("private deleted-record diagnostic")
        return self.rows


def make_client(*, writer=None, home_store=None, database=None, peer="127.0.0.1"):
    database = database or DatabaseAdapter()
    control = LocalControl(
        {"database": database},
        expected_host=HOST,
        allowed_origin=ORIGIN,
        start_order=("database",),
        stop_order=("database",),
    )
    app = create_local_control_app(
        control,
        home_store=home_store,
        overview_owner_id=OWNER_ID,
        record_lifecycle_writer=writer,
    )
    client = TestClient(app, base_url=f"http://{HOST}", client=(peer, 50000))
    client._test_control = control
    return client


def mutation_headers(client: TestClient) -> dict[str, str]:
    csrf = client.get("/api/status").json()["csrf_token"]
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf}


def lifecycle_payload(expected_revision=0, idempotency_key="archive-attempt"):
    return {"expected_revision": expected_revision, "idempotency_key": idempotency_key}


def home_row(identity, kind, status, payload, *, owner_id=OWNER_ID):
    return {
        "id": identity,
        "owner_id": owner_id,
        "node_type": kind,
        "status": status,
        "payload_json": json.dumps({"id": identity, "owner_id": owner_id, **payload}),
    }


def test_lifecycle_mutations_require_exact_local_host_origin_csrf_and_loopback():
    writer = RecordingWriter()
    client = make_client(writer=writer)
    valid = mutation_headers(client)
    path = "/api/records/idea/idea-1/archive"
    body = lifecycle_payload()

    assert client.post(path, json=body).status_code == 403
    assert client.post(path, json=body, headers={**valid, "Origin": "http://attacker.invalid"}).status_code == 403
    assert client.post(path, json=body, headers={**valid, "X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post(path, json=body, headers={**valid, "Host": "attacker.invalid"}).status_code == 403
    assert writer.calls == []

    remote_client = make_client(writer=writer, peer="203.0.113.10")
    remote_headers = {"Origin": ORIGIN, "X-CSRF-Token": remote_client._test_control.csrf_token}
    assert remote_client.post(path, json=body, headers=remote_headers).status_code == 403
    assert writer.calls == []


def test_deleted_records_get_uses_local_request_guards():
    store = HomeStore()
    client = make_client(home_store=store)
    assert client.get("/api/deleted-records", headers={"Host": "attacker.invalid"}).status_code == 403
    assert client.get("/api/deleted-records", headers={"Origin": "http://attacker.invalid"}).status_code == 403

    remote_client = make_client(home_store=store, peer="203.0.113.10")
    assert remote_client.get("/api/deleted-records").status_code == 403
    assert store.owners == []


def test_lifecycle_route_has_only_fixed_kind_and_action_and_validates_revision_floor():
    writer = RecordingWriter()
    client = make_client(writer=writer)
    headers = mutation_headers(client)

    assert client.post("/api/records/person/person-1/archive", json=lifecycle_payload(), headers=headers).status_code == 404
    assert client.post("/api/records/idea/idea-1/delete", json=lifecycle_payload(), headers=headers).status_code == 404
    assert client.post("/api/records/asset/asset-1/archive", json=lifecycle_payload(0), headers=headers).status_code == 400
    assert writer.calls == []


def test_idea_revision_zero_reaches_owner_bound_writer():
    writes = OwnerBoundWritePort()
    client = make_client(writer=LocalRecordLifecycleWriter(writes))
    headers = mutation_headers(client)

    response = client.post(
        "/api/records/idea/idea-1/archive",
        json=lifecycle_payload(0, "idea-zero"),
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"id": "idea-1-archived", "revision": 1, "replayed": False}
    assert writes.calls == [(OWNER_ID, "archive_idea", "idea-1", 0, "idea-zero")]


@pytest.mark.parametrize(
    ("error", "status", "safe_detail"),
    [
        (RevisionConflictError("private revision detail"), 409, "Record changed; reload before retrying"),
        (Neo4jUnavailableError("private Neo4j location"), 503, "Record lifecycle action could not be completed"),
    ],
)
def test_lifecycle_errors_are_mapped_without_storage_details(error, status, safe_detail):
    writer = RecordingWriter(error=error)
    client = make_client(writer=writer)

    response = client.post(
        "/api/records/idea/idea-1/archive",
        json=lifecycle_payload(3),
        headers=mutation_headers(client),
    )

    assert response.status_code == status
    assert response.json() == {"detail": safe_detail}
    assert "private" not in response.text
    assert "Neo4j location" not in response.text


def test_deleted_records_are_owner_scoped_and_allowlist_current_archived_records_only():
    store = HomeStore([
        home_row("idea-old", "idea", "archived", {
            "title": "旧版は非表示", "description": "旧履歴", "revision": 1,
            "created_at": "2026-09-20T00:00:00Z",
            "private_notes": "must not leak",
        }),
        home_row("idea-tip", "idea", "archived", {
            "title": "復元できる案", "description": "本人だけの説明", "revision": 2,
            "supersedes_id": "idea-old", "created_at": "2026-09-21T00:00:00Z",
            "source_text": "must not leak",
        }),
        home_row("asset-tip", "asset", "archived", {
            "name": "復元できる資料", "description": "手元の経験", "revision": 1,
            "created_at": "2026-09-22T00:00:00Z", "details": {"private": "must not leak"},
        }),
        home_row("idea-active", "idea", "active", {
            "title": "一覧に出さない案", "description": "active", "revision": 1,
            "created_at": "2026-09-23T00:00:00Z",
        }),
        home_row("owner-profile", "owner_profile", "archived", {
            "title": "プロフィールは対象外", "created_at": "2026-09-24T00:00:00Z",
        }),
    ])
    client = make_client(home_store=store)

    response = client.get("/api/deleted-records")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert store.owners == [OWNER_ID]
    assert response.json() == {
        "status": "ready",
        "records": [
            {"id": "asset-tip", "kind": "asset", "title": "復元できる資料", "description": "手元の経験", "revision": 1},
            {"id": "idea-tip", "kind": "idea", "title": "復元できる案", "description": "本人だけの説明", "revision": 2},
        ],
    }
    assert "must not leak" not in response.text
    assert "旧版は非表示" not in response.text
    assert "一覧に出さない案" not in response.text


def test_deleted_records_reports_stopped_and_sanitizes_failed_reads():
    stopped_store = HomeStore()
    stopped_client = make_client(home_store=stopped_store, database=DatabaseAdapter("stopped"))
    stopped = stopped_client.get("/api/deleted-records")
    assert stopped.status_code == 200
    assert stopped.json() == {"status": "stopped", "records": []}
    assert stopped_store.owners == []

    failed_store = HomeStore(fail=True)
    failed_client = make_client(home_store=failed_store)
    failed = failed_client.get("/api/deleted-records")
    assert failed.status_code == 503
    assert failed.json() == {"status": "failed", "records": []}
    assert "private deleted-record diagnostic" not in failed.text

    unavailable_client = make_client(home_store=HomeStore(), database=DatabaseAdapter(fail=True))
    unavailable = unavailable_client.get("/api/deleted-records")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"status": "failed", "records": []}
    assert "private database diagnostic" not in unavailable.text
