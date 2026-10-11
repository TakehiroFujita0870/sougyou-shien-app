"""Opt-in proof using the repository's exact disposable Neo4j harness."""
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nebula.founder_graph import Asset, Claim, EgressPolicy, Idea, MaterialKind, Provenance, Source, SourceRevision
from nebula.founder_graph_candidate_job_processor import RelationCandidateJobProcessor
from nebula.founder_graph_neo4j import Neo4jGraphGateway
from nebula.founder_graph_neo4j_read import Neo4jGraphReadService
from nebula.founder_graph_neo4j_write import Neo4jGraphWriteService, Neo4jIdeaBriefStore
from nebula.graph_admin_mcp import GraphAdminSurface
from nebula.graph_admin_audit import safe_graph
from nebula.idea_brief import IdeaBriefVersion, IdeaBriefSection, SECTION_TITLES
from neo4j_disposable_harness import DisposableNeo4j, fixed_docker, is_opted_in
from test_founder_graph_neo4j_lifecycle_real import _wait_ready
from test_graph_admin_cleanup import call, manifest, request


@pytest.mark.skipif(not is_opted_in(os.environ, "NEBULA_NEO4J_GRAPH_ADMIN_REAL"), reason="explicit disposable Neo4j opt-in")
def test_real_inventory_relation_archive_restore_and_new_surface_journal_replay():
    from neo4j import GraphDatabase
    docker = fixed_docker()
    assert docker is not None, "documented Docker CLI required"
    resource = DisposableNeo4j(docker, uuid4().hex, role="neo4j-graph-admin", name_prefix="nebula-admin")
    driver = None
    try:
        port = resource.start()
        driver = GraphDatabase.driver(f"bolt://127.0.0.1:{port}")
        assert _wait_ready(driver)
        gateway = Neo4jGraphGateway(driver, "owner")
        gateway.migrate()
        writes, reads = Neo4jGraphWriteService(gateway), Neo4jGraphReadService(gateway)
        store = Neo4jIdeaBriefStore(gateway)
        for node in (Idea(id="idea", owner_id="owner", title="架空の倉庫案", egress_policy=EgressPolicy.SHAREABLE),
                     Asset(id="asset", owner_id="owner", name="倉庫", egress_policy=EgressPolicy.SHAREABLE),
                     Source(id="synthetic", owner_id="owner", title="架空", egress_policy=EgressPolicy.SHAREABLE,
                         provenance=Provenance(actor="nebula_synthetic_fixture", operation="create_synthetic_fixture", rule_version="synthetic-fixture-v1"))):
            writes.put_node(node, idempotency_key=node.id)
        brief = IdeaBriefVersion(id="brief", owner_id="owner", idea_lineage_root_id="idea", based_on_idea_id="idea",
            report_markdown="## エグゼクティブサマリー\n\n所有する倉庫を活用する。", egress_policy=EgressPolicy.SHAREABLE)
        store.save(brief, expected_latest_revision=None, idempotency_key="brief")
        processor = RelationCandidateJobProcessor(jobs=SimpleNamespace(owner_id="owner"), writes=writes, brief_store=store, worker_id="fixture")
        surface = GraphAdminSurface(writes, reads, processor, allow_delete=True)
        assert safe_graph(writes, reads)[0]["summary"]["node_count"] == 4
        candidate = call(surface, "propose_graph_cleanup", {"manifests": [manifest()]})["candidates"][0]
        applied = call(surface, "apply_graph_cleanup", request(surface,
            [{"action": "relation", "manifest": manifest(), "candidate_id": candidate["id"]}], key="relation", dry_run=False))
        assert applied["outcome"] == "success"
        assert call(surface, "propose_graph_cleanup", {"manifests": [manifest()]})["candidates"][0]["duplicate"]
        args = request(surface, [{"action": "archive", "node_id": "synthetic", "expected_revision": 0}], key="archive", dry_run=False)
        archived = call(surface, "apply_graph_cleanup", args)
        assert archived["outcome"] == "success"
        fresh = GraphAdminSurface(writes, reads, processor, allow_delete=True)
        assert call(fresh, "apply_graph_cleanup", args)["replayed"]
        assert writes.get_node("synthetic").fields["status"] == "archived"
        restored = call(fresh, "apply_graph_cleanup", request(fresh,
            [{"action": "restore", "node_id": "synthetic", "expected_revision": 1}], key="restore", dry_run=False))
        assert restored["outcome"] == "success" and writes.get_node("synthetic").revision == 2
        assert store.get_latest("idea").report_markdown == brief.report_markdown
        # The same validator checks external Evidence/Claim/source lineage too.
        researched_idea = Idea(id="idea-grounded", owner_id="owner", title="根拠付き架空案", egress_policy=EgressPolicy.SHAREABLE)
        claim = Claim(id="claim-grounded", owner_id="owner", text="架空の資料による根拠", egress_policy=EgressPolicy.SHAREABLE)
        for node in (researched_idea, claim):
            writes.put_node(node, idempotency_key=node.id)
        source = Source(id="source-grounded", owner_id="owner", title="架空資料", kind=MaterialKind.WEB, locator="https://example.test/grounded", current_revision_id="revision-grounded", revision=1, egress_policy=EgressPolicy.SHAREABLE)
        revision = SourceRevision(id="revision-grounded", owner_id="owner", source_id=source.id, content="架空の資料による根拠", locator=source.locator, egress_policy=EgressPolicy.SHAREABLE)
        captured = writes.capture_source(source, revision, idempotency_key="source-grounded")
        evidence_id = writes.capture_evidence(claim.id, captured.content_chunk_ids[0], egress_policy=EgressPolicy.SHAREABLE, idempotency_key="evidence-grounded").target_id
        researched_brief = IdeaBriefVersion(id="brief-grounded", owner_id="owner", idea_lineage_root_id=researched_idea.id,
            based_on_idea_id=researched_idea.id, egress_policy=EgressPolicy.SHAREABLE,
            report_markdown="\n\n".join(f"## {title}\n\n架空の資料による根拠" for title in SECTION_TITLES),
            sections=tuple(IdeaBriefSection(index=i, content="架空の資料による根拠", evidence_ids=(evidence_id,) if i == 1 else ()) for i in range(8)))
        store.save(researched_brief, expected_latest_revision=None, idempotency_key="brief-grounded")
        assert evidence_id in {n["id"] for n in safe_graph(writes, reads)[0]["collections"]["nodes"]}, safe_graph(writes, reads)[0]["collections"]["nodes"]
        grounded = {"idea_id": researched_idea.id, "brief_id": researched_brief.id,
                    "expected_revision": researched_brief.revision, "candidates": [{
            "source_id": researched_idea.id, "target_id": "asset", "predicate": "REUSES",
            "basis": "external_evidence", "support": {"section_index": 1}, "evidence_ids": [evidence_id]}]}
        proposal = call(fresh, "propose_graph_cleanup", {"manifests": [grounded]})["candidates"][0]
        assert proposal["basis"] == "external_evidence" and proposal["claim_ids"] == ["claim-grounded"]
        before_private = call(fresh, "audit_graph", {})
        writes.put_node(Idea(id="private-real", owner_id="owner", title="機密"), idempotency_key="private-real")
        assert call(fresh, "audit_graph", {}) == before_private
    finally:
        if driver is not None:
            driver.close()
        resource.close()
