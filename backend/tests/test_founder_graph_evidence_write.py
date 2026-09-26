from __future__ import annotations

import json
from hashlib import sha256

import pytest

from dots.founder_graph import Claim, ContentChunk, Evidence, EgressPolicy, MaterialKind, NodeType, Source, SourceRevision
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_read import _view_from_row
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_write import GraphWriteError, InMemoryGraphWriteService


def _seed() -> tuple[InMemoryGraphWriteService, str, str]:
    writes = InMemoryGraphWriteService("owner-1")
    source = Source(
        owner_id="owner-1", id="source-1", title="Source", kind=MaterialKind.WEB,
        locator="https://example.test/source", current_revision_id="revision-1", revision=1,
    )
    revision = SourceRevision(
        owner_id="owner-1", id="revision-1", source_id=source.id, content="A source sentence.",
        locator=source.locator, revision=1,
    )
    source_receipt = writes.capture_source(source, revision, idempotency_key="source-seed")
    claim = Claim(owner_id="owner-1", id="claim-1", text="A claim")
    writes.put_node(claim, idempotency_key="claim-seed", operation="append_claim")
    return writes, claim.id, source_receipt.content_chunk_ids[0]


def test_capture_evidence_derives_source_range_and_replays_without_exposing_source() -> None:
    writes, claim_id, chunk_id = _seed()
    first = writes.capture_evidence(claim_id, chunk_id, idempotency_key="ev-1")
    replay = writes.capture_evidence(claim_id, chunk_id, idempotency_key="ev-1")

    evidence = writes.get_node(first.target_id)
    assert isinstance(evidence, Evidence)
    assert evidence.claim_id == claim_id and evidence.content_chunk_id == chunk_id
    assert evidence.source_revision_id == writes.get_node(chunk_id).source_revision_id
    assert (evidence.char_start, evidence.char_end) == (0, len("A source sentence."))
    assert evidence.content_hash == writes.get_node(chunk_id).text_hash
    assert evidence.egress_policy is EgressPolicy.LOCAL_ONLY
    assert replay.replayed and replay.target_id == first.target_id
    assert writes.structural_edges().count((first.target_id, "EVIDENCE_FROM", chunk_id)) == 1
    assert len([item for item in writes.audit_events() if item.operation == "capture_evidence"]) == 1
    fields = GraphReadService(writes).fetch(first.target_id, owner_id="owner-1").fields
    assert not {"claim_id", "content_chunk_id", "source_revision_id", "locator", "excerpt"} & set(fields)
    with pytest.raises(GraphWriteError):
        writes.put_node(evidence, idempotency_key="bypass-evidence")


def test_source_grounded_evidence_domain_rejects_copied_excerpt_and_bad_range_hash() -> None:
    common = {"owner_id": "owner-1", "material_id": None, "claim_id": "claim-1",
              "source_revision_id": "revision-1", "content_chunk_id": "chunk-1",
              "char_start": 0, "char_end": 3, "locator": "chars:0-3",
              "content_hash": sha256(b"abc").hexdigest()}
    with pytest.raises(ValueError, match="cannot copy"):
        Evidence(**common, excerpt="abc")
    with pytest.raises(ValueError, match="SHA-256"):
        Evidence(**{**common, "content_hash": "bad"})


def test_neo4j_chunk_stores_source_revision_reference_for_lineage_validation() -> None:
    chunk = ContentChunk(owner_id="owner-1", id="chunk-queryable", source_revision_id="revision-queryable",
                         ordinal=0, char_start=0, char_end=3, text="abc")

    assert _node_properties(chunk)["source_revision_id"] == "revision-queryable"


def test_capture_evidence_rejects_changed_replay() -> None:
    writes, claim_id, chunk_id = _seed()
    writes.capture_evidence(claim_id, chunk_id, idempotency_key="ev-2")
    with pytest.raises(GraphWriteError):
        writes.capture_evidence(
            claim_id, chunk_id, polarity="contradicts", idempotency_key="ev-2"
        )


def test_shareable_evidence_requires_shareable_claim_but_keeps_local_source_chain() -> None:
    writes, claim_id, chunk_id = _seed()
    with pytest.raises(GraphWriteError, match="shareable Claim"):
        writes.capture_evidence(
            claim_id, chunk_id, egress_policy=EgressPolicy.SHAREABLE, idempotency_key="ev-private-claim",
        )
    shared_claim = Claim(owner_id="owner-1", id="claim-shareable", text="A shareable claim",
                         egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(shared_claim, idempotency_key="claim-shareable-seed", operation="append_claim")
    receipt = writes.capture_evidence(
        shared_claim.id, chunk_id, egress_policy=EgressPolicy.SHAREABLE, idempotency_key="ev-shareable",
    )
    evidence = writes.get_node(receipt.target_id)
    assert evidence.egress_policy is EgressPolicy.SHAREABLE
    assert writes.get_node(evidence.source_revision_id).egress_policy is EgressPolicy.LOCAL_ONLY


def test_capture_evidence_hides_foreign_owner_and_requires_structural_lineage() -> None:
    writes, claim_id, chunk_id = _seed()
    with pytest.raises(GraphWriteError):
        writes.capture_evidence(claim_id, "foreign-id", idempotency_key="ev-3")
    foreign_chunk = ContentChunk(owner_id="owner-2", id="foreign-id", source_revision_id="foreign-revision",
                                 ordinal=0, char_start=0, char_end=3, text="abc")
    writes._nodes[foreign_chunk.id] = foreign_chunk
    with pytest.raises(GraphWriteError):
        writes.capture_evidence(claim_id, "foreign-id", idempotency_key="ev-3b")
    writes._structural_edges.remove((writes.get_node(chunk_id).source_revision_id, "HAS_CHUNK", chunk_id))
    with pytest.raises(GraphWriteError):
        writes.capture_evidence(claim_id, chunk_id, idempotency_key="ev-4")
    assert not any(isinstance(node, Evidence) and node.content_chunk_id == chunk_id for node in writes.nodes())


def test_capture_evidence_rolls_back_node_edge_and_audit_on_audit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    writes, claim_id, chunk_id = _seed()
    before_edges, before_audit = writes.structural_edges(), writes.audit_events()
    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(writes, "_append_audit", fail_audit)
    with pytest.raises(RuntimeError):
        writes.capture_evidence(claim_id, chunk_id, idempotency_key="ev-5")
    assert writes.structural_edges() == before_edges
    assert writes.audit_events() == before_audit
    assert not any(isinstance(node, Evidence) and node.content_chunk_id == chunk_id for node in writes.nodes())


class _NeoResult:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.row = row
    def single(self, **_kwargs: object) -> dict[str, object] | None:
        return self.row


class _NeoState:
    def __init__(self) -> None:
        self.owner = "neo-owner"
        claim = Claim(owner_id=self.owner, id="claim-neo", text="Claim")
        revision = SourceRevision(owner_id=self.owner, id="revision-neo", source_id="source-neo", content="Neo source")
        chunk = ContentChunk(owner_id=self.owner, id="chunk-neo", source_revision_id=revision.id, ordinal=0,
                             char_start=0, char_end=len(revision.content), text=revision.content)
        self.nodes = {item.id: _node_properties(item) for item in (claim, revision, chunk)}
        self.audit: dict[str, dict[str, object]] = {}
        self.edges: list[tuple[str, str, str]] = [(revision.id, "HAS_CHUNK", chunk.id)]
        self.claim_type = NodeType.CLAIM.value
        self.claim_status = "active"
        self.chunk_type = NodeType.CONTENT_CHUNK.value
        self.chunk_status = "active"
        self.revision_type = NodeType.SOURCE_REVISION.value
        self.revision_status = "active"
        self.fail_edge = False

    def session(self, *, database: str) -> "_NeoSession":
        assert database == "neo4j"
        return _NeoSession(self)


class _NeoSession:
    def __init__(self, state: _NeoState) -> None:
        self.state = state
    def __enter__(self) -> "_NeoSession":
        return self
    def __exit__(self, *_args: object) -> None:
        return None
    def close(self) -> None:
        return None
    def execute_write(self, callback):
        before = (dict(self.state.nodes), dict(self.state.audit), list(self.state.edges))
        try:
            return callback(self)
        except Exception:
            self.state.nodes, self.state.audit, self.state.edges = before
            raise
    def run(self, query: str, **params: object) -> _NeoResult:
        if "MATCH (c:Claim" in query:
            ch = self.state.nodes.get(str(params["chunk_id"]))
            if params["claim_id"] != "claim-neo" or params["chunk_id"] != "chunk-neo":
                return _NeoResult()
            if ch["owner_id"] != params["owner_id"]:
                return _NeoResult()
            return _NeoResult({"claim_type": self.state.claim_type, "claim_status": self.state.claim_status,
                "chunk_type": self.state.chunk_type, "chunk_status": self.state.chunk_status,
                "chunk_payload": ch["payload_json"]})
        if "OPTIONAL MATCH (r)-[edge:HAS_CHUNK]->(ch)" in query:
            return _NeoResult({"revision_type": self.state.revision_type,
                "revision_status": self.state.revision_status,
                "lineage_count": self.state.edges.count(("revision-neo", "HAS_CHUNK", "chunk-neo"))})
        if "MATCH (a:FounderGraphAudit" in query:
            return _NeoResult(self.state.audit.get(str(params["idempotency_key"])))
        if "MATCH (n {id: $id}) RETURN n.owner_id" in query:
            node = self.state.nodes.get(str(params["id"]))
            return _NeoResult({"owner_id": node["owner_id"], "node_type": node["node_type"], "revision": node["revision"]} if node else None)
        if "CREATE (n:Evidence)" in query:
            self.state.nodes[str(params["properties"]["id"])] = dict(params["properties"])
        if "CREATE (a:FounderGraphAudit" in query:
            self.state.audit[str(params["idempotency_key"])] = dict(params)
        if "MERGE (e)-[:EVIDENCE_FROM]" in query:
            if self.state.fail_edge:
                self.state.fail_edge = False
                return _NeoResult()
            edge = (str(params["evidence_id"]), "EVIDENCE_FROM", str(params["chunk_id"]))
            if edge not in self.state.edges:
                self.state.edges.append(edge)
            return _NeoResult({"id": params["evidence_id"]})
        return _NeoResult()


def test_neo4j_capture_evidence_persists_node_edge_and_audit_in_one_transaction() -> None:
    state = _NeoState()
    gateway = Neo4jGraphGateway(state, state.owner)
    first = gateway.capture_evidence("claim-neo", "chunk-neo", idempotency_key="neo-ev")
    replay = gateway.capture_evidence("claim-neo", "chunk-neo", idempotency_key="neo-ev")
    assert first.target_type == NodeType.EVIDENCE.value
    assert replay.replayed and replay.target_id == first.target_id
    assert state.edges == [("revision-neo", "HAS_CHUNK", "chunk-neo"), (first.target_id, "EVIDENCE_FROM", "chunk-neo")]
    assert len(state.audit) == 1
    persisted = state.nodes[first.target_id]
    view = _view_from_row({key: persisted.get(key) for key in ("id", "owner_id", "node_type", "revision", "status", "payload_json")}, owner_id=state.owner)
    assert view is not None
    assert not {"claim_id", "content_chunk_id", "source_revision_id", "locator", "excerpt"} & set(view.fields)


def test_neo4j_capture_evidence_rolls_back_node_and_audit_if_edge_write_fails() -> None:
    state = _NeoState()
    state.fail_edge = True
    gateway = Neo4jGraphGateway(state, state.owner)
    with pytest.raises(GraphWriteError):
        gateway.capture_evidence("claim-neo", "chunk-neo", idempotency_key="neo-fail")
    assert not state.audit and state.edges == [("revision-neo", "HAS_CHUNK", "chunk-neo")]
    assert not any(node.get("node_type") == NodeType.EVIDENCE.value for node in state.nodes.values())


@pytest.mark.parametrize("corruption", [
    "claim_type", "chunk_status", "foreign_chunk", "malformed_payload", "payload_hash",
    "payload_range", "revision_type", "revision_status", "missing_lineage", "duplicate_lineage",
])
def test_neo4j_capture_evidence_rejects_invalid_reference_state_without_writes(corruption: str) -> None:
    state = _NeoState()
    if corruption == "claim_type":
        state.claim_type = NodeType.IDEA.value
    elif corruption == "chunk_status":
        state.chunk_status = "archived"
    elif corruption == "foreign_chunk":
        state.nodes["chunk-neo"]["owner_id"] = "other-owner"
    elif corruption == "malformed_payload":
        state.nodes["chunk-neo"]["payload_json"] = "{"
    elif corruption == "payload_hash":
        payload = json.loads(state.nodes["chunk-neo"]["payload_json"])
        payload["text_hash"] = "0" * 64
        state.nodes["chunk-neo"]["payload_json"] = json.dumps(payload)
    elif corruption == "payload_range":
        payload = json.loads(state.nodes["chunk-neo"]["payload_json"])
        payload["char_end"] += 1
        state.nodes["chunk-neo"]["payload_json"] = json.dumps(payload)
    elif corruption == "revision_type":
        state.revision_type = NodeType.IDEA.value
    elif corruption == "revision_status":
        state.revision_status = "archived"
    elif corruption == "missing_lineage":
        state.edges.clear()
    else:
        state.edges.append(("revision-neo", "HAS_CHUNK", "chunk-neo"))

    with pytest.raises(GraphWriteError):
        Neo4jGraphGateway(state, state.owner).capture_evidence(
            "claim-neo", "chunk-neo", idempotency_key=f"invalid-{corruption}"
        )
    assert not state.audit
    assert not any(node.get("node_type") == NodeType.EVIDENCE.value for node in state.nodes.values())
