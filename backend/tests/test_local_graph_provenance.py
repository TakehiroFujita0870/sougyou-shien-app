from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from types import MappingProxyType
from collections.abc import Mapping

import pytest
from fastapi.testclient import TestClient

from dots.founder_graph import Asset, EgressPolicy, Idea, Status
from dots.founder_graph_read import NodeView
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.local_control import LocalControl, create_local_control_app
from dots.local_graph_provenance import (
    GraphProvenanceNotFound,
    Neo4jGraphProvenanceStore,
    read_local_graph_provenance,
)


NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self):
        self.nodes = {
            "ra": _view("ra", "relation_assertion", "owner", "confirmed", {
                "status": "confirmed", "valid_from": "2026-09-25T00:00:00+00:00", "expires_at": None,
                "source_id": "idea", "source_kind": "idea", "target_id": "asset", "target_kind": "asset", "based_on_brief_id": "brief",
                "based_on_brief_section_index": 2, "evidence_ids": ("ev-share", "ev-private"),
            }),
            "idea": _view("idea", "idea", "owner", "active", {"title": "Idea"}),
            "asset": _view("asset", "asset", "owner", "active", {"name": "Asset"}),
            "ev-share": _view("ev-share", "evidence", "owner", "active", {
                "egress_policy": "shareable", "status": "active", "polarity": "supports", "confidence": 0.8,
                "excerpt": "MUST NOT LEAK excerpt", "locator": "MUST NOT LEAK locator",
            }),
            "ev-private": _view("ev-private", "evidence", "owner", "active", {
                "egress_policy": "local_only", "status": "active", "polarity": "opposes", "confidence": 0.6,
            }),
        }
        self.successor = False
        self.idea_successor = False
        self.asset_successor = False
        self.lifecycle_aliases = {}
        self.latest_brief_id = "brief"
        self.brief = IdeaBriefVersion(
            id="brief", owner_id="owner", idea_lineage_root_id="idea", based_on_idea_id="idea",
            sections=(IdeaBriefSection(index=2, content="Chapter text", evidence_ids=("ev-share", "ev-private")),),
        )

    def fetch(self, node_id: str, *, owner_id: str):
        node = self.nodes.get(node_id)
        if node is None or node.owner_id != owner_id:
            raise GraphProvenanceNotFound("not found")
        return node

    def has_successor(self, assertion_id: str, *, owner_id: str) -> bool:
        return self.successor

    def has_idea_successor(self, idea_id: str, *, owner_id: str) -> bool:
        return self.idea_successor

    def resolve_lifecycle_references(self, references, *, owner_id: str):
        if owner_id != "owner":
            return {identity: None for identity, _kind in references}
        resolved = {}
        for identity, kind in references:
            if kind == "idea" and self.idea_successor:
                resolved[identity] = self.lifecycle_aliases.get(identity)
            elif kind == "asset" and self.asset_successor:
                resolved[identity] = self.lifecycle_aliases.get(identity)
            else:
                resolved[identity] = identity
        return resolved

    def get_brief(self, brief_id: str, *, owner_id: str):
        return self.brief if brief_id == self.brief.id and owner_id == self.brief.owner_id else None

    def get_latest_brief(self, root_id: str, *, owner_id: str):
        return self.brief if self.latest_brief_id == self.brief.id and root_id == self.brief.idea_lineage_root_id else None


def _view(identity, kind, owner, status, fields):
    return NodeView(identity, kind, owner, identity, "", status, 1, MappingProxyType(fields))


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class _LifecycleRowsDriver:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def session(self, *, database):
        assert database == "neo4j"
        return _LifecycleRowsSession(self)


class _LifecycleRowsSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **params):
        self.driver.calls.append((query, params))
        assert params["owner_id"] == "owner"
        assert set(params["node_types"]) and set(params["node_types"]).issubset({"idea", "asset"})
        return self.driver.rows


def _lifecycle_rows(writes):
    return tuple({
        "id": record.id,
        "node_type": record.node_type.value,
        "revision": record.revision,
        "supersedes_id": record.supersedes_id,
        "status": record.status.value,
        "payload_json": json.dumps(_json_value(record), ensure_ascii=False),
    } for record in writes.read_snapshot().nodes if isinstance(record, (Idea, Asset)))


def test_provenance_returns_only_exact_brief_section_and_shareable_evidence_metadata():
    store = FakeStore()
    result = read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)
    assert result == {
        "status": "ready", "assertion_id": "ra",
        "section": {
            "brief_id": "brief", "revision": 1, "idea_id": "idea", "section_index": 2,
            "title": "顧客とマーケットサイズ", "content": "Chapter text",
        },
        "evidence": [{"id": "ev-share", "polarity": "supports", "confidence": 0.8, "status": "active"}],
    }
    assert "MUST NOT LEAK" not in repr(result)


@pytest.mark.parametrize("case", ["successor", "idea_successor", "old_brief", "wrong_owner", "wrong_idea", "wrong_kind", "wrong_section", "malformed_evidence", "expired"])
def test_provenance_fails_closed_for_noncurrent_or_mismatched_evidence(case):
    store = FakeStore()
    if case == "successor":
        store.successor = True
    elif case == "idea_successor":
        store.idea_successor = True
    elif case == "old_brief":
        store.latest_brief_id = "newer-brief"
    elif case == "wrong_owner":
        store.nodes["idea"] = _view("idea", "idea", "other-owner", "active", {})
    elif case == "wrong_idea":
        store.brief = IdeaBriefVersion(
            id="brief", owner_id="owner", idea_lineage_root_id="other-idea", based_on_idea_id="other-idea",
            sections=(IdeaBriefSection(index=2, content="wrong chapter", evidence_ids=("ev-share", "ev-private")),),
        )
    elif case == "wrong_kind":
        store.nodes["ra"] = _view("ra", "relation_assertion", "owner", "confirmed", {
            **store.nodes["ra"].fields, "source_kind": "unknown",
        })
    elif case == "wrong_section":
        store.nodes["ra"] = _view("ra", "relation_assertion", "owner", "confirmed", {
            **store.nodes["ra"].fields, "based_on_brief_section_index": 8,
        })
    elif case == "malformed_evidence":
        store.nodes["ra"] = _view("ra", "relation_assertion", "owner", "confirmed", {
            **store.nodes["ra"].fields, "evidence_ids": None,
        })
    else:
        store.nodes["ra"] = _view("ra", "relation_assertion", "owner", "expired", {
            **store.nodes["ra"].fields, "expires_at": "2026-09-26T00:00:00+00:00",
        })
    with pytest.raises(GraphProvenanceNotFound):
        read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)


def test_legacy_assertion_without_brief_has_null_section():
    store = FakeStore()
    store.nodes["ra"] = _view("ra", "relation_assertion", "owner", "confirmed", {
        **store.nodes["ra"].fields, "based_on_brief_id": None, "based_on_brief_section_index": None,
    })
    result = read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)
    assert result["section"] is None


def test_provenance_resolves_idea_endpoint_after_lifecycle_only_restore():
    store = FakeStore()
    store.nodes["idea"] = _view("idea", "idea", "owner", "superseded", {"title": "Idea"})
    store.nodes["restored-idea"] = _view("restored-idea", "idea", "owner", "active", {"title": "Idea"})
    store.idea_successor = True
    store.lifecycle_aliases["idea"] = "restored-idea"

    result = read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)

    assert result["status"] == "ready"
    assert result["assertion_id"] == "ra"
    assert result["section"]["brief_id"] == "brief"
    assert result["evidence"] == [{"id": "ev-share", "polarity": "supports", "confidence": 0.8, "status": "active"}]


def test_provenance_does_not_alias_idea_across_a_normal_revision():
    store = FakeStore()
    store.nodes["idea"] = _view("idea", "idea", "owner", "superseded", {"title": "Idea"})
    store.nodes["edited-idea"] = _view("edited-idea", "idea", "owner", "active", {"title": "Edited idea"})
    store.idea_successor = True

    with pytest.raises(GraphProvenanceNotFound):
        read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)


def test_legacy_provenance_store_without_batch_resolver_still_rejects_idea_successors():
    store = FakeStore()
    store.resolve_lifecycle_references = None
    store.idea_successor = True

    with pytest.raises(GraphProvenanceNotFound):
        read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)


def test_provenance_resolves_asset_endpoint_after_lifecycle_only_restore():
    store = FakeStore()
    store.nodes["asset"] = _view("asset", "asset", "owner", "superseded", {"name": "Asset"})
    store.nodes["restored-asset"] = _view("restored-asset", "asset", "owner", "active", {"name": "Asset"})
    store.asset_successor = True
    store.lifecycle_aliases["asset"] = "restored-asset"

    result = read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)

    assert result["status"] == "ready"
    assert result["section"]["brief_id"] == "brief"
    assert result["evidence"] == [{"id": "ev-share", "polarity": "supports", "confidence": 0.8, "status": "active"}]


def test_provenance_keeps_nonrevisioned_claim_endpoint_identity():
    store = FakeStore()
    store.nodes["claim"] = _view("claim", "claim", "owner", "active", {"statement": "Synthetic claim"})
    store.nodes["ra"] = _view("ra", "relation_assertion", "owner", "confirmed", {
        **store.nodes["ra"].fields,
        "target_id": "claim", "target_kind": "claim", "predicate": "ADDRESSES",
    })

    result = read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)

    assert result["status"] == "ready"
    assert result["assertion_id"] == "ra"
    assert result["section"]["brief_id"] == "brief"


def test_provenance_does_not_alias_asset_across_a_normal_revision():
    store = FakeStore()
    store.nodes["asset"] = _view("asset", "asset", "owner", "superseded", {"name": "Asset"})
    store.nodes["edited-asset"] = _view("edited-asset", "asset", "owner", "active", {"name": "Edited asset"})
    store.asset_successor = True

    with pytest.raises(GraphProvenanceNotFound):
        read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)


@pytest.mark.parametrize("kind", ["idea", "asset"])
@pytest.mark.parametrize("normal_edit", [False, True])
def test_neo4j_shaped_lifecycle_rows_resolve_only_archive_restore_suffix(kind, normal_edit):
    writes = InMemoryGraphWriteService("owner")
    idea = Idea(
        owner_id="owner", id="idea-root", title="Synthetic idea", status=Status.ACTIVE,
        egress_policy=EgressPolicy.SHAREABLE, revision=1,
    )
    asset = Asset(
        owner_id="owner", id="asset-root", name="Synthetic asset", status=Status.ACTIVE,
        egress_policy=EgressPolicy.SHAREABLE, revision=1,
    )
    writes.put_node(idea, idempotency_key="seed-idea", operation="capture_idea")
    writes.put_node(asset, idempotency_key="seed-asset", operation="capture_asset")
    if kind == "idea":
        archived = writes.archive_idea(idea.id, expected_revision=1, idempotency_key="archive-idea")
        restored_receipt = writes.restore_idea(
            archived.target_id, expected_revision=archived.revision, idempotency_key="restore-idea",
        )
    else:
        archived = writes.archive_asset(asset.id, expected_revision=1, idempotency_key="archive-asset")
        restored_receipt = writes.restore_asset(
            archived.target_id, expected_revision=archived.revision, idempotency_key="restore-asset",
        )
    restored = writes.get_node(restored_receipt.target_id)
    if normal_edit:
        if kind == "idea":
            replacement = restored.revise(title="Edited after restore")
            writes.record_correction(
                restored.id, replacement, expected_revision=restored.revision,
                idempotency_key="edit-idea-after-restore",
            )
        else:
            writes.revise_asset(
                asset_id=restored.id, name="Edited after restore", description=restored.description,
                expected_revision=restored.revision, idempotency_key="edit-asset-after-restore",
            )
    driver = _LifecycleRowsDriver(_lifecycle_rows(writes))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(
        ((idea.id, "idea"), (asset.id, "asset"), ("claim-1", "claim")), owner_id="owner",
    )

    assert len(driver.calls) == 1
    idea_tip = max(
        (node for node in writes.read_snapshot().nodes if isinstance(node, Idea)), key=lambda node: node.revision,
    )
    asset_tip = max(
        (node for node in writes.read_snapshot().nodes if isinstance(node, Asset)), key=lambda node: node.revision,
    )
    assert resolved[idea.id] == (None if normal_edit and kind == "idea" else idea_tip.id)
    assert resolved[asset.id] == (None if normal_edit and kind == "asset" else asset_tip.id)
    assert resolved["claim-1"] == "claim-1"


@pytest.mark.parametrize("scalar_revision", [0, 1])
def test_lifecycle_reference_resolves_legacy_initial_asset_row(scalar_revision):
    writes = InMemoryGraphWriteService("owner")
    asset = Asset(
        owner_id="owner", id="asset-root", name="Synthetic capability", status=Status.ACTIVE,
        egress_policy=EgressPolicy.SHAREABLE, revision=1,
    )
    writes.put_node(asset, idempotency_key="seed-legacy-asset", operation="capture_asset")
    archived = writes.archive_asset(asset.id, expected_revision=1, idempotency_key="archive-legacy-asset")
    restored_receipt = writes.restore_asset(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-legacy-asset",
    )
    rows = list(_lifecycle_rows(writes))
    legacy_root = next(row for row in rows if row["id"] == asset.id)
    payload = json.loads(legacy_root["payload_json"])
    payload.pop("revision")
    payload.pop("supersedes_id")
    legacy_root["payload_json"] = json.dumps(payload, ensure_ascii=False)
    legacy_root["revision"] = scalar_revision
    legacy_root["supersedes_id"] = None
    driver = _LifecycleRowsDriver(tuple(rows))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(((asset.id, "asset"),), owner_id="owner")

    assert resolved == {asset.id: restored_receipt.target_id}
    assert len(driver.calls) == 1


@pytest.mark.parametrize(
    ("row_revision", "row_supersedes", "missing_fields"),
    [
        (2, None, {"revision", "supersedes_id"}),
        (0, None, {"revision"}),
        (0, "asset-parent", {"revision", "supersedes_id"}),
    ],
)
def test_lifecycle_reference_rejects_noninitial_or_inconsistent_legacy_asset_rows(
    row_revision, row_supersedes, missing_fields,
):
    asset = Asset(owner_id="owner", id="legacy-asset", name="Synthetic capability")
    payload = _json_value(asset)
    for field in missing_fields:
        payload.pop(field)
    driver = _LifecycleRowsDriver(({
        "id": asset.id,
        "node_type": "asset",
        "revision": row_revision,
        "supersedes_id": row_supersedes,
        "status": "active",
        "payload_json": json.dumps(payload, ensure_ascii=False),
    },))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(((asset.id, "asset"),), owner_id="owner")

    assert resolved == {asset.id: None}
    assert len(driver.calls) == 1


def test_unrelated_unsupported_asset_kind_does_not_poison_requested_lineage():
    writes = InMemoryGraphWriteService("owner")
    asset = Asset(
        owner_id="owner", id="requested-asset", name="Synthetic capability",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(asset, idempotency_key="seed-requested-asset", operation="capture_asset")
    archived = writes.archive_asset(asset.id, expected_revision=1, idempotency_key="archive-requested-asset")
    restored = writes.restore_asset(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-requested-asset",
    )
    rows = list(_lifecycle_rows(writes))
    unrelated = _json_value(Asset(owner_id="owner", id="unrelated-legacy", name="Legacy capability"))
    unrelated["kind"] = "capability"
    unrelated.pop("revision")
    unrelated.pop("supersedes_id")
    rows.append({
        "id": unrelated["id"], "node_type": "asset", "revision": 0,
        "supersedes_id": None, "status": "active",
        "payload_json": json.dumps(unrelated, ensure_ascii=False),
    })
    driver = _LifecycleRowsDriver(tuple(rows))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(((asset.id, "asset"),), owner_id="owner")

    assert resolved == {asset.id: restored.target_id}
    assert len(driver.calls) == 1


def test_related_malformed_row_reached_through_scalar_parent_fails_closed():
    asset = Asset(owner_id="owner", id="requested-asset", name="Synthetic capability")
    # Include the requested root itself so only the malformed related child
    # prevents the otherwise-current reference from resolving.
    root_payload = _json_value(asset)
    rows = [{
        "id": asset.id, "node_type": "asset", "revision": 1,
        "supersedes_id": None, "status": "active",
        "payload_json": json.dumps(root_payload, ensure_ascii=False),
    }, {
        "id": "malformed-child", "node_type": "asset", "revision": 2,
        "supersedes_id": asset.id, "status": "active", "payload_json": "{malformed",
    }]
    driver = _LifecycleRowsDriver(tuple(rows))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(((asset.id, "asset"),), owner_id="owner")

    assert resolved == {asset.id: None}
    assert len(driver.calls) == 1


def test_related_payload_parent_mismatch_fails_closed_even_when_scalar_parent_differs():
    asset = Asset(owner_id="owner", id="requested-asset", name="Synthetic capability")
    rows = []
    rows.append({
        "id": asset.id, "node_type": "asset", "revision": 1,
        "supersedes_id": None, "status": "active",
        "payload_json": json.dumps(_json_value(asset), ensure_ascii=False),
    })
    child = _json_value(Asset(owner_id="owner", id="mismatched-child", name="Synthetic capability"))
    child["revision"] = 2
    child["supersedes_id"] = asset.id
    child["provenance"]["target_id"] = child["id"]
    child["provenance"]["source_id"] = asset.id
    rows.append({
        "id": child["id"], "node_type": "asset", "revision": 2,
        "supersedes_id": "unrelated-parent", "status": "active",
        "payload_json": json.dumps(child, ensure_ascii=False),
    })
    driver = _LifecycleRowsDriver(tuple(rows))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(((asset.id, "asset"),), owner_id="owner")

    assert resolved == {asset.id: None}
    assert len(driver.calls) == 1


def test_lifecycle_reference_batch_is_owner_scoped_and_does_not_query_for_other_owner():
    driver = _LifecycleRowsDriver(())
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(
        (("idea-id", "idea"), ("asset-id", "asset")), owner_id="different-owner",
    )

    assert resolved == {"idea-id": None, "asset-id": None}
    assert driver.calls == []


def test_lifecycle_reference_batch_fails_closed_when_owner_scan_is_capped():
    driver = _LifecycleRowsDriver(tuple({} for _ in range(1001)))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(
        (("idea-id", "idea"), ("asset-id", "asset")), owner_id="owner",
    )

    assert resolved == {"idea-id": None, "asset-id": None}
    assert len(driver.calls) == 1


def test_unrelated_malformed_revision_row_does_not_poison_requested_reference():
    writes = InMemoryGraphWriteService("owner")
    asset = Asset(owner_id="owner", id="asset-id", name="Synthetic capability")
    writes.put_node(asset, idempotency_key="seed-asset", operation="capture_asset")
    rows = list(_lifecycle_rows(writes))
    rows.append({
        "id": "unrelated-idea", "node_type": "idea", "revision": 1,
        "supersedes_id": None, "status": "active", "payload_json": "{malformed",
    })
    driver = _LifecycleRowsDriver(tuple(rows))
    store = Neo4jGraphProvenanceStore(driver, owner_id="owner")

    resolved = store.resolve_lifecycle_references(((asset.id, "asset"),), owner_id="owner")

    assert resolved == {asset.id: asset.id}
    assert len(driver.calls) == 1


@pytest.mark.parametrize("field_case", ["confidence_none", "confidence_missing", "status_none", "status_missing", "status_mismatch"])
def test_malformed_evidence_metadata_is_omitted(field_case):
    store = FakeStore()
    evidence = store.nodes["ev-share"]
    fields = dict(evidence.fields)
    if field_case == "confidence_none":
        fields["confidence"] = None
    elif field_case == "confidence_missing":
        fields.pop("confidence")
    elif field_case == "status_none":
        fields["status"] = None
    elif field_case == "status_missing":
        fields.pop("status")
    else:
        fields["status"] = "revoked"
    store.nodes["ev-share"] = _view("ev-share", "evidence", "owner", "active", fields)

    result = read_local_graph_provenance(store, assertion_id="ra", owner_id="owner", at=NOW)

    assert result["evidence"] == []


class Adapter:
    def status(self): return "running"
    def start(self): pass
    def stop(self): pass


def test_route_preserves_local_guards_no_store_and_generic_missing_response():
    control = LocalControl(
        {"database": Adapter()}, expected_host="localhost:8765", allowed_origin="http://localhost:8765",
        start_order=("database",), stop_order=("database",),
    )
    client = TestClient(
        create_local_control_app(control, overview_owner_id="owner"),
        base_url="http://localhost:8765", client=("127.0.0.1", 50000),
    )
    response = client.get("/api/graph/semantic-edges/ra/provenance")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "failed"}
    assert client.get("/api/graph/semantic-edges/ra/provenance", headers={"Host": "attacker.invalid"}).status_code == 403


def test_route_maps_missing_to_generic_404_and_stopped_to_non_reading_envelope():
    class Database(Adapter):
        def status(self): return "stopped"

    class Store:
        calls = 0
        def read_provenance(self, assertion_id, *, owner_id):
            self.calls += 1
            raise GraphProvenanceNotFound("private diagnostic")

    control = LocalControl(
        {"database": Database()}, expected_host="localhost:8765", allowed_origin="http://localhost:8765",
        start_order=("database",), stop_order=("database",),
    )
    store = Store()
    client = TestClient(
        create_local_control_app(control, overview_owner_id="owner", graph_view_store=store),
        base_url="http://localhost:8765", client=("127.0.0.1", 50000),
    )
    response = client.get("/api/graph/semantic-edges/ra/provenance")
    assert response.status_code == 200
    assert response.json() == {"status": "stopped", "assertion_id": "ra", "section": None, "evidence": []}
    assert store.calls == 0

    control.adapters["database"].status = lambda: "running"
    response = client.get("/api/graph/semantic-edges/private-id/provenance")
    assert response.status_code == 404
    assert response.json() == {"detail": "Provenance was not found"}
    assert "private diagnostic" not in response.text
