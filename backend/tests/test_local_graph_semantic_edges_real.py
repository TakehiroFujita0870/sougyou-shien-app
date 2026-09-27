"""Opt-in RP06 projection smoke against an explicitly disposable loopback Neo4j."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from dots.local_graph_view import MAX_NODES, Neo4jGraphViewStore, read_local_graph


@pytest.mark.skipif(
    not os.environ.get("FOUNDER_GRAPH_NEO4J_TEST_URI"),
    reason="requires an explicitly configured disposable loopback Neo4j",
)
def test_real_owner_scoped_semantic_projection_suppresses_successor_beyond_node_window():
    neo4j = pytest.importorskip("neo4j")
    from neo4j.exceptions import DatabaseUnavailable, ServiceUnavailable
    uri = os.environ["FOUNDER_GRAPH_NEO4J_TEST_URI"]
    parsed = urlsplit(uri)
    if parsed.scheme != "bolt" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port is None:
        raise ValueError("real graph-view smoke requires an explicit loopback Bolt URI")

    owner_id = f"rp06-real-{uuid4().hex}"
    driver = neo4j.GraphDatabase.driver(
        uri,
        auth=None,
        connection_timeout=2,
        connection_acquisition_timeout=2,
        max_transaction_retry_time=2,
    )
    store = Neo4jGraphViewStore(driver)
    now = datetime.now(timezone.utc).isoformat()
    idea_id = "ad-synthetic-idea"
    asset_id = "aa-synthetic-asset"
    public_evidence_id = "ab-public-evidence"
    private_evidence_id = "ac-private-evidence"
    old_assertion_id = "ae-old-assertion"
    current_assertion_id = "af-current-assertion"
    successor_id = "z-rejected-successor"

    def payload(identity, kind, **fields):
        return json.dumps(
            {"id": identity, "owner_id": owner_id, "node_type": kind, "status": fields.pop("status", "active"), **fields},
            ensure_ascii=False,
        )

    common_assertion = {
        "source_id": idea_id,
        "source_kind": "idea",
        "target_id": asset_id,
        "target_kind": "asset",
        "predicate": "REUSES",
        "confidence": 0.82,
        "egress_policy": "local_only",
        "evidence_ids": [public_evidence_id, private_evidence_id],
        "based_on_brief_id": "synthetic-brief-v1",
        "based_on_brief_section_index": 3,
        "valid_from": now,
        "expires_at": None,
    }

    records = [
        (asset_id, "asset", "active", payload(asset_id, "asset", name="Synthetic asset")),
        (public_evidence_id, "evidence", "active", payload(public_evidence_id, "evidence", egress_policy="shareable", excerpt="PUBLIC_EVIDENCE_BODY_MUST_NOT_ESCAPE")),
        (private_evidence_id, "evidence", "active", payload(private_evidence_id, "evidence", egress_policy="local_only", excerpt="PRIVATE_EVIDENCE_BODY_MUST_NOT_ESCAPE")),
        (idea_id, "idea", "active", payload(idea_id, "idea", title="Synthetic idea")),
        (
            old_assertion_id,
            "relation_assertion",
            "inferred",
            payload(old_assertion_id, "relation_assertion", status="inferred", **common_assertion),
        ),
        (
            current_assertion_id,
            "relation_assertion",
            "inferred",
            payload(current_assertion_id, "relation_assertion", status="inferred", **common_assertion),
        ),
    ]
    # These lexically later rows force the old assertion's rejected successor
    # outside both the Neo4j result limit and the local 200-node projection.
    records.extend(
        (f"m-filler-{index:03d}", "synthetic_filler", "active", payload(f"m-filler-{index:03d}", "synthetic_filler"))
        for index in range(MAX_NODES + 1 - len(records))
    )
    records.append((successor_id, "relation_assertion", "rejected", payload(
        successor_id,
        "relation_assertion",
        status="rejected",
        source_id=idea_id,
        source_kind="idea",
        target_id=asset_id,
        target_kind="asset",
        predicate="REUSES",
        confidence=0.1,
        egress_policy="local_only",
        evidence_ids=[public_evidence_id],
        based_on_brief_id="synthetic-brief-v1",
        based_on_brief_section_index=3,
        valid_from=now,
        expires_at=None,
        supersedes_id=old_assertion_id,
    )))

    def seed(tx):
        for identity, kind, status, payload_json in records:
            label = {"idea": "Idea", "asset": "Asset", "evidence": "Evidence", "relation_assertion": "RelationAssertion"}.get(kind)
            if label is not None:
                tx.run(
                    f"CREATE (n:{label} {{id: $id, owner_id: $owner_id, node_type: $kind, status: $status, payload_json: $payload_json}})",
                    id=identity, owner_id=owner_id, kind=kind, status=status, payload_json=payload_json,
                ).consume()
            else:
                tx.run(
                    "CREATE (n {id: $id, owner_id: $owner_id, node_type: $kind, status: $status, payload_json: $payload_json})",
                    id=identity, owner_id=owner_id, kind=kind, status=status, payload_json=payload_json,
                ).consume()
        tx.run(
            "MATCH (old:RelationAssertion {id: $old_id, owner_id: $owner_id}), "
            "(successor:RelationAssertion {id: $successor_id, owner_id: $owner_id}) "
            "CREATE (successor)-[:SUPERSEDES]->(old)",
            old_id=old_assertion_id, successor_id=successor_id, owner_id=owner_id,
        ).consume()
        for assertion_id in (old_assertion_id, current_assertion_id):
            tx.run(
                "MATCH (ra:RelationAssertion {id: $assertion_id, owner_id: $owner_id}), "
                "(idea {id: $idea_id, owner_id: $owner_id}), "
                "(asset {id: $asset_id, owner_id: $owner_id}), "
                "(public:Evidence {id: $public_id, owner_id: $owner_id}), "
                "(private:Evidence {id: $private_id, owner_id: $owner_id}) "
                "CREATE (ra)-[:ASSERTS_FROM]->(idea), (ra)-[:ASSERTS_TO]->(asset), "
                "(ra)-[:EVIDENCED_BY]->(public), (ra)-[:EVIDENCED_BY]->(private)",
                assertion_id=assertion_id, owner_id=owner_id, idea_id=idea_id, asset_id=asset_id,
                public_id=public_evidence_id, private_id=private_evidence_id,
            ).consume()

    try:
        ready_until = time.monotonic() + 60
        while True:
            try:
                with driver.session(database="neo4j") as session:
                    session.run("RETURN 1 AS ready").consume()
                break
            except (DatabaseUnavailable, ServiceUnavailable):
                if time.monotonic() >= ready_until:
                    raise TimeoutError("disposable Neo4j database did not become query-ready within 60 seconds")
                time.sleep(1)
        with driver.session(database="neo4j") as session:
            session.execute_write(seed)

        raw_nodes = store.read_nodes(owner_id)
        assert len(raw_nodes) == MAX_NODES + 1
        assert all(row["owner_id"] == owner_id for row in raw_nodes)
        old_row = next(row for row in raw_nodes if row["id"] == old_assertion_id)
        assert old_row["has_successor"] is True
        assert all(row["id"] != successor_id for row in raw_nodes)

        result = read_local_graph(store, owner_id=owner_id)

        assert result["status"] == "ready"
        assert result["truncated"] is True
        assert [edge["id"] for edge in result["semantic_edges"]] == [current_assertion_id]
        assert result["semantic_edges"][0] == {
            "id": current_assertion_id,
            "source_id": idea_id,
            "target_id": asset_id,
            "predicate": "REUSES",
            "status": "inferred",
            "confidence": 0.82,
            "evidence_ids": [public_evidence_id],
            "based_on_brief_id": "synthetic-brief-v1",
            "based_on_brief_section_index": 3,
        }
        serialized = json.dumps(result, ensure_ascii=False)
        assert old_assertion_id not in {edge["id"] for edge in result["semantic_edges"]}
        assert successor_id not in serialized
        assert "PUBLIC_EVIDENCE_BODY_MUST_NOT_ESCAPE" not in serialized
        assert "PRIVATE_EVIDENCE_BODY_MUST_NOT_ESCAPE" not in serialized
    finally:
        try:
            with driver.session(database="neo4j") as session:
                session.execute_write(
                    lambda tx: tx.run(
                        "MATCH (n {owner_id: $owner_id}) DETACH DELETE n",
                        owner_id=owner_id,
                    ).consume()
                )
        finally:
            driver.close()
