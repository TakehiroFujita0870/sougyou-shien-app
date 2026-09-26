from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json

import pytest

from dots.founder_graph import ContentChunk, Source, SourceRevision, build_content_chunks
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService
from dots.founder_graph_write import GraphWriteError, payload_fingerprint


class Result:
    def __init__(self, rows=()):
        self.rows = tuple(rows)

    def __iter__(self):
        return iter(self.rows)


class RepairSession:
    def __init__(self, owner_id: str):
        self.owner_id = owner_id
        self.nodes: dict[str, dict] = {}
        self.edges: list[tuple[str, str, str]] = []
        self.audits: dict[str, dict] = {}
        self.calls: list[tuple[str, bool]] = []
        self.in_write = False
        self.audit_failure = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None

    def execute_read(self, callback):
        return callback(self)

    def execute_write(self, callback):
        nodes, edges, audits = dict(self.nodes), list(self.edges), dict(self.audits)
        self.in_write = True
        try:
            return callback(self)
        except Exception:
            self.nodes, self.edges, self.audits = nodes, edges, audits
            raise
        finally:
            self.in_write = False

    def run(self, query: str, **params):
        self.calls.append((query, self.in_write))
        if query.startswith("MATCH (n) WHERE (n.owner_id"):
            labels = {"Source", "SourceRevision", "ContentChunk"}
            return Result(
                {key: value[key] for key in ("id", "owner_id", "node_type", "payload_json")}
                for value in self.nodes.values()
                if value["label"] in labels and value["owner_id"] in {params["owner_id"], None}
            )
        if query.startswith("MATCH (a)-[e]->(b)"):
            result = []
            for start, rel, end in self.edges:
                if start in params["node_ids"] or end in params["node_ids"]:
                    result.append({"start_id": start, "edge_type": rel, "end_id": end,
                                   "start_owner": self.nodes[start]["owner_id"],
                                   "end_owner": self.nodes[end]["owner_id"]})
            return Result(result)
        if "MERGE (a)-[:" in query:
            relationship = query.split("MERGE (a)-[:", 1)[1].split("]", 1)[0]
            expected_labels = {
                "HAS_SOURCE_REVISION": ("Source", "SourceRevision"),
                "CURRENT_SOURCE_REVISION": ("Source", "SourceRevision"),
                "HAS_CHUNK": ("SourceRevision", "ContentChunk"),
            }[relationship]
            if f"MATCH (a:{expected_labels[0]} " not in query or f"(b:{expected_labels[1]} " not in query:
                return Result(({"matched": 0},))
            edge = (params["start_id"], relationship, params["end_id"])
            if edge not in self.edges:
                self.edges.append(edge)
            return Result(({"matched": 1},))
        if query.startswith("MATCH (a:FounderGraphAudit"):
            row = self.audits.get(params["audit_id"])
            return Result(()) if row is None else Result((row,))
        if "MERGE (a:FounderGraphAudit" in query:
            if self.audit_failure:
                raise RuntimeError("simulated audit write failure")
            self.audits.setdefault(params["audit_id"], dict(params))
            return Result()
        raise AssertionError(f"Unexpected query: {query}")


class RepairDriver:
    def __init__(self, session):
        self.value = session

    def session(self, *, database):
        assert database == "neo4j"
        return self.value


def _service() -> tuple[Neo4jGraphWriteService, RepairSession, Source, SourceRevision, tuple[ContentChunk, ...]]:
    owner_id = "owner-1"
    source = Source(owner_id=owner_id, id="source-1", title="Conversation", current_revision_id="revision-1")
    revision = SourceRevision(owner_id=owner_id, id="revision-1", source_id=source.id, content="Saved conversation.")
    chunks = build_content_chunks(revision)
    session = RepairSession(owner_id)
    for node in (source, revision, *chunks):
        properties = _node_properties(node)
        properties["label"] = {"source": "Source", "source_revision": "SourceRevision", "content_chunk": "ContentChunk"}[properties["node_type"]]
        session.nodes[node.id] = properties
    service = Neo4jGraphWriteService(Neo4jGraphGateway(RepairDriver(session), owner_id))
    return service, session, source, revision, chunks


def test_neo4j_source_chain_repair_preview_and_apply_are_atomic_and_idempotent():
    service, session, source, revision, chunks = _service()
    preview = service.preview_source_chain_repair()
    assert preview.edges_to_add == (
        (source.id, "HAS_SOURCE_REVISION", revision.id),
        (source.id, "CURRENT_SOURCE_REVISION", revision.id),
        (revision.id, "HAS_CHUNK", chunks[0].id),
    )
    assert session.edges == [] and session.audits == {}
    assert all(not in_write for _query, in_write in session.calls)

    session.calls.clear()
    applied = service.apply_source_chain_repair()
    assert applied.edges_added == preview.edges_to_add
    assert session.edges == list(preview.edges_to_add)
    assert len(session.audits) == 1
    assert session.calls and all(in_write for _query, in_write in session.calls)

    repeated = service.apply_source_chain_repair()
    assert repeated.edges_to_add == ()
    assert len(session.audits) == 1


@pytest.mark.parametrize("corruption", ["malformed", "missing_owner", "foreign_edge", "contradictory_edge", "chunk_conflict"])
def test_neo4j_source_chain_repair_fails_closed_without_writes(corruption: str):
    service, session, source, revision, chunks = _service()
    if corruption == "malformed":
        session.nodes[source.id]["payload_json"] = "{"
    elif corruption == "missing_owner":
        session.nodes[source.id]["owner_id"] = None
    elif corruption == "foreign_edge":
        foreign = replace(revision, id="foreign-revision", owner_id="owner-2")
        props = _node_properties(foreign)
        props["label"] = "SourceRevision"
        session.nodes[foreign.id] = props
        session.edges.append((source.id, "HAS_SOURCE_REVISION", foreign.id))
    elif corruption == "contradictory_edge":
        session.edges.append((source.id, "HAS_SOURCE_REVISION", chunks[0].id))
    else:
        chunk_payload = json.loads(session.nodes[chunks[0].id]["payload_json"])
        chunk_payload["text"] = "different"
        session.nodes[chunks[0].id]["payload_json"] = json.dumps(chunk_payload)

    with pytest.raises(GraphWriteError):
        service.apply_source_chain_repair()
    assert session.audits == {}
    assert len(session.edges) == (1 if corruption in {"foreign_edge", "contradictory_edge"} else 0)


def test_neo4j_source_chain_repair_rolls_back_edges_when_audit_write_fails():
    service, session, _source, _revision, _chunks = _service()
    session.audit_failure = True
    with pytest.raises(GraphWriteError):
        service.apply_source_chain_repair()
    assert session.edges == []
    assert session.audits == {}


def test_neo4j_source_chain_repair_rejects_a_conflicting_deterministic_audit():
    service, session, _source, _revision, _chunks = _service()
    preview = service.preview_source_chain_repair()
    fingerprint = payload_fingerprint("repair_source_chain_edges", service.owner_id, preview.edges_to_add)
    key = f"source-chain-repair:{fingerprint[:32]}"
    audit_id = f"audit_{sha256(f'{service.owner_id}:{key}'.encode()).hexdigest()[:32]}"
    session.audits[audit_id] = {"owner_id": "another-owner"}

    with pytest.raises(GraphWriteError, match="audit conflicts"):
        service.apply_source_chain_repair()
    assert session.edges == []
    assert len(session.audits) == 1
