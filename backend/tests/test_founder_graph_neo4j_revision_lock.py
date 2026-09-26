from __future__ import annotations

import json

import pytest

from dots.founder_graph import NodeType, ResearchCampaign, Source
from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.founder_graph_write import (
    GraphWriteError,
    IdempotencyConflictError,
    RevisionConflictError,
    WriteReceipt,
    payload_fingerprint,
)


class Result:
    def __init__(self, row=None, rows=()):
        self.row = row
        self.rows = tuple(rows)

    def single(self, **_kwargs):
        return self.row

    def __iter__(self):
        return iter(self.rows if self.rows else (() if self.row is None else (self.row,)))


class RevisionLockSession:
    def __init__(self, *, existing_row, source_revision_rows=(), campaign_record=None, replay=None, replay_after_lock=None, lock_match=True):
        self.existing_row = existing_row
        self.source_revision_rows = tuple(source_revision_rows)
        self.campaign_record = campaign_record
        self.replay = replay
        self.replay_after_lock = replay_after_lock
        self.lock_match = lock_match
        self.audit_row = None
        self.audit_reads = 0
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None

    def execute_write(self, callback):
        return callback(self)

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (a:FounderGraphAudit" in query:
            self.audit_reads += 1
            row = self.audit_row or self.replay
            return Result(row)
        if "_dots_revision_write_lock" in query:
            if self.replay_after_lock is not None:
                self.audit_row = self.replay_after_lock
            row = self.existing_row if self.lock_match and self.existing_row and self.existing_row["owner_id"] == params.get("owner_id") else None
            return Result(row)
        if "MATCH (n {id: $id})" in query:
            return Result(self.existing_row)
        if "MATCH (r:SourceRevision {source_id: $source_id})" in query:
            return Result(rows=self.source_revision_rows)
        if "MATCH (n:ResearchCampaign" in query and "payload_json" in query:
            return Result(self.campaign_record)
        if "MATCH (h:FounderGraphHistory" in query:
            return Result()
        if "CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r)" in query:
            return Result({"id": params.get("source_revision_id")})
        return Result()


class Driver:
    def __init__(self, session):
        self.value = session

    def session(self, *, database):
        assert database == "neo4j"
        return self.value


def _campaign(*, aggregate_revision: int, purpose: str = "Inspect a synthetic product idea") -> ResearchCampaign:
    return ResearchCampaign(
        owner_id="owner-local",
        id="campaign-local",
        purpose=purpose,
        aggregate_revision=aggregate_revision,
    )


def _source(*, revision: int, title: str = "Synthetic source", current_revision_id=None) -> Source:
    return Source(
        owner_id="owner-local",
        id="source-local",
        title=title,
        revision=revision,
        current_revision_id=current_revision_id,
    )


@pytest.mark.parametrize(
    ("node", "node_type", "current_revision", "history"),
    [
        (_source(revision=2, current_revision_id="source-revision-2"), NodeType.SOURCE, 1, (
            {"id": "source-revision-1", "owner_id": "owner-local", "node_type": NodeType.SOURCE_REVISION.value,
             "source_id": "source-local", "revision": 1, "supersedes_id": None},
            {"id": "source-revision-2", "owner_id": "owner-local", "node_type": NodeType.SOURCE_REVISION.value,
             "source_id": "source-local", "revision": 2, "supersedes_id": "source-revision-1"},
        )),
        (_campaign(aggregate_revision=1), NodeType.RESEARCH_CAMPAIGN, 0, ()),
    ],
)
def test_existing_revisioned_node_locks_owner_target_before_validation_and_history_reads(
    node, node_type, current_revision, history,
):
    existing = {"owner_id": "owner-local", "node_type": node_type.value, "revision": current_revision}
    campaign_record = None
    if node_type is NodeType.RESEARCH_CAMPAIGN:
        from dots.founder_graph_neo4j import _node_properties

        current = _campaign(aggregate_revision=current_revision)
        properties = _node_properties(current)
        campaign_record = {
            "id": current.id, "owner_id": current.owner_id, "node_type": node_type.value,
            "revision": current_revision, "payload_json": properties["payload_json"],
        }
    session = RevisionLockSession(existing_row=existing, source_revision_rows=history, campaign_record=campaign_record)
    gateway = Neo4jGraphGateway(Driver(session), "owner-local")

    receipt = gateway.put_node(node, idempotency_key=f"update-{node_type.value}", expected_revision=current_revision)

    lock_index = next(i for i, (query, _) in enumerate(session.calls) if "_dots_revision_write_lock" in query)
    source_history_indexes = [i for i, (query, _) in enumerate(session.calls) if "MATCH (r:SourceRevision {source_id: $source_id})" in query]
    history_create_index = next(i for i, (query, _) in enumerate(session.calls) if "CREATE (h:FounderGraphHistory" in query)
    node_set_index = next(i for i, (query, _) in enumerate(session.calls) if "SET n = $properties" in query)
    audit_index = next(i for i, (query, _) in enumerate(session.calls) if "CREATE (a:FounderGraphAudit" in query)

    assert receipt.revision == current_revision + 1
    assert session.calls[lock_index][1]["owner_id"] == "owner-local"
    assert lock_index < history_create_index < node_set_index < audit_index
    assert all(lock_index < index for index in source_history_indexes)
    assert "_dots_revision_write_lock" not in json.dumps(session.calls[node_set_index][1]["properties"])


@pytest.mark.parametrize(
    ("node", "node_type", "expected_revision", "locked_revision"),
    [
        (_source(revision=2), NodeType.SOURCE, 1, 2),
        (_campaign(aggregate_revision=2), NodeType.RESEARCH_CAMPAIGN, 1, 2),
    ],
)
def test_stale_revision_after_lock_has_no_history_node_edge_or_audit_write(
    node, node_type, expected_revision, locked_revision,
):
    session = RevisionLockSession(existing_row={
        "owner_id": "owner-local", "node_type": node_type.value, "revision": locked_revision,
    })
    gateway = Neo4jGraphGateway(Driver(session), "owner-local")

    with pytest.raises(RevisionConflictError):
        gateway.put_node(node, idempotency_key=f"stale-{node_type.value}", expected_revision=expected_revision)

    assert sum("_dots_revision_write_lock" in query for query, _ in session.calls) == 1
    assert not any(
        marker in query
        for query, _ in session.calls
        for marker in ("CREATE (h:FounderGraphHistory", "SET n = $properties", "CURRENT_SOURCE_REVISION", "CREATE (a:FounderGraphAudit")
    )


def test_foreign_owner_target_is_not_locked_or_reference_validated():
    session = RevisionLockSession(existing_row={
        "owner_id": "owner-other", "node_type": NodeType.SOURCE.value, "revision": 1,
    })
    gateway = Neo4jGraphGateway(Driver(session), "owner-local")

    with pytest.raises(GraphWriteError, match="owner does not match"):
        gateway.put_node(
            _source(revision=2, current_revision_id="source-revision-2"),
            idempotency_key="foreign-source",
            expected_revision=1,
        )

    lock_query = next(query for query, _ in session.calls if "_dots_revision_write_lock" in query)
    assert "owner_id: $owner_id" in lock_query
    assert not any("SourceRevision" in query for query, _ in session.calls)
    assert not any(
        marker in query
        for query, _ in session.calls
        for marker in ("CREATE (h:FounderGraphHistory", "SET n = $properties", "CREATE (a:FounderGraphAudit")
    )


def test_revisioned_node_with_missing_expected_label_fails_closed_without_mutation():
    session = RevisionLockSession(
        existing_row={"owner_id": "owner-local", "node_type": NodeType.SOURCE.value, "revision": 1},
        lock_match=False,
    )
    gateway = Neo4jGraphGateway(Driver(session), "owner-local")

    with pytest.raises(GraphWriteError, match="could not be locked"):
        gateway.put_node(_source(revision=2), idempotency_key="missing-source-label", expected_revision=1)

    assert not any(
        marker in query
        for query, _ in session.calls
        for marker in ("CREATE (h:FounderGraphHistory", "SET n = $properties", "CREATE (a:FounderGraphAudit")
    )


def test_matching_initial_replay_returns_without_acquiring_revision_lock():
    node = _source(revision=2)
    fingerprint = payload_fingerprint("put_node", node, 1, "owner-local")
    replay = {
        "payload_fingerprint": fingerprint,
        "target_id": node.id,
        "target_type": NodeType.SOURCE.value,
        "revision": 2,
    }
    session = RevisionLockSession(existing_row=None, replay=replay)
    gateway = Neo4jGraphGateway(Driver(session), "owner-local")

    receipt = gateway.put_node(node, idempotency_key="already-recorded", expected_revision=1)

    assert receipt.replayed is True
    assert not any("_dots_revision_write_lock" in query for query, _ in session.calls)
    assert len(session.calls) == 1


def test_inflight_same_key_is_rechecked_after_lock_and_returns_receipt_without_persisted_changes():
    node = _source(revision=2)
    fingerprint = payload_fingerprint("put_node", node, 1, "owner-local")
    replay = {
        "payload_fingerprint": fingerprint,
        "target_id": node.id,
        "target_type": NodeType.SOURCE.value,
        "revision": 2,
    }
    session = RevisionLockSession(
        existing_row={"owner_id": "owner-local", "node_type": NodeType.SOURCE.value, "revision": 2},
        replay_after_lock=replay,
    )
    gateway = Neo4jGraphGateway(Driver(session), "owner-local")

    receipt = gateway.put_node(node, idempotency_key="concurrent-same-key", expected_revision=1)

    assert isinstance(receipt, WriteReceipt)
    assert receipt.replayed is True
    assert session.audit_reads == 2
    assert sum("_dots_revision_write_lock" in query for query, _ in session.calls) == 1
    assert not any(
        marker in query
        for query, _ in session.calls
        for marker in ("CREATE (h:FounderGraphHistory", "SET n = $properties", "CREATE (a:FounderGraphAudit")
    )


def test_inflight_same_key_with_different_payload_fails_after_lock_without_mutation():
    requested = _source(revision=2, title="Requested payload")
    conflicting = _source(revision=2, title="Different payload")
    replay = {
        "payload_fingerprint": payload_fingerprint("put_node", conflicting, 1, "owner-local"),
        "target_id": requested.id,
        "target_type": NodeType.SOURCE.value,
        "revision": 2,
    }
    session = RevisionLockSession(
        existing_row={"owner_id": "owner-local", "node_type": NodeType.SOURCE.value, "revision": 2},
        replay_after_lock=replay,
    )
    gateway = Neo4jGraphGateway(Driver(session), "owner-local")

    with pytest.raises(IdempotencyConflictError):
        gateway.put_node(requested, idempotency_key="concurrent-reused-key", expected_revision=1)

    assert session.audit_reads == 2
    assert not any(
        marker in query
        for query, _ in session.calls
        for marker in ("CREATE (h:FounderGraphHistory", "SET n = $properties", "CREATE (a:FounderGraphAudit")
    )
