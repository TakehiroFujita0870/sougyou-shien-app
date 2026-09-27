from dataclasses import replace

from dots.founder_graph import Asset, EgressPolicy, Idea, Provenance, Status
from dots.founder_graph_lifecycle_resolver import (
    lifecycle_reference_aliases,
    resolve_restored_asset_reference,
    resolve_restored_idea_reference,
)


def _successor(previous: Idea, *, node_id: str, status: Status, operation: str) -> Idea:
    return replace(
        previous,
        id=node_id,
        revision=previous.revision + 1,
        supersedes_id=previous.id,
        status=status,
        provenance=Provenance(
            actor="local-owner", operation=operation, target_id=node_id,
            source_id=previous.id, idempotency_key=f"key-{node_id}",
        ),
    )


def _restored_chain() -> tuple[Idea, ...]:
    root = Idea(id="idea-0", owner_id="owner", title="A", status=Status.ACTIVE)
    archived = _successor(root, node_id="idea-1", status=Status.ARCHIVED, operation="archive_idea")
    restored = _successor(archived, node_id="idea-2", status=Status.ACTIVE, operation="restore_idea")
    return root, archived, restored


def test_restored_tip_resolves_older_lifecycle_only_reference() -> None:
    chain = _restored_chain()

    assert resolve_restored_idea_reference("idea-0", chain) is chain[-1]
    assert resolve_restored_idea_reference("idea-1", chain) is chain[-1]


def test_resolver_does_not_revive_reference_across_content_edit() -> None:
    root, archived, restored = _restored_chain()
    edited = replace(
        restored, id="idea-3", revision=restored.revision + 1,
        supersedes_id=restored.id, title="Changed",
        provenance=Provenance(actor="local-owner", operation="revise", target_id="idea-3", source_id=restored.id),
    )

    assert resolve_restored_idea_reference(root.id, (root, archived, restored, edited)) is None


def test_resolver_rejects_changed_share_policy_and_wrong_owner() -> None:
    root, archived, restored = _restored_chain()
    changed = replace(restored, egress_policy=EgressPolicy.SHAREABLE)
    wrong_owner = replace(restored, owner_id="another-owner")

    assert resolve_restored_idea_reference(root.id, (root, archived, changed)) is None
    assert resolve_restored_idea_reference(root.id, (root, archived, wrong_owner)) is None


def test_resolver_requires_active_tip_and_valid_restore_operation() -> None:
    root, archived, _restored = _restored_chain()
    still_archived = _successor(archived, node_id="idea-2", status=Status.ARCHIVED, operation="restore_idea")
    forged = _successor(archived, node_id="idea-2", status=Status.ACTIVE, operation="revise")

    assert resolve_restored_idea_reference(root.id, (root, archived, still_archived)) is None
    assert resolve_restored_idea_reference(root.id, (root, archived, forged)) is None


def test_resolver_restores_any_write_supported_current_idea_status() -> None:
    root = Idea(id="idea-pending", owner_id="owner", title="A", status=Status.PENDING_APPROVAL)
    archived = _successor(root, node_id="idea-pending-archived", status=Status.ARCHIVED, operation="archive_idea")
    restored = _successor(
        archived, node_id="idea-pending-restored", status=Status.PENDING_APPROVAL,
        operation="restore_idea",
    )

    assert resolve_restored_idea_reference(root.id, (root, archived, restored)) is restored


def test_asset_reference_resolves_only_across_archive_restore_not_revision() -> None:
    root = Asset(id="asset-0", owner_id="owner", name="Asset", status=Status.ACTIVE)
    archived = replace(
        root, id="asset-1", revision=2, supersedes_id=root.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="local-owner", operation="archive_asset", target_id="asset-1", source_id=root.id),
    )
    restored = replace(
        archived, id="asset-2", revision=3, supersedes_id=archived.id, status=Status.ACTIVE,
        provenance=Provenance(actor="local-owner", operation="restore_asset", target_id="asset-2", source_id=archived.id),
    )
    revised = replace(
        restored, id="asset-3", revision=4, supersedes_id=restored.id, name="Changed",
        provenance=Provenance(actor="local-owner", operation="revise_asset", target_id="asset-3", source_id=restored.id),
    )

    assert resolve_restored_asset_reference(root.id, (root, archived, restored)) is restored
    assert resolve_restored_asset_reference(root.id, (root, archived, restored, revised)) is None


def test_lifecycle_alias_map_resolves_idea_and_asset_restore_chains_once() -> None:
    idea_chain = _restored_chain()
    asset = Asset(id="asset-0", owner_id="owner", name="Asset", status=Status.ACTIVE)
    asset_archived = replace(
        asset, id="asset-1", revision=2, supersedes_id=asset.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="local-owner", operation="archive_asset", target_id="asset-1", source_id=asset.id),
    )
    asset_restored = replace(
        asset_archived, id="asset-2", revision=3, supersedes_id=asset_archived.id, status=Status.ACTIVE,
        provenance=Provenance(actor="local-owner", operation="restore_asset", target_id="asset-2", source_id=asset_archived.id),
    )
    ordinary_edit = replace(
        asset_restored, id="asset-3", revision=4, supersedes_id=asset_restored.id, description="Changed",
        provenance=Provenance(actor="local-owner", operation="revise_asset", target_id="asset-3", source_id=asset_restored.id),
    )

    aliases = lifecycle_reference_aliases((*idea_chain, asset, asset_archived, asset_restored))
    assert aliases == {
        "idea-0": "idea-2", "idea-1": "idea-2", "idea-2": "idea-2",
        "asset-0": "asset-2", "asset-1": "asset-2", "asset-2": "asset-2",
    }
    edited_aliases = lifecycle_reference_aliases((*idea_chain, asset, asset_archived, asset_restored, ordinary_edit))
    assert not {"asset-0", "asset-1", "asset-2"}.intersection(edited_aliases)


def test_lifecycle_alias_map_uses_only_archive_restore_suffix_after_normal_revision() -> None:
    idea_root = Idea(id="idea-root", owner_id="owner", title="Original", status=Status.ACTIVE)
    idea_edit = replace(
        idea_root, id="idea-edit", revision=1, supersedes_id=idea_root.id, title="Edited",
        provenance=Provenance(actor="local-owner", operation="revise_idea", target_id="idea-edit", source_id=idea_root.id),
    )
    idea_archived = _successor(idea_edit, node_id="idea-archived", status=Status.ARCHIVED, operation="archive_idea")
    idea_restored = _successor(idea_archived, node_id="idea-restored", status=Status.ACTIVE, operation="restore_idea")
    asset_root = Asset(id="asset-root", owner_id="owner", name="Original")
    asset_edit = replace(
        asset_root, id="asset-edit", revision=2, supersedes_id=asset_root.id, name="Edited",
        provenance=Provenance(actor="local-owner", operation="revise_asset", target_id="asset-edit", source_id=asset_root.id),
    )
    asset_archived = replace(
        asset_edit, id="asset-archived", revision=3, supersedes_id=asset_edit.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="local-owner", operation="archive_asset", target_id="asset-archived", source_id=asset_edit.id),
    )
    asset_restored = replace(
        asset_archived, id="asset-restored", revision=4, supersedes_id=asset_archived.id, status=Status.ACTIVE,
        provenance=Provenance(actor="local-owner", operation="restore_asset", target_id="asset-restored", source_id=asset_archived.id),
    )

    aliases = lifecycle_reference_aliases((
        idea_root, idea_edit, idea_archived, idea_restored,
        asset_root, asset_edit, asset_archived, asset_restored,
    ))

    assert "idea-root" not in aliases
    assert aliases["idea-edit"] == aliases["idea-archived"] == aliases["idea-restored"] == "idea-restored"
    assert "asset-root" not in aliases
    assert aliases["asset-edit"] == aliases["asset-archived"] == aliases["asset-restored"] == "asset-restored"
