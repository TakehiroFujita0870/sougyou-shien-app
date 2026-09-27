"""HTTP composition must reuse the canonical owner-bound brief store."""

from dots import main as main_module
from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.founder_graph_neo4j_read import Neo4jGraphReadService
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService, Neo4jIdeaBriefStore
from dots.founder_graph_write import InMemoryGraphWriteService


def _capture_surface(monkeypatch):
    captured = {}

    def surface(writes, *, brief_store=None):
        captured.update(writes=writes, brief_store=brief_store)
        return object()

    monkeypatch.setattr(main_module, "McpWriteSurface", surface)
    return captured


def test_persistent_http_surface_reuses_the_canonical_gateway(monkeypatch):
    gateway = Neo4jGraphGateway(object(), "owner-a")
    writes = Neo4jGraphWriteService(gateway)
    captured = _capture_surface(monkeypatch)

    main_module.create_app(
        founder_graph_write_service=writes,
        founder_graph_read_service=Neo4jGraphReadService(gateway),
        founder_graph_owner_id="owner-a",
    )

    assert captured["writes"] is writes
    assert isinstance(captured["brief_store"], Neo4jIdeaBriefStore)
    assert captured["brief_store"].gateway is gateway


def test_memory_http_surface_keeps_its_existing_write_store(monkeypatch):
    writes = InMemoryGraphWriteService("owner-a")
    captured = _capture_surface(monkeypatch)

    main_module.create_app(founder_graph_write_service=writes, founder_graph_owner_id="owner-a")

    assert captured["writes"] is writes
    assert captured["brief_store"] is None
