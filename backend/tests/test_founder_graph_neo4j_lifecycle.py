from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pytest

from nebula.founder_graph import Asset, Idea, NodeType, Status
from nebula.founder_graph_neo4j import Neo4jGraphGateway, Neo4jUnavailableError, _node_properties
from nebula.founder_graph_write import (
    GraphWriteError,
    IdempotencyConflictError,
    InMemoryGraphWriteService,
    RevisionConflictError,
)


@dataclass
class FakeResult:
    row: dict[str, object] | None = None
    rows: tuple[dict[str, object], ...] = ()

    def single(self, **_kwargs):
        return self.row

    def __iter__(self):
        return iter(self.rows if self.rows else (() if self.row is None else (self.row,)))


class LifecycleSession:
    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id
        self.nodes: dict[str, dict[str, object]] = {}
        self.audits: dict[str, dict[str, object]] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_audit_create = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self) -> None:
        return None

    def execute_write(self, callback):
        nodes_before = deepcopy(self.nodes)
        audits_before = deepcopy(self.audits)
        try:
            return callback(self)
        except Exception:
            self.nodes = nodes_before
            self.audits = audits_before
            raise

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (a:FounderGraphAudit" in query:
            row = next((audit for audit in self.audits.values()
                        if audit.get("owner_id") == params.get("owner_id")
                        and audit.get("idempotency_key") == params.get("idempotency_key")), None)
            if row is None and "key" in params:
                row = next((audit for audit in self.audits.values()
                            if audit.get("owner_id") == params.get("owner_id")
                            and audit.get("idempotency_key") == params.get("key")), None)
            return FakeResult(row)

        if "CREATE (a:FounderGraphAudit" in query:
            if self.fail_audit_create:
                raise RuntimeError("synthetic audit write failure")
            row = {
                "id": params["audit_id"], "owner_id": params["owner_id"],
                "actor": params["actor"], "operation": params["operation"],
                "target_id": params["target_id"], "target_type": params["target_type"],
                "revision": params["revision"], "idempotency_key": params["idempotency_key"],
                "payload_fingerprint": params["payload_fingerprint"],
            }
            self.audits[str(row["idempotency_key"])] = row
            return FakeResult()

        if "SET i._nebula_idea_write_lock" in query or "SET n._nebula_revision_write_lock" in query:
            node = self.nodes.get(str(params.get("id")))
            if node is None or node.get("owner_id") != params.get("owner_id"):
                return FakeResult()
            return FakeResult({
                "id": node["id"], "owner_id": node["owner_id"],
                "node_type": node["node_type"], "revision": node.get("revision", 0),
            })

        if "MATCH (i:Idea {id: $id, owner_id: $owner_id})" in query:
            node = self.nodes.get(str(params.get("id")))
            return FakeResult(self._record(node) if node and node.get("node_type") == "idea"
                              and node.get("owner_id") == params.get("owner_id") else None)

        if "MATCH (i:Idea {owner_id: $owner_id})" in query:
            return FakeResult(rows=tuple(
                self._record(node, supersedes=True) for node in self.nodes.values()
                if node.get("node_type") == "idea" and node.get("owner_id") == params.get("owner_id")
            ))

        if "MATCH (n {id: $id, owner_id: $owner_id})" in query and "$node_types" in query:
            node = self.nodes.get(str(params.get("id")))
            return FakeResult(self._record(node, supersedes=True) if node
                              and node.get("owner_id") == params.get("owner_id")
                              and node.get("node_type") in params.get("node_types", ()) else None)

        if "MATCH (n {owner_id: $owner_id, supersedes_id: $parent_id})" in query:
            return FakeResult(rows=tuple(
                self._record(node, supersedes=True) for node in self.nodes.values()
                if node.get("owner_id") == params.get("owner_id")
                and node.get("supersedes_id") == params.get("parent_id")
                and node.get("node_type") in params.get("node_types", ())
            ))

        if "MATCH (n {id: $id})" in query:
            node = self.nodes.get(str(params.get("id")))
            return FakeResult({"owner_id": node.get("owner_id"), "node_type": node.get("node_type"),
                               "revision": node.get("revision", 0)} if node else None)

        if "CREATE (n:" in query and "SET n = $properties" in query:
            properties = deepcopy(params["properties"])
            self.nodes[str(properties["id"])] = properties
            return FakeResult()

        raise AssertionError(f"unexpected lifecycle query: {query}")

    @staticmethod
    def _record(node: dict[str, object], *, supersedes: bool = False) -> dict[str, object]:
        result = {key: node.get(key) for key in (
            "id", "owner_id", "node_type", "revision", "payload_json",
        )}
        if supersedes:
            result["supersedes_id"] = node.get("supersedes_id")
        return result


class LifecycleDriver:
    def __init__(self, owner_id: str = "owner-lifecycle") -> None:
        self.session_value = LifecycleSession(owner_id)

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


def _seed_gateway(node: Idea | Asset):
    driver = LifecycleDriver(node.owner_id)
    driver.session_value.nodes[node.id] = _node_properties(node)
    return driver, Neo4jGraphGateway(driver, node.owner_id)


def test_neo4j_idea_edit_preserves_research_fields_and_replays_without_new_revision() -> None:
    original = Idea(id="idea-edit", owner_id="owner-lifecycle", title="元の題名",
                    description="元の説明", summary="調査済み概要", status=Status.ACTIVE)
    driver, gateway = _seed_gateway(original)
    result = gateway.revise_idea(
        idea_id=original.id, title="新しい題名", description="元の説明",
        expected_revision=0, idempotency_key="edit-idea-1",
    )
    saved = gateway._decode_idea_record(driver.session_value._record(driver.session_value.nodes[result.target_id]))
    assert saved.title == "新しい題名" and saved.description == "元の説明"
    assert saved.summary == original.summary and saved.status == original.status
    assert saved.supersedes_id == original.id and saved.revision == 1
    assert driver.session_value.nodes[original.id]["status"] == Status.ACTIVE.value
    replay = gateway.revise_idea(
        idea_id=original.id, title="新しい題名", description="元の説明",
        expected_revision=0, idempotency_key="edit-idea-1",
    )
    assert replay.replayed and replay.target_id == result.target_id
    assert len(driver.session_value.nodes) == 2
    with pytest.raises(RevisionConflictError):
        gateway.revise_idea(idea_id=original.id, title="別案", description="", expected_revision=0, idempotency_key="edit-idea-2")
    with pytest.raises(IdempotencyConflictError):
        gateway.revise_idea(idea_id=original.id, title="別案", description="", expected_revision=0, idempotency_key="edit-idea-1")


def test_neo4j_idea_description_edit_does_not_reuse_old_research_summary() -> None:
    original = Idea(id="idea-description", owner_id="owner-lifecycle", title="事業案",
                    description="旧内容", summary="旧内容に基づく調査", status=Status.ACTIVE)
    driver, gateway = _seed_gateway(original)
    receipt = gateway.revise_idea(
        idea_id=original.id, title=original.title, description="新内容",
        expected_revision=0, idempotency_key="edit-description",
    )
    saved = gateway._decode_idea_record(driver.session_value._record(driver.session_value.nodes[receipt.target_id]))
    assert saved.description == "新内容" and saved.summary == ""
    assert gateway._decode_idea_record(driver.session_value._record(driver.session_value.nodes[original.id])).summary == "旧内容に基づく調査"


@pytest.mark.parametrize("kind", ["idea", "asset"])
def test_neo4j_lifecycle_archive_restore_matches_memory_and_replay_is_noop(kind: str) -> None:
    owner_id = "owner-lifecycle"
    node = Idea(id="idea-lifecycle", owner_id=owner_id, title="Keep history", status=Status.ACTIVE) if kind == "idea" else Asset(
        id="asset-lifecycle", owner_id=owner_id, name="Keep history",
    )
    driver, gateway = _seed_gateway(node)
    memory = InMemoryGraphWriteService(owner_id)
    memory.put_node(node, idempotency_key=f"seed-{kind}", operation=f"capture_{kind}")

    archive_kwargs = {"expected_revision": node.revision, "idempotency_key": f"archive-{kind}"}
    archive = getattr(gateway, f"archive_{kind}")(node.id, **archive_kwargs)
    memory_archive = getattr(memory, f"archive_{kind}")(node.id, **archive_kwargs)
    assert (archive.operation, archive.target_id, archive.target_type, archive.revision) == (
        memory_archive.operation, memory_archive.target_id, memory_archive.target_type, memory_archive.revision,
    )
    archived_id = archive.target_id
    assert driver.session_value.nodes[node.id]["status"] == Status.ACTIVE.value
    assert driver.session_value.nodes[archived_id]["status"] == Status.ARCHIVED.value
    assert archive.revision == node.revision + 1

    replay = getattr(gateway, f"archive_{kind}")(node.id, **archive_kwargs)
    assert replay.replayed and replay.target_id == archived_id
    assert set(driver.session_value.nodes) == {node.id, archived_id}

    restore_kwargs = {"expected_revision": archive.revision, "idempotency_key": f"restore-{kind}"}
    restored = getattr(gateway, f"restore_{kind}")(archived_id, **restore_kwargs)
    memory_restored = getattr(memory, f"restore_{kind}")(archived_id, **restore_kwargs)
    assert (restored.operation, restored.target_id, restored.target_type, restored.revision) == (
        memory_restored.operation, memory_restored.target_id, memory_restored.target_type, memory_restored.revision,
    )
    current_id = restored.target_id
    assert driver.session_value.nodes[current_id]["status"] == Status.ACTIVE.value
    assert restored.revision == archive.revision + 1
    restore_replay = getattr(gateway, f"restore_{kind}")(archived_id, **restore_kwargs)
    assert restore_replay.replayed and restore_replay.target_id == current_id
    with pytest.raises(IdempotencyConflictError):
        getattr(gateway, f"restore_{kind}")(
            archived_id,
            expected_revision=archive.revision + 1,
            idempotency_key=restore_kwargs["idempotency_key"],
        )
    with pytest.raises(RevisionConflictError):
        getattr(gateway, f"restore_{kind}")(
            archived_id,
            expected_revision=archive.revision,
            idempotency_key=f"stale-restore-{kind}",
        )

    # A stale successful replay is an exact receipt lookup, never a rollback.
    stale_replay = getattr(gateway, f"archive_{kind}")(node.id, **archive_kwargs)
    assert stale_replay.replayed and stale_replay.target_id == archived_id
    assert driver.session_value.nodes[current_id]["status"] == Status.ACTIVE.value
    assert len(driver.session_value.audits) == 2


@pytest.mark.parametrize("kind", ["idea", "asset"])
def test_neo4j_lifecycle_rejects_stale_cas_and_changed_idempotency_payload(kind: str) -> None:
    node = Idea(id="idea-cas", owner_id="owner-lifecycle", title="CAS") if kind == "idea" else Asset(
        id="asset-cas", owner_id="owner-lifecycle", name="CAS",
    )
    _driver, gateway = _seed_gateway(node)
    archive = getattr(gateway, f"archive_{kind}")
    with pytest.raises(RevisionConflictError):
        archive(node.id, expected_revision=node.revision + 1, idempotency_key=f"stale-{kind}")
    success = archive(node.id, expected_revision=node.revision, idempotency_key=f"same-{kind}")
    with pytest.raises(IdempotencyConflictError):
        archive(node.id, expected_revision=node.revision + 1, idempotency_key=f"same-{kind}")
    assert success.revision == node.revision + 1


@pytest.mark.parametrize("kind", ["idea", "asset"])
def test_neo4j_lifecycle_rolls_back_successor_when_audit_write_fails(kind: str) -> None:
    node = Idea(id="idea-rollback", owner_id="owner-lifecycle", title="Rollback") if kind == "idea" else Asset(
        id="asset-rollback", owner_id="owner-lifecycle", name="Rollback",
    )
    driver, gateway = _seed_gateway(node)
    driver.session_value.fail_audit_create = True

    with pytest.raises(Neo4jUnavailableError, match="Neo4j operation failed"):
        getattr(gateway, f"archive_{kind}")(
            node.id, expected_revision=node.revision, idempotency_key=f"rollback-{kind}",
        )

    assert set(driver.session_value.nodes) == {node.id}
    assert not driver.session_value.audits
    assert any("_nebula_idea_write_lock" in query or "_nebula_revision_write_lock" in query
               for query, _params in driver.session_value.calls)


def test_neo4j_lifecycle_does_not_mutate_a_different_owners_record() -> None:
    node = Idea(id="idea-other-owner", owner_id="someone-else", title="Private")
    driver = LifecycleDriver("owner-lifecycle")
    driver.session_value.nodes[node.id] = _node_properties(node)
    gateway = Neo4jGraphGateway(driver, "owner-lifecycle")
    with pytest.raises(GraphWriteError):
        gateway.archive_idea(node.id, expected_revision=node.revision, idempotency_key="wrong-owner")
    assert set(driver.session_value.nodes) == {node.id}
    assert not driver.session_value.audits
