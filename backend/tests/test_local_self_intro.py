import json
from types import SimpleNamespace

import pytest

from dots.local_self_intro import Neo4jSelfIntroductionWriter, SelfIntroductionConflict


class Store:
    def __init__(self):
        self.record = None

    def read_home(self, owner_id):
        return [self.record] if self.record else []


class Gateway:
    def __init__(self):
        self.saved = []

    def put_node(self, node, **kwargs):
        self.saved.append((node, kwargs))
        return SimpleNamespace(target_id=node.id)


def test_self_intro_is_append_only_local_asset_and_rejects_stale_edit():
    store, gateway = Store(), Gateway()
    writer = Neo4jSelfIntroductionWriter(store, gateway)
    identity = writer.save("owner-mvp", "  創業者です。  ", None, "save-one")
    record, args = gateway.saved[0]
    assert identity == record.id
    assert record.description == "創業者です。"
    assert record.egress_policy.value == "local_only"
    assert args["operation"] == "capture_asset"

    store.record = {"id": identity, "owner_id": "owner-mvp", "node_type": "asset", "status": "active",
                    "payload_json": json.dumps({"id": identity, "owner_id": "owner-mvp", "name": "自己紹介", "kind": "knowledge",
                                                "description": "創業者です。", "created_at": "2026-09-25T00:00:00Z"})}
    with pytest.raises(SelfIntroductionConflict):
        writer.save("owner-mvp", "別の版", None, "save-two")
    successor = writer.save("owner-mvp", "新しい版", identity, "save-three")
    assert successor != identity
    assert gateway.saved[-1][0].details["supersedes_id"] == identity


def test_self_intro_rejects_invalid_content_without_writing():
    gateway = Gateway()
    writer = Neo4jSelfIntroductionWriter(Store(), gateway)
    with pytest.raises(ValueError):
        writer.save("owner-mvp", " ", None, "invalid")
    assert gateway.saved == []
