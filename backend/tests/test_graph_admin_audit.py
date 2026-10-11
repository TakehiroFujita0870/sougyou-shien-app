from dataclasses import replace
import json

import pytest

from nebula.founder_graph import Idea, EgressPolicy, Provenance
from nebula.founder_graph_read import GraphReadService
from nebula.founder_graph_write import InMemoryGraphWriteService
from nebula.graph_admin_audit import audit_page, safe_graph, synthetic_provenance


def fixture(count=3):
    writes = InMemoryGraphWriteService("owner")
    for index in range(count):
        node = Idea(id=f"idea-{index:04}", owner_id="owner", title="秘密本文を返さない",
                    egress_policy=EgressPolicy.SHAREABLE)
        writes.put_node(node, idempotency_key=f"seed-{index}")
    return writes, GraphReadService(writes)


def test_inventory_has_no_visual_limit_and_paginates_without_gaps():
    writes, reads = fixture(505)
    graph, _, _ = safe_graph(writes, reads)
    assert graph["summary"]["node_count"] == graph["summary"]["isolated_count"] == 505
    cursor, identities = None, []
    while True:
        page = audit_page(graph, limit=100, cursor=cursor)
        identities.extend(n["id"] for n in page["results"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(identities) == len(set(identities)) == 505
    assert "秘密本文" not in json.dumps(graph, ensure_ascii=False)


def test_hidden_node_does_not_change_counts_cursor_or_digest():
    writes, reads = fixture()
    before, _, _ = safe_graph(writes, reads)
    writes.put_node(Idea(id="private", owner_id="owner", title="非公開"), idempotency_key="hidden")
    after, _, _ = safe_graph(writes, reads)
    assert before == after


def test_cursor_rejects_changed_snapshot_wrong_collection_and_invalid_offset():
    writes, reads = fixture()
    before, _, _ = safe_graph(writes, reads)
    cursor = audit_page(before, limit=1)["next_cursor"]
    with pytest.raises(ValueError):
        audit_page(before, collection="isolated", cursor=cursor)
    writes.put_node(Idea(id="new", owner_id="owner", title="新規", egress_policy=EgressPolicy.SHAREABLE), idempotency_key="new")
    after, _, _ = safe_graph(writes, reads)
    with pytest.raises(ValueError, match="restart"):
        audit_page(after, cursor=cursor)
    for limit in (0, 101, True):
        with pytest.raises(ValueError):
            audit_page(before, limit=limit)


def test_only_provenance_not_test_name_is_synthetic():
    assert not synthetic_provenance({"title": "synthetic test acceptance-leaf"})
    assert synthetic_provenance({"provenance": {"actor": "nebula_synthetic_fixture",
        "operation": "create_synthetic_fixture", "rule_version": "synthetic-fixture-v1"}})


def test_management_edges_count_separately_and_private_edges_are_absent():
    writes, reads = fixture()
    writes._structural_edges.extend([("idea-0000", "SUPERSEDES", "idea-0001"),
                                    ("idea-0001", "CITES", "idea-0002"),
                                    ("private", "REUSES", "idea-0000")])
    graph, _, _ = safe_graph(writes, reads)
    assert graph["summary"]["edge_count"] == 2
    assert graph["summary"]["edge_categories"] == {"grounding": 1, "management": 1}
    assert graph["collections"]["isolated"] == []
    assert sorted(c["size"] for c in graph["collections"]["components"]) == [3]
