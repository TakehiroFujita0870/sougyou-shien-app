from __future__ import annotations

import json

import pytest

from dots.founder_graph import NodeType, RelationType
from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.founder_graph_neo4j_read import GraphRelationView, Neo4jGraphReadService
from dots.founder_graph_read import GraphReadError, GraphReadNotFoundError


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def single(self, **_kwargs):
        return self.rows[0] if self.rows else None


class FakeReadSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fetch_rows: list[dict[str, object]] = []
        self.search_rows: list[dict[str, object]] = []
        self.search_relation_rows: list[dict[str, object]] = []
        self.search_relation_rows_by_call: list[list[dict[str, object]]] = []
        self.search_relation_call_count = 0
        self.relation_rows: list[dict[str, object]] = []

    def close(self) -> None:
        return None

    def execute_read(self, callback):
        return callback(self)

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (a)-[r]->(b)" in query and "matched_ids" in query:
            if self.search_relation_rows_by_call:
                index = min(self.search_relation_call_count, len(self.search_relation_rows_by_call) - 1)
                self.search_relation_call_count += 1
                return FakeResult(self.search_relation_rows_by_call[index])
            return FakeResult(self.search_relation_rows)
        if "MATCH (a)-[r]->(b)" in query:
            return FakeResult(self.relation_rows)
        if "$node_id" in query:
            return FakeResult(self.fetch_rows)
        return FakeResult(self.search_rows)


class FakeReadDriver:
    def __init__(self) -> None:
        self.session_value = FakeReadSession()

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


def _gateway() -> tuple[FakeReadDriver, Neo4jGraphReadService]:
    driver = FakeReadDriver()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    return driver, Neo4jGraphReadService(gateway)


def _node_row(
    node_id: str,
    *,
    node_type: str = NodeType.IDEA.value,
    owner_id: str = "owner-1",
    title: str = "Graph idea",
    status: str = "active",
    search_text: str = "graph idea",
    private_raw: str = "do not project",
) -> dict[str, object]:
    payload = {
        "id": node_id,
        "owner_id": owner_id,
        "node_type": node_type,
        "title": title,
        "status": status,
        "egress_policy": "shareable",
        "private_raw": private_raw,
        "source_text": "source text",
    }
    return {
        "id": node_id,
        "owner_id": owner_id,
        "node_type": node_type,
        "status": status,
        "revision": 0,
        "payload_json": json.dumps(payload),
        "search_text": search_text,
    }


def _relation_row(source: dict[str, object], target: dict[str, object], relation: str) -> dict[str, object]:
    return {
        "source_id": source["id"],
        "relation": relation,
        "evidence_ids_json": json.dumps(["evidence-1"]),
        "target_id": target["id"],
        "source_owner_id": source["owner_id"],
        "source_node_type": source["node_type"],
        "source_status": source["status"],
        "source_revision": source["revision"],
        "source_payload_json": source["payload_json"],
        "source_search_text": source["search_text"],
        "target_owner_id": target["owner_id"],
        "target_node_type": target["node_type"],
        "target_status": target["status"],
        "target_revision": target["revision"],
        "target_payload_json": target["payload_json"],
        "target_search_text": target["search_text"],
    }


def test_fetch_hydrates_allowlisted_view_without_exposing_raw_payload() -> None:
    driver, reads = _gateway()
    driver.session_value.fetch_rows = [_node_row("idea-1", title="A persisted idea")]

    view = reads.fetch("idea-1", owner_id="owner-1")

    assert view.id == "idea-1"
    assert view.title == "A persisted idea"
    assert view.fields["source_text"] == "source text"
    assert "private_raw" not in view.fields
    assert all("idea-1" not in query for query, _params in driver.session_value.calls)
    query, params = driver.session_value.calls[0]
    assert "owner_id = $owner_id" in query
    assert params["node_id"] == "idea-1"


def test_fetch_hides_foreign_and_non_current_rows() -> None:
    driver, reads = _gateway()
    driver.session_value.fetch_rows = [_node_row("foreign", owner_id="owner-2")]
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch("foreign", owner_id="owner-1")

    driver.session_value.fetch_rows = [_node_row("old", status="superseded")]
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch("old", owner_id="owner-1")

    assert reads.search("anything", owner_id="owner-2").hits == ()


def test_search_returns_neighbor_path_and_uses_parameterized_queries() -> None:
    driver, reads = _gateway()
    person = _node_row(
        "person-1",
        node_type=NodeType.PERSON.value,
        title="Founder network",
        search_text="founder network",
    )
    idea = _node_row("idea-1", title="Circular materials", search_text="circular materials")
    driver.session_value.search_rows = [person]
    driver.session_value.search_relation_rows = [_relation_row(person, idea, RelationType.CAN_CONTRIBUTE_TO.value)]

    page = reads.search("Founder ) MATCH (n)", owner_id="owner-1")

    assert page.hits[0].node.id == person["id"]
    idea_hit = next(hit for hit in page.hits if hit.node.id == idea["id"])
    assert idea_hit.path == ("person-1", RelationType.CAN_CONTRIBUTE_TO.value, "idea-1")
    assert idea_hit.score < page.hits[0].score
    assert all("Founder ) MATCH (n)" not in query for query, _params in driver.session_value.calls)
    assert any(params.get("tokens") for _query, params in driver.session_value.calls)


def test_search_expands_two_parameterized_relation_queries_to_two_hops() -> None:
    driver, reads = _gateway()
    person = _node_row(
        "person-1",
        node_type=NodeType.PERSON.value,
        title="Founder network",
        search_text="founder network",
    )
    idea = _node_row("idea-1", title="Circular materials", search_text="circular materials")
    asset = _node_row("asset-1", node_type=NodeType.ASSET.value, title="Material expertise", search_text="material expertise")
    driver.session_value.search_rows = [person]
    driver.session_value.search_relation_rows_by_call = [
        [_relation_row(person, idea, RelationType.CAN_CONTRIBUTE_TO.value)],
        [_relation_row(idea, asset, RelationType.REUSES.value)],
    ]

    page = reads.search("Founder", owner_id="owner-1")

    asset_hit = next(hit for hit in page.hits if hit.node.id == asset["id"])
    assert asset_hit.path == (
        "person-1",
        RelationType.CAN_CONTRIBUTE_TO.value,
        "idea-1",
        RelationType.REUSES.value,
        "asset-1",
    )
    assert asset_hit.evidence_ids == ("evidence-1",)
    assert driver.session_value.search_relation_call_count == 2
    assert all(params.get("matched_ids") for query, params in driver.session_value.calls if "matched_ids" in params)


def test_search_paginates_with_stable_cursor() -> None:
    driver, reads = _gateway()
    driver.session_value.search_rows = [
        _node_row("idea-0", title="Graph seed", search_text="graph seed"),
        _node_row("idea-1", title="Graph seed", search_text="graph seed"),
        _node_row("idea-2", title="Graph seed", search_text="graph seed"),
    ]

    first = reads.search("Graph", owner_id="owner-1", limit=2)
    second = reads.search("Graph", owner_id="owner-1", limit=2, cursor=first.next_cursor)

    assert first.next_cursor == "2"
    assert [hit.node.id for hit in first.hits] == ["idea-0", "idea-1"]
    assert [hit.node.id for hit in second.hits] == ["idea-2"]


def test_relations_are_owner_scoped_and_stably_sorted() -> None:
    driver, reads = _gateway()
    root = _node_row("root")
    first = _node_row("first")
    second = _node_row("second")
    driver.session_value.fetch_rows = [root]
    driver.session_value.relation_rows = [
        {
            "source_id": "root",
            "relation": RelationType.REUSES.value,
            "target_id": "second",
            "source_owner_id": "owner-1",
            "target_owner_id": "owner-1",
            "source_node_type": NodeType.IDEA.value,
            "target_node_type": NodeType.IDEA.value,
        },
        {
            "source_id": "root",
            "relation": RelationType.ADDRESSES.value,
            "target_id": "first",
            "source_owner_id": "owner-1",
            "target_owner_id": "owner-1",
            "source_node_type": NodeType.IDEA.value,
            "target_node_type": NodeType.IDEA.value,
        },
    ]

    relations = reads.relations("root", owner_id="owner-1")

    assert relations == (
        GraphRelationView("root", RelationType.ADDRESSES.value, "first", NodeType.IDEA.value, NodeType.IDEA.value),
        GraphRelationView("root", RelationType.REUSES.value, "second", NodeType.IDEA.value, NodeType.IDEA.value),
    )
    relation_query, relation_params = driver.session_value.calls[-1]
    assert "owner_id = $owner_id" in relation_query
    assert relation_params["owner_id"] == "owner-1"


def test_relations_require_a_current_local_node() -> None:
    _driver, reads = _gateway()

    with pytest.raises(GraphReadNotFoundError):
        reads.relations("missing", owner_id="owner-1")
    with pytest.raises(GraphReadNotFoundError):
        reads.relations("root", owner_id="owner-2")


def test_malformed_payload_is_a_recoverable_read_error() -> None:
    driver, reads = _gateway()
    row = _node_row("broken")
    row["payload_json"] = "not-json"
    driver.session_value.fetch_rows = [row]

    with pytest.raises(GraphReadError, match="valid JSON"):
        reads.fetch("broken", owner_id="owner-1")
