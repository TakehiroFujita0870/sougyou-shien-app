from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from hashlib import sha256

import pytest

from dots.founder_graph import (
    Asset,
    Claim,
    EgressPolicy,
    Evidence,
    Idea,
    NodeType,
    ReportSection,
    ReportStatus,
    ReportVersion,
    ResearchCampaign,
    ResearchRun,
    Source,
    SourceRevision,
    Status,
)
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_write import (
    GraphWriteError,
    GraphWriteNotFoundError,
    IdempotencyConflictError,
    InMemoryGraphWriteService,
)


@dataclass
class FakeResult:
    row: dict[str, object] | None = None
    rows: tuple[dict[str, object], ...] = ()

    def single(self, **_kwargs):
        return self.row

    def __iter__(self):
        return iter(self.rows if self.rows else (() if self.row is None else (self.row,)))


class ReportReferenceSession:
    def __init__(self, *, owner_id: str) -> None:
        self.owner_id = owner_id
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.nodes: dict[str, dict[str, object]] = {}
        self.audit_rows: dict[str, dict[str, object]] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self) -> None:
        return None

    def execute_write(self, callback):
        return callback(self)

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (c:Claim" in query and "ContentChunk" in query:
            claim = self.nodes[params["claim_id"]]
            chunk = self.nodes[params["chunk_id"]]
            return FakeResult(dict(claim_type=claim["node_type"], claim_status=claim["status"], claim_payload=claim["payload_json"],
                chunk_type=chunk["node_type"], chunk_status=chunk["status"], chunk_payload=chunk["payload_json"]))
        if "OPTIONAL MATCH (r)-[edge:HAS_CHUNK]" in query:
            return FakeResult(dict(revision_type=NodeType.SOURCE_REVISION.value, revision_status=Status.ACTIVE.value, lineage_count=1))
        if "MERGE (e)-[:EVIDENCE_FROM]->(ch)" in query:
            return FakeResult({"id": params["evidence_id"]})
        if "MATCH (a:FounderGraphAudit" in query:
            for row in self.audit_rows.values():
                if row.get("idempotency_key") == params.get("idempotency_key"):
                    return FakeResult(row)
            return FakeResult()
        if "MATCH (n) WHERE n.id IN $node_ids" in query:
            rows = tuple(
                {
                    "id": identifier,
                    "owner_id": properties["owner_id"],
                    "node_type": properties["node_type"],
                    "payload_json": properties["payload_json"],
                }
                for identifier, properties in self.nodes.items()
                if identifier in params["node_ids"] and properties["owner_id"] == params["owner_id"]
            )
            return FakeResult(rows=rows)
        if "MATCH (n {id: $id})" in query:
            properties = self.nodes.get(params["id"])
            if properties is None:
                return FakeResult()
            return FakeResult({
                "owner_id": properties["owner_id"],
                "node_type": properties["node_type"],
                "revision": properties["revision"],
            })
        if "CREATE (n:" in query and "SET n = $properties" in query:
            properties = params["properties"]
            self.nodes[properties["id"]] = properties
            return FakeResult()
        if "CREATE (a:FounderGraphAudit" in query:
            row = {
                "payload_fingerprint": params.get("payload_fingerprint"),
                "target_id": params.get("target_id"),
                "target_type": params.get("target_type"),
                "revision": params.get("revision", 0),
                "idempotency_key": params.get("idempotency_key"),
                "source_revision_id": params.get("source_revision_id"),
                "content_chunk_ids": params.get("content_chunk_ids"),
            }
            self.audit_rows[str(params["idempotency_key"])] = row
            return FakeResult()
        return FakeResult()


class ReportReferenceDriver:
    def __init__(self, owner_id: str) -> None:
        self.session_value = ReportReferenceSession(owner_id=owner_id)

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


def _approved_fixture(owner_id: str = "owner-1") -> tuple[ResearchCampaign, ResearchRun, Claim, Evidence]:
    campaign = ResearchCampaign(
        owner_id=owner_id,
        id="campaign-1",
        purpose="validate report references",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ).approve()
    run = ResearchRun(
        owner_id=owner_id,
        id="run-1",
        campaign_id=campaign.id,
        input_snapshot={},
        model_snapshot="luna",
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
    )
    claim = Claim(owner_id=owner_id, id="claim-1", text="A supported claim", confidence=0.9)
    evidence = Evidence(owner_id=owner_id, id="evidence-1", material_id="material-1", claim_id=claim.id)
    return campaign, run, claim, evidence


def _report(
    owner_id: str,
    *,
    run_id: str,
    claim_id: str,
    evidence_id: str,
    report_id: str = "report-1",
    parent_id: str | None = None,
) -> ReportVersion:
    sections = tuple(
        ReportSection(
            id=section_id,
            owner_id=owner_id,
            content="summary" if section_id == 0 else "",
            claim_ids=(claim_id,) if section_id == 0 else (),
            evidence_ids=(evidence_id,) if section_id == 0 else (),
        )
        for section_id in range(8)
    )
    return ReportVersion(
        owner_id=owner_id,
        id=report_id,
        sections=sections,
        run_ids=(run_id,),
        evidence_ids=(evidence_id,),
        status=ReportStatus.DRAFT,
        parent_id=parent_id,
    )


def _seed(driver: ReportReferenceDriver, *nodes: object) -> None:
    for node in nodes:
        properties = _node_properties(node)
        driver.session_value.nodes[properties["id"]] = properties


def test_persistent_report_write_validates_authorized_run_and_references() -> None:
    owner_id = "owner-1"
    driver = ReportReferenceDriver(owner_id)
    campaign, run, claim, evidence = _approved_fixture(owner_id)
    _seed(driver, campaign, run, claim, evidence)
    gateway = Neo4jGraphGateway(driver, owner_id)

    receipt = gateway.put_node(_report(owner_id, run_id=run.id, claim_id=claim.id, evidence_id=evidence.id), idempotency_key="report-valid")

    assert receipt.target_id == "report-1"
    assert driver.session_value.nodes["report-1"]["node_type"] == NodeType.REPORT_VERSION.value
    assert any("CREATE (n:ReportVersion)" in query for query, _params in driver.session_value.calls)
    assert "report-valid" in driver.session_value.audit_rows


@pytest.mark.parametrize("claim_policy,accepted", [(EgressPolicy.LOCAL_ONLY, False), (EgressPolicy.SHAREABLE, True)])
def test_persistent_evidence_shareability_requires_shareable_claim(claim_policy, accepted) -> None:
    owner = "owner-evidence"
    driver = ReportReferenceDriver(owner)
    claim = Claim(owner_id=owner, id="claim-evidence", text="claim", confidence=0.9, egress_policy=claim_policy)
    chunk_text = "source passage"
    revision_id, chunk_id = "revision-evidence", "chunk-evidence"
    driver.session_value.nodes[claim.id] = _node_properties(claim)
    payload = dict(id=chunk_id, owner_id=owner, source_revision_id=revision_id, char_start=0,
        char_end=len(chunk_text), text=chunk_text, text_hash=sha256(chunk_text.encode()).hexdigest())
    driver.session_value.nodes[chunk_id] = dict(id=chunk_id, owner_id=owner, node_type=NodeType.CONTENT_CHUNK.value,
        status=Status.ACTIVE.value, payload_json=json.dumps(payload))
    gateway = Neo4jGraphGateway(driver, owner)
    if accepted:
        receipt = gateway.capture_evidence(claim.id, chunk_id, egress_policy=EgressPolicy.SHAREABLE, idempotency_key="shareable-evidence")
        assert receipt.target_type == NodeType.EVIDENCE.value
    else:
        with pytest.raises(GraphWriteError, match="shareable Evidence requires an active shareable Claim"):
            gateway.capture_evidence(claim.id, chunk_id, egress_policy=EgressPolicy.SHAREABLE, idempotency_key="private-claim-evidence")
        assert not any("CREATE (n:Evidence)" in query for query, _ in driver.session_value.calls)


def test_persistent_report_write_rejects_missing_campaign_before_create() -> None:
    owner_id = "owner-1"
    driver = ReportReferenceDriver(owner_id)
    _campaign, run, claim, evidence = _approved_fixture(owner_id)
    missing_campaign_run = ResearchRun(
        owner_id=owner_id,
        id=run.id,
        campaign_id="missing-campaign",
        input_snapshot={},
        model_snapshot=run.model_snapshot,
        authorization_snapshot_id=run.authorization_snapshot_id,
        authorization_revision=run.authorization_revision,
    )
    _seed(driver, missing_campaign_run, claim, evidence)
    gateway = Neo4jGraphGateway(driver, owner_id)

    with pytest.raises(GraphWriteNotFoundError, match="report reference does not exist"):
        gateway.put_node(_report(owner_id, run_id=run.id, claim_id=claim.id, evidence_id=evidence.id), idempotency_key="report-missing-campaign")

    assert not any("CREATE (n:ReportVersion)" in query for query, _params in driver.session_value.calls)
    assert not driver.session_value.audit_rows


def test_persistent_report_write_rejects_evidence_for_unreferenced_claim() -> None:
    owner_id = "owner-1"
    driver = ReportReferenceDriver(owner_id)
    campaign, run, claim, _evidence = _approved_fixture(owner_id)
    wrong_evidence = Evidence(owner_id=owner_id, id="evidence-1", material_id="material-1", claim_id="other-claim")
    _seed(driver, campaign, run, claim, wrong_evidence)
    gateway = Neo4jGraphGateway(driver, owner_id)

    with pytest.raises(GraphWriteError, match="section evidence must identify a referenced claim"):
        gateway.put_node(_report(owner_id, run_id=run.id, claim_id=claim.id, evidence_id=wrong_evidence.id), idempotency_key="report-wrong-evidence")

    assert not any("CREATE (n:ReportVersion)" in query for query, _params in driver.session_value.calls)
    assert not driver.session_value.audit_rows


def test_persistent_report_write_accepts_same_owner_report_parent() -> None:
    owner_id = "owner-1"
    driver = ReportReferenceDriver(owner_id)
    campaign, run, claim, evidence = _approved_fixture(owner_id)
    parent = _report(owner_id, run_id=run.id, claim_id=claim.id, evidence_id=evidence.id, report_id="report-parent")
    _seed(driver, campaign, run, claim, evidence, parent)
    gateway = Neo4jGraphGateway(driver, owner_id)

    receipt = gateway.put_node(
        _report(
            owner_id,
            run_id=run.id,
            claim_id=claim.id,
            evidence_id=evidence.id,
            report_id="report-child",
            parent_id=parent.id,
        ),
        idempotency_key="report-child",
    )

    assert receipt.target_id == "report-child"
    assert driver.session_value.nodes[receipt.target_id]["node_type"] == NodeType.REPORT_VERSION.value


@pytest.mark.parametrize("parent_id", ("missing-report-parent", "claim-1"))
def test_persistent_report_write_rejects_missing_or_wrong_type_parent_before_create(parent_id: str) -> None:
    owner_id = "owner-1"
    driver = ReportReferenceDriver(owner_id)
    campaign, run, claim, evidence = _approved_fixture(owner_id)
    _seed(driver, campaign, run, claim, evidence)
    gateway = Neo4jGraphGateway(driver, owner_id)

    with pytest.raises((GraphWriteError, GraphWriteNotFoundError)):
        gateway.put_node(
            _report(owner_id, run_id=run.id, claim_id=claim.id, evidence_id=evidence.id, parent_id=parent_id),
            idempotency_key="report-invalid-parent",
        )

    assert not any("CREATE (n:ReportVersion)" in query for query, _params in driver.session_value.calls)
    assert not driver.session_value.audit_rows


def test_persistent_report_write_rejects_cross_owner_parent_before_create() -> None:
    owner_id = "owner-1"
    driver = ReportReferenceDriver(owner_id)
    campaign, run, claim, evidence = _approved_fixture(owner_id)
    foreign_parent = _report("owner-2", run_id=run.id, claim_id=claim.id, evidence_id=evidence.id, report_id="foreign-parent")
    _seed(driver, campaign, run, claim, evidence, foreign_parent)
    gateway = Neo4jGraphGateway(driver, owner_id)

    with pytest.raises(GraphWriteNotFoundError, match="report reference does not exist"):
        gateway.put_node(
            _report(owner_id, run_id=run.id, claim_id=claim.id, evidence_id=evidence.id, parent_id=foreign_parent.id),
            idempotency_key="report-cross-owner-parent",
        )

    assert not any("CREATE (n:ReportVersion)" in query for query, _params in driver.session_value.calls)
    assert not driver.session_value.audit_rows


def test_capture_idea_receipt_and_chunks_match_in_memory_and_neo4j_replay() -> None:
    owner_id = "owner-1"
    idea = Idea(owner_id=owner_id, id="capture-idea", title="Captured idea")
    source = Source(
        owner_id=owner_id,
        id="capture-source",
        title="Conversation",
        kind="conversation",
        revision=1,
        current_revision_id="capture-revision",
    )
    revision = SourceRevision(
        owner_id=owner_id,
        id="capture-revision",
        source_id=source.id,
        content="😀" * 2_401 + "\n\n" + "source text",
    )
    memory = InMemoryGraphWriteService(owner_id)
    driver = ReportReferenceDriver(owner_id)
    gateway = Neo4jGraphGateway(driver, owner_id)

    memory_first = memory.capture_idea(idea, source, revision, idempotency_key="capture")
    neo_first = gateway.capture_idea(idea, source, revision, idempotency_key="capture")
    memory_replay = memory.capture_idea(idea, source, revision, idempotency_key="capture")
    neo_replay = gateway.capture_idea(idea, source, revision, idempotency_key="capture")

    assert neo_first.target_id == memory_first.target_id == idea.id
    assert neo_first.target_type == memory_first.target_type == NodeType.IDEA.value
    assert neo_first.source_revision_id == memory_first.source_revision_id == revision.id
    assert neo_first.content_chunk_ids == memory_first.content_chunk_ids
    assert memory_replay.replayed is True
    assert neo_replay.replayed is True
    assert neo_replay.source_revision_id == neo_first.source_revision_id
    assert neo_replay.content_chunk_ids == neo_first.content_chunk_ids
    assert set(driver.session_value.nodes) == {idea.id, source.id, revision.id, *memory_first.content_chunk_ids}
    assert memory.audit_events()[0].payload_fingerprint == driver.session_value.audit_rows["capture"]["payload_fingerprint"]

    changed_revision = SourceRevision(
        owner_id=owner_id,
        id=revision.id,
        source_id=source.id,
        content=revision.content + " changed",
    )
    with pytest.raises(IdempotencyConflictError):
        memory.capture_idea(idea, source, changed_revision, idempotency_key="capture")
    with pytest.raises(IdempotencyConflictError):
        gateway.capture_idea(idea, source, changed_revision, idempotency_key="capture")


def test_asset_generic_put_has_memory_and_fake_neo4j_parity() -> None:
    owner_id = "owner-asset"
    memory = InMemoryGraphWriteService(owner_id)
    driver = ReportReferenceDriver(owner_id)
    gateway = Neo4jGraphGateway(driver, owner_id)
    asset = Asset(owner_id=owner_id, id="asset-one", name="Synthetic kit", kind="artifact", description="Safe summary")
    assert memory.put_node(asset, idempotency_key="asset-write", operation="capture_asset") == gateway.put_node(
        asset, idempotency_key="asset-write", operation="capture_asset")
    assert driver.session_value.nodes[asset.id]["node_type"] == "asset"
    assert driver.session_value.nodes[asset.id]["payload_json"]
    assert memory.put_node(asset, idempotency_key="asset-write", operation="capture_asset").replayed
    assert gateway.put_node(asset, idempotency_key="asset-write", operation="capture_asset").replayed
    with pytest.raises(IdempotencyConflictError):
        memory.put_node(Asset(owner_id=owner_id, id=asset.id, name="Changed"), idempotency_key="asset-write", operation="capture_asset")
    with pytest.raises(IdempotencyConflictError):
        gateway.put_node(Asset(owner_id=owner_id, id=asset.id, name="Changed"), idempotency_key="asset-write", operation="capture_asset")


def test_capture_idea_empty_content_receipt_matches_in_memory_and_neo4j() -> None:
    owner_id = "owner-1"
    idea = Idea(owner_id=owner_id, id="empty-capture-idea", title="Empty source idea")
    source = Source(
        owner_id=owner_id,
        id="empty-capture-source",
        title="Empty conversation",
        kind="conversation",
        revision=1,
        current_revision_id="empty-capture-revision",
    )
    revision = SourceRevision(
        owner_id=owner_id,
        id="empty-capture-revision",
        source_id=source.id,
        content="",
    )
    memory = InMemoryGraphWriteService(owner_id)
    driver = ReportReferenceDriver(owner_id)
    gateway = Neo4jGraphGateway(driver, owner_id)

    memory_receipt = memory.capture_idea(idea, source, revision, idempotency_key="capture-empty")
    neo4j_receipt = gateway.capture_idea(idea, source, revision, idempotency_key="capture-empty")

    assert neo4j_receipt.source_revision_id == memory_receipt.source_revision_id == revision.id
    assert neo4j_receipt.content_chunk_ids == memory_receipt.content_chunk_ids == ()
    assert set(driver.session_value.nodes) == {idea.id, source.id, revision.id}
    assert memory.audit_events()[0].payload_fingerprint == driver.session_value.audit_rows["capture-empty"]["payload_fingerprint"]
