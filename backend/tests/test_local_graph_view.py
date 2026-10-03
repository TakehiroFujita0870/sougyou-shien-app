import json
from dataclasses import replace

from dots.founder_graph import Asset, EgressPolicy, Idea, NodeType, Provenance, RelationAssertion, RelationType, RelationshipStatus, Status
from dots.founder_graph_neo4j_codec import node_properties
from dots.founder_graph_facet_hierarchy import FacetPathNode, FacetRegionHit, RegionEntity
from dots.local_graph_view import MAX_NODES, read_local_facet_region, read_local_graph


def node(identity, owner="owner-mvp", kind="idea", title="良いアイデア"):
    return {"id": identity, "owner_id": owner, "node_type": kind, "status": "active", "payload_json": json.dumps({"id": identity, "owner_id": owner, "title": title, "source_text": "PRIVATE"})}


class Store:
    def __init__(self, nodes=(), edges=(), citations=()):
        self.nodes, self.edges, self.citations = nodes, edges, citations

    def read_nodes(self, owner_id):
        return self.nodes

    def read_edges(self, owner_id, ids):
        return self.edges

    def read_idea_citations(self, owner_id, idea_ids):
        return self.citations

    def read_facet_region(self, owner_id, facet_id, depth):
        self.facet_calls = (owner_id, facet_id, depth)
        return self.facet_hits


def test_graph_projects_safe_owner_nodes_and_relations():
    result = read_local_graph(Store([node("i1"), node("i2")], [{"source": "i1", "target": "i2", "relation": "INSPIRED_BY", "relation_owner": "owner-mvp"}]), owner_id="owner-mvp")
    assert result["status"] == "ready"
    assert result["nodes"] == [{"id": "i1", "kind": "idea", "label": "良いアイデア"}, {"id": "i2", "kind": "idea", "label": "良いアイデア"}]
    assert result["edges"] == [{"source": "i1", "target": "i2", "label": "INSPIRED_BY"}]
    assert "PRIVATE" not in str(result)


def test_graph_exposes_only_safe_source_urls_for_navigation():
    public = node("source-public", kind="source")
    public["payload_json"] = json.dumps({
        "id": "source-public", "owner_id": "owner-mvp", "title": "公開資料",
        "locator": "https://example.test/research?id=1", "content": "PRIVATE SOURCE CONTENT",
    })
    unsafe = node("source-unsafe", kind="source")
    unsafe["payload_json"] = json.dumps({
        "id": "source-unsafe", "owner_id": "owner-mvp", "title": "共有キー付き資料",
        "locator": "https://example.test/research?access_token=private-value", "content": "PRIVATE SOURCE CONTENT",
    })
    missing = node("source-missing", kind="source")
    missing["payload_json"] = json.dumps({
        "id": "source-missing", "owner_id": "owner-mvp", "title": "URLなし", "content": "PRIVATE SOURCE CONTENT",
    })
    non_source = node("idea-with-locator", kind="idea")
    non_source["payload_json"] = json.dumps({
        "id": "idea-with-locator", "owner_id": "owner-mvp", "title": "アイデア",
        "locator": "https://example.test/should-not-open",
    })

    result = read_local_graph(Store([public, unsafe, missing, non_source]), owner_id="owner-mvp")
    by_id = {item["id"]: item for item in result["nodes"]}

    assert by_id["source-public"]["url"] == "https://example.test/research?id=1"
    assert "url" not in by_id["source-unsafe"]
    assert "url" not in by_id["source-missing"]
    assert "url" not in by_id["idea-with-locator"]
    assert "private-value" not in str(result)
    assert "PRIVATE SOURCE CONTENT" not in str(result)


def test_graph_projects_one_current_shareable_citation_edge_without_private_metadata():
    idea = node("idea-1")
    idea["payload_json"] = json.dumps({"id": "idea-1", "owner_id": "owner-mvp", "title": "案", "egress_policy": "shareable"})
    source = node("source-1", kind="source")
    source["payload_json"] = json.dumps({
        "id": "source-1", "owner_id": "owner-mvp", "title": "公開資料",
        "locator": "https://example.test/source", "egress_policy": "shareable", "secret": "PRIVATE",
    })
    rows = [
        {"idea_id": "idea-1", "source_id": "source-1", "evidence_id": "evidence-1", "url": "https://example.test/source"},
        {"idea_id": "idea-1", "source_id": "source-1", "evidence_id": "evidence-2", "url": "https://example.test/source"},
    ]
    result = read_local_graph(Store([idea, source], citations=rows), owner_id="owner-mvp")
    assert result["edges"] == [{"source": "idea-1", "target": "source-1", "label": "CITES"}]
    assert "evidence-1" not in str(result)
    assert "PRIVATE" not in str(result)


def test_graph_does_not_project_citations_to_unsafe_or_private_sources():
    idea = node("idea-1")
    idea["payload_json"] = json.dumps({"id": "idea-1", "owner_id": "owner-mvp", "title": "案", "egress_policy": "shareable"})
    private = node("source-private", kind="source")
    private["payload_json"] = json.dumps({
        "id": "source-private", "owner_id": "owner-mvp", "title": "内部資料",
        "locator": "https://example.test/private", "egress_policy": "local_only",
    })
    unsafe = node("source-unsafe", kind="source")
    unsafe["payload_json"] = json.dumps({
        "id": "source-unsafe", "owner_id": "owner-mvp", "title": "秘密URL",
        "locator": "https://example.test/?token=secret", "egress_policy": "shareable",
    })
    rows = [
        {"idea_id": "idea-1", "source_id": "source-private", "evidence_id": "evidence-1", "url": "https://example.test/private"},
        {"idea_id": "idea-1", "source_id": "source-unsafe", "evidence_id": "evidence-2", "url": "https://example.test/?token=secret"},
    ]
    result = read_local_graph(Store([idea, private, unsafe], citations=rows), owner_id="owner-mvp")
    assert result["edges"] == []


def test_graph_stopped_empty_and_foreign_owner_fail_closed():
    assert read_local_graph(Store(), owner_id="owner-mvp")["status"] == "empty"
    assert read_local_graph(Store(), owner_id="owner-mvp", storage_status="stopped")["status"] == "stopped"
    assert read_local_graph(Store([node("x", owner="other")]), owner_id="owner-mvp")["status"] == "failed"


def test_graph_hides_internal_claims_without_exposing_their_content():
    claim = node("claim-1", kind="claim")
    claim["payload_json"] = json.dumps({"id": "claim-1", "owner_id": "owner-mvp", "text": "非公開の主張"})
    result = read_local_graph(Store([claim]), owner_id="owner-mvp")
    assert result["nodes"] == []
    assert "非公開の主張" not in str(result)


def test_internal_records_do_not_consume_the_visible_node_budget():
    internal = [node(f"claim-{index}", kind="claim") for index in range(700)]
    result = read_local_graph(Store([*internal, node("idea-1"), node("idea-2")]), owner_id="owner-mvp")
    assert [item["id"] for item in result["nodes"]] == ["idea-1", "idea-2"]
    assert result["truncated"] is False


def test_graph_caps_visible_nodes_at_five_hundred():
    result = read_local_graph(Store([node(f"idea-{index}") for index in range(MAX_NODES + 1)]), owner_id="owner-mvp")
    assert len(result["nodes"]) == MAX_NODES
    assert result["truncated"] is True


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


def test_graph_restores_idea_asset_semantic_endpoints_only_for_lifecycle_successors():
    idea0 = Idea(owner_id="owner-mvp", id="idea-0", title="Idea", status=Status.ACTIVE, egress_policy=EgressPolicy.SHAREABLE)
    idea1 = replace(
        idea0, id="idea-1", revision=1, supersedes_id=idea0.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="owner", operation="archive_idea", target_id="idea-1", source_id=idea0.id),
    )
    idea2 = replace(
        idea1, id="idea-2", revision=2, supersedes_id=idea1.id, status=Status.ACTIVE,
        provenance=Provenance(actor="owner", operation="restore_idea", target_id="idea-2", source_id=idea1.id),
    )
    asset0 = Asset(owner_id="owner-mvp", id="asset-0", name="Asset", egress_policy=EgressPolicy.SHAREABLE)
    asset1 = replace(
        asset0, id="asset-1", revision=2, supersedes_id=asset0.id, status=Status.ARCHIVED,
        provenance=Provenance(actor="owner", operation="archive_asset", target_id="asset-1", source_id=asset0.id),
    )
    asset2 = replace(
        asset1, id="asset-2", revision=3, supersedes_id=asset1.id, status=Status.ACTIVE,
        provenance=Provenance(actor="owner", operation="restore_asset", target_id="asset-2", source_id=asset1.id),
    )
    assertion = RelationAssertion(
        owner_id="owner-mvp", id="relation", source_id=idea0.id, source_kind=NodeType.IDEA,
        target_id=asset0.id, target_kind=NodeType.ASSET, predicate=RelationType.REUSES,
        assertion_family_id="relation-family", status=RelationshipStatus.PROPOSED,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    records = (idea0, idea1, idea2, asset0, asset1, asset2, assertion)
    superseded = {record.supersedes_id for record in records if record.supersedes_id}
    rows = []
    for record in records:
        properties = node_properties(record)
        rows.append({
            "id": record.id, "owner_id": record.owner_id, "node_type": record.node_type.value,
            "status": properties["status"], "payload_json": properties["payload_json"],
            "has_successor": record.id in superseded,
        })

    result = read_local_graph(Store(rows), owner_id="owner-mvp")

    assert {node["id"] for node in result["nodes"]} == {"idea-2", "asset-2"}
    assert result["semantic_edges"] == [{
        "id": "relation", "source_id": "idea-2", "target_id": "asset-2",
        "predicate": "REUSES", "status": "proposed", "confidence": None,
        "evidence_ids": [], "based_on_brief_id": None, "based_on_brief_section_index": None,
    }]
