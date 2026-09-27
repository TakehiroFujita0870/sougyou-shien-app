"""Append-only local self-introduction edits through the Founder Graph gateway."""
from __future__ import annotations

from typing import Any, Protocol

from dots.founder_graph import Asset, EgressPolicy, Provenance, ProvenanceOrigin
from dots.local_home import HomeStore, read_local_home


class SelfIntroductionConflict(Exception):
    """The visible version changed since the owner opened the editor."""


class SelfIntroductionWriter(Protocol):
    def save(self, owner_id: str, text: str, expected_id: str | None, idempotency_key: str) -> str: ...


class Neo4jSelfIntroductionWriter:
    def __init__(self, home_store: HomeStore, gateway: Any) -> None:
        self._home_store = home_store
        self._gateway = gateway

    def save(self, owner_id: str, text: str, expected_id: str | None, idempotency_key: str) -> str:
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("self introduction must be 1-4000 characters")
        if expected_id is not None and (not isinstance(expected_id, str) or not expected_id.strip()):
            raise ValueError("expected_id is invalid")
        current = read_local_home(self._home_store, owner_id=owner_id)
        if current["status"] == "failed":
            raise RuntimeError("home read failed")
        prior = next((asset for asset in current["assets"] if asset["name"] == "自己紹介"), None)
        if (prior["id"] if prior else None) != expected_id:
            raise SelfIntroductionConflict()
        record = Asset(
            owner_id=owner_id,
            name="自己紹介",
            description=text.strip(),
            details={"supersedes_id": expected_id} if expected_id else {},
            egress_policy=EgressPolicy.LOCAL_ONLY,
            provenance=Provenance(actor="local-owner", operation="edit_self_intro", origin=ProvenanceOrigin.MANUAL, idempotency_key=idempotency_key),
        )
        receipt = self._gateway.put_node(record, idempotency_key=idempotency_key, operation="capture_asset", actor="local-owner")
        return receipt.target_id
