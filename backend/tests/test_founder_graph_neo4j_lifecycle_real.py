"""Opt-in archive/restore proof against an exact disposable Neo4j instance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import threading
import time
from uuid import uuid4

import pytest

from nebula.founder_graph import (
    Asset,
    AssetKind,
    Claim,
    EgressPolicy,
    Idea,
    MaterialKind,
    NodeType,
    Provenance,
    RelationAssertion,
    RelationType,
    RelationshipStatus,
    ResearchCampaign,
    ResearchRun,
    Source,
    SourceRevision,
    Status,
)
from nebula.founder_graph_lifecycle_resolver import resolve_restored_idea_reference
from nebula.founder_graph_neo4j import Neo4jGraphGateway
from nebula.founder_graph_neo4j_read import Neo4jGraphReadService
from nebula.founder_graph_neo4j_write import Neo4jGraphWriteService
from nebula.founder_graph_read import GraphReadNotFoundError
from nebula.idea_brief import IdeaBriefSection, IdeaBriefVersion
from nebula.founder_graph_write import RevisionConflictError
from neo4j_disposable_harness import DisposableNeo4j, HarnessError, fixed_docker, is_opted_in, IMAGE


OPT_IN = "NEBULA_NEO4J_RECORD_LIFECYCLE_REAL"
ROLE = "neo4j-record-lifecycle"
NAME_PREFIX = "nebula-lifecycle"


def _wait_ready(driver, timeout_seconds: float = 90) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            driver.verify_connectivity()
            with driver.session(database="neo4j") as session:
                if session.run("RETURN 1 AS ready").single()["ready"] == 1:
                    return True
        except Exception:
            threading.Event().wait(0.2)
    return False


def _seed_records(writer: Neo4jGraphWriteService, owner: str, suffix: str):
    now = datetime.now(timezone.utc)
    idea = Idea(
        owner_id=owner, id=f"idea-{suffix}", title=f"Synthetic lifecycle idea {suffix}",
        summary="Synthetic archive/restore fixture", egress_policy=EgressPolicy.SHAREABLE,
    )
    claim = Claim(
        owner_id=owner, id=f"claim-{suffix}", text=f"Synthetic lifecycle claim {suffix}",
        confidence=0.8, egress_policy=EgressPolicy.SHAREABLE,
    )
    writer.put_node(idea, idempotency_key=f"seed-idea-{suffix}", operation="capture_idea")
    writer.put_node(claim, idempotency_key=f"seed-claim-{suffix}", operation="append_claim")

    source_id = f"source-{suffix}"
    revision_id = f"source-revision-{suffix}"
    url = f"https://example.test/lifecycle/{suffix}"
    source = Source(
        owner_id=owner, id=source_id, title=f"Synthetic source {suffix}", kind=MaterialKind.WEB,
        locator=url, current_revision_id=revision_id, revision=1,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    source_revision = SourceRevision(
        owner_id=owner, id=revision_id, source_id=source_id,
        content=f"Synthetic evidence text {suffix}", locator=url,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    captured_source = writer.capture_source(
        source, source_revision, idempotency_key=f"capture-source-{suffix}",
    )
    captured_evidence = writer.capture_evidence(
        claim.id, captured_source.content_chunk_ids[0], egress_policy=EgressPolicy.SHAREABLE,
        idempotency_key=f"capture-evidence-{suffix}",
    )

    campaign = ResearchCampaign(
        owner_id=owner, id=f"campaign-{suffix}", purpose="Synthetic lifecycle research",
        target_idea_id=idea.id, allowed_categories=("idea.summary",), trial_budget=1,
        expires_at=now + timedelta(hours=1), egress_policy=EgressPolicy.SHAREABLE,
        created_at=now - timedelta(seconds=10), provenance=Provenance(
            actor="synthetic-test", operation="seed", target_id=f"campaign-{suffix}",
            occurred_at=now - timedelta(seconds=10),
        ),
    )
    writer.put_node(campaign, idempotency_key=f"seed-campaign-{suffix}", expected_revision=0)
    approved_at = now + timedelta(seconds=1)
    approved = campaign.approve(approved_at=approved_at)
    writer.put_node(
        approved, expected_revision=campaign.aggregate_revision,
        idempotency_key=f"approve-campaign-{suffix}",
    )
    run = ResearchRun(
        owner_id=owner, id=f"run-{suffix}", campaign_id=campaign.id,
        input_snapshot={"query": "synthetic lifecycle"}, model_snapshot="synthetic-test@1",
        sources=(source_id,), evidence_ids=(captured_evidence.target_id,), results={"summary": "synthetic"},
        status=Status.COMPLETED, egress_policy=EgressPolicy.SHAREABLE,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision,
        started_at=approved_at + timedelta(seconds=1), finished_at=approved_at + timedelta(seconds=2),
    )
    writer.record_research_run(
        run, expected_campaign_revision=approved.aggregate_revision,
        idempotency_key=f"record-run-{suffix}",
    )
    brief = IdeaBriefVersion(
        owner_id=owner, id=f"brief-{suffix}", idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id, research_run_ids=(run.id,), egress_policy="shareable",
        sections=tuple(
            IdeaBriefSection(
                index=index, content=f"Synthetic brief section {index}",
                evidence_ids=(captured_evidence.target_id,) if index == 1 else (),
            )
            for index in range(8)
        ),
    )
    writer.gateway.save_idea_brief(
        brief, expected_latest_revision=None, idempotency_key=f"save-brief-{suffix}",
    )
    assertion = RelationAssertion(
        owner_id=owner, id=f"assertion-{suffix}", source_id=idea.id, source_kind=NodeType.IDEA,
        target_id=claim.id, target_kind=NodeType.CLAIM, predicate=RelationType.ADDRESSES,
        assertion_family_id=f"family-{suffix}", status=RelationshipStatus.CONFIRMED,
        evidence_ids=(captured_evidence.target_id,), based_on_brief_id=brief.id,
        based_on_brief_section_index=1, egress_policy=EgressPolicy.SHAREABLE,
    )
    writer.save_relation_assertion(
        assertion, expected_family_revision=None, idempotency_key=f"save-assertion-{suffix}",
    )
    asset = Asset(
        owner_id=owner, id=f"asset-{suffix}", name=f"Synthetic lifecycle asset {suffix}",
        kind=AssetKind.KNOWLEDGE, description="Synthetic asset fixture",
    )
    writer.put_node(asset, idempotency_key=f"seed-asset-{suffix}", operation="capture_asset")
    return idea, asset, brief, assertion, captured_evidence.target_id, url


def test_real_neo4j_archive_restore_preserves_history_and_rebinds_existing_records():
    if not is_opted_in(os.environ, OPT_IN):
        pytest.skip(f"set {OPT_IN}=1 for this synthetic disposable-Neo4j proof")
    docker = fixed_docker()
    if docker is None:
        pytest.skip("supported Docker CLI is unavailable; no container created")
    try:
        docker.call("version", "--format", "{{.Server.Version}}")
        docker.call("image", "inspect", IMAGE)
    except HarnessError:
        pytest.skip("Docker daemon or preloaded Neo4j image unavailable; no image pull attempted")

    run_id = uuid4().hex
    disposable = DisposableNeo4j(docker, run_id, role=ROLE, name_prefix=NAME_PREFIX)
    driver = None
    owner = f"owner-{run_id[:12]}"
    try:
        port = disposable.start()
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(f"bolt://127.0.0.1:{port}", auth=None)
        assert _wait_ready(driver), "disposable Neo4j did not pass bounded readiness queries"
        gateway = Neo4jGraphGateway(driver, owner)
        gateway.migrate()
        writer = Neo4jGraphWriteService(gateway)
        reads = Neo4jGraphReadService(gateway)
        idea, asset, brief, assertion, evidence_id, source_url = _seed_records(writer, owner, run_id[:12])

        before_brief = reads.fetch_idea_brief(idea.id, owner_id=owner)
        assert before_brief["brief_id"] == brief.id and len(before_brief["sections"]) == 8
        assert before_brief["brief_citations"][1][0]["url"] == source_url
        before_relation = reads.fetch_relation_assertion(assertion.id, owner_id=owner)
        assert before_relation.source_id == idea.id and before_relation.target_id == assertion.target_id
        assert reads.fetch(evidence_id, owner_id=owner).id == evidence_id
        assert reads.fetch(asset.id, owner_id=owner).id == asset.id

        archived_idea = writer.archive_idea(
            idea.id, expected_revision=idea.revision, idempotency_key=f"archive-idea-{run_id}",
        )
        archived_asset = writer.archive_asset(
            asset.id, expected_revision=asset.revision, idempotency_key=f"archive-asset-{run_id}",
        )
        assert archived_idea.revision == idea.revision + 1
        assert archived_asset.revision == asset.revision + 1
        with pytest.raises(RevisionConflictError):
            writer.archive_idea(
                idea.id, expected_revision=idea.revision + 1, idempotency_key=f"stale-idea-{run_id}",
            )
        with pytest.raises(RevisionConflictError):
            writer.archive_asset(
                asset.id, expected_revision=asset.revision + 1, idempotency_key=f"stale-asset-{run_id}",
            )
        assert writer.archive_idea(
            idea.id, expected_revision=idea.revision, idempotency_key=f"archive-idea-{run_id}",
        ).replayed
        for old_id in (idea.id, asset.id):
            with pytest.raises(GraphReadNotFoundError):
                reads.fetch(old_id, owner_id=owner)
        assert not any(hit.node.id in {idea.id, archived_idea.target_id} for hit in reads.search(
            idea.title, owner_id=owner,
        ).hits)
        with pytest.raises(GraphReadNotFoundError):
            reads.fetch_idea_brief(idea.id, owner_id=owner)
        with pytest.raises(GraphReadNotFoundError):
            reads.fetch_relation_assertion(assertion.id, owner_id=owner)

        restored_idea = writer.restore_idea(
            archived_idea.target_id, expected_revision=archived_idea.revision,
            idempotency_key=f"restore-idea-{run_id}",
        )
        restored_asset = writer.restore_asset(
            archived_asset.target_id, expected_revision=archived_asset.revision,
            idempotency_key=f"restore-asset-{run_id}",
        )
        assert restored_idea.revision == archived_idea.revision + 1
        assert restored_asset.revision == archived_asset.revision + 1
        assert writer.restore_idea(
            archived_idea.target_id, expected_revision=archived_idea.revision,
            idempotency_key=f"restore-idea-{run_id}",
        ).replayed
        assert writer.restore_asset(
            archived_asset.target_id, expected_revision=archived_asset.revision,
            idempotency_key=f"restore-asset-{run_id}",
        ).replayed

        with pytest.raises(GraphReadNotFoundError):
            reads.fetch(idea.id, owner_id=owner)
        with pytest.raises(GraphReadNotFoundError):
            reads.fetch(asset.id, owner_id=owner)
        current = reads.fetch(restored_idea.target_id, owner_id=owner)
        assert current.id == restored_idea.target_id
        projection = reads.fetch_idea_brief(restored_idea.target_id, owner_id=owner)
        assert projection["brief_id"] == brief.id and projection["idea_id"] == restored_idea.target_id
        assert len(projection["sections"]) == 8
        assert projection["brief_citations"][1][0]["url"] == source_url
        relation = reads.fetch_relation_assertion(assertion.id, owner_id=owner)
        assert relation.source_id == restored_idea.target_id
        assert relation.target_id == assertion.target_id
        assert reads.fetch(evidence_id, owner_id=owner).id == evidence_id
        assert reads.fetch(restored_asset.target_id, owner_id=owner).id == restored_asset.target_id
        with gateway.read_session() as session:
            chain = gateway.execute_read(
                session, lambda tx: gateway.read_idea_chain_tx(tx, idea.id),
            )
        assert resolve_restored_idea_reference(idea.id, chain) is chain[-1]

        with driver.session(database="neo4j") as session:
            persisted = list(session.run(
                "MATCH (n {owner_id: $owner_id}) "
                "WHERE n.id IN $ids RETURN n.id AS id, n.revision AS revision, n.status AS status",
                owner_id=owner,
                ids=[idea.id, archived_idea.target_id, restored_idea.target_id,
                     asset.id, archived_asset.target_id, restored_asset.target_id],
            ))
        assert len(persisted) == 6
        assert len({row["id"] for row in persisted}) == 6
    finally:
        try:
            if driver is not None:
                try:
                    with driver.session(database="neo4j") as session:
                        session.run(
                            "MATCH (n {owner_id: $owner_id}) DETACH DELETE n",
                            owner_id=owner,
                        ).consume()
                finally:
                    driver.close()
        finally:
            disposable.close()
