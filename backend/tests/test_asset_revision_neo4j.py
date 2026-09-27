from __future__ import annotations

import json
from hashlib import sha256

import pytest

from dots.founder_graph import Asset, EgressPolicy, NodeType
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_write import GraphWriteError, payload_fingerprint


class _Result:
    def __init__(self, row=None, rows=()):
        self.row = row
        self.rows = tuple(rows)

    def single(self, **_kwargs):
        return self.row

    def __iter__(self):
        return iter(self.rows or (() if self.row is None else (self.row,)))


class _AssetRevisionSession:
    def __init__(self, original):
        self.original = original
        self.created = {}
        self.audit = {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None

    def execute_write(self, callback):
        return callback(self)

    def run(self, query, **params):
        self.calls.append((query, params))
        if "MATCH (a:FounderGraphAudit" in query:
            key = params.get("key", params.get("idempotency_key"))
            row = self.audit.get(key)
            if row is not None and "AS fingerprint" in query:
                row = {**row, "fingerprint": row.get("payload_fingerprint")}
            return _Result(row)
        if "_dots_revision_write_lock" in query:
            if params.get("id") == self.original.id and "Asset" in query:
                return _Result({"id": self.original.id, "owner_id": self.original.owner_id,
                                "node_type": "asset", "revision": 1})
            return _Result()
        if "RETURN n.id AS id, n.owner_id AS owner_id, n.node_type AS node_type" in query and "payload_json" in query:
            if params.get("id") == self.original.id:
                props = _node_properties(self.original)
                return _Result({"id": self.original.id, "owner_id": self.original.owner_id,
                                "node_type": "asset", "revision": 1, "payload_json": props["payload_json"]})
        if "supersedes_id: $asset_id" in query:
            matches = [node for node in self.created.values() if node.get("supersedes_id") == params.get("asset_id")]
            return _Result(rows=tuple({"id": node["id"]} for node in matches))
        if "MATCH (n {id: $id})" in query:
            return _Result()
        if "CREATE (n:Asset)" in query:
            self.created[params["properties"]["id"]] = params["properties"]
            return _Result()
        if "CREATE (a:FounderGraphAudit" in query:
            self.audit[params["idempotency_key"]] = {
                "operation": params["operation"], "payload_fingerprint": params["payload_fingerprint"],
                "target_id": params["target_id"], "target_type": params["target_type"],
                "revision": params["revision"], "idempotency_key": params["idempotency_key"],
            }
        return _Result()


class _Driver:
    def __init__(self, session):
        self.value = session

    def session(self, *, database):
        assert database == "neo4j"
        return self.value


class _SerializedSameKeySession(_AssetRevisionSession):
    """Model another transaction committing its receipt while this call waits for the node lock."""

    def __init__(self, original, receipt):
        super().__init__(original)
        self.pending_receipt = receipt
        self.audit_reads = 0
        self.lock_acquired = False

    def run(self, query, **params):
        if "MATCH (a:FounderGraphAudit" in query:
            self.calls.append((query, params))
            self.audit_reads += 1
            if self.audit_reads == 1:
                return _Result()
            assert self.lock_acquired
            return _Result(self.pending_receipt)
        if "_dots_revision_write_lock" in query:
            self.lock_acquired = True
        return super().run(query, **params)


def test_neo4j_asset_writer_appends_and_replays_canonical_revision() -> None:
    original = Asset(owner_id="owner-1", id="persisted-asset", name="Original",
                     description="Original body", egress_policy=EgressPolicy.SHAREABLE)
    session = _AssetRevisionSession(original)
    gateway = Neo4jGraphGateway(_Driver(session), "owner-1")

    args = {
        "asset_id": original.id, "name": "Updated", "description": "Updated body",
        "expected_revision": 1, "idempotency_key": "persisted-asset-edit",
    }
    receipt = gateway.revise_asset(**args)
    replay = gateway.revise_asset(**args)
    stored = session.created[receipt.target_id]
    payload = json.loads(stored["payload_json"])

    assert receipt.revision == 2 and receipt.target_type == NodeType.ASSET.value
    assert replay.replayed and replay.target_id == receipt.target_id
    assert payload["supersedes_id"] == original.id and payload["revision"] == 2
    assert stored["supersedes_id"] == original.id
    assert payload["egress_policy"] == EgressPolicy.SHAREABLE.value


def test_neo4j_asset_writer_rechecks_same_key_receipt_after_acquiring_lock() -> None:
    original = Asset(owner_id="owner-1", id="persisted-asset", name="Original")
    arguments = {
        "asset_id": original.id, "name": "Updated", "description": "Updated body",
        "expected_revision": 1, "idempotency_key": "concurrent-asset-edit",
    }
    successor_id = f"asset_{sha256(b'owner-1:concurrent-asset-edit').hexdigest()[:32]}"
    session = _SerializedSameKeySession(original, {
        "payload_fingerprint": payload_fingerprint(
            "revise_asset", original.id, arguments["name"], arguments["description"], 1, "owner-1",
        ),
        "target_id": successor_id, "target_type": NodeType.ASSET.value, "revision": 2,
    })
    gateway = Neo4jGraphGateway(_Driver(session), "owner-1")

    receipt = gateway.revise_asset(**arguments)

    assert receipt.replayed and receipt.target_id == successor_id and receipt.revision == 2
    assert session.audit_reads == 2 and session.lock_acquired
    assert not session.created


def test_neo4j_generic_asset_capture_rejects_nonroot_revision_before_storage() -> None:
    session = _AssetRevisionSession(Asset(owner_id="owner-1", id="unused-root", name="Root"))
    gateway = Neo4jGraphGateway(_Driver(session), "owner-1")
    nonroot = Asset(
        owner_id="owner-1", id="forged-successor", name="Forged", revision=2,
        supersedes_id="missing-parent",
    )

    with pytest.raises(GraphWriteError, match="start at revision one"):
        gateway.put_node(nonroot, idempotency_key="forged-capture", operation="capture_asset")
    with pytest.raises(GraphWriteError, match="start at revision one"):
        gateway.put_node(nonroot, idempotency_key="forged-command", operation="revise_asset")
    assert session.calls == []


@pytest.mark.parametrize(
    ("scalar_parent", "payload_parent"),
    [(None, "legacy-root"), ("legacy-root", None)],
)
def test_neo4j_asset_decoder_rejects_scalar_payload_parent_mismatch(
    scalar_parent: str | None, payload_parent: str | None,
) -> None:
    gateway = Neo4jGraphGateway(
        _Driver(_AssetRevisionSession(Asset(owner_id="owner-1", id="unused", name="Unused"))), "owner-1"
    )
    payload_asset = Asset(
        owner_id="owner-1", id="decoded-asset", name="Decoded",
        revision=2 if payload_parent is not None else 1,
        supersedes_id=payload_parent,
    )
    properties = _node_properties(payload_asset)
    row = {
        "id": payload_asset.id, "owner_id": "owner-1", "node_type": "asset",
        "revision": payload_asset.revision, "supersedes_id": scalar_parent,
        "payload_json": properties["payload_json"],
    }

    with pytest.raises(GraphWriteError, match="persisted Asset state is invalid"):
        gateway._decode_asset_record(row)


def test_neo4j_asset_decoder_accepts_legacy_root_with_both_parent_fields_missing() -> None:
    gateway = Neo4jGraphGateway(
        _Driver(_AssetRevisionSession(Asset(owner_id="owner-1", id="unused", name="Unused"))), "owner-1"
    )
    properties = _node_properties(Asset(owner_id="owner-1", id="legacy-root", name="Legacy"))
    payload = json.loads(properties["payload_json"])
    payload.pop("revision", None)
    payload.pop("supersedes_id", None)
    row = {
        "id": "legacy-root", "owner_id": "owner-1", "node_type": "asset",
        "revision": 0, "supersedes_id": None, "payload_json": json.dumps(payload),
    }

    decoded = gateway._decode_asset_record(row)

    assert decoded.id == "legacy-root"
    assert decoded.revision == 1
    assert decoded.supersedes_id is None
