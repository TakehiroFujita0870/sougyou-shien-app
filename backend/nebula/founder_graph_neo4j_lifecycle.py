"""Transaction bodies for Neo4j Idea and Asset lifecycle transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .founder_graph import NodeType, Provenance, Status
from .founder_graph_write import GraphWriteNotFoundError, RevisionConflictError, WriteReceipt


def transition_idea_status_tx(
    gateway: Any,
    tx: Any,
    idea_id: str,
    expected_revision: int,
    key: str,
    actor: str,
    operation: str,
    target_status: Status,
    fingerprint: str,
    successor_id: str,
    non_current_statuses: frozenset[Status],
) -> WriteReceipt:
    replay = gateway._put_node_replay_tx(tx, operation=operation, idempotency_key=key, fingerprint=fingerprint)
    if replay is not None:
        return replay
    supplied = gateway._decode_idea_record(gateway._idea_record_tx(tx, idea_id), expected_id=idea_id)
    root_id = gateway._idea_root_for_tx(tx, supplied.id)
    chain = gateway._lock_current_idea_tx(tx, root_id)
    replay = gateway._put_node_replay_tx(tx, operation=operation, idempotency_key=key, fingerprint=fingerprint)
    if replay is not None:
        return replay
    current = chain[-1]
    if current.id != idea_id or current.revision != expected_revision:
        raise RevisionConflictError("Idea changed; reload its current revision")
    if target_status is Status.ARCHIVED:
        if current.status in non_current_statuses:
            raise GraphWriteNotFoundError("Idea does not exist for the local owner")
    else:
        if current.status is not Status.ARCHIVED:
            raise GraphWriteNotFoundError("archived Idea does not exist for the local owner")
        previous = next((item for item in reversed(chain[:-1]) if item.status is not Status.ARCHIVED), None)
        if previous is None or previous.status in non_current_statuses:
            raise GraphWriteNotFoundError("Idea has no restorable current revision")
        target_status = previous.status
    successor = replace(
        current, id=successor_id, status=target_status, revision=current.revision + 1,
        supersedes_id=current.id, created_at=datetime.now(timezone.utc), updated_at=None,
        provenance=Provenance(
            actor=actor, operation=operation, target_id=successor_id,
            source_id=current.id, idempotency_key=key,
        ),
    )
    return gateway._put_node_tx(
        tx, successor, NodeType.IDEA, gateway.label_for(NodeType.IDEA), key, 0,
        operation, actor, fingerprint,
    )


def transition_asset_status_tx(
    gateway: Any,
    tx: Any,
    asset_id: str,
    expected_revision: int,
    key: str,
    actor: str,
    operation: str,
    target_status: Status,
    fingerprint: str,
    successor_id: str,
) -> WriteReceipt:
    replay = gateway._put_node_replay_tx(tx, operation=operation, idempotency_key=key, fingerprint=fingerprint)
    if replay is not None:
        return replay
    locked = gateway._lock_revisioned_node_tx(tx, gateway.label_for(NodeType.ASSET), asset_id)
    if locked is None:
        raise GraphWriteNotFoundError("Asset does not exist for the local owner")
    replay = gateway._put_node_replay_tx(tx, operation=operation, idempotency_key=key, fingerprint=fingerprint)
    if replay is not None:
        return replay
    chain = gateway._asset_chain_tx(tx, asset_id)
    current = chain[-1]
    if current.id != asset_id or current.revision != expected_revision:
        raise RevisionConflictError("Asset changed; reload its current revision")
    expected_status = Status.ACTIVE if target_status is Status.ARCHIVED else Status.ARCHIVED
    if current.status is not expected_status:
        raise GraphWriteNotFoundError("Asset is not available for this status change")
    successor = replace(
        current.revise(
            id=successor_id, revision=current.revision + 1,
            provenance=Provenance(
                actor=actor, operation=operation, target_id=successor_id,
                source_id=current.id, idempotency_key=key,
            ),
        ),
        status=target_status,
    )
    return gateway._put_node_tx(
        tx, successor, NodeType.ASSET, gateway.label_for(NodeType.ASSET), key, 0,
        operation, actor, fingerprint, allow_asset_revision=True,
    )
