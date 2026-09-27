import json

from dots.local_graph_view import Neo4jGraphViewStore, read_local_graph


OWNER = "synthetic-owner"


def _node(identity, kind, *, payload=None, owner=OWNER, status="active", has_successor=None):
    value = {"id": identity, "owner_id": owner, "status": status}
    value.update(payload or {})
    row = {
        "id": identity,
        "owner_id": owner,
        "node_type": kind,
        "status": status,
        "payload_json": json.dumps(value),
    }
    if has_successor is not None:
        row["has_successor"] = has_successor
    return row


class Store:
    def __init__(self, nodes):
        self.nodes = nodes

    def read_nodes(self, owner_id):
        return self.nodes

    def read_edges(self, owner_id, ids):
        return ()


def _assertion(identity="assertion-1", **overrides):
    value = {
        "source_id": "idea-1",
        "source_kind": "idea",
        "target_id": "asset-1",
        "target_kind": "asset",
        "predicate": "REUSES",
        "status": "inferred",
        "confidence": 0.82,
        "egress_policy": "shareable",
        "evidence_ids": ["evidence-public", "evidence-private"],
        "based_on_brief_id": "brief-v2",
        "based_on_brief_section_index": 3,
        "valid_from": "2026-09-01T00:00:00+00:00",
        "expires_at": None,
        "supersedes_id": None,
    }
    value.update(overrides)
    return _node(identity, "relation_assertion", payload=value, status=value["status"])


def _base_nodes(*assertions):
    return [
        _node("idea-1", "idea", payload={"title": "Synthetic idea", "private_note": "DO_NOT_RETURN"}),
        _node("asset-1", "asset", payload={"name": "Synthetic asset", "private_note": "DO_NOT_RETURN"}),
        _node("evidence-public", "evidence", payload={"status": "active", "egress_policy": "shareable", "excerpt": "DO_NOT_RETURN"}),
        _node("evidence-private", "evidence", payload={"status": "active", "egress_policy": "local_only", "excerpt": "DO_NOT_RETURN"}),
        *assertions,
    ]


def test_semantic_projection_contains_only_safe_current_relation_fields():
    result = read_local_graph(Store(_base_nodes(_assertion())), owner_id=OWNER)

    assert result["semantic_edges"] == [{
        "id": "assertion-1",
        "source_id": "idea-1",
        "target_id": "asset-1",
        "predicate": "REUSES",
        "status": "inferred",
        "confidence": 0.82,
        "evidence_ids": ["evidence-public"],
        "based_on_brief_id": "brief-v2",
        "based_on_brief_section_index": 3,
    }]
    assert "DO_NOT_RETURN" not in json.dumps(result)


def test_superseded_assertion_is_hidden_even_when_successor_is_rejected():
    previous = _assertion()
    successor = _assertion("assertion-2", status="rejected", supersedes_id="assertion-1")

    result = read_local_graph(Store(_base_nodes(previous, successor)), owner_id=OWNER)

    assert result["semantic_edges"] == []


def test_successor_outside_node_window_still_suppresses_old_assertion():
    old = _assertion()
    old["has_successor"] = True  # Neo4j computes this across the full owner graph.

    result = read_local_graph(Store(_base_nodes(old)), owner_id=OWNER)

    assert result["semantic_edges"] == []


def test_neo4j_node_query_checks_successors_globally_with_owner_scope():
    query = Neo4jGraphViewStore._NODES

    assert "EXISTS { MATCH (successor:RelationAssertion {owner_id: $owner_id})-[:SUPERSEDES]->(n) }" in query
    assert "LIMIT 201" in query


def test_foreign_owner_missing_or_noncurrent_endpoints_and_local_only_assertions_are_hidden():
    base = _base_nodes()
    invalid = [
        _assertion("wrong-endpoint", target_id="missing-asset"),
        _assertion("wrong-kind", target_id="idea-1", target_kind="asset"),
        _assertion("long-predicate", predicate="X" * 61),
        _assertion("archived-endpoint", target_id="archived-asset"),
    ]
    base.extend(invalid)
    base.append(_node("archived-asset", "asset", status="archived", payload={"name": "Hidden"}))

    result = read_local_graph(Store(base), owner_id=OWNER)

    assert result["semantic_edges"] == []


def test_relation_to_hidden_previous_asset_revision_is_not_projected():
    nodes = _base_nodes(_assertion())
    nodes[1]["has_successor"] = True  # Successor may fall outside the bounded node window.

    result = read_local_graph(Store(nodes), owner_id=OWNER)

    assert "asset-1" not in {node["id"] for node in result["nodes"]}
    assert result["semantic_edges"] == []


def test_owner_local_only_assertion_remains_visible_with_only_shareable_evidence_ids():
    private_assertion = _assertion(egress_policy="local_only")

    result = read_local_graph(Store(_base_nodes(private_assertion)), owner_id=OWNER)

    assert result["semantic_edges"][0]["id"] == "assertion-1"
    assert result["semantic_edges"][0]["evidence_ids"] == ["evidence-public"]


def test_foreign_owner_rows_fail_closed_without_semantic_projection():
    foreign = _node(
        "foreign-assertion",
        "relation_assertion",
        owner="other-owner",
        payload={**json.loads(_assertion()["payload_json"]), "id": "foreign-assertion", "owner_id": "other-owner"},
    )
    result = read_local_graph(Store(_base_nodes(foreign)), owner_id=OWNER)

    assert result["status"] == "failed"
    assert result["semantic_edges"] == []
