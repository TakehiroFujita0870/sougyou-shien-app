from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import (
    Claim,
    Evidence,
    NodeType,
    ReportSection,
    ReportStatus,
    ReportVersion,
    ResearchCampaign,
    ResearchRun,
)
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_write import GraphWriteError, GraphWriteNotFoundError


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
