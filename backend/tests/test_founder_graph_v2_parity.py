from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from dots.founder_graph import (
    ContentChunk,
    EntityRevision,
    Facet,
    Idea,
    NodeType,
    PersonAsset,
    RelationAssertion,
    RelationType,
    RelationshipStatus,
    Status,
)
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_read import Neo4jGraphReadService
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_write import InMemoryGraphWriteService


class _Result:
    def __init__(self, row: dict[str, object] | None = None, rows: tuple[dict[str, object], ...] = ()) -> None:
        self.row = row
        self.rows = rows

    def __iter__(self):
        return iter(self.rows if self.rows else (() if self.row is None else (self.row,)))

    def single(self, **_kwargs):
        return self.row


class _ParitySession:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, object]] = {}
        self.audit: dict[str, dict[str, object]] = {}

    def close(self) -> None:
        return None

    def execute_write(self, callback):
        return callback(self)

    def execute_read(self, callback):
        return callback(self)

    def run(self, query: str, **params):
        if "MATCH (a:FounderGraphAudit" in query:
            return _Result(self.audit.get(str(params["idempotency_key"])))
        if "MATCH (n {id: $id})" in query:
            properties = self.nodes.get(str(params["id"]))
            return _Result(None if properties is None else {
                "owner_id": properties["owner_id"],
                "node_type": properties["node_type"],
                "revision": properties["revision"],
            })
        if "CREATE (n:" in query and "SET n = $properties" in query:
            properties = dict(params["properties"])
            self.nodes[str(properties["id"])] = properties
            return _Result()
        if "CREATE (a:FounderGraphAudit" in query:
            self.audit[str(params["idempotency_key"])] = {
                "payload_fingerprint": params["payload_fingerprint"],
                "target_id": params["target_id"],
                "target_type": params["target_type"],
                "revision": params.get("revision", 0),
            }
            return _Result()
        if "MATCH (n) WHERE n.id = $node_id" in query:
            properties = self.nodes.get(str(params["node_id"]))
            if properties is None or properties["owner_id"] != params["owner_id"]:
                return _Result()
            return _Result(_read_row(properties))
        if "MATCH (n) WHERE n.owner_id = $owner_id" in query:
            rows = tuple(
                _read_row(properties)
                for properties in self.nodes.values()
                if properties["owner_id"] == params["owner_id"]
            )
            return _Result(rows=rows)
        return _Result()


class _ParityDriver:
    def __init__(self) -> None:
        self.session_value = _ParitySession()

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


def _read_row(properties: dict[str, object]) -> dict[str, object]:
    return {
        "id": properties["id"],
        "owner_id": properties["owner_id"],
        "node_type": properties["node_type"],
        "status": properties["status"],
        "revision": properties["revision"],
        "payload_json": properties["payload_json"],
        "search_text": properties["search_text"],
    }


def _fixture(owner_id: str = "synthetic-owner") -> tuple[object, ...]:
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    return (
        Idea(
            owner_id=owner_id,
            id="idea-1",
            title="Founder graph",
            summary="Connect people and capabilities",
            status=Status.ACTIVE,
        ),
        PersonAsset(owner_id=owner_id, id="person-1", name="Aki Ito"),
        EntityRevision(
            owner_id=owner_id,
            id="revision-1",
            entity_id="idea-1",
            entity_type=NodeType.IDEA,
            revision=1,
            payload_schema="idea.v2",
            public_payload={"title": "Founder graph", "summary": "Connect people and capabilities"},
        ),
        ContentChunk(
            owner_id=owner_id,
            id="chunk-1",
            source_revision_id="source-revision-1",
            ordinal=0,
            char_start=0,
            char_end=19,
            text="founder graph chunk",
        ),
        Facet(owner_id=owner_id, id="facet-1", namespace="business-model", value="Product"),
        RelationAssertion(
            owner_id=owner_id,
            id="assertion-1",
            source_id="person-1",
            target_id="idea-1",
            source_kind=NodeType.PERSON,
            target_kind=NodeType.IDEA,
            predicate=RelationType.CAN_CONTRIBUTE_TO,
            assertion_family_id="family-1",
            status=RelationshipStatus.PROPOSED,
            confidence=0.8,
            expires_at=expires_at,
        ),
    )


def _view_manifest(reads, nodes: tuple[object, ...], owner_id: str) -> dict[str, object]:
    views = tuple(reads.fetch(str(node.id), owner_id=owner_id) for node in nodes)
    return {
        "node_count": len(views),
        "node_types": tuple(sorted(view.node_type for view in views)),
        "ids": tuple(sorted(view.id for view in views)),
        "views": tuple(
            (
                view.id,
                view.node_type,
                view.title,
                view.snippet,
                view.status,
                view.revision,
                json.dumps(dict(view.fields), ensure_ascii=False, sort_keys=True),
            )
            for view in views
        ),
    }


def test_schema_v2_write_and_read_match_in_memory_for_all_v2_node_types() -> None:
    owner_id = "synthetic-owner"
    nodes = _fixture(owner_id)
    memory_writes = InMemoryGraphWriteService(owner_id)
    neo4j_driver = _ParityDriver()
    neo4j_gateway = Neo4jGraphGateway(neo4j_driver, owner_id)

    for index, node in enumerate(nodes):
        memory_writes.put_node(node, idempotency_key=f"memory-{index}")
        neo4j_gateway.put_node(node, idempotency_key=f"neo4j-{index}")

    memory_reads = GraphReadService(memory_writes)
    neo4j_reads = Neo4jGraphReadService(neo4j_gateway)

    assert _view_manifest(memory_reads, nodes, owner_id) == _view_manifest(neo4j_reads, nodes, owner_id)
    assert set(neo4j_driver.session_value.nodes) == {node.id for node in nodes}
    assert {properties["node_type"] for properties in neo4j_driver.session_value.nodes.values()} >= {
        NodeType.ENTITY_REVISION.value,
        NodeType.RELATION_ASSERTION.value,
        NodeType.CONTENT_CHUNK.value,
        NodeType.FACET.value,
    }


def test_schema_v2_representative_search_has_the_same_safe_result_ids() -> None:
    owner_id = "synthetic-owner"
    nodes = _fixture(owner_id)
    memory_writes = InMemoryGraphWriteService(owner_id)
    neo4j_driver = _ParityDriver()
    neo4j_gateway = Neo4jGraphGateway(neo4j_driver, owner_id)
    for index, node in enumerate(nodes):
        memory_writes.put_node(node, idempotency_key=f"memory-search-{index}")
        neo4j_gateway.put_node(node, idempotency_key=f"neo4j-search-{index}")

    memory_hits = GraphReadService(memory_writes).search("founder", owner_id=owner_id)
    neo4j_hits = Neo4jGraphReadService(neo4j_gateway).search("founder", owner_id=owner_id)

    assert [hit.node.id for hit in memory_hits.hits] == [hit.node.id for hit in neo4j_hits.hits]
    assert all("text" not in hit.node.fields for hit in neo4j_hits.hits if hit.node.node_type == NodeType.CONTENT_CHUNK.value)
    assert all("private_notes" not in hit.node.fields for hit in neo4j_hits.hits)


def test_node_properties_round_trip_preserves_v2_payload_without_private_projection() -> None:
    chunk = _fixture()[3]
    properties = _node_properties(chunk)
    payload = json.loads(str(properties["payload_json"]))

    assert payload["text"] == "founder graph chunk"
    assert properties["node_type"] == NodeType.CONTENT_CHUNK.value
    assert properties["owner_id"] == "synthetic-owner"
