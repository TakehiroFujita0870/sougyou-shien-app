"""Synthetic Run/Campaign history acceptance; Docker is always opt-in."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from dots.founder_graph import (
    EgressPolicy, Idea, Provenance, ResearchCampaign, ResearchRun, Status,
)
from dots.founder_graph_historical_brief import (
    HistoricalResearchValidationError, validate_historical_researched_brief,
)
from dots.founder_graph_neo4j import (
    Neo4jGraphGateway, Neo4jUnavailableError, _node_properties, _node_revision,
)
from dots.founder_graph_write import (
    GraphWriteError, IdempotencyConflictError, InMemoryGraphWriteService,
)
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from neo4j_disposable_harness import (
    IMAGE, OPT_IN, DisposableNeo4j, HarnessError, fixed_docker, is_opted_in,
)
from neo4j_revision_lock_transactions import TaggedDriver, TaggedSession, is_blocked_status


UTC = timezone.utc


def _provenance(target: str, operation: str, at: datetime, key: str) -> Provenance:
    return Provenance(actor="synthetic-test", operation=operation, target_id=target,
                      occurred_at=at, idempotency_key=key)


def _campaign(owner: str, campaign_id: str, idea_id: str, *, budget: int = 3):
    now = datetime.now(UTC)
    created = now - timedelta(minutes=3)
    pending = ResearchCampaign(
        id=campaign_id, owner_id=owner, purpose="Synthetic bounded research",
        scope={"target_ids": [idea_id]}, questions=("synthetic question",),
        target_idea_id=idea_id, allowed_categories=("idea.summary",),
        external_sources=("https://example.invalid/synthetic",), trial_budget=budget,
        expires_at=now + timedelta(days=2), egress_policy=EgressPolicy.SHAREABLE,
        created_at=created,
        provenance=_provenance(campaign_id, "create_research_campaign", created, f"create:{campaign_id}"),
    )
    approved_at = now - timedelta(minutes=2)
    return pending, pending.approve(
        approved_at=approved_at,
        provenance=_provenance(campaign_id, "approve_research_campaign", approved_at, f"approve:{campaign_id}"),
    )


def _run(campaign: ResearchCampaign, run_id: str, *, start: datetime | None = None,
         finish: datetime | None = None) -> ResearchRun:
    started = start or datetime.now(UTC) - timedelta(minutes=1)
    finished = finish or started + timedelta(seconds=10)
    return ResearchRun(
        id=run_id, owner_id=campaign.owner_id, campaign_id=campaign.id,
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
        input_snapshot={"question": "synthetic only"}, model_snapshot="synthetic-model",
        sources=("synthetic-source",), evidence_ids=("synthetic-evidence",),
        results={"summary": "synthetic result"}, status=Status.COMPLETED,
        egress_policy=campaign.egress_policy, started_at=started, finished_at=finished,
        provenance=_provenance(run_id, "record_research_run", finished, f"run:{run_id}"),
    )


def _brief(idea: Idea, run: ResearchRun, *, created_at: datetime) -> IdeaBriefVersion:
    return IdeaBriefVersion(
        owner_id=idea.owner_id, idea_lineage_root_id=idea.id, based_on_idea_id=idea.id,
        sections=tuple(IdeaBriefSection(index=i, content=f"Synthetic section {i}") for i in range(8)),
        research_run_ids=(run.id,), created_at=created_at,
    )


def _preflight_history_fixture():
    owner, idea_id = "owner-rh-preflight", "idea-rh-preflight"
    idea = Idea(id=idea_id, owner_id=owner, title="Synthetic idea")
    pending, approved = _campaign(owner, "campaign-rh-preflight", idea_id)
    writes = InMemoryGraphWriteService(owner)
    writes.put_node(pending, idempotency_key="preflight-create", expected_revision=0)
    writes.put_node(approved, idempotency_key="preflight-approve", expected_revision=0)
    finished = datetime.now(UTC) - timedelta(seconds=2)
    run = _run(approved, "run-rh-preflight", start=finished - timedelta(seconds=10), finish=finished)
    writes.record_research_run(run, expected_campaign_revision=1, idempotency_key="preflight-run")
    registered = writes.get_node(approved.id)
    brief_created = max(finished + timedelta(seconds=1), registered.provenance.occurred_at + timedelta(seconds=1))
    brief = _brief(idea, run, created_at=brief_created)
    assert registered.run_count == 1 and run.finished_at <= brief.created_at
    history = (pending, approved, registered)
    validate_historical_researched_brief(brief, idea, (writes.get_node(run.id),), history)

    changed_at = max(brief.created_at, registered.provenance.occurred_at) + timedelta(seconds=1)
    changed = registered.change_scope({"target_ids": [idea_id], "synthetic": "changed"}, at=changed_at)
    writes.put_node(changed, idempotency_key="preflight-scope", expected_revision=2)
    reapproved = changed.approve(approved_at=changed_at + timedelta(seconds=1))
    writes.put_node(reapproved, idempotency_key="preflight-reapprove", expected_revision=3)
    revoked_at = changed_at + timedelta(seconds=2)
    revoked = reapproved._transition(
        status=Status.REVOKED, authorized=False, approved_at=None,
        aggregate_revision=reapproved.aggregate_revision + 1,
        provenance=_provenance(approved.id, "revoke_research_campaign", revoked_at, "preflight-revoke"),
    )
    writes.put_node(revoked, idempotency_key="preflight-revoke", expected_revision=4)
    history = (pending, approved, registered, changed, reapproved, revoked)
    assert tuple(item.aggregate_revision for item in history) == tuple(range(6))
    validate_historical_researched_brief(brief, idea, (run,), history)
    after_revoke = replace(run, started_at=revoked_at + timedelta(seconds=1),
                           finished_at=revoked_at + timedelta(seconds=2))
    with pytest.raises(HistoricalResearchValidationError):
        validate_historical_researched_brief(
            _brief(idea, after_revoke, created_at=revoked_at + timedelta(seconds=3)),
            idea, (after_revoke,), history,
        )
    rejected = _run(revoked, "run-after-revoke")
    with pytest.raises(GraphWriteError):
        writes.record_research_run(rejected, expected_campaign_revision=5,
                                   idempotency_key="preflight-after-revoke")


def test_always_on_memory_preflight_uses_production_historical_validator_and_ordered_fixture():
    _preflight_history_fixture()


class _PausedGateway(Neo4jGraphGateway):
    def __init__(self, *args, acquired=None, release=None, requested=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acquired, self.release, self.requested = acquired, release, requested

    def _lock_revisioned_node_tx(self, tx, label, node_id):
        if self.requested:
            self.requested.set()
        row = super()._lock_revisioned_node_tx(tx, label, node_id)
        if row is not None and self.acquired and self.release:
            self.acquired.set()
            if not self.release.wait(15):
                raise TimeoutError("test did not release the paused writer")
        return row


class _ClosingTaggedSession(TaggedSession):
    def close(self):
        self._session.close()


class _ClosingTaggedDriver(TaggedDriver):
    def session(self, *, database):
        metadata = {
            "dots_revision_lock_run": self.run_id,
            "dots_revision_lock_writer": self.writer,
        }
        return _ClosingTaggedSession(self.driver.session(database=database), metadata)


def _tagged_gateway(driver, run_id, writer, owner, **kwargs):
    return _PausedGateway(_ClosingTaggedDriver(driver, run_id, writer), owner, **kwargs)


def _campaign_snapshot(driver, owner, campaign_id, run_id, idempotency_key):
    with driver.session(database="neo4j") as session:
        current = session.run(
            "MATCH (c:ResearchCampaign {id:$id, owner_id:$owner}) "
            "RETURN c.payload_json AS payload", id=campaign_id, owner=owner,
        ).single()
        history = list(session.run(
            "MATCH (h:FounderGraphHistory {target_id:$id, owner_id:$owner}) "
            "RETURN h.revision AS revision, h.payload_json AS payload ORDER BY h.revision",
            id=campaign_id, owner=owner,
        ))
        run = session.run(
            "MATCH (r:ResearchRun {id:$id, owner_id:$owner}) "
            "RETURN count(r) AS count, collect(r.payload_json) AS payloads",
            id=run_id, owner=owner,
        ).single()
        links = session.run(
            "MATCH (:ResearchCampaign {id:$cid, owner_id:$owner})-[:HAS_RUN]->"
            "(:ResearchRun {id:$rid, owner_id:$owner}) RETURN count(*) AS count",
            cid=campaign_id, rid=run_id, owner=owner,
        ).single()["count"]
        audit = session.run(
            "MATCH (a:FounderGraphAudit {owner_id:$owner, idempotency_key:$key}) "
            "RETURN count(a) AS count, collect(a.id) AS ids, collect(a.target_id) AS targets, "
            "collect(a.payload_fingerprint) AS fingerprints",
            owner=owner, key=idempotency_key,
        ).single()
        return (current["payload"] if current else None,
                tuple((row["revision"], row["payload"]) for row in history),
                (run["count"], tuple(run["payloads"])) if run else None, links,
                (audit["count"], tuple(audit["ids"]), tuple(audit["targets"]),
                 tuple(audit["fingerprints"])) if audit else None)


def _campaign_registry(gateway, driver, campaign_id, run_id):
    with driver.session(database="neo4j") as session:
        tx = session.begin_transaction(metadata={"dots_history_read_run": run_id})
        try:
            result = gateway._campaign_authorization_registry_tx(tx, campaign_id)
            tx.commit()
            return result
        except BaseException:
            tx.rollback()
            raise


def _assert_stored_run_matches_fixture(gateway, run):
    record = gateway.fetch_node_record(run.id)
    assert record is not None
    assert record["id"] == run.id
    assert record["owner_id"] == run.owner_id
    assert record["node_type"] == "research_run"
    assert record["revision"] == _node_revision(run)
    assert record["payload_json"] == _node_properties(run)["payload_json"]


def test_real_read_helpers_use_existing_gateway_contract_and_explicit_transaction():
    pending, approved = _campaign("owner-helper", "campaign-helper", "idea-helper")
    run = _run(approved, "run-helper")
    class Transaction:
        def __init__(self):
            self.committed = False
        def commit(self):
            self.committed = True
        def rollback(self):
            raise AssertionError("successful history read must not roll back")
    class Session:
        def __init__(self):
            self.tx = Transaction()
            self.metadata = None
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def begin_transaction(self, *, metadata):
            self.metadata = metadata
            return self.tx
    class Driver:
        def __init__(self):
            self.value = Session()
        def session(self, *, database):
            assert database == "neo4j"
            return self.value
    class Gateway:
        def __init__(self):
            self.seen_tx = None
        def _campaign_authorization_registry_tx(self, tx, campaign_id):
            assert campaign_id == approved.id
            self.seen_tx = tx
            return (pending, approved)
    driver, gateway = Driver(), Gateway()
    assert _campaign_registry(gateway, driver, approved.id, "d" * 32) == (pending, approved)
    assert gateway.seen_tx is driver.value.tx and driver.value.tx.committed
    assert driver.value.metadata == {"dots_history_read_run": "d" * 32}

    class Readback:
        def fetch_node_record(self, node_id):
            assert node_id == run.id
            return {"id": run.id, "owner_id": run.owner_id, "node_type": "research_run",
                    "revision": _node_revision(run), "payload_json": _node_properties(run)["payload_json"]}
    _assert_stored_run_matches_fixture(Readback(), run)


def _assert_blocked(driver, run_id):
    with driver.session(database="neo4j") as session:
        rows = list(session.run(
            "SHOW TRANSACTIONS YIELD metaData, currentQuery, status, resourceInformation "
            "WHERE metaData.dots_revision_lock_run=$run_id "
            "AND metaData.dots_revision_lock_writer='writer-b' "
            "RETURN status, currentQuery, resourceInformation", run_id=run_id,
        ))
    return any(is_blocked_status(row.get("status"))
               and "_dots_revision_write_lock" in str(row.get("currentQuery") or "")
               and bool(row.get("resourceInformation")) for row in rows)


def _verify_audit_constraint(driver):
    with driver.session(database="neo4j") as session:
        constraints = list(session.run(
            "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
            "WHERE name='dots_foundergraphaudit_id' "
            "RETURN name, type, entityType, labelsOrTypes, properties",
        ))
    assert any(row["type"] == "UNIQUENESS" and row["entityType"] == "NODE"
               and row["labelsOrTypes"] == ["FounderGraphAudit"]
               and row["properties"] == ["id"] for row in constraints)


def test_real_neo4j_run_history_and_audit_atomicity():
    # Keep the production-validator and memory-writer fixture preflight in the
    # same test path, including runs selected with `-k real`.
    _preflight_history_fixture()
    if not is_opted_in(os.environ):
        pytest.skip(f"set {OPT_IN}=1 only after independent review and explicit run approval")
    docker = fixed_docker()
    if docker is None:
        pytest.skip("supported Docker CLI is unavailable; no container created")
    try:
        docker.call("version", "--format", "{{.Server.Version}}")
        docker.call("image", "inspect", IMAGE)
    except HarnessError:
        pytest.skip("Docker daemon or preloaded image unavailable; no pull attempted")

    run_id = uuid4().hex
    disposable = DisposableNeo4j(docker, run_id)
    driver = None
    try:
        port = disposable.start()
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(f"bolt://127.0.0.1:{port}", auth=None)
        deadline, ready = time.monotonic() + 90, False
        while time.monotonic() < deadline:
            try:
                driver.verify_connectivity()
                with driver.session(database="neo4j") as session:
                    ready = session.run("RETURN 1 AS ready").single()["ready"] == 1
                if ready:
                    break
            except Exception:
                threading.Event().wait(0.2)
        assert ready, "disposable Neo4j did not pass bounded readiness queries"

        owner, idea_id = f"owner-{run_id[:12]}", f"idea-{run_id[:12]}"
        gateway = Neo4jGraphGateway(driver, owner)
        gateway.migrate()
        _verify_audit_constraint(driver)
        pending, approved = _campaign(owner, f"campaign-{run_id[:12]}", idea_id)
        gateway.put_node(pending, idempotency_key=f"create-{run_id}", expected_revision=0,
                         operation="create_research_campaign")
        gateway.put_node(approved, idempotency_key=f"approve-{run_id}", expected_revision=0,
                         operation="approve_research_campaign")
        finished = datetime.now(UTC) - timedelta(seconds=5)
        run = _run(approved, f"run-{run_id[:12]}", start=finished - timedelta(seconds=10), finish=finished)
        acquired, release, requested = threading.Event(), threading.Event(), threading.Event()
        first = _tagged_gateway(driver, run_id, "writer-a", owner, acquired=acquired, release=release)
        second = _tagged_gateway(driver, run_id, "writer-b", owner, requested=requested)
        key = f"same-{run_id}"
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(first.record_research_run, run,
                                   expected_campaign_revision=1, idempotency_key=key)
            try:
                assert acquired.wait(15), "writer A did not acquire Campaign lock"
                future_b = pool.submit(second.record_research_run, run,
                                       expected_campaign_revision=1, idempotency_key=key)
                assert requested.wait(5), "writer B did not reach lock request"
                timeout = time.monotonic() + 10
                while time.monotonic() < timeout and not _assert_blocked(driver, run_id):
                    threading.Event().wait(0.1)
                assert _assert_blocked(driver, run_id), "writer B was not observed blocked"
            finally:
                release.set()
            receipt_a, receipt_b = future_a.result(timeout=20), future_b.result(timeout=20)
        assert receipt_a.replayed is False and receipt_b.replayed is True
        before_conflict = _campaign_snapshot(driver, owner, approved.id, run.id, key)
        with pytest.raises(IdempotencyConflictError):
            gateway.record_research_run(replace(run, results={"summary": "changed"}),
                                        expected_campaign_revision=1, idempotency_key=key)
        assert before_conflict[2] is not None and before_conflict[2][0] == 1
        assert before_conflict[3] == 1 and before_conflict[4] is not None
        assert before_conflict[4][0] == 1
        assert _campaign_snapshot(driver, owner, approved.id, run.id, key) == before_conflict
        with driver.session(database="neo4j") as session:
            persisted_count = session.run(
                "MATCH (c:ResearchCampaign {id:$cid, owner_id:$owner})-[:HAS_RUN]->(r:ResearchRun) "
                "RETURN count(r) AS count",
                cid=approved.id, owner=owner,
            ).single()["count"]
        assert persisted_count == 1
        _assert_stored_run_matches_fixture(gateway, run)

        registered = _campaign_registry(gateway, driver, approved.id, run_id).campaigns[-1]
        assert registered.aggregate_revision == 2 and registered.run_count == 1
        brief_created = max(finished + timedelta(seconds=1), registered.provenance.occurred_at + timedelta(seconds=1))
        change_at = brief_created + timedelta(seconds=1)
        changed = registered.change_scope({"target_ids": [idea_id], "synthetic": "changed"}, at=change_at)
        gateway.put_node(changed, idempotency_key=f"scope-{run_id}", expected_revision=2,
                         operation="change_campaign_scope")
        reapproved = changed.approve(approved_at=change_at + timedelta(seconds=1))
        gateway.put_node(reapproved, idempotency_key=f"reapprove-{run_id}", expected_revision=3,
                         operation="approve_research_campaign")
        revoked_at = change_at + timedelta(seconds=2)
        revoked = reapproved._transition(
            status=Status.REVOKED, authorized=False, approved_at=None,
            aggregate_revision=reapproved.aggregate_revision + 1,
            provenance=_provenance(approved.id, "revoke_research_campaign", revoked_at, f"revoke-{run_id}"),
        )
        gateway.put_node(revoked, idempotency_key=f"revoke-{run_id}", expected_revision=4,
                         operation="revoke_research_campaign")
        registry = _campaign_registry(gateway, driver, approved.id, run_id)
        assert tuple(item.aggregate_revision for item in registry.campaigns) == tuple(range(6))
        assert registry.campaigns == (pending, approved, registered, changed, reapproved, revoked)
        idea = Idea(id=idea_id, owner_id=owner, title="Synthetic idea")
        brief = _brief(idea, run, created_at=brief_created)
        validate_historical_researched_brief(brief, idea, (run,), registry.campaigns)
        after_revoke = replace(run, started_at=revoked_at + timedelta(seconds=1),
                               finished_at=revoked_at + timedelta(seconds=2))
        with pytest.raises(HistoricalResearchValidationError):
            validate_historical_researched_brief(
                _brief(idea, after_revoke, created_at=revoked_at + timedelta(seconds=3)),
                idea, (after_revoke,), registry.campaigns,
            )
        before_rejected_run = _campaign_snapshot(driver, owner, approved.id, "run-after-revoke", "after-revoke")
        with pytest.raises(GraphWriteError):
            gateway.record_research_run(
                _run(revoked, "run-after-revoke"), expected_campaign_revision=5,
                idempotency_key="after-revoke",
            )
        assert _campaign_snapshot(driver, owner, approved.id, "run-after-revoke", "after-revoke") == before_rejected_run

        # A second Campaign isolates the late Audit uniqueness failure/retry case.
        owner2 = f"owner-fault-{run_id[:10]}"
        fault_pending, fault_approved = _campaign(owner2, f"campaign-fault-{run_id[:10]}", f"idea-fault-{run_id[:10]}")
        fault_gateway = Neo4jGraphGateway(driver, owner2)
        fault_gateway.put_node(fault_pending, idempotency_key=f"fault-create-{run_id}", expected_revision=0,
                               operation="create_research_campaign")
        fault_gateway.put_node(fault_approved, idempotency_key=f"fault-approve-{run_id}", expected_revision=0,
                               operation="approve_research_campaign")
        fault_run = _run(fault_approved, f"run-fault-{run_id[:10]}")
        fault_key = f"fault-run-{run_id}"
        audit_id = "audit_" + hashlib.sha256(f"{owner2}:{fault_key}".encode()).hexdigest()[:32]
        before = _campaign_snapshot(driver, owner2, fault_approved.id, fault_run.id, fault_key)
        before_registry = _campaign_registry(fault_gateway, driver, fault_approved.id, run_id).campaigns
        try:
            with driver.session(database="neo4j") as session:
                session.run(
                    "CREATE (:FounderGraphAudit {id:$id, owner_id:$owner, idempotency_key:$key, "
                    "operation:'synthetic_sentinel'})", id=audit_id, owner=f"foreign-{owner2}", key=f"sentinel-{run_id}",
                ).consume()
            with pytest.raises(Neo4jUnavailableError, match="Neo4j operation failed"):
                fault_gateway.record_research_run(fault_run, expected_campaign_revision=1,
                                                 idempotency_key=fault_key)
            assert _campaign_snapshot(driver, owner2, fault_approved.id, fault_run.id, fault_key) == before
            assert _campaign_registry(fault_gateway, driver, fault_approved.id, run_id).campaigns == before_registry
        finally:
            with driver.session(database="neo4j") as session:
                session.run("MATCH (a:FounderGraphAudit {id:$id, owner_id:$owner}) DELETE a",
                            id=audit_id, owner=f"foreign-{owner2}").consume()
        retry = fault_gateway.record_research_run(fault_run, expected_campaign_revision=1,
                                                  idempotency_key=fault_key)
        assert retry.replayed is False
        fault_registry = _campaign_registry(fault_gateway, driver, fault_approved.id, run_id)
        assert fault_registry.campaigns[:2] == (fault_pending, fault_approved)
        assert fault_registry.campaigns[-1].aggregate_revision == 2
        assert fault_registry.campaigns[-1].run_count == 1
        _assert_stored_run_matches_fixture(fault_gateway, fault_run)
        committed = _campaign_snapshot(driver, owner2, fault_approved.id, fault_run.id, fault_key)
        assert committed[2] is not None and committed[2][0] == 1
        assert committed[3] == 1 and committed[4][0] == 1
    finally:
        try:
            if driver is not None:
                driver.close()
        finally:
            disposable.close()
