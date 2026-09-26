from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from dots.founder_graph import EgressPolicy, NodeType, Provenance, ResearchCampaign, ResearchRun, Status
from dots.founder_graph_neo4j import Neo4jGraphGateway, Neo4jUnavailableError
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService
from dots.founder_graph_write import (
    GraphWriteError,
    IdempotencyConflictError,
    RevisionConflictError,
    WriteReceipt,
    research_run_payload_fingerprint,
)


class Result:
    def __init__(self, row=None):
        self.row = row

    def single(self, **_kwargs):
        return self.row


def fixture_campaign(*, budget=2):
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=1)
    return ResearchCampaign(
        owner_id="owner-run-test", id="campaign-run-test", purpose="synthetic",
        scope={"target_ids": ["idea-run-test"]}, target_idea_id="idea-run-test",
        allowed_categories=("idea.summary",), trial_budget=budget,
        expires_at=now + timedelta(hours=1), egress_policy=EgressPolicy.SHAREABLE,
        created_at=created, provenance=Provenance(
            actor="synthetic", operation="create", target_id="campaign-run-test",
            occurred_at=created, idempotency_key="campaign-run-test-key",
        ),
    ).approve(approved_at=now - timedelta(minutes=5))


def fixture_run(campaign, *, run_id="run-test", status=Status.COMPLETED):
    now = datetime.now(timezone.utc)
    return ResearchRun(
        id=run_id, owner_id=campaign.owner_id, campaign_id=campaign.id,
        input_snapshot={"question": "synthetic"}, model_snapshot="synthetic@1",
        sources=("source-test",), evidence_ids=("evidence-test",),
        results={"summary": "synthetic"}, status=status, egress_policy=EgressPolicy.SHAREABLE,
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
        started_at=now - timedelta(minutes=2), finished_at=now - timedelta(minutes=1),
        provenance=Provenance(actor="synthetic", operation="record_research_run", target_id=run_id,
                              occurred_at=now, idempotency_key=f"run:{run_id}"),
    )


class RunSession:
    def __init__(self, campaign):
        from dots.founder_graph_neo4j import _node_properties

        properties = _node_properties(campaign)
        self.campaign_record = {
            "id": campaign.id, "owner_id": campaign.owner_id, "node_type": NodeType.RESEARCH_CAMPAIGN.value,
            "revision": campaign.aggregate_revision, "payload_json": properties["payload_json"],
        }
        self.calls = []
        self.audit = None
        self.audit_after_lock = None
        self.runs = {}
        self.links = []
        self.history_count = 0
        self.closed = False
        self.fail_after_callback = False
        self.fail_recovery_read = False
        self.drop_receipt = False
        self.change_receipt = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.closed = True

    def execute_write(self, callback):
        result = callback(self)
        if self.fail_after_callback:
            self.fail_after_callback = False
            if self.drop_receipt:
                self.audit = None
            elif self.change_receipt and self.audit:
                self.audit["payload_fingerprint"] = "synthetic-other-fingerprint"
            raise RuntimeError("synthetic unknown commit outcome")
        return result

    def execute_read(self, callback):
        if self.fail_recovery_read:
            raise RuntimeError("private synthetic driver diagnostic")
        return callback(self)

    def run(self, query, **params):
        self.calls.append((query, params))
        if "MATCH (a:FounderGraphAudit" in query:
            if self.audit_after_lock:
                return Result()
            return Result(self.audit)
        if "_dots_revision_write_lock" in query:
            if self.audit_after_lock:
                self.audit = self.audit_after_lock
                self.audit_after_lock = None
            return Result({key: self.campaign_record[key] for key in ("id", "owner_id", "node_type", "revision")})
        if "MATCH (c:ResearchCampaign" in query and "payload_json" in query:
            return Result(self.campaign_record)
        if "MATCH (n {id: $run_id})" in query:
            return Result({"id": params["run_id"]} if params["run_id"] in self.runs else None)
        if "CREATE (h:FounderGraphHistory" in query:
            self.history_count += 1
        elif "SET c = $properties" in query:
            props = params["properties"]
            self.campaign_record = {
                "id": props["id"], "owner_id": props["owner_id"], "node_type": props["node_type"],
                "revision": props["revision"], "payload_json": props["payload_json"],
            }
        elif "CREATE (r:ResearchRun" in query:
            self.runs[params["properties"]["id"]] = params["properties"]
        elif "HAS_RUN" in query and "CREATE" in query:
            self.links.append((params["campaign_id"], params["run_id"]))
            return Result({"id": params["run_id"]})
        elif "CREATE (a:FounderGraphAudit" in query:
            self.audit = {name: params[name] for name in (
                "owner_id", "idempotency_key", "operation", "target_id", "target_type", "revision", "payload_fingerprint",
            )}
        return Result()


class RunDriver:
    def __init__(self, session):
        self.value = session
        self.open_count = 0

    def session(self, *, database):
        assert database == "neo4j"
        self.open_count += 1
        return self.value


def writer(session):
    return Neo4jGraphWriteService(Neo4jGraphGateway(RunDriver(session), "owner-run-test"))


@pytest.mark.parametrize("status", [Status.COMPLETED, Status.PARTIAL, Status.FAILED, Status.CANCELLED])
def test_terminal_runs_and_campaign_budget_history_edge_and_audit_share_one_transaction(status):
    campaign = fixture_campaign()
    run = fixture_run(campaign, status=status)
    session = RunSession(campaign)

    receipt = writer(session).record_research_run(
        run, expected_campaign_revision=campaign.aggregate_revision, idempotency_key="run-key-success",
    )

    stored_campaign = json.loads(session.campaign_record["payload_json"])
    assert receipt == WriteReceipt("record_research_run", run.id, NodeType.RESEARCH_RUN.value, 0, "run-key-success")
    assert stored_campaign["run_count"] == 1
    assert stored_campaign["aggregate_revision"] == campaign.aggregate_revision + 1
    assert set(session.runs) == {run.id}
    assert session.links == [(campaign.id, run.id)]
    assert session.history_count == 1 and session.audit["target_id"] == run.id
    assert session.calls[0][0].startswith("MATCH (a:FounderGraphAudit")
    lock = next(i for i, (query, _) in enumerate(session.calls) if "_dots_revision_write_lock" in query)
    writes = [i for i, (query, _) in enumerate(session.calls) if "CREATE (h:FounderGraphHistory" in query]
    assert writes and lock < writes[0]


def test_matching_replay_precedes_lock_and_changed_payload_conflicts():
    campaign = fixture_campaign()
    run = fixture_run(campaign)
    changed_campaign = campaign._transition(
        status=Status.REVOKED, authorized=False, approved_at=None,
        aggregate_revision=campaign.aggregate_revision + 1,
    )
    session = RunSession(changed_campaign)
    session.audit = {
        "owner_id": campaign.owner_id, "idempotency_key": "retry-key", "operation": "record_research_run",
        "target_id": run.id, "target_type": NodeType.RESEARCH_RUN.value, "revision": 0,
        "payload_fingerprint": research_run_payload_fingerprint(run, campaign.aggregate_revision, campaign.owner_id),
    }
    service = writer(session)
    replay = service.record_research_run(
        replace(run, finished_at=run.finished_at + timedelta(seconds=1)),
        expected_campaign_revision=campaign.aggregate_revision, idempotency_key="retry-key",
    )
    assert replay.replayed and len(session.calls) == 1

    with pytest.raises(IdempotencyConflictError):
        service.record_research_run(
            replace(run, results={"summary": "changed"}),
            expected_campaign_revision=campaign.aggregate_revision, idempotency_key="retry-key",
        )
    assert len(session.calls) == 2


@pytest.mark.parametrize("failure", ["wrong_owner", "stale_revision", "stale_snapshot", "revoked", "pending_run", "over_budget", "before_approval", "expired", "duplicate_run"])
def test_invalid_run_or_campaign_is_rejected_without_business_writes(failure):
    campaign = fixture_campaign(budget=1)
    run = fixture_run(campaign)
    expected = campaign.aggregate_revision
    if failure == "wrong_owner":
        run = replace(run, owner_id="other-owner")
    elif failure == "stale_revision":
        expected += 1
    elif failure == "stale_snapshot":
        run = replace(run, authorization_snapshot_id="old-snapshot")
    elif failure == "revoked":
        campaign = campaign._transition(status=Status.REVOKED, authorized=False, approved_at=None)
    elif failure == "pending_run":
        run = fixture_run(campaign, status=Status.RUNNING)
    elif failure == "over_budget":
        campaign = campaign.register_run(at=datetime.now(timezone.utc))
        expected = campaign.aggregate_revision
    elif failure == "expired":
        campaign = campaign._transition(expires_at=run.finished_at - timedelta(seconds=1))
    elif failure == "before_approval":
        run = replace(run, started_at=campaign.approved_at - timedelta(seconds=1))
    session = RunSession(campaign)
    if failure == "duplicate_run":
        session.runs[run.id] = {}

    with pytest.raises((GraphWriteError, RevisionConflictError)):
        writer(session).record_research_run(run, expected_campaign_revision=expected, idempotency_key=f"bad-{failure}")

    assert not any(
        marker in query
        for query, _ in session.calls
        for marker in ("CREATE (h:FounderGraphHistory", "SET c = $properties", "CREATE (r:ResearchRun", "HAS_RUN", "CREATE (a:FounderGraphAudit")
    )
    if failure == "duplicate_run":
        assert any("MATCH (n {id: $run_id})" in query for query, _ in session.calls)


def test_audit_appearing_after_campaign_lock_replays_without_run_mutation():
    campaign = fixture_campaign()
    run = fixture_run(campaign)
    fingerprint = research_run_payload_fingerprint(run, campaign.aggregate_revision, campaign.owner_id)
    session = RunSession(campaign)
    session.audit_after_lock = {
        "owner_id": campaign.owner_id, "idempotency_key": "race-key", "operation": "record_research_run",
        "target_id": run.id, "target_type": NodeType.RESEARCH_RUN.value, "revision": 0,
        "payload_fingerprint": fingerprint,
    }

    receipt = writer(session).record_research_run(
        run, expected_campaign_revision=campaign.aggregate_revision, idempotency_key="race-key",
    )

    assert receipt.replayed
    assert sum("MATCH (a:FounderGraphAudit" in query for query, _ in session.calls) == 2
    assert not session.runs and session.history_count == 0 and not session.links


@pytest.mark.parametrize("receipt_state", ["matching", "conflicting", "missing", "lookup_failure"])
def test_unknown_commit_uses_safe_readonly_receipt_recovery(receipt_state):
    campaign = fixture_campaign()
    run = fixture_run(campaign)
    session = RunSession(campaign)
    session.fail_after_callback = True
    session.drop_receipt = receipt_state == "missing"
    session.change_receipt = receipt_state == "conflicting"
    session.fail_recovery_read = receipt_state == "lookup_failure"
    service = writer(session)

    if receipt_state == "conflicting":
        with pytest.raises(IdempotencyConflictError):
            service.record_research_run(run, expected_campaign_revision=campaign.aggregate_revision, idempotency_key="uncertain-key")
    elif receipt_state in {"missing", "lookup_failure"}:
        with pytest.raises(Neo4jUnavailableError) as error:
            service.record_research_run(run, expected_campaign_revision=campaign.aggregate_revision, idempotency_key="uncertain-key")
        assert str(error.value) == "Neo4j operation failed"
        assert "private synthetic driver diagnostic" not in str(error.value)
    else:
        receipt = service.record_research_run(run, expected_campaign_revision=campaign.aggregate_revision, idempotency_key="uncertain-key")
        assert receipt.replayed

    assert session.closed
    assert sum("CREATE (r:ResearchRun" in query for query, _ in session.calls) == 1
    if receipt_state == "missing":
        assert session.audit is None
