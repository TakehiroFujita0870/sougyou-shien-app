from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

from dots.founder_graph_read import NodeView
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.local_control import LocalControl, create_local_control_app
from dots.local_graph_provenance import GraphProvenanceNotFound, read_local_graph_provenance


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

    def get_brief(self, brief_id: str, *, owner_id: str):
        return self.brief if brief_id == self.brief.id and owner_id == self.brief.owner_id else None

    def get_latest_brief(self, root_id: str, *, owner_id: str):
        return self.brief if self.latest_brief_id == self.brief.id and root_id == self.brief.idea_lineage_root_id else None


def _view(identity, kind, owner, status, fields):
    return NodeView(identity, kind, owner, identity, "", status, 1, MappingProxyType(fields))


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


@pytest.mark.parametrize("case", ["successor", "idea_successor", "old_brief", "wrong_owner", "wrong_idea", "wrong_section", "malformed_evidence", "expired"])
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
