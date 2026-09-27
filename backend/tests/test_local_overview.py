from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json

from dots.local_overview import Neo4jOverviewStore, read_local_overview


OWNER = "owner-a"


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        owner_id = parameters.get("owner_id")
        node_types = parameters.get("node_types")
        return FakeResult([
            row for row in self.rows
            if row.get("owner_id") == owner_id and row.get("node_type") in node_types
        ])


class FakeDriver:
    def __init__(self, rows):
        self.session_value = FakeSession(rows)
        self.session_parameters = None

    def session(self, **parameters):
        self.session_parameters = parameters
        return self.session_value


def stored(identity, kind, payload, *, status="active", owner_id=OWNER, revision=0):
    return {
        "id": identity,
        "owner_id": owner_id,
        "node_type": kind,
        "status": status,
        "revision": revision,
        "payload_json": json.dumps({"id": identity, "owner_id": owner_id, **payload}),
    }


def test_neo4j_store_uses_owner_scoped_persistence_query_and_safe_projection():
    rows = [
        stored("idea-old", "idea", {"title": "Old idea", "created_at": "2026-09-01T00:00:00+00:00"}),
        stored("idea-new", "idea", {"title": "Current idea", "created_at": "2026-09-03T00:00:00+00:00", "supersedes_id": "idea-old"}, revision=1),
        stored("person-1", "person", {"name": "Mika", "created_at": "2026-09-02T03:00:00+03:00", "contact": {"email": "private@example.test"}}),
        stored("asset-1", "asset", {"name": "Market research", "created_at": "2026-09-04T00:00:00Z", "details": {"private": "secret"}}),
        stored("report-old", "report_version", {"created_at": "2026-09-05T00:00:00Z", "supersedes_id": None}),
        stored("report-new", "report_version", {"created_at": "2026-09-06T00:00:00Z", "supersedes_id": "report-old"}),
        stored("idea-deleted", "idea", {"title": "Deleted", "created_at": "2026-09-07T00:00:00Z"}, status="archived"),
        stored("idea-status-superseded", "idea", {"title": "Superseded", "created_at": "2026-09-08T00:00:00Z"}, status="superseded"),
    ]
    driver = FakeDriver(rows)

    result = read_local_overview(Neo4jOverviewStore(driver), owner_id=OWNER)

    query, parameters = driver.session_value.calls[0]
    assert "n.owner_id = $owner_id" in query
    assert parameters["owner_id"] == OWNER
    assert set(parameters["node_types"]) == {"idea", "person", "asset", "report_version"}
    assert driver.session_parameters == {"database": "neo4j"}
    assert result.status == "ready"
    assert result.count_basis == "stored_active_records"
    assert result.counts == {"idea_records": 1, "person_records": 1, "asset_records": 1, "report_version_records": 1}
    assert [(item.id, item.title) for item in result.recent] == [
        ("report-new", "調査レポート"),
        ("asset-1", "Market research"),
        ("idea-new", "Current idea"),
        ("person-1", "Mika"),
    ]
    serialized = json.dumps(asdict(result), ensure_ascii=False, default=lambda value: value.isoformat())
    assert "private@example.test" not in serialized
    assert '"private"' not in serialized
    assert "report-old" not in serialized


def test_only_owner_records_are_returned_by_database_adapter():
    rows = [
        stored("idea-1", "idea", {"title": "Mine", "created_at": "2026-09-01T00:00:00Z"}),
        stored("idea-foreign", "idea", {"title": "Foreign", "created_at": "2026-09-02T00:00:00Z"}, owner_id="owner-b"),
    ]
    result = read_local_overview(Neo4jOverviewStore(FakeDriver(rows)), owner_id=OWNER)
    assert result.counts["idea_records"] == 1
    assert [item.title for item in result.recent] == ["Mine"]


def test_stopped_empty_and_driver_failure_are_distinct_and_sanitized():
    empty = read_local_overview(Neo4jOverviewStore(FakeDriver([])), owner_id=OWNER)
    stopped = read_local_overview(Neo4jOverviewStore(FakeDriver([])), owner_id=OWNER, storage_status="stopped")

    class BrokenDriver:
        def session(self, **_parameters):
            raise RuntimeError("private driver details")

    failed = read_local_overview(Neo4jOverviewStore(BrokenDriver()), owner_id=OWNER)
    assert empty.status == "empty"
    assert stopped.status == "stopped"
    assert failed.status == "failed"
    assert "private driver details" not in json.dumps(asdict(failed))


def test_invalid_payload_timestamp_identity_or_missing_safe_title_fails_closed():
    bad_rows = [
        stored("bad-time", "idea", {"title": "Idea", "created_at": "not-a-time"}),
        stored("bad-owner", "idea", {"title": "Idea", "created_at": "2026-09-01T00:00:00Z", "owner_id": "owner-b"}),
        stored("bad-title", "asset", {"name": "", "created_at": "2026-09-01T00:00:00Z"}),
    ]
    for row in bad_rows:
        result = read_local_overview(Neo4jOverviewStore(FakeDriver([row])), owner_id=OWNER)
        assert result.status == "failed"
        assert not result.recent


def test_recent_limit_is_capped_and_timestamps_are_normalized_to_utc():
    rows = [
        stored(f"idea-{index}", "idea", {"title": f"Idea {index}", "created_at": f"2026-09-{index + 1:02d}T00:00:00Z"})
        for index in range(12)
    ]
    result = read_local_overview(Neo4jOverviewStore(FakeDriver(rows)), owner_id=OWNER, recent_limit=3)
    assert len(result.recent) == 3
    assert result.recent[0].updated_at.tzinfo == timezone.utc
