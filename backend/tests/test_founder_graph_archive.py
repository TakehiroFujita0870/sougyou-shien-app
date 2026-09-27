from __future__ import annotations

import pytest

from dots.founder_graph import Asset, AssetKind, EgressPolicy, Idea, Status
from dots.founder_graph_write import InMemoryGraphWriteService, RevisionConflictError


def test_idea_archive_restore_append_history_and_old_replay_does_not_rearchive() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    original = Idea(
        owner_id="owner-1", id="idea-1", title="Founder idea", summary="Summary",
        description="Description", source_text="Source", tags=("founder",),
        status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(original, idempotency_key="create-idea")

    archived = writes.archive_idea(
        original.id, expected_revision=original.revision, idempotency_key="archive-idea",
    )
    archived_node = writes.get_node(archived.target_id)
    assert isinstance(archived_node, Idea)
    assert archived_node.status is Status.ARCHIVED
    assert archived_node.supersedes_id == original.id
    assert (archived_node.title, archived_node.summary, archived_node.description) == (
        original.title, original.summary, original.description,
    )
    assert archived_node.source_text == original.source_text
    assert archived_node.tags == original.tags
    assert archived_node.egress_policy is original.egress_policy
    assert writes.get_node(original.id) == original

    restored = writes.restore_idea(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-idea",
    )
    restored_node = writes.get_node(restored.target_id)
    assert isinstance(restored_node, Idea)
    assert restored_node.status is Status.ACTIVE
    assert restored_node.supersedes_id == archived.target_id
    assert restored_node.revision == archived.revision + 1

    archived_replay = writes.archive_idea(
        original.id, expected_revision=original.revision, idempotency_key="archive-idea",
    )
    assert archived_replay.replayed is True
    assert archived_replay.target_id == archived.target_id
    assert writes.get_node(restored.target_id) == restored_node
    assert writes.get_node(archived.target_id) == archived_node
    assert len(writes.audit_events()) == 3


def test_idea_archive_and_restore_require_the_current_revision() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea", status=Status.ACTIVE)
    writes.put_node(idea, idempotency_key="create-idea")
    corrected = idea.revise(title="Corrected")
    writes.record_correction(idea.id, corrected, idempotency_key="correct-idea", expected_revision=0)

    with pytest.raises(RevisionConflictError):
        writes.archive_idea(idea.id, expected_revision=idea.revision, idempotency_key="stale-archive")
    archived = writes.archive_idea(
        corrected.id, expected_revision=corrected.revision, idempotency_key="archive-current",
    )
    with pytest.raises(RevisionConflictError):
        writes.restore_idea(archived.target_id, expected_revision=corrected.revision, idempotency_key="stale-restore")


def test_asset_archive_restore_preserve_sharing_and_are_idempotent() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    asset = Asset(
        owner_id="owner-1", id="asset-1", name="Shared asset", kind=AssetKind.ARTIFACT,
        description="Original", egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(asset, idempotency_key="create-asset", operation="capture_asset")

    archived = writes.archive_asset(
        asset.id, expected_revision=asset.revision, idempotency_key="archive-asset",
    )
    archived_node = writes.get_node(archived.target_id)
    assert isinstance(archived_node, Asset)
    assert archived_node.status is Status.ARCHIVED
    assert archived_node.supersedes_id == asset.id
    assert archived_node.name == asset.name
    assert archived_node.description == asset.description
    assert archived_node.kind is asset.kind
    assert archived_node.egress_policy is asset.egress_policy
    assert archived_node.details == asset.details

    restored = writes.restore_asset(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-asset",
    )
    restored_node = writes.get_node(restored.target_id)
    assert isinstance(restored_node, Asset)
    assert restored_node.status is Status.ACTIVE
    assert restored_node.supersedes_id == archived.target_id
    assert restored_node.revision == archived.revision + 1
    replay = writes.restore_asset(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-asset",
    )
    assert replay.replayed is True
    assert replay.target_id == restored.target_id
    assert writes.get_node(restored.target_id) == restored_node

    with pytest.raises(RevisionConflictError):
        writes.archive_asset(asset.id, expected_revision=asset.revision, idempotency_key="stale-archive")
    assert len(writes.audit_events()) == 3
