from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

import pytest

from dots.founder_graph import (
    Idea,
    NodeType,
    PersonAsset,
    RelationType,
    Relationship,
    Source,
    SourceRevision,
    build_content_chunks,
)
from dots.founder_graph_neo4j import (
    Neo4jGraphGateway,
    Neo4jQueryContractError,
    Neo4jUnavailableError,
)
from dots.founder_graph_write import (
    GraphWriteError,
    GraphWriteNotFoundError,
    RevisionConflictError,
    payload_fingerprint,
)


@dataclass
class FakeResult:
    row: dict[str, object] | None = None
    rows: tuple[dict[str, object], ...] = ()

    def single(self, **_kwargs):
        return self.row

    def __iter__(self):
        return iter(self.rows if self.rows else (() if self.row is None else (self.row,)))


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.audit_row: dict[str, object] | None = None
        self.existing_row: dict[str, object] | None = None
        self.endpoint_row: dict[str, object] | None = None
        self.source_row: dict[str, object] | None = None
        self.source_revision_rows: tuple[dict[str, object], ...] = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self) -> None:
        return None

    def execute_write(self, callback):
        return callback(self)

    def execute_read(self, callback):
        return callback(self)

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (a:FounderGraphAudit" in query:
            if self.audit_row is not None and self.audit_row.get("idempotency_key") == params.get("idempotency_key"):
                return FakeResult(self.audit_row)
            return FakeResult()
        if "_dots_revision_write_lock" in query:
            return FakeResult(self.existing_row)
        if "MATCH (n {id: $id})" in query:
            return FakeResult(self.existing_row)
        if "MATCH (s:Source {id: $source_id})" in query:
            return FakeResult(self.source_row)
        if "MATCH (r:SourceRevision {source_id: $source_id})" in query:
            return FakeResult(rows=self.source_revision_rows)
        if "MATCH (a {id: $source_id}), (b {id: $target_id})" in query:
            return FakeResult(self.endpoint_row)
        if "CREATE (a:FounderGraphAudit" in query:
            self.audit_row = {
                "payload_fingerprint": params.get("payload_fingerprint"),
                "target_id": params.get("target_id"),
                "target_type": params.get("target_type"),
                "revision": params.get("revision", 0),
                "idempotency_key": params.get("idempotency_key"),
                "source_revision_id": params.get("source_revision_id"),
                "content_chunk_ids": params.get("content_chunk_ids"),
            }
        return FakeResult()


class FakeDriver:
    def __init__(self) -> None:
        self.session_value = FakeSession()

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


class LegacyCaptureSession(FakeSession):
    def __init__(self, *, audit_row: dict[str, object], source_revision: SourceRevision) -> None:
        super().__init__()
        self.audit_row = dict(audit_row)
        self.original_audit_row = dict(audit_row)
        self.source_revision = source_revision
        self.chunks: dict[str, dict[str, object]] = {}
        self.backfill_events: dict[str, dict[str, object]] = {}

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (a:FounderGraphAudit" in query:
            if params.get("idempotency_key") == self.audit_row.get("idempotency_key"):
                return FakeResult(self.audit_row)
            return FakeResult()
        if "MATCH (i:Idea" in query and "SourceRevision" in query:
            if (
                params.get("owner_id") != self.source_revision.owner_id
                or params.get("source_revision_id") != self.source_revision.id
            ):
                return FakeResult()
            return FakeResult({
                "owner_id": self.source_revision.owner_id,
                "payload_json": json.dumps({
                    "source_id": self.source_revision.source_id,
                    "content_hash": self.source_revision.content_hash,
                    "revision": self.source_revision.revision,
                }),
            })
        if "MATCH (n) WHERE n.id IN $chunk_ids" in query:
            rows = tuple(
                {
                    "id": chunk_id,
                    "owner_id": props["owner_id"],
                    "labels": ["ContentChunk"],
                    "payload_json": props["payload_json"],
                }
                for chunk_id, props in self.chunks.items()
                if chunk_id in params.get("chunk_ids", ())
            )
            return FakeResult(rows=rows)
        if "CREATE (n:ContentChunk)" in query:
            properties = dict(params["properties"])
            self.chunks[str(properties["id"])] = properties
            return FakeResult()
        if "MERGE (a:FounderGraphAudit {id: $audit_id})" in query:
            audit_id = str(params["audit_id"])
            event = self.backfill_events.setdefault(audit_id, {
                "id": audit_id,
                "owner_id": params["owner_id"],
                "actor": params["actor"],
                "operation": params["operation"],
                "target_id": params["target_id"],
                "target_type": params["target_type"],
                "revision": params["revision"],
                "idempotency_key": params["idempotency_key"],
                "payload_fingerprint": params["payload_fingerprint"],
                "source_revision_id": params["source_revision_id"],
                "content_chunk_ids": params["content_chunk_ids"],
            })
            return FakeResult(event)
        return FakeResult()


class RollbackSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.created_nodes: list[str] = []

    def execute_write(self, callback):
        calls = list(self.calls)
        audit_row = self.audit_row
        created_nodes = list(self.created_nodes)
        try:
            return callback(self)
        except Exception:
            self.calls = calls
            self.audit_row = audit_row
            self.created_nodes = created_nodes
            raise

    def run(self, query: str, **params):
        if "CREATE (a:FounderGraphAudit" in query:
            raise RuntimeError("audit sink unavailable")
        if "CREATE (n:" in query and "SET n = $properties" in query:
            self.created_nodes.append(str(params["properties"]["id"]))
        return super().run(query, **params)


class ChunkFailureSession(RollbackSession):
    def run(self, query: str, **params):
        if "CREATE (n:ContentChunk)" in query:
            raise RuntimeError("content chunk write failed")
        return super().run(query, **params)


def test_put_node_uses_static_label_parameterized_payload_and_audit() -> None:
    driver = FakeDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    node = Idea(owner_id="owner-1", id="idea-1", title="title with ) MATCH (n)")

    receipt = gateway.put_node(node, idempotency_key="idea-1", operation="capture_idea")
    replay = gateway.put_node(node, idempotency_key="idea-1", operation="capture_idea")

    assert receipt.target_id == node.id
    assert replay.replayed is True
    create_calls = [call for call in driver.session_value.calls if "CREATE (n:Idea)" in call[0]]
    assert len(create_calls) == 1
    query, params = create_calls[0]
    assert node.title not in query
    assert params["properties"]["payload_json"]
    assert any("FounderGraphAudit" in query for query, _params in driver.session_value.calls)


def test_capture_idea_writes_source_chain_in_one_transaction_and_replays() -> None:
    driver = FakeDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    idea = Idea(owner_id="owner-1", id="idea-capture-1", title="Captured idea")
    source = Source(
        owner_id="owner-1",
        id="source-capture-1",
        title="Captured conversation",
        kind="conversation",
        revision=1,
        current_revision_id="source-revision-capture-1",
    )
    source_revision = SourceRevision(
        owner_id="owner-1",
        id="source-revision-capture-1",
        source_id=source.id,
        content="Raw conversation",
    )

    receipt = gateway.capture_idea(
        idea,
        source,
        source_revision,
        idempotency_key="capture-1",
    )
    replay = gateway.capture_idea(
        idea,
        source,
        source_revision,
        idempotency_key="capture-1",
    )

    assert receipt.target_id == idea.id
    assert replay.replayed is True
    assert receipt.source_revision_id == source_revision.id
    assert replay.source_revision_id == receipt.source_revision_id
    assert replay.content_chunk_ids == receipt.content_chunk_ids
    queries = [query for query, _params in driver.session_value.calls]
    assert sum("CREATE (n:Source)" in query for query in queries) == 1
    assert sum("CREATE (n:SourceRevision)" in query for query in queries) == 1
    assert sum("CREATE (n:ContentChunk)" in query for query in queries) == 1
    assert sum("CREATE (n:Idea)" in query for query in queries) == 1
    assert sum("CREATE (a:FounderGraphAudit" in query for query in queries) == 1


def test_capture_idea_backfills_legacy_audit_refs_once_and_returns_opaque_stable_receipt(caplog) -> None:
    owner_id = "owner-1"
    idea = Idea(owner_id=owner_id, id="idea-legacy-capture", title="Legacy idea")
    source = Source(
        owner_id=owner_id,
        id="source-legacy-capture",
        title="Legacy source",
        kind="conversation",
        revision=1,
        current_revision_id="source-revision-legacy-capture",
    )
    source_revision = SourceRevision(
        owner_id=owner_id,
        id="source-revision-legacy-capture",
        source_id=source.id,
        content="Private legacy conversation text.",
    )
    idempotency_key = "legacy-capture"
    legacy_audit = {
        "id": "audit-legacy-capture",
        "owner_id": owner_id,
        "actor": "local-owner",
        "operation": "capture_idea",
        "target_id": idea.id,
        "target_type": NodeType.IDEA.value,
        "revision": 0,
        "idempotency_key": idempotency_key,
        "payload_fingerprint": payload_fingerprint(
            "capture_idea", idea, source, source_revision, owner_id
        ),
    }
    driver = FakeDriver()
    legacy_session = LegacyCaptureSession(audit_row=legacy_audit, source_revision=source_revision)
    driver.session_value = legacy_session
    gateway = Neo4jGraphGateway(driver, owner_id)
    expected_chunks = build_content_chunks(source_revision)

    first = gateway.capture_idea(idea, source, source_revision, idempotency_key=idempotency_key)
    original_audit_after_first = dict(legacy_session.audit_row)
    replay = gateway.capture_idea(idea, source, source_revision, idempotency_key=idempotency_key)

    expected_chunk_ids = tuple(chunk.id for chunk in expected_chunks)
    assert first.replayed is True
    assert replay.replayed is True
    assert first.source_revision_id == replay.source_revision_id == source_revision.id
    assert first.content_chunk_ids == replay.content_chunk_ids == expected_chunk_ids
    assert len(legacy_session.chunks) == len(expected_chunks)
    assert sum("CREATE (n:ContentChunk)" in query for query, _params in legacy_session.calls) == len(expected_chunks)
    assert legacy_session.audit_row == legacy_session.original_audit_row == original_audit_after_first
    assert len(legacy_session.backfill_events) == 1
    event = next(iter(legacy_session.backfill_events.values()))
    assert event["operation"] == "capture_idea_chunk_backfill"
    assert event["source_revision_id"] == source_revision.id
    assert event["content_chunk_ids"] == list(expected_chunk_ids)
    assert event["idempotency_key"] != idempotency_key
    assert "Private legacy conversation text." not in repr((first, replay, event, caplog.text))
    audit_params = [
        params
        for query, params in legacy_session.calls
        if "MERGE (a:FounderGraphAudit" in query
    ]
    assert len(audit_params) == 2
    assert all("Private legacy conversation text." not in repr(params) for params in audit_params)


def test_capture_idea_neo4j_transaction_rolls_back_chunks_when_audit_fails() -> None:
    driver = FakeDriver()
    driver.session_value = RollbackSession()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    idea = Idea(owner_id="owner-1", id="idea-rollback", title="Rollback idea")
    source = Source(
        owner_id="owner-1",
        id="source-rollback",
        title="Rollback source",
        kind="conversation",
        revision=1,
        current_revision_id="source-revision-rollback",
    )
    source_revision = SourceRevision(
        owner_id="owner-1",
        id="source-revision-rollback",
        source_id=source.id,
        content="Conversation text that would produce a chunk.",
    )

    with pytest.raises(Neo4jUnavailableError, match="operation failed"):
        gateway.capture_idea(idea, source, source_revision, idempotency_key="capture-rollback")

    assert driver.session_value.created_nodes == []
    assert driver.session_value.audit_row is None
    assert driver.session_value.calls == []


def test_capture_idea_neo4j_transaction_rolls_back_source_nodes_when_chunk_creation_fails() -> None:
    driver = FakeDriver()
    driver.session_value = ChunkFailureSession()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    idea = Idea(owner_id="owner-1", id="idea-chunk-failure", title="Chunk failure idea")
    source = Source(
        owner_id="owner-1",
        id="source-chunk-failure",
        title="Chunk failure source",
        kind="conversation",
        revision=1,
        current_revision_id="source-revision-chunk-failure",
    )
    source_revision = SourceRevision(
        owner_id="owner-1",
        id="source-revision-chunk-failure",
        source_id=source.id,
        content="Conversation text that produces a chunk.",
    )

    with pytest.raises(Neo4jUnavailableError, match="operation failed"):
        gateway.capture_idea(idea, source, source_revision, idempotency_key="capture-chunk-failure")

    assert driver.session_value.created_nodes == []
    assert driver.session_value.audit_row is None
    assert driver.session_value.calls == []


def test_link_entities_requires_existing_same_owner_endpoints_and_static_relation_type() -> None:
    driver = FakeDriver()
    driver.session_value.endpoint_row = {
        "source_owner": "owner-1",
        "target_owner": "owner-1",
        "source_type": NodeType.PERSON.value,
        "target_type": NodeType.IDEA.value,
    }
    gateway = Neo4jGraphGateway(driver, "owner-1")
    person = PersonAsset(owner_id="owner-1", id="person-1", name="Founder")
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea")
    relationship = Relationship.from_entities(
        source=person,
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target=idea,
        status="proposed",
        evidence_ids=("evidence-1",),
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )

    receipt = gateway.link_entities(relationship, idempotency_key="link-1")

    assert receipt.target_type == "relationship"
    relation_queries = [query for query, _params in driver.session_value.calls if "CREATE (a)-[r:CAN_CONTRIBUTE_TO" in query]
    assert len(relation_queries) == 1

    driver.session_value.endpoint_row = None
    with pytest.raises(GraphWriteNotFoundError):
        gateway.link_entities(relationship, idempotency_key="link-missing")


def test_source_or_campaign_transition_requires_next_revision_and_keeps_old_payload() -> None:
    driver = FakeDriver()
    driver.session_value.existing_row = {
        "owner_id": "owner-1",
        "node_type": NodeType.SOURCE.value,
        "revision": 0,
    }
    gateway = Neo4jGraphGateway(driver, "owner-1")
    source = Source(owner_id="owner-1", id="source-1", title="source", revision=2)

    with pytest.raises(RevisionConflictError):
        gateway.put_node(source, idempotency_key="stale", expected_revision=0)

    assert not any("FounderGraphHistory" in query for query, _params in driver.session_value.calls)


def test_source_revision_rejects_missing_parent_before_create() -> None:
    driver = FakeDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    revision = SourceRevision(owner_id="owner-1", source_id="missing-source", id="source-revision-1", content="first")

    with pytest.raises(GraphWriteNotFoundError, match="source does not exist"):
        gateway.put_node(revision, idempotency_key="source-revision-missing")

    assert not any("CREATE (n:SourceRevision)" in query for query, _params in driver.session_value.calls)


def test_source_revision_rejects_foreign_parent_before_create() -> None:
    driver = FakeDriver()
    driver.session_value.source_row = {
        "owner_id": "owner-2",
        "node_type": NodeType.SOURCE.value,
    }
    gateway = Neo4jGraphGateway(driver, "owner-1")
    revision = SourceRevision(owner_id="owner-1", source_id="foreign-source", id="source-revision-1", content="first")

    with pytest.raises(GraphWriteError, match="local Source"):
        gateway.put_node(revision, idempotency_key="source-revision-foreign")

    assert not any("CREATE (n:SourceRevision)" in query for query, _params in driver.session_value.calls)


def test_source_rejects_invalid_current_revision_pointer_before_create() -> None:
    driver = FakeDriver()
    driver.session_value.source_revision_rows = (
        {
            "id": "source-revision-1",
            "owner_id": "owner-1",
            "source_id": "source-1",
            "revision": 1,
            "supersedes_id": None,
        },
    )
    gateway = Neo4jGraphGateway(driver, "owner-1")
    source = Source(
        owner_id="owner-1",
        id="source-1",
        title="source",
        revision=1,
        current_revision_id="missing-revision",
    )

    with pytest.raises(GraphWriteError, match="current_revision_id"):
        gateway.put_node(source, idempotency_key="source-invalid-current")

    assert not any("CREATE (n:Source)" in query for query, _params in driver.session_value.calls)


def test_unknown_label_and_relation_are_rejected_before_driver_access() -> None:
    driver = FakeDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")

    with pytest.raises(Neo4jQueryContractError):
        gateway.label_for("MATCH (n) DELETE n")
    with pytest.raises(Neo4jQueryContractError):
        gateway.relation_type_for("CREATE (n)")
    assert driver.session_value.calls == []


def test_migrate_executes_only_versioned_schema_queries() -> None:
    driver = FakeDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")

    count = gateway.migrate(current_version=0, target_version=1)

    assert count > 0
    assert len(driver.session_value.calls) == count
    assert all(query.startswith("CREATE ") for query, _params in driver.session_value.calls)


def test_default_migrate_targets_schema_v4_and_rollback_drops_only_v4_v3_and_v2_structure() -> None:
    driver = FakeDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")

    migrated = gateway.migrate()
    rolled_back = gateway.rollback()

    assert migrated > rolled_back
    assert rolled_back == 16
    rollback_queries = [query for query, _params in driver.session_value.calls[-rolled_back:]]
    assert all(query.startswith("DROP ") for query in rollback_queries)
    assert all("IF EXISTS" in query for query in rollback_queries)
    assert any("EntityRevision" in query for query, _params in driver.session_value.calls[migrated - rolled_back : migrated])


def test_neo4j_source_expected_revision_update_replaces_owner_scoped_current_edge() -> None:
    source = Source(
        owner_id="owner-1",
        id="source-current-edge",
        title="Source",
        revision=2,
        current_revision_id="source-revision-2",
    )
    revision_rows = (
        {
            "id": "source-revision-1",
            "owner_id": "owner-1",
            "node_type": NodeType.SOURCE_REVISION.value,
            "source_id": source.id,
            "revision": 1,
            "supersedes_id": None,
        },
        {
            "id": "source-revision-2",
            "owner_id": "owner-1",
            "node_type": NodeType.SOURCE_REVISION.value,
            "source_id": source.id,
            "revision": 2,
            "supersedes_id": "source-revision-1",
        },
    )

    class SourceUpdateSession(FakeSession):
        def __init__(self, *, target_exists: bool = True, fail_audit: bool = False) -> None:
            super().__init__()
            self.target_exists = target_exists
            self.fail_audit = fail_audit
            self.execute_write_calls = 0
            self.existing_row = {
                "owner_id": "owner-1", "node_type": NodeType.SOURCE.value, "revision": 1,
            }
            self.source_revision_rows = revision_rows

        def execute_write(self, callback):
            self.execute_write_calls += 1
            return callback(self)

        def run(self, query: str, **params):
            if "CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r)" in query:
                self.calls.append((query, params))
                return FakeResult({"id": params.get("source_revision_id")} if self.target_exists else None)
            if "CREATE (a:FounderGraphAudit" in query and self.fail_audit:
                self.calls.append((query, params))
                raise RuntimeError("audit write failed")
            return super().run(query, **params)

    driver = FakeDriver()
    driver.session_value = SourceUpdateSession()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    receipt = gateway.put_node(source, idempotency_key="source-pointer-2", expected_revision=1)

    calls = driver.session_value.calls
    delete_call = next(
        (index, query, params) for index, (query, params) in enumerate(calls)
        if "CURRENT_SOURCE_REVISION" in query and "DELETE edge" in query
    )
    create_call = next(
        (index, query, params) for index, (query, params) in enumerate(calls)
        if "CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r)" in query
    )
    set_index = next(index for index, (query, _params) in enumerate(calls) if "SET n = $properties" in query)
    audit_index = next(
        index for index, (query, _params) in enumerate(calls)
        if "CREATE (a:FounderGraphAudit" in query
    )
    assert receipt.revision == 2
    assert delete_call[2] == {"source_id": source.id, "owner_id": "owner-1"}
    assert create_call[2] == {
        "source_id": source.id, "source_revision_id": "source-revision-2", "owner_id": "owner-1",
    }
    assert set_index < delete_call[0] < create_call[0] < audit_index
    assert sum("CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r)" in query for query, _params in calls) == 1
    assert driver.session_value.execute_write_calls == 1


@pytest.mark.parametrize("failure", ["missing-target", "audit"])
def test_neo4j_source_expected_revision_update_propagates_edge_or_audit_failure(failure: str) -> None:
    source = Source(
        owner_id="owner-1",
        id="source-current-edge",
        title="Source",
        revision=2,
        current_revision_id="source-revision-2",
    )
    revision_rows = (
        {"id": "source-revision-1", "owner_id": "owner-1", "node_type": NodeType.SOURCE_REVISION.value,
         "source_id": source.id, "revision": 1, "supersedes_id": None},
        {"id": "source-revision-2", "owner_id": "owner-1", "node_type": NodeType.SOURCE_REVISION.value,
         "source_id": source.id, "revision": 2, "supersedes_id": "source-revision-1"},
    )

    class FailingSourceUpdateSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.existing_row = {
                "owner_id": "owner-1", "node_type": NodeType.SOURCE.value, "revision": 1,
            }
            self.source_revision_rows = revision_rows
            self.execute_write_calls = 0

        def execute_write(self, callback):
            self.execute_write_calls += 1
            return callback(self)

        def run(self, query: str, **params):
            if "CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r)" in query and failure == "missing-target":
                self.calls.append((query, params))
                return FakeResult()
            if "CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r)" in query:
                self.calls.append((query, params))
                return FakeResult({"id": params.get("source_revision_id")})
            if "CREATE (a:FounderGraphAudit" in query and failure == "audit":
                self.calls.append((query, params))
                raise RuntimeError("audit write failed")
            return super().run(query, **params)

    driver = FakeDriver()
    driver.session_value = FailingSourceUpdateSession()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    expected_error = GraphWriteNotFoundError if failure == "missing-target" else Neo4jUnavailableError
    with pytest.raises(expected_error) as error:
        gateway.put_node(source, idempotency_key="source-pointer-2", expected_revision=1)

    calls = driver.session_value.calls
    assert driver.session_value.execute_write_calls == 1
    assert any("DELETE edge" in query for query, _params in calls)
    assert any("CREATE (s)-[:CURRENT_SOURCE_REVISION]->(r)" in query for query, _params in calls)
    if failure == "audit":
        assert isinstance(error.value.__cause__, RuntimeError)
        assert any("CREATE (a:FounderGraphAudit" in query for query, _params in calls)
    else:
        assert not any("CREATE (a:FounderGraphAudit" in query for query, _params in calls)
