import json

from dots.founder_graph_facet_hierarchy import FacetPathNode, FacetRegionHit, RegionEntity
from dots.local_graph_view import read_local_facet_region, read_local_graph


def node(identity, owner="owner-mvp", kind="idea", title="良いアイデア"):
    return {"id": identity, "owner_id": owner, "node_type": kind, "status": "active", "payload_json": json.dumps({"id": identity, "owner_id": owner, "title": title, "source_text": "PRIVATE"})}


class Store:
    def __init__(self, nodes=(), edges=()):
        self.nodes, self.edges = nodes, edges

    def read_nodes(self, owner_id):
        return self.nodes

    def read_edges(self, owner_id, ids):
        return self.edges

    def read_facet_region(self, owner_id, facet_id, depth):
        self.facet_calls = (owner_id, facet_id, depth)
        return self.facet_hits


def test_graph_projects_safe_owner_nodes_and_relations():
    result = read_local_graph(Store([node("i1"), node("i2")], [{"source": "i1", "target": "i2", "relation": "INSPIRED_BY", "relation_owner": "owner-mvp"}]), owner_id="owner-mvp")
    assert result["status"] == "ready"
    assert result["nodes"] == [{"id": "i1", "kind": "idea", "label": "良いアイデア"}, {"id": "i2", "kind": "idea", "label": "良いアイデア"}]
    assert result["edges"] == [{"source": "i1", "target": "i2", "label": "INSPIRED_BY"}]
    assert "PRIVATE" not in str(result)


def test_graph_stopped_empty_and_foreign_owner_fail_closed():
    assert read_local_graph(Store(), owner_id="owner-mvp")["status"] == "empty"
    assert read_local_graph(Store(), owner_id="owner-mvp", storage_status="stopped")["status"] == "stopped"
    assert read_local_graph(Store([node("x", owner="other")]), owner_id="owner-mvp")["status"] == "failed"


def test_facet_region_projection_exposes_status_and_opaque_evidence_only():
    store = Store()
    store.facet_hits = (FacetRegionHit(
        entity=RegionEntity("owner-mvp", "idea-1", "idea", "事業案"),
        root_facet_id="facet-root", matched_facet_id="facet-child", facet_depth=1,
        classification_status="inferred", classification_evidence_ids=("ev-class",),
        taxonomy_status_path=("confirmed",), taxonomy_evidence_path=(("ev-tax",),),
        facet_path=(FacetPathNode("facet-root", "分類", 0), FacetPathNode("facet-child", "子分類", 1)),
    ),)
    result = read_local_facet_region(store, owner_id="owner-mvp", facet_id="facet-root", depth=1)
    assert result["status"] == "ready"
    assert store.facet_calls == ("owner-mvp", "facet-root", 1)
    assert result["hits"][0]["classification_status"] == "inferred"
    assert result["hits"][0]["taxonomy_status_path"] == ["confirmed"]
    assert result["hits"][0]["facet_path"] == [
        {"facet_id": "facet-root", "label": "分類", "depth": 0},
        {"facet_id": "facet-child", "label": "子分類", "depth": 1},
    ]
    assert result["hits"][0]["evidence_ids"] == ["ev-tax", "ev-class"]
    assert "本文" not in str(result)
