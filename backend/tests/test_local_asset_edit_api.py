import pytest
from fastapi.testclient import TestClient

from dots.founder_graph import Asset, AssetHomeCategory, AssetKind, EgressPolicy
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.local_control import LocalControl, create_local_control_app
from dots.local_home import LocalAssetWriter


@pytest.fixture
def asset_client():
    writes = InMemoryGraphWriteService("owner-test")
    original = Asset(owner_id="owner-test", id="asset-test", name="Original",
                     description="Original content", egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(original, idempotency_key="create-asset")
    control = LocalControl({}, expected_host="localhost:8765", allowed_origin="http://localhost:8765",
                           start_order=(), stop_order=())
    app = create_local_control_app(control, overview_owner_id="owner-test", asset_writer=LocalAssetWriter(writes))
    client = TestClient(app, base_url="http://localhost:8765", client=("127.0.0.1", 12345))
    headers = {"Origin": "http://localhost:8765", "X-CSRF-Token": client.get("/api/status").json()["csrf_token"]}
    payload = {"name": "Edited", "description": "Edited content", "expected_revision": 1,
               "idempotency_key": "asset-edit"}
    return client, headers, payload, writes, original


def test_asset_edit_appends_replays_and_rejects_stale_or_changed_key(asset_client):
    client, headers, payload, writes, original = asset_client
    url = "/api/assets/asset-test"
    saved = client.put(url, json=payload, headers=headers)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    revised = writes.get_node(saved.json()["id"])
    assert revised.egress_policy is original.egress_policy
    assert writes.get_node(original.id) == original
    replay = client.put(url, json=payload, headers=headers)
    assert replay.status_code == 200 and replay.json()["id"] == revised.id
    assert replay.json()["replayed"]
    assert client.put(url, json={**payload, "idempotency_key": "other"}, headers=headers).status_code == 409
    assert client.put(url, json={**payload, "name": "Different"}, headers=headers).status_code == 409


def test_asset_edit_requires_local_csrf_and_forbids_sharing_changes(asset_client):
    client, headers, payload, writes, original = asset_client
    url = "/api/assets/asset-test"
    assert client.put(url, json=payload).status_code == 403
    assert client.put(url, json=payload, headers={**headers, "Origin": "https://other.test"}).status_code == 403
    assert client.put(url, json={**payload, "egress_policy": "local_only"}, headers=headers).status_code == 422
    assert client.put(url, json={**payload, "expected_revision": True}, headers=headers).status_code == 422
    assert len(writes.nodes()) == 1


def test_asset_edit_accepts_three_categories_without_replacing_domain_kind(asset_client):
    client, headers, payload, writes, original = asset_client
    assert client.put(f"/api/assets/{original.id}", json={**payload, "category": "person"}, headers=headers).status_code == 422
    saved = client.put(f"/api/assets/{original.id}", json={**payload, "category": "criterion"}, headers=headers)
    assert saved.status_code == 200
    revised = writes.get_node(saved.json()["id"])
    assert revised.kind is AssetKind.KNOWLEDGE
    assert revised.home_category is AssetHomeCategory.CRITERION
    assert writes.get_node(original.id).kind is AssetKind.KNOWLEDGE


def test_legacy_asset_edit_kind_is_accepted_as_category_alias(asset_client):
    client, headers, payload, writes, original = asset_client
    saved = client.put(f"/api/assets/{original.id}", json={**payload, "kind": "barrier"}, headers=headers)
    assert saved.status_code == 200
    revised = writes.get_node(saved.json()["id"])
    assert revised.kind is AssetKind.KNOWLEDGE
    assert revised.home_category is AssetHomeCategory.BARRIER
