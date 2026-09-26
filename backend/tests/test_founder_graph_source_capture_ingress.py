from hashlib import sha256
from dataclasses import replace

import pytest

from dots.founder_graph import ContentChunk, EgressPolicy, MaterialKind, NodeType, Source, SourceRevision
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.founder_graph_write import GraphWriteError, IdempotencyConflictError, InMemoryGraphWriteService


def bundle(*, key: str = "source-1", summary: str = "A short authored summary.", owner: str = "owner-1"):
    digest = sha256(key.encode()).hexdigest()[:32]
    source_id, revision_id, url = f"source_{digest}", f"source-revision_{digest}", "https://example.org/research"
    source = Source(owner_id=owner, id=source_id, title="Research source", kind=MaterialKind.WEB, locator=url,
        current_revision_id=revision_id, revision=1, egress_policy=EgressPolicy.LOCAL_ONLY)
    revision = SourceRevision(owner_id=owner, id=revision_id, source_id=source_id, content=summary, locator=url,
        revision=1, egress_policy=EgressPolicy.LOCAL_ONLY)
    return source, revision


def test_ingress_is_atomic_local_only_typed_and_replay_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = InMemoryGraphWriteService("owner-1")
    source, revision = bundle()
    first = writes.capture_source(source, revision, idempotency_key="source-1")
    replay = writes.capture_source(source, revision, idempotency_key="source-1")
    nodes = {node.id: node for node in writes.nodes()}
    assert first.operation == "capture_source" and first.target_type == NodeType.SOURCE.value
    assert replay.replayed and replay.content_chunk_ids == first.content_chunk_ids
    assert nodes[source.id].current_revision_id == revision.id and nodes[revision.id].source_id == source.id
    assert all(isinstance(nodes[item], ContentChunk) and nodes[item].egress_policy is EgressPolicy.LOCAL_ONLY for item in first.content_chunk_ids)
    changed_source, changed_revision = bundle(summary="Changed summary.")
    with pytest.raises(IdempotencyConflictError):
        writes.capture_source(changed_source, changed_revision, idempotency_key="source-1")

    other, other_revision = bundle(key="rollback")
    monkeypatch.setattr(writes, "_append_audit", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("audit failure")))
    with pytest.raises(RuntimeError):
        writes.capture_source(other, other_revision, idempotency_key="rollback")
    assert other.id not in {node.id for node in writes.nodes()}


def test_ingress_rejects_foreign_owner_and_invalid_source_values() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    source, revision = bundle(owner="owner-2")
    with pytest.raises(GraphWriteError, match="local owner"):
        writes.capture_source(source, revision, idempotency_key="foreign")
    source, revision = bundle()
    with pytest.raises(GraphWriteError, match="HTTP"):
        writes.capture_source(replace(source, locator="file:///secret"), replace(revision, locator="file:///secret"), idempotency_key="invalid")


def test_mcp_capture_source_returns_only_opaque_receipt_and_rejects_network_scopes() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    args = {"url": "https://example.org/research", "title": "Public source", "summary": "Self-authored note", "idempotency_key": "mcp-source"}
    receipt = surface.call("capture_source", args, owner_id="owner-1")
    replay = surface.call("capture_source", args, owner_id="owner-1")
    assert replay.replayed and receipt.source_revision_id
    assert "Public source" not in repr(receipt) and "Self-authored note" not in repr(receipt)
    assert not any(node.node_type is NodeType.IDEA for node in writes.nodes())
    with pytest.raises(McpWriteError):
        surface.call("capture_source", {**args, "url": "https://user:secret@example.org"}, owner_id="owner-1")
    with pytest.raises(McpWriteError):
        surface.call("capture_source", {**args, "egress_policy": "shareable"}, owner_id="owner-1")


class _Result:
    def __init__(self, row=None): self.row = row
    def single(self, **_kwargs): return self.row
    def __iter__(self): return iter(() if self.row is None else (self.row,))


class _Session:
    def __init__(self): self.calls = []; self.audit = None
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def close(self): pass
    def execute_write(self, callback): return callback(self)
    def run(self, query, **params):
        self.calls.append((query, params))
        if "MATCH (a:FounderGraphAudit" in query:
            return _Result(self.audit if self.audit and self.audit.get("idempotency_key") == params.get("idempotency_key") else None)
        if "CREATE (a:FounderGraphAudit" in query:
            self.audit = {"idempotency_key": params["idempotency_key"], "payload_fingerprint": params["fingerprint"],
                "target_id": params["target_id"], "target_type": params["target_type"], "revision": 1,
                "source_revision_id": params["revision_id"], "content_chunk_ids": params["chunk_ids"]}
        return _Result()


class _Driver:
    def __init__(self): self.value = _Session()
    def session(self, *, database): assert database == "neo4j"; return self.value


def test_neo4j_source_write_is_single_callback_with_replay_before_create() -> None:
    driver = _Driver()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    source, revision = bundle()
    first = gateway.capture_source(source, revision, idempotency_key="source-1")
    replay = gateway.capture_source(source, revision, idempotency_key="source-1")
    assert replay.replayed and replay.target_id == first.target_id
    queries = [query for query, _params in driver.value.calls]
    assert queries[0].startswith("MATCH (a:FounderGraphAudit")
    assert next(i for i, query in enumerate(queries) if "CREATE (a:FounderGraphAudit" in query) > 1


@pytest.mark.parametrize("kwargs", [{"idempotency_key": ""}, {"actor": "  "}])
def test_neo4j_source_write_rejects_blank_audit_identity_before_opening_query(kwargs) -> None:
    driver = _Driver()
    gateway = Neo4jGraphGateway(driver, "owner-1")
    source, revision = bundle()
    defaults = {"idempotency_key": "source-1", "actor": "local-owner"}
    defaults.update(kwargs)
    with pytest.raises(GraphWriteError):
        gateway.capture_source(source, revision, **defaults)
    assert driver.value.calls == []
