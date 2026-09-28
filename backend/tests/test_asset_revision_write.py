from __future__ import annotations

import pytest
from hashlib import sha256

from dots.founder_graph import Asset, AssetKind, EgressPolicy, KnowledgeAsset
from dots.founder_graph_write import (
    GraphWriteNotFoundError,
    GraphWriteError,
    IdempotencyConflictError,
    InMemoryGraphWriteService,
    NodeAlreadyExistsError,
    RevisionConflictError,
)
from dots.founder_graph_read import GraphReadNotFoundError, GraphReadService
from dots.founder_graph_lifecycle_resolver import resolve_restored_asset_reference


def test_revise_asset_appends_owner_scoped_shareable_revision_and_replays() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    original = KnowledgeAsset(
        owner_id="owner-1", id="asset-root", name="Original title",
        description="Original content", egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(original, idempotency_key="asset-create", operation="capture_asset")

    args = {
        "asset_id": original.id, "name": "Edited title", "description": "Edited content",
        "expected_revision": 1, "idempotency_key": "asset-edit-1",
    }
    first = writes.revise_asset(**args)
    replay = writes.revise_asset(**args)
    successor = writes.get_node(first.target_id)

    assert first.operation == "revise_asset"
    assert first.target_type == "asset"
    assert first.revision == 2
    assert successor.id != original.id
    assert successor.supersedes_id == original.id
    assert successor.revision == 2
    assert successor.name == "Edited title"
    assert successor.description == "Edited content"
    assert successor.kind is original.kind
    assert successor.egress_policy is EgressPolicy.SHAREABLE
    assert successor.details == original.details
    assert writes.get_node(original.id) == original
    assert replay.replayed and replay.target_id == successor.id
    assert len([node for node in writes.nodes() if isinstance(node, Asset) and node.supersedes_id == original.id]) == 1


def test_reclassifying_asset_preserves_content_sharing_and_revision_history() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    original = KnowledgeAsset(owner_id="owner-1", id="strength-root", name="現場経験",
                              description="改善の経験", egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(original, idempotency_key="classification-create")
    first = writes.revise_asset(asset_id=original.id, name=original.name,
                                description=original.description, expected_revision=1,
                                idempotency_key="move-to-barrier", kind=AssetKind.BARRIER)
    barrier = writes.get_node(first.target_id)
    assert barrier.kind is AssetKind.BARRIER
    assert barrier.egress_policy is original.egress_policy
    assert barrier.description == original.description
    second = writes.revise_asset(asset_id=barrier.id, name=barrier.name,
                                 description=barrier.description, expected_revision=2,
                                 idempotency_key="move-to-strength", kind=AssetKind.STRENGTH)
    assert writes.get_node(second.target_id).kind is AssetKind.STRENGTH
    assert writes.get_node(original.id).kind is AssetKind.KNOWLEDGE
    assert resolve_restored_asset_reference(second.target_id, (original, barrier, writes.get_node(second.target_id))) == writes.get_node(second.target_id)
    assert resolve_restored_asset_reference(original.id, (original, barrier, writes.get_node(second.target_id))) is None
    with pytest.raises(IdempotencyConflictError):
        writes.revise_asset(asset_id=original.id, name=original.name,
                            description=original.description, expected_revision=1,
                            idempotency_key="move-to-barrier", kind=AssetKind.STRENGTH)


def test_revise_asset_rejects_stale_or_noncurrent_assets_and_key_reuse() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    original = Asset(owner_id="owner-1", id="asset-cas", name="Original")
    writes.put_node(original, idempotency_key="asset-cas-create", operation="capture_asset")
    saved = writes.revise_asset(
        asset_id=original.id, name="Current", description="current",
        expected_revision=1, idempotency_key="asset-cas-edit",
    )
    with pytest.raises(RevisionConflictError):
        writes.revise_asset(
            asset_id=original.id, name="Stale", description="stale",
            expected_revision=1, idempotency_key="asset-cas-stale",
        )
    with pytest.raises(RevisionConflictError):
        writes.revise_asset(
            asset_id=saved.target_id, name="Stale revision", description="stale",
            expected_revision=1, idempotency_key="asset-cas-stale-revision",
        )
    with pytest.raises(IdempotencyConflictError):
        writes.revise_asset(
            asset_id=original.id, name="Different payload", description="current",
            expected_revision=1, idempotency_key="asset-cas-edit",
        )


def test_revise_asset_rejects_foreign_asset_without_creating_a_successor() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    foreign = Asset(owner_id="owner-2", id="asset-foreign", name="Foreign")
    with pytest.raises(GraphWriteNotFoundError):
        writes.revise_asset(
            asset_id=foreign.id, name="Changed", description="changed",
            expected_revision=1, idempotency_key="asset-foreign-edit",
        )
    assert writes.nodes() == ()


def test_generic_asset_capture_cannot_seed_successor_or_orphan_revision() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    for node in (
        Asset(owner_id="owner-1", id="asset-orphan-create", name="Orphan", revision=2,
              supersedes_id="missing-parent"),
        Asset(owner_id="owner-1", id="asset-branch-create", name="Branch", revision=2,
              supersedes_id="asset-root-create"),
    ):
        with pytest.raises(GraphWriteError, match="start at revision one"):
            writes.put_node(node, idempotency_key=f"capture-{node.id}", operation="capture_asset")
    assert writes.nodes() == ()


def test_asset_search_and_fetch_expose_only_the_current_revision() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    original = Asset(owner_id="owner-1", id="asset-read", name="OldUniqueTitle",
                     description="OldUniqueDescription")
    writes.put_node(original, idempotency_key="asset-read-create", operation="capture_asset")
    receipt = writes.revise_asset(
        asset_id=original.id, name="CurrentUniqueTitle", description="CurrentUniqueDescription",
        expected_revision=1, idempotency_key="asset-read-edit",
    )
    reads = GraphReadService(writes)

    assert [hit.node.id for hit in reads.search("CurrentUniqueTitle", owner_id="owner-1").hits] == [receipt.target_id]
    assert reads.search("OldUniqueTitle", owner_id="owner-1").hits == ()
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch(original.id, owner_id="owner-1")
    assert reads.fetch(receipt.target_id, owner_id="owner-1").id == receipt.target_id


def test_asset_revision_fails_closed_on_broken_lineage_and_metadata_drift() -> None:
    orphaned = InMemoryGraphWriteService("owner-1")
    invalid_root = Asset(owner_id="owner-1", id="asset-orphan", name="Orphan",
                         revision=2, supersedes_id="missing-parent")
    orphaned._nodes[invalid_root.id] = invalid_root
    orphaned._node_history[invalid_root.id] = [invalid_root]
    with pytest.raises(GraphWriteError):
        orphaned.revise_asset(
            asset_id=invalid_root.id, name="Changed", description="changed",
            expected_revision=2, idempotency_key="asset-orphan-edit",
        )

    drifted = InMemoryGraphWriteService("owner-1")
    parent = Asset(owner_id="owner-1", id="asset-parent", name="Parent",
                   egress_policy=EgressPolicy.SHAREABLE)
    drifted.put_node(parent, idempotency_key="asset-parent-create", operation="capture_asset")
    child = Asset(
        owner_id="owner-1", id="asset-child", name="Child", revision=2,
        supersedes_id=parent.id, egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    drifted._nodes[child.id] = child
    drifted._node_history[child.id] = [child]
    with pytest.raises(GraphWriteError):
        drifted.revise_asset(
            asset_id=parent.id, name="Changed", description="changed",
            expected_revision=1, idempotency_key="asset-parent-edit",
        )


@pytest.mark.parametrize("edit_child", [False, True])
def test_asset_revision_rejects_private_details_drift(edit_child) -> None:
    writes = InMemoryGraphWriteService("owner-1")
    parent = Asset(owner_id="owner-1", id="details-root", name="Root", details={"note": "original"})
    writes.put_node(parent, idempotency_key="details-create")
    child = Asset(owner_id="owner-1", id="details-child", name="Child", revision=2,
                  supersedes_id=parent.id, details={"note": "mutated"})
    writes._nodes[child.id] = child  # Simulate corrupt persisted state, never a public capture.
    current = child if edit_child else parent
    with pytest.raises(GraphWriteError, match="history is invalid"):
        writes.revise_asset(asset_id=current.id, name="Edited", description="synthetic",
                            expected_revision=current.revision, idempotency_key="details-edit")
    assert len(writes.nodes()) == 2


def test_asset_revision_collision_and_audit_failure_roll_back_cleanly(monkeypatch) -> None:
    writes = InMemoryGraphWriteService("owner-1")
    original = Asset(owner_id="owner-1", id="asset-rollback", name="Original")
    writes.put_node(original, idempotency_key="asset-rollback-create", operation="capture_asset")
    key = "asset-rollback-edit"
    collision_id = f"asset_{sha256(f'owner-1:{key}'.encode()).hexdigest()[:32]}"
    collision = Asset(owner_id="owner-1", id=collision_id, name="Collision")
    writes.put_node(collision, idempotency_key="asset-collision-create", operation="capture_asset")
    with pytest.raises(NodeAlreadyExistsError, match="already registered"):
        writes.revise_asset(
            asset_id=original.id, name="Edited", description="edited",
            expected_revision=1, idempotency_key=key,
        )
    assert writes.get_node(collision_id) == collision

    rollback = InMemoryGraphWriteService("owner-1")
    rollback.put_node(original, idempotency_key="asset-rollback-create-2", operation="capture_asset")
    monkeypatch.setattr(rollback, "_append_audit", lambda *_args: (_ for _ in ()).throw(RuntimeError("audit failed")))
    with pytest.raises(RuntimeError, match="audit failed"):
        rollback.revise_asset(
            asset_id=original.id, name="Edited", description="edited",
            expected_revision=1, idempotency_key="asset-audit-fail",
        )
    assert tuple(node.id for node in rollback.nodes()) == (original.id,)
