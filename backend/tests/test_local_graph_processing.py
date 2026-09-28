from __future__ import annotations

import pytest

from dots.local_graph_processing import GraphProcessingReadError, Neo4jGraphProcessingStore


class Result:
    def __init__(self, row):
        self.row = row

    def single(self):
        return self.row


class Transaction:
    def __init__(self, row, calls):
        self.row = row
        self.calls = calls

    def run(self, query, **params):
        self.calls.append((query, params))
        return Result(self.row)


class Session:
    def __init__(self, row, calls, options):
        self.row = row
        self.calls = calls
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute_read(self, callback):
        return callback(Transaction(self.row, self.calls))


class Driver:
    def __init__(self, row):
        self.row = row
        self.calls = []
        self.options = []

    def session(self, **options):
        self.options.append(options)
        return Session(self.row, self.calls, options)


def test_graph_processing_read_is_owner_scoped_aggregate_and_exposes_only_known_counts():
    driver = Driver({
        "pending": 2,
        "leased": 1,
        "succeeded": 5,
        "failed": 1,
        "superseded": 3,
        "unknown_state_count": 0,
    })

    counts = Neo4jGraphProcessingStore(driver).read_counts("owner-a")

    assert counts == {"pending": 2, "leased": 1, "succeeded": 5, "failed": 1, "superseded": 3}
    assert driver.options == [{"database": "neo4j"}]
    query, params = driver.calls[0]
    assert params == {"owner_id": "owner-a", "known_states": ["pending", "leased", "succeeded", "failed", "superseded"]}
    assert "MATCH (job:FounderGraphJob {owner_id: $owner_id})" in query
    assert "payload_json" not in query and "markdown" not in query
    assert not any(word in query.upper() for word in (" SET ", " DELETE ", " CREATE ", " MERGE "))


def test_graph_processing_read_requires_owner_and_rejects_unknown_or_invalid_counts():
    with pytest.raises(ValueError, match="owner_id"):
        Neo4jGraphProcessingStore(Driver({})).read_counts(" ")

    for row in [
        {"pending": 0, "leased": 0, "succeeded": 0, "failed": 0, "superseded": 0, "unknown_state_count": 1},
        {"pending": -1, "leased": 0, "succeeded": 0, "failed": 0, "superseded": 0, "unknown_state_count": 0},
        {"pending": True, "leased": 0, "succeeded": 0, "failed": 0, "superseded": 0, "unknown_state_count": 0},
        None,
    ]:
        with pytest.raises(GraphProcessingReadError):
            Neo4jGraphProcessingStore(Driver(row)).read_counts("owner-a")
