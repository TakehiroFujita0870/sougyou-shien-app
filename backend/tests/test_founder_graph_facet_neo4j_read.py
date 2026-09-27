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


def _row(identifier, kind, fields, *, owner="owner-1"):
    payload = {
        "id": identifier,
        "owner_id": owner,
        "node_type": kind,
        "status": "active",
        "egress_policy": "shareable",
        **fields,
    }
    return {
        "id": identifier,
        "owner_id": owner,
        "node_type": kind,
        "status": "active",
        "revision": 1,
        "payload_json": json.dumps(payload),
        "search_text": "",
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
    with pytest.raises(GraphReadNotFoundError):
        reads.facet_region("root", owner_id="owner-2", max_facet_depth=1)
    with pytest.raises(GraphReadNotFoundError):
        reads.facet_region("foreign-facet", owner_id="owner-1", max_facet_depth=1)
