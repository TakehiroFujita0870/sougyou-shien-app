from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect

import dots.main as main_module
import dots.founder_graph_mcp_stdio as stdio_module
from fastapi.testclient import TestClient
from dots.founder_graph import Idea, NodeType, PersonAsset, RelationType, Relationship
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService, PersistedNodeReference
from dots.founder_graph_neo4j_read import Neo4jGraphReadService
from dots.founder_graph_runtime import create_neo4j_graph_composition, resolve_graph_backend
from dots.main import create_app, create_configured_app, create_neo4j_app
from dots.founder_graph_mcp_stdio import create_neo4j_stdio_server


@dataclass
class _Result:
    row: dict[str, object] | None = None

    def single(self, **_kwargs):
        return self.row

    def __iter__(self):
        return iter(() if self.row is None else (self.row,))


class _Session:
    def __init__(self, records: dict[str, dict[str, object]]) -> None:
        self.records = records
        self.calls: list[tuple[str, dict[str, object]]] = []

    def close(self) -> None:
        return None

    def execute_read(self, callback):
        return callback(self)

    def execute_write(self, callback):
        return callback(self)

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (n {id: $node_id, owner_id: $owner_id})" in query:
            return _Result(self.records.get(params["node_id"]))
        if "FounderGraphAudit" in query and query.startswith("MATCH"):
            return _Result()
        if "MATCH (n {id: $id})" in query:
            return _Result()
        if "MATCH (a {id: $source_id}), (b {id: $target_id})" in query:
            return _Result({
                "source_owner": "owner-1",
                "target_owner": "owner-1",
                "source_type": NodeType.PERSON.value,
                "target_type": NodeType.IDEA.value,
            })
        if "MATCH (s:Source" in query or "MATCH (r:SourceRevision" in query:
            return _Result()
        return _Result()


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_value = session

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


class _UnavailableDriver:
    def session(self, *, database: str):
        assert database == "neo4j"
        raise OSError("Neo4j is stopped")


def test_composition_binds_one_gateway_without_implicit_connection() -> None:
    session = _Session({})
    composition = create_neo4j_graph_composition(_Driver(session), "owner-1")

    assert composition.gateway.owner_id == "owner-1"
    assert composition.writes.owner_id == composition.reads.owner_id == "owner-1"
    assert session.calls == []


def test_app_rejects_persistent_write_without_matching_persistent_read() -> None:
    session = _Session({})
    composition = create_neo4j_graph_composition(_Driver(session), "owner-1")

    try:
        create_app(founder_graph_write_service=composition.writes, founder_graph_owner_id="owner-1")
    except ValueError as error:
        assert "explicit founder_graph_read_service" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("persistent write must not silently use an in-memory read service")


def test_backend_resolution_prefers_explicit_memory_for_isolated_tests(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "memory")

    assert resolve_graph_backend() == "memory"
    assert create_configured_app().title == "Dots. API"


def test_backend_resolution_uses_configured_neo4j_without_backend_flag(monkeypatch) -> None:
    monkeypatch.delenv("DOTS_GRAPH_BACKEND", raising=False)
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")

    assert resolve_graph_backend() == "neo4j"


def test_configured_app_wires_neo4j_when_selected(monkeypatch) -> None:
    session = _Session({})
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "owner-persistent")
    monkeypatch.setattr(main_module, "create_neo4j_driver_from_env", lambda: _Driver(session))

    app = create_configured_app()

    assert app.title == "Dots. API"
    assert session.calls == []


def test_configured_neo4j_outage_fails_closed_for_fastapi_and_stdio(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "owner-persistent")
    monkeypatch.setattr(main_module, "create_neo4j_driver_from_env", _UnavailableDriver)
    monkeypatch.setattr(stdio_module, "create_neo4j_driver_from_env", _UnavailableDriver)

    api = TestClient(create_configured_app())
    headers = {"X-Local-Owner-Id": "owner-persistent"}
    read = api.post("/v1/founder-graph/mcp/read/search", headers=headers, json={"query": "idea"})
    write = api.post(
        "/v1/founder-graph/mcp/write/capture_idea",
        headers=headers,
        json={"title": "must not be stored in memory", "idempotency_key": "outage-write"},
    )
    stdio = stdio_module.create_stdio_server()
    stdio_write = stdio.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture_idea",
                "arguments": {"title": "must not be stored in memory", "idempotency_key": "outage-stdio"},
            },
        }
    )

    assert read.status_code == write.status_code == 503
    assert read.json()["detail"]["code"] == write.json()["detail"]["code"] == "unavailable"
    assert stdio_write["error"]["data"]["code"] == "unavailable"


def test_unknown_backend_fails_closed_before_app_creation(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "unknown")

    try:
        create_configured_app()
    except ValueError as error:
        assert "memory or neo4j" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("unknown backend must fail closed")


def test_selected_neo4j_without_password_does_not_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)

    try:
        create_configured_app()
    except RuntimeError as error:
        assert "DOTS_NEO4J_PASSWORD" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("Neo4j configuration errors must not fall back to memory")


def test_neo4j_app_factory_wires_matching_ports_without_connecting() -> None:
    session = _Session({})

    app = create_neo4j_app(_Driver(session), "owner-1")

    assert app.title == "Dots. API"
    assert session.calls == []


def test_neo4j_stdio_factory_uses_same_composition_without_connecting() -> None:
    session = _Session({})

    server = create_neo4j_stdio_server(_Driver(session), "owner-1")
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

    assert response["result"]["tools"]
    assert {tool["name"] for tool in response["result"]["tools"]} == {
        "search", "fetch", "capture_idea", "capture_source", "capture_person", "capture_organization", "append_claim",
        "link_entities", "save_research_report", "record_decision", "record_correction", "confirm_person_merge",
    }
    assert session.calls == []


def test_neo4j_search_has_bounded_cold_start_budget() -> None:
    default = inspect.signature(Neo4jGraphReadService.search).parameters["timeout_ms"].default

    assert default == 5_000


def _record(node: object) -> dict[str, object]:
    props = _node_properties(node)
    return {
        "id": props["id"],
        "owner_id": props["owner_id"],
        "node_type": props["node_type"],
        "revision": props["revision"],
        "payload_json": props["payload_json"],
    }


def test_persistent_adapter_hydrates_correction_node_and_keeps_owner_bound() -> None:
    idea = Idea(owner_id="owner-1", id="idea-1", title="Persisted", revision=2)
    session = _Session({idea.id: _record(idea)})
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))

    loaded = service.get_node("idea-1")

    assert isinstance(loaded, Idea)
    assert loaded.title == "Persisted"
    assert loaded.revision == 2
    assert service.get_node("missing") is None


def test_persistent_adapter_returns_minimal_endpoint_projection_and_delegates_link() -> None:
    person = PersonAsset(owner_id="owner-1", id="person-1", name="Founder")
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea")
    session = _Session({person.id: _record(person), idea.id: _record(idea)})
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))
    relationship = Relationship.from_entities(
        source=service.get_node(person.id),
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target=service.get_node(idea.id),
        status="proposed",
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        evidence_ids=("evidence-1",),
    )

    receipt = service.link_entities(relationship, idempotency_key="link-1")

    assert isinstance(service.get_node(person.id), PersistedNodeReference)
    assert receipt.target_type == "relationship"
    assert any("CREATE (a)-[r:CAN_CONTRIBUTE_TO" in query for query, _ in session.calls)


def test_persistent_adapter_correction_uses_gateway_and_revision_guard() -> None:
    idea = Idea(owner_id="owner-1", id="idea-1", title="Before", revision=1)
    session = _Session({idea.id: _record(idea)})
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))
    replacement = idea.revise(title="After")

    receipt = service.record_correction(
        idea.id,
        replacement,
        idempotency_key="correction-1",
        expected_revision=1,
    )

    assert receipt.operation == "record_correction"
    assert receipt.revision == 2
    assert any("CREATE (n:Idea)" in query for query, _ in session.calls)
