"""Opt-in provenance roundtrip against an explicitly disposable loopback Neo4j."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from dots.founder_graph import (
    Asset, Claim, EgressPolicy, Evidence, Idea, NodeType, Provenance,
    RelationAssertion, RelationType, RelationshipStatus, ResearchCampaign, ResearchRun, Status,
)
from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.idea_brief_neo4j import Neo4jIdeaBriefStore
from dots.local_graph_provenance import (
    GraphProvenanceNotFound, Neo4jGraphProvenanceStore, read_local_graph_provenance,
)


@pytest.mark.skipif(
    not os.environ.get("FOUNDER_GRAPH_NEO4J_TEST_URI"),
    reason="requires an explicitly configured disposable loopback Neo4j",
)
def test_real_provenance_returns_exact_safe_brief_and_rejects_foreign_stale_records():
    neo4j = pytest.importorskip("neo4j")
    from neo4j.exceptions import DatabaseUnavailable, ServiceUnavailable

    uri = os.environ["FOUNDER_GRAPH_NEO4J_TEST_URI"]
    parsed = urlsplit(uri)
    if parsed.scheme != "bolt" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port is None:
        raise ValueError("provenance smoke requires an explicit loopback Bolt URI")

    token = uuid4().hex
    owner_id, foreign_owner_id = f"rp06-prov-{token}", f"rp06-prov-other-{token}"
    driver = neo4j.GraphDatabase.driver(
        uri, auth=None, connection_timeout=2, connection_acquisition_timeout=2, max_transaction_retry_time=2,
    )
    writes = Neo4jGraphWriteService(Neo4jGraphGateway(driver, owner_id))
    foreign_writes = Neo4jGraphWriteService(Neo4jGraphGateway(driver, foreign_owner_id))
    brief_store = Neo4jIdeaBriefStore(driver, owner_id=owner_id)
    provenance_store = Neo4jGraphProvenanceStore(driver, owner_id=owner_id)
    now = datetime.now(timezone.utc)
    idea = Idea(id=f"idea-{token}", owner_id=owner_id, title="Synthetic provenance idea")
    old_asset = Asset(id=f"asset-old-{token}", owner_id=owner_id, name="Synthetic old target")
    current_asset = Asset(id=f"asset-current-{token}", owner_id=owner_id, name="Synthetic current target")
    claim = Claim(id=f"claim-{token}", owner_id=owner_id, text="Synthetic claim")
    evidence = Evidence(
        id=f"evidence-{token}", owner_id=owner_id, material_id=f"material-{token}", claim_id=claim.id,
        excerpt="PRIVATE_SYNTHETIC_EXCERPT_MUST_NOT_ESCAPE", locator="PRIVATE_SYNTHETIC_LOCATOR_MUST_NOT_ESCAPE",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    foreign_idea = Idea(id=f"idea-foreign-{token}", owner_id=foreign_owner_id, title="Synthetic foreign idea")
    foreign_asset = Asset(id=f"asset-foreign-{token}", owner_id=foreign_owner_id, name="Synthetic foreign target")
    owned = (idea, old_asset, current_asset, claim, evidence)
    foreign_assertion_id = f"assertion-foreign-{token}"
    old_assertion_id = f"assertion-old-{token}"
    current_assertion_id = f"assertion-current-{token}"
    campaign_id = f"campaign-{token}"
    run_id = f"run-{token}"
    brief_id = f"brief-{token}"

    def link(*, assertion_id: str, target: Asset, family: str, supersedes: str | None = None):
        value = RelationAssertion(
            id=assertion_id, owner_id=owner_id, source_id=idea.id, source_kind=NodeType.IDEA,
            target_id=target.id, target_kind=NodeType.ASSET, predicate=RelationType.REUSES,
            assertion_family_id=family, revision=1, supersedes_id=supersedes,
            status=RelationshipStatus.INFERRED, confidence=0.84, evidence_ids=(evidence.id,),
            based_on_brief_id=brief_id, based_on_brief_section_index=2,
            valid_from=now - timedelta(minutes=1),
            provenance=Provenance(actor="local-owner", operation="link_entities", target_id="placeholder"),
        )
        return replace(value, provenance=Provenance(actor="local-owner", operation="link_entities", target_id=assertion_id))

    try:
        ready_until = time.monotonic() + 60
        while True:
            try:
                with driver.session(database="neo4j") as session:
                    session.run("RETURN 1 AS ready").consume()
                break
            except (DatabaseUnavailable, ServiceUnavailable):
                if time.monotonic() >= ready_until:
                    raise TimeoutError("disposable Neo4j did not become query-ready within 60 seconds")
                time.sleep(1)

        for index, node in enumerate(owned):
            writes.put_node(node, idempotency_key=f"seed-{token}-{index}")
        foreign_writes.put_node(foreign_idea, idempotency_key=f"foreign-seed-idea-{token}")
        foreign_writes.put_node(foreign_asset, idempotency_key=f"foreign-seed-asset-{token}")
        foreign_assertion = RelationAssertion(
            id=foreign_assertion_id, owner_id=foreign_owner_id,
            source_id=foreign_idea.id, source_kind=NodeType.IDEA,
            target_id=foreign_asset.id, target_kind=NodeType.ASSET,
            predicate=RelationType.REUSES, assertion_family_id=f"family-foreign-{token}",
        )
        foreign_writes.save_relation_assertion(foreign_assertion, idempotency_key=f"foreign-link-{token}")

        campaign = ResearchCampaign(
            id=campaign_id, owner_id=owner_id, purpose="Synthetic provenance validation",
            scope={"target_ids": [idea.id]}, questions=("Synthetic test question",), target_idea_id=idea.id,
            allowed_categories=("idea.summary",), trial_budget=1,
            expires_at=now + timedelta(hours=1), egress_policy=EgressPolicy.LOCAL_ONLY,
            created_at=now - timedelta(minutes=4),
            provenance=Provenance(occurred_at=now - timedelta(minutes=4)),
        ).approve(approved_at=now - timedelta(minutes=2))
        writes.put_node(campaign, idempotency_key=f"campaign-{token}")
        run = ResearchRun(
            id=run_id, owner_id=owner_id, campaign_id=campaign.id, input_snapshot={"idea": idea.id},
            model_snapshot="synthetic-test@1", results={"finding": "Synthetic finding"},
            evidence_ids=(evidence.id,), status=Status.COMPLETED, egress_policy=EgressPolicy.LOCAL_ONLY,
            authorization_snapshot_id=campaign.authorization_snapshot_id,
            authorization_revision=campaign.authorization_revision,
            started_at=now - timedelta(minutes=1), finished_at=now,
        )
        writes.record_research_run(run, expected_campaign_revision=campaign.aggregate_revision, idempotency_key=f"run-{token}")

        brief = IdeaBriefVersion(
            id=brief_id, owner_id=owner_id, idea_lineage_root_id=idea.id, based_on_idea_id=idea.id,
            research_run_ids=(run.id,),
            sections=tuple(
                IdeaBriefSection(
                    index=index, content=f"Synthetic brief section {index} " + ("chapter-only-text" if index == 2 else ""),
                    evidence_ids=(evidence.id,) if index == 2 else (),
                )
                for index in range(8)
            ),
        )
        brief_store.save(brief)
        previous = link(
            assertion_id=old_assertion_id, target=old_asset,
            family=f"family-old-{token}",
        )
        writes.save_relation_assertion(previous, idempotency_key=f"link-old-{token}")
        current = link(
            assertion_id=current_assertion_id, target=current_asset,
            family=f"family-current-{token}", supersedes=previous.id,
        )
        writes.save_relation_assertion(current, idempotency_key=f"link-current-{token}")

        result = read_local_graph_provenance(
            provenance_store, assertion_id=current.id, owner_id=owner_id, at=now + timedelta(seconds=1),
        )
        assert result == {
            "status": "ready", "assertion_id": current.id,
            "section": {
                "brief_id": brief.id, "revision": 1, "idea_id": idea.id, "section_index": 2,
                "title": "顧客とマーケットサイズ", "content": "Synthetic brief section 2 chapter-only-text",
            },
            "evidence": [{"id": evidence.id, "polarity": "supports", "confidence": 1.0, "status": "active"}],
        }
        encoded = json.dumps(result, ensure_ascii=False)
        assert "PRIVATE_SYNTHETIC_EXCERPT_MUST_NOT_ESCAPE" not in encoded
        assert "PRIVATE_SYNTHETIC_LOCATOR_MUST_NOT_ESCAPE" not in encoded

        with pytest.raises(GraphProvenanceNotFound):
            read_local_graph_provenance(provenance_store, assertion_id=previous.id, owner_id=owner_id, at=now + timedelta(seconds=1))
        foreign_reader = Neo4jGraphProvenanceStore(driver, owner_id=owner_id)
        with pytest.raises(GraphProvenanceNotFound):
            read_local_graph_provenance(foreign_reader, assertion_id=foreign_assertion_id, owner_id=owner_id, at=now + timedelta(seconds=1))

        newer_brief = brief.revise(change_reason="Synthetic superseding brief", research_run_ids=())
        brief_store.save(newer_brief)
        with pytest.raises(GraphProvenanceNotFound):
            read_local_graph_provenance(provenance_store, assertion_id=current.id, owner_id=owner_id, at=now + timedelta(seconds=1))
    finally:
        try:
            with driver.session(database="neo4j") as session:
                session.execute_write(lambda tx: tx.run(
                    "MATCH (n) WHERE n.owner_id IN $owners DETACH DELETE n",
                    owners=[owner_id, foreign_owner_id],
                ).consume())
        finally:
            driver.close()
