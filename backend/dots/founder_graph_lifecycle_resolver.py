"""Resolve historical Idea references across archive/restore-only successors."""

from __future__ import annotations

from typing import Sequence

from .founder_graph import Asset, Idea, Status


_NON_CURRENT_IDEA_STATUSES = frozenset({
    Status.ARCHIVED, Status.SUPERSEDED, Status.RETRACTED, Status.EXPIRED,
    Status.CANCELLED, Status.REVOKED, Status.FAILED,
})


def resolve_restored_idea_reference(reference_id: str, chain: Sequence[Idea]) -> Idea | None:
    """Return the active tip only when ``reference_id`` crosses lifecycle-only successors.

    This is deliberately not a general revision alias: any content revision,
    malformed lineage, branch, owner change, or altered shareability/content
    permanently prevents old references from becoming current again.
    """

    if not isinstance(reference_id, str) or not reference_id or not chain:
        return None
    if any(not isinstance(item, Idea) for item in chain):
        return None
    if chain[0].revision != 0 or chain[-1].status in _NON_CURRENT_IDEA_STATUSES:
        return None
    if any(
        current.owner_id != chain[0].owner_id
        or current.revision != previous.revision + 1
        or current.supersedes_id != previous.id
        for previous, current in zip(chain, chain[1:])
    ):
        return None
    index = next((i for i, node in enumerate(chain) if node.id == reference_id), None)
    if index is None:
        return None
    for position, (previous, current) in enumerate(zip(chain[index:], chain[index + 1:]), start=index + 1):
        provenance = current.provenance
        operation = provenance.operation
        if (
            current.title != previous.title
            or current.summary != previous.summary
            or current.description != previous.description
            or current.source_text != previous.source_text
            or current.tags != previous.tags
            or current.egress_policy is not previous.egress_policy
            or provenance.source_id != previous.id
            or provenance.target_id != current.id
        ):
            return None
        if operation == "archive_idea":
            if previous.status in _NON_CURRENT_IDEA_STATUSES or current.status is not Status.ARCHIVED:
                return None
        elif operation == "restore_idea":
            if previous.status is not Status.ARCHIVED:
                return None
            expected = next((item.status for item in reversed(chain[:position - 1])
                             if item.status is not Status.ARCHIVED), None)
            if expected in _NON_CURRENT_IDEA_STATUSES or current.status is not expected:
                return None
        else:
            return None
    return chain[-1]


def resolve_restored_asset_reference(reference_id: str, chain: Sequence[Asset]) -> Asset | None:
    """Resolve Asset references only across content-identical archive/restore successors."""

    if not isinstance(reference_id, str) or not reference_id or not chain:
        return None
    if any(not isinstance(item, Asset) for item in chain):
        return None
    if chain[0].revision != 1 or chain[-1].status is not Status.ACTIVE:
        return None
    if any(
        type(current) is not type(chain[0])
        or current.owner_id != chain[0].owner_id
        or current.kind is not chain[0].kind
        or current.egress_policy is not chain[0].egress_policy
        or current.details != chain[0].details
        or current.revision != previous.revision + 1
        or current.supersedes_id != previous.id
        for previous, current in zip(chain, chain[1:])
    ):
        return None
    index = next((i for i, node in enumerate(chain) if node.id == reference_id), None)
    if index is None:
        return None
    for previous, current in zip(chain[index:], chain[index + 1:]):
        provenance = current.provenance
        if (
            current.name != previous.name
            or current.description != previous.description
            or current.details != previous.details
            or current.kind is not previous.kind
            or current.egress_policy is not previous.egress_policy
            or provenance.source_id != previous.id
            or provenance.target_id != current.id
        ):
            return None
        if provenance.operation == "archive_asset":
            if previous.status is not Status.ACTIVE or current.status is not Status.ARCHIVED:
                return None
        elif provenance.operation == "restore_asset":
            if previous.status is not Status.ARCHIVED or current.status is not Status.ACTIVE:
                return None
        else:
            return None
    return chain[-1]
