"""Opt-in real Neo4j race proof; default tests never contact Docker."""

from __future__ import annotations

from dataclasses import replace
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping
from uuid import uuid4

import pytest

from dots.founder_graph import EgressPolicy, MaterialKind, ResearchCampaign, Source, SourceRevision
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_revision
from dots.founder_graph_write import InMemoryGraphWriteService, RevisionConflictError, validate_capture_source
from neo4j_disposable_harness import (
    IMAGE, OPT_IN, DisposableNeo4j, HarnessError, fixed_docker, is_opted_in,
)
from neo4j_revision_lock_transactions import TaggedDriver, is_blocked_status


class _PausedGateway(Neo4jGraphGateway):
    def __init__(self, *args: Any, acquired=None, release=None, requested=None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._acquired, self._release, self._requested = acquired, release, requested

    def _lock_revisioned_node_tx(self, tx: Any, label: str, node_id: str) -> Any | None:
        if self._requested is not None:
            self._requested.set()
        row = super()._lock_revisioned_node_tx(tx, label, node_id)
        if row is not None and self._acquired is not None and self._release is not None:
            self._acquired.set()
            if not self._release.wait(15):
                raise TimeoutError("test did not release paused lock holder")
        return row


def _tagged_gateway(driver: Any, run_id: str, writer: str, owner: str, **kwargs: Any) -> _PausedGateway:
    """Build a race gateway through the same path exercised by the real test."""
    return _PausedGateway(TaggedDriver(driver, run_id, writer), owner, **kwargs)


def test_race_gateway_factory_uses_tagged_driver_transaction_path():
    class Transaction:
        def __init__(self):
            self.committed = False
        def commit(self):
            self.committed = True
        def rollback(self):
            raise AssertionError("successful fake write must not roll back")

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
        def session(self, **_kwargs):
            return self.value

    driver = Driver()
    gateway = _tagged_gateway(driver, "b" * 32, "writer-a", "owner-synthetic")
    with gateway._session() as session:
        assert gateway._execute_write(session, lambda _tx: "written") == "written"
    assert driver.value.metadata == {
        "dots_revision_lock_run": "b" * 32,
        "dots_revision_lock_writer": "writer-a",
    }
    assert driver.value.tx.committed


def _assert_blocked_writer(driver: Any, *, run_id: str) -> bool:
    with driver.session(database="neo4j") as session:
        rows = list(session.run(
            "SHOW TRANSACTIONS YIELD metaData, currentQuery, status, resourceInformation "
            "WHERE metaData.dots_revision_lock_run = $run_id "
            "AND metaData.dots_revision_lock_writer = 'writer-b' "
            "RETURN status, currentQuery, resourceInformation",
            run_id=run_id,
        ))
    return any(
        is_blocked_status(row.get("status"))
        and "_dots_revision_write_lock" in str(row.get("currentQuery") or "")
        and bool(row.get("resourceInformation"))
        for row in rows
    )


def _stored_snapshot(driver: Any, *, owner: str, node_id: str, keys: tuple[str, str], source: bool) -> Mapping[str, Any]:
    with driver.session(database="neo4j") as session:
        if source:
            row = session.run(
                "MATCH (n:Source {id: $id, owner_id: $owner}) "
                "OPTIONAL MATCH (n)-[edge:CURRENT_SOURCE_REVISION]->(r:SourceRevision {owner_id: $owner}) "
                "RETURN n.payload_json AS payload_json, n.current_revision_id AS current_revision_id, "
                "collect(r.id) AS current_ids, n._dots_revision_write_lock AS lock_value",
                id=node_id, owner=owner,
            ).single()
        else:
            row = session.run(
                "MATCH (n:ResearchCampaign {id: $id, owner_id: $owner}) "
                "RETURN n.payload_json AS payload_json, n.aggregate_revision AS current_revision_id, "
                "n._dots_revision_write_lock AS lock_value",
                id=node_id, owner=owner,
            ).single()
        history = session.run(
            "MATCH (h:FounderGraphHistory {owner_id: $owner, target_id: $id}) "
            "RETURN count(h) AS count, collect(h.revision) AS revisions",
            owner=owner, id=node_id,
        ).single()
        audits = session.run(
            "MATCH (a:FounderGraphAudit {owner_id: $owner, target_id: $id}) "
            "WHERE a.operation = 'put_node' AND a.idempotency_key IN $keys "
            "RETURN collect(a.idempotency_key) AS keys",
            owner=owner, id=node_id, keys=list(keys),
        ).single()
    return {
        "payload": json.loads(row["payload_json"]),
        "current_revision_id": row["current_revision_id"],
        "current_ids": list(row.get("current_ids", [])) if source else [],
        "lock_value": row.get("lock_value"),
        "history_count": history["count"],
        "history_revisions": list(history["revisions"]),
        "audit_keys": sorted(audits["keys"]),
    }


def _campaign_race_fixture(owner: str, node_id: str):
    baseline = ResearchCampaign(owner_id=owner, id=node_id, purpose="Synthetic race fixture", aggregate_revision=1)
    next_revision = baseline.aggregate_revision + 1
    proposed = (
        replace(baseline, purpose="Writer A synthetic campaign", aggregate_revision=next_revision),
        replace(baseline, purpose="Writer B synthetic campaign", aggregate_revision=next_revision),
    )
    return baseline, proposed, baseline.aggregate_revision


def test_campaign_race_fixture_revision_matches_gateway_expected_value():
    campaign, proposed, expected_revision = _campaign_race_fixture("owner-synthetic", "campaign-synthetic")
    assert _node_revision(campaign) == expected_revision == 1
    assert all(_node_revision(candidate) == expected_revision + 1 == 2 for candidate in proposed)
    for index, candidate in enumerate(proposed):
        writes = InMemoryGraphWriteService(campaign.owner_id)
        writes.put_node(campaign, idempotency_key=f"campaign-base-{index}", expected_revision=0)
        receipt = writes.put_node(
            candidate, idempotency_key=f"campaign-candidate-{index}", expected_revision=expected_revision,
        )
        assert receipt.revision == 2


def _source_race_fixture(owner: str, node_id: str):
    locator = f"https://example.invalid/synthetic/{node_id}"
    revision_one = SourceRevision(
        owner_id=owner, source_id=node_id, id=f"rev1-{node_id}", revision=1,
        content="Synthetic fixture only.", locator=locator, egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    source = Source(
        owner_id=owner, id=node_id, title="Synthetic Source", kind=MaterialKind.WEB,
        locator=locator, revision=1, current_revision_id=revision_one.id,
        egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    revision_two = SourceRevision(
        owner_id=owner, source_id=node_id, id=f"rev2-{node_id}", revision=2,
        supersedes_id=revision_one.id, content="Synthetic revision two.", locator=locator,
        egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    proposed = (
        replace(source, title="Writer A synthetic Source", revision=2, current_revision_id=revision_two.id),
        replace(source, title="Writer B synthetic Source", revision=2, current_revision_id=None),
    )
    return source, revision_one, revision_two, proposed


@pytest.mark.parametrize("writer_index", [0, 1])
def test_source_race_fixture_passes_capture_and_candidate_write_validation(writer_index):
    owner, node_id = "owner-synthetic", f"source-synthetic-{writer_index}"
    source, revision_one, revision_two, proposed = _source_race_fixture(owner, node_id)
    validate_capture_source(source, revision_one, owner)

    writes = InMemoryGraphWriteService(owner)
    writes.capture_source(source, revision_one, idempotency_key=f"source-preflight-{writer_index}")
    writes.put_node(revision_two, idempotency_key=f"revision-preflight-{writer_index}", expected_revision=0)
    receipt = writes.put_node(
        proposed[writer_index], idempotency_key=f"candidate-preflight-{writer_index}", expected_revision=1,
    )
    assert receipt.revision == 2


def _race_one_node(driver: Any, run_id: str, kind: str) -> None:
    owner, node_id = f"owner-{run_id[:10]}-{kind}", f"node-{run_id[:10]}-{kind}"
    base_gateway = Neo4jGraphGateway(driver, owner)
    expected_revision = 1
    if kind == "source":
        source, revision_one, revision_two, proposed = _source_race_fixture(owner, node_id)
        validate_capture_source(source, revision_one, owner)
        base_gateway.capture_source(source, revision_one, idempotency_key=f"setup-capture-{run_id[:16]}")
        base_gateway.put_node(revision_two, idempotency_key=f"setup-revision-{run_id[:16]}", expected_revision=0)
    else:
        campaign, proposed, expected_revision = _campaign_race_fixture(owner, node_id)
        base_gateway.put_node(campaign, idempotency_key=f"setup-campaign-{run_id[:16]}", expected_revision=0)

    acquired, release, requested = threading.Event(), threading.Event(), threading.Event()
    first_gateway = _tagged_gateway(driver, run_id, "writer-a", owner,
                                    acquired=acquired, release=release)
    second_gateway = _tagged_gateway(driver, run_id, "writer-b", owner, requested=requested)
    keys = (f"race-a-{run_id[:16]}", f"race-b-{run_id[:16]}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_gateway.put_node, proposed[0], idempotency_key=keys[0], expected_revision=expected_revision)
        try:
            assert acquired.wait(15), "writer A did not acquire the Neo4j node lock"
            second = pool.submit(second_gateway.put_node, proposed[1], idempotency_key=keys[1], expected_revision=expected_revision)
            assert requested.wait(5), "writer B did not reach the lock request"
            deadline = time.monotonic() + 10
            while not _assert_blocked_writer(driver, run_id=run_id) and time.monotonic() < deadline:
                threading.Event().wait(0.1)
            assert _assert_blocked_writer(driver, run_id=run_id), "Neo4j did not report writer B blocked on the revision lock"
        finally:
            release.set()
        first_receipt = first.result(timeout=20)
        with pytest.raises(RevisionConflictError):
            second.result(timeout=20)

    snapshot = _stored_snapshot(driver, owner=owner, node_id=node_id, keys=keys, source=(kind == "source"))
    assert first_receipt.revision == expected_revision + 1
    assert snapshot["history_count"] == 1 and snapshot["history_revisions"] == [expected_revision]
    assert snapshot["audit_keys"] == [keys[0]] and snapshot["lock_value"] is None
    if kind == "source":
        assert snapshot["payload"]["title"] == proposed[0].title
        assert snapshot["payload"]["current_revision_id"] == proposed[0].current_revision_id
        assert snapshot["current_ids"] == [proposed[0].current_revision_id]
    else:
        assert snapshot["payload"]["purpose"] == proposed[0].purpose
        assert snapshot["payload"]["aggregate_revision"] == expected_revision + 1


def test_real_neo4j_serializes_source_and_campaign_writers_once():
    if not is_opted_in(os.environ):
        pytest.skip(f"set {OPT_IN}=1 only after independent harness review and run approval")
    docker = fixed_docker()
    if docker is None:
        pytest.skip("supported Windows Docker CLI is unavailable; no test container created")
    try:
        docker.call("version", "--format", "{{.Server.Version}}")
        docker.call("image", "inspect", IMAGE)
    except HarnessError:
        pytest.skip("Docker daemon or preloaded Neo4j image is unavailable; no image pull attempted")

    run_id = uuid4().hex
    disposable = DisposableNeo4j(docker, run_id)
    neo4j_driver = None
    try:
        port = disposable.start()
        from neo4j import GraphDatabase

        neo4j_driver = GraphDatabase.driver(f"bolt://127.0.0.1:{port}", auth=None)
        ready_deadline = time.monotonic() + 90
        ready = False
        while time.monotonic() < ready_deadline:
            try:
                neo4j_driver.verify_connectivity()
                with neo4j_driver.session(database="neo4j") as session:
                    ready = session.run("RETURN 1 AS ok").single()["ok"] == 1
                if ready:
                    break
            except Exception:
                threading.Event().wait(0.2)
        assert ready, "disposable Neo4j did not pass bounded Bolt readiness queries"
        gateway = Neo4jGraphGateway(neo4j_driver, f"owner-{run_id[:12]}")
        gateway.migrate()
        _race_one_node(neo4j_driver, run_id, "source")
        _race_one_node(neo4j_driver, run_id, "campaign")
    finally:
        try:
            if neo4j_driver is not None:
                neo4j_driver.close()
        finally:
            disposable.close()
