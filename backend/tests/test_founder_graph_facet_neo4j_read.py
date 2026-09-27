from __future__ import annotations

import json

import pytest

from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.founder_graph_neo4j_read import Neo4jGraphReadService
from dots.founder_graph_read import GraphReadNotFoundError


class _Result:
    def __init__(self, rows):
        self.rows = tuple(rows)

    def __iter__(self):
        return iter(self.rows)


class _Session:
    def __init__(self, nodes, evidence):
        self.nodes = nodes
        self.evidence = evidence

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None

    def execute_read(self, callback):
        return callback(self)

    def run(self, query, **params):
        if "MATCH (n:Facet" in query:
            return _Result(
                row for row in self.nodes
                if row["owner_id"] == params["owner_id"] and row["node_type"] == "facet"
            )
        if "node_types" in params:
            return _Result(row for row in self.nodes if row["owner_id"] == params["owner_id"])
        if "evidence_ids" in params:
            return _Result({"id": key} for key in params["evidence_ids"] if key in self.evidence)
        return _Result(())


class _Driver:
    def __init__(self, nodes, evidence):
        self.session_value = _Session(nodes, evidence)

    def session(self, *, database):
        assert database == "neo4j"
        return self.session_value


def _row(identifier, kind, fields, *, owner="owner-1", egress_policy="shareable"):
    payload = {
        "id": identifier,
        "owner_id": owner,
        "node_type": kind,
        "status": "active",
        "egress_policy": egress_policy,
        **fields,
    }
    return {
        "id": identifier,
        "owner_id": owner,
        "node_type": kind,
        "status": "active",
        "egress_policy": egress_policy,
        "revision": 1,
        "payload_json": json.dumps(payload),
        "search_text": " ".join(str(value) for value in fields.values()),
    }


def test_neo4j_facet_region_limits_owner_depth_and_keeps_status_evidence() -> None:
    nodes = [
        _row("root", "facet", {"namespace": "topic", "value": "Business"}),
        _row("child", "facet", {"namespace": "topic", "value": "Startup"}),
        _row("other", "facet", {"namespace": "topic", "value": "Other"}),
        _row("idea-child", "idea", {"title": "Child idea", "summary": "summary"}),
        _row("idea-other", "idea", {"title": "Other idea", "summary": "summary"}),
        _row("foreign-facet", "facet", {"namespace": "topic", "value": "Private"}, owner="owner-2"),
        _row("taxonomy", "relation_assertion", {
            "source_id": "root", "source_kind": "facet", "target_id": "child",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["ev-tax"],
        }),
        _row("proposal", "relation_assertion", {
            "source_id": "root", "source_kind": "facet", "target_id": "other",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "proposed",
            "evidence_ids": [],
        }),
        _row("class-child", "relation_assertion", {
            "source_id": "idea-child", "source_kind": "idea", "target_id": "child",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "inferred",
            "evidence_ids": ["ev-class"],
        }),
        _row("class-other", "relation_assertion", {
            "source_id": "idea-other", "source_kind": "idea", "target_id": "other",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["ev-other"],
        }),
    ]
    driver = _Driver(nodes, {"ev-tax", "ev-class", "ev-other"})
    reads = Neo4jGraphReadService(Neo4jGraphGateway(driver, "owner-1"))

    shallow = reads.facet_region("root", owner_id="owner-1", max_facet_depth=0)
    deep = reads.facet_region("root", owner_id="owner-1", max_facet_depth=1)

    assert shallow == ()
    assert [hit.entity.id for hit in deep] == ["idea-child"]
    assert deep[0].classification_status == "inferred"
    assert deep[0].taxonomy_status_path == ("confirmed",)
    assert deep[0].evidence_ids == ("ev-tax", "ev-class")
    assert [item.label for item in deep[0].facet_path] == ["topic: Business", "topic: Startup"]
    with pytest.raises(GraphReadNotFoundError):
        reads.facet_region("root", owner_id="owner-2", max_facet_depth=1)
    with pytest.raises(GraphReadNotFoundError):
        reads.facet_region("foreign-facet", owner_id="owner-1", max_facet_depth=1)


def test_neo4j_facet_region_does_not_reveal_private_intermediate_facets() -> None:
    nodes = [
        _row("root", "facet", {"namespace": "topic", "value": "Root"}),
        _row("private-middle", "facet", {"namespace": "topic", "value": "Private"}, egress_policy="local_only"),
        _row("public-child", "facet", {"namespace": "topic", "value": "Child"}),
        _row("idea-child", "idea", {"title": "Child idea", "summary": "summary"}),
        _row("root-private", "relation_assertion", {
            "source_id": "root", "source_kind": "facet", "target_id": "private-middle",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["ev-path"],
        }, egress_policy="local_only"),
        _row("private-public", "relation_assertion", {
            "source_id": "private-middle", "source_kind": "facet", "target_id": "public-child",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["ev-path"],
        }),
        _row("child-classification", "relation_assertion", {
            "source_id": "idea-child", "source_kind": "idea", "target_id": "public-child",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["ev-path"],
        }),
    ]
    reads = Neo4jGraphReadService(Neo4jGraphGateway(_Driver(nodes, {"ev-path"}), "owner-1"))

    assert reads.facet_region("root", owner_id="owner-1", max_facet_depth=3) == ()


def test_neo4j_facet_region_drops_edges_with_noncurrent_or_nonshareable_evidence() -> None:
    nodes = [
        _row("root", "facet", {"namespace": "topic", "value": "Root"}),
        _row("child", "facet", {"namespace": "topic", "value": "Child"}),
        _row("idea", "idea", {"title": "Idea", "summary": "summary"}),
        _row("taxonomy", "relation_assertion", {
            "source_id": "root", "source_kind": "facet", "target_id": "child",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["private-or-stale-evidence"],
        }),
        _row("classification", "relation_assertion", {
            "source_id": "idea", "source_kind": "idea", "target_id": "child",
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["private-or-stale-evidence"],
        }),
    ]
    reads = Neo4jGraphReadService(Neo4jGraphGateway(_Driver(nodes, set()), "owner-1"))

    assert reads.facet_region("root", owner_id="owner-1", max_facet_depth=2) == ()


def test_neo4j_facet_search_filters_before_page_limit() -> None:
    nodes = [
        _row(f"asset-{index}", "asset", {"name": f"Bakery asset {index}"})
        for index in range(21)
    ]
    nodes.append(_row("facet-bakery", "facet", {"namespace": "domain", "value": "Bakery"}))
    reads = Neo4jGraphReadService(Neo4jGraphGateway(_Driver(nodes, set()), "owner-1"))

    page = reads.search_facets("bakery", owner_id="owner-1", limit=1)

    assert [hit.node.id for hit in page.hits] == ["facet-bakery"]
    assert page.next_cursor is None


def test_neo4j_facet_region_keeps_distinct_memberships_for_one_entity() -> None:
    nodes = [
        _row("root", "facet", {"namespace": "domain", "value": "Root"}),
        _row("left", "facet", {"namespace": "domain", "value": "Left"}),
        _row("right", "facet", {"namespace": "domain", "value": "Right"}),
        _row("idea", "idea", {"title": "Idea", "summary": "summary"}),
    ]
    for facet_id in ("left", "right"):
        nodes.append(_row(f"tax-{facet_id}", "relation_assertion", {
            "source_id": "root", "source_kind": "facet", "target_id": facet_id,
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["ev-tax"],
        }))
        nodes.append(_row(f"class-{facet_id}", "relation_assertion", {
            "source_id": "idea", "source_kind": "idea", "target_id": facet_id,
            "target_kind": "facet", "predicate": "CLASSIFIED_AS", "status": "confirmed",
            "evidence_ids": ["ev-class"],
        }))
    reads = Neo4jGraphReadService(Neo4jGraphGateway(_Driver(nodes, {"ev-tax", "ev-class"}), "owner-1"))

    hits = reads.facet_region("root", owner_id="owner-1", max_facet_depth=1)

    assert [(hit.entity.id, hit.matched_facet_id) for hit in hits] == [
        ("idea", "left"), ("idea", "right"),
    ]
