from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from dots.founder_graph import Idea, NodeType, PersonAsset, RelationType, Relationship, Source, SourceRevision
from dots.founder_graph_neo4j import (
    Neo4jGraphGateway,
    Neo4jQueryContractError,
)
from dots.founder_graph_write import GraphWriteError, GraphWriteNotFoundError, RevisionConflictError


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
            }
        return FakeResult()


class FakeDriver:
    def __init__(self) -> None:
        self.session_value = FakeSession()

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


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
    queries = [query for query, _params in driver.session_value.calls]
    assert sum("CREATE (n:Source)" in query for query in queries) == 1
    assert sum("CREATE (n:SourceRevision)" in query for query in queries) == 1
    assert sum("CREATE (n:Idea)" in query for query in queries) == 1
    assert sum("CREATE (a:FounderGraphAudit" in query for query in queries) == 1


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
