"""Opt-in real-Neo4j proof for RelationAssertion transaction semantics.

Default execution is Docker-free. The opt-in path is synthetic-only and uses
an exact-UUID disposable Neo4j instance owned by the shared safe harness.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import os
from threading import Event
import time
from uuid import uuid4

import pytest

from dots.founder_graph import (
    Claim,
    Evidence,
    NodeType,
    RelationAssertion,
    RelationType,
    RelationshipStatus,
)
from dots.founder_graph_neo4j import Neo4jGraphGateway, Neo4jUnavailableError, _node_properties
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService
from dots.founder_graph_write import RevisionConflictError
from neo4j_disposable_harness import (
    IMAGE,
    DisposableNeo4j,
    HarnessError,
    fixed_docker,
    is_opted_in,
)
from neo4j_revision_lock_transactions import TaggedDriver, is_blocked_status


OPT_IN = "DOTS_NEO4J_RELATION_ASSERTION_REAL"
ROLE = "neo4j-relation-assertion"
NAME_PREFIX = "dots-relassert"


def _poll_until_ready(driver, timeout_seconds: float = 90) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            driver.verify_connectivity()
            with driver.session(database="neo4j") as session:
                if session.run("RETURN 1 AS ready").single()["ready"] == 1:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def _fixture(driver, owner: str, suffix: str) -> tuple[str, str, str]:
    source = Claim(owner_id=owner, id=f"claim-source-{suffix}", text="Synthetic source claim")
    target = Claim(owner_id=owner, id=f"claim-target-{suffix}", text="Synthetic target claim")
    evidence = Evidence(
        owner_id=owner, id=f"evidence-{suffix}", material_id=f"material-{suffix}",
        claim_id=source.id, excerpt="Synthetic evidence only.",
    )
    with driver.session(database="neo4j") as session:
        for node, label in ((source, "Claim"), (target, "Claim"), (evidence, "Evidence")):
            session.run(
                f"CREATE (n:{label}) SET n = $properties",
                properties=_node_properties(node),
            ).consume()
    return source.id, target.id, evidence.id


def _assertion(
    owner: str, source_id: str, target_id: str, evidence_id: str, *,
    suffix: str, family: str,
) -> RelationAssertion:
    return RelationAssertion(
        owner_id=owner, id=f"assertion-{suffix}", source_id=source_id,
        source_kind=NodeType.CLAIM, target_id=target_id, target_kind=NodeType.CLAIM,
        predicate=RelationType.DERIVED_FROM, assertion_family_id=family,
        status=RelationshipStatus.CONFIRMED, evidence_ids=(evidence_id,),
    )


class _PausedRelationGateway(Neo4jGraphGateway):
    def __init__(self, *args, acquired=None, release=None, requested=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._acquired = acquired
        self._release = release
        self._requested = requested

    def _lock_assertion_families_tx(self, tx, family_ids):
        if self._requested is not None:
            self._requested.set()
        super()._lock_assertion_families_tx(tx, family_ids)
        if self._acquired is not None and self._release is not None:
            self._acquired.set()
            if not self._release.wait(15):
                raise TimeoutError("test did not release the held RelationAssertion family lock")


class _ObservedAuditTransaction:
    def __init__(self, transaction, attempted: Event):
        self._transaction = transaction
        self._attempted = attempted

    def run(self, query, *args, **kwargs):
        if "CREATE (a:FounderGraphAudit" in query:
            self._attempted.set()
        return self._transaction.run(query, *args, **kwargs)


class _AuditObservedGateway(Neo4jGraphGateway):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_query_attempted = Event()

    def _save_relation_assertion_tx(self, tx, *args, **kwargs):
        return super()._save_relation_assertion_tx(
            _ObservedAuditTransaction(tx, self.audit_query_attempted), *args, **kwargs,
        )


def _tagged_relation_gateway(driver, run_id, writer, owner, **kwargs):
    return _PausedRelationGateway(
        TaggedDriver(driver, run_id, writer, purpose="relation_assertion"), owner, **kwargs,
    )


def _assert_blocked_relation_writer(driver, *, run_id: str) -> bool:
    with driver.session(database="neo4j") as session:
        rows = list(session.run(
            "SHOW TRANSACTIONS YIELD metaData, currentQuery, status, resourceInformation "
            "WHERE metaData.dots_relation_assertion_run = $run_id "
            "AND metaData.dots_relation_assertion_writer = 'writer-b' "
            "RETURN status, currentQuery, resourceInformation",
            run_id=run_id,
        ))
    return any(
        is_blocked_status(row.get("status"))
        and "_dots_relation_write_lock" in str(row.get("currentQuery") or "")
        and bool(row.get("resourceInformation"))
        for row in rows
    )


def _snapshot(driver, owner: str) -> dict[str, tuple[tuple[object, ...], ...]]:
    with driver.session(database="neo4j") as session:
        assertions = tuple(tuple(row.values()) for row in session.run(
            "MATCH (n:RelationAssertion {owner_id:$owner}) "
            "RETURN n.id AS id, n.assertion_family_id AS family, n.revision AS revision, "
            "n.status AS status, n.supersedes_id AS supersedes_id, n.payload_json AS payload "
            "ORDER BY id",
            owner=owner,
        ))
        edges = tuple(tuple(row.values()) for row in session.run(
            "MATCH (a:RelationAssertion {owner_id:$owner})-[r]->(b) "
            "RETURN a.id AS assertion_id, type(r) AS relation, b.id AS target_id, "
            "b.owner_id AS target_owner ORDER BY assertion_id, relation, target_id",
            owner=owner,
        ))
        audits = tuple(tuple(row.values()) for row in session.run(
            "MATCH (a:FounderGraphAudit {owner_id:$owner}) "
            "RETURN a.id AS id, a.idempotency_key AS key, a.operation AS operation, "
            "a.target_id AS target, a.target_type AS target_type, a.revision AS revision, "
            "a.payload_fingerprint AS fingerprint ORDER BY key",
            owner=owner,
        ))
        family_locks = tuple(tuple(row.values()) for row in session.run(
            "MATCH (l:FounderGraphAssertionFamilyLock {owner_id:$owner}) "
            "RETURN l.family_key AS family_key, l._dots_relation_write_lock AS active_lock "
            "ORDER BY family_key",
            owner=owner,
        ))
    receipt_projection = tuple(row for row in audits if row[2] == "save_relation_assertion")
    return {
        "assertions": assertions,
        "structural_edges": edges,
        "audits": audits,
        "receipts": receipt_projection,
        "family_locks": family_locks,
    }


def _install_audit_id_collision(driver, owner: str, key: str) -> str:
    audit_id = f"audit_{sha256(f'{owner}:{key}'.encode()).hexdigest()[:32]}"
    with driver.session(database="neo4j") as session:
        session.run(
            "CREATE (:FounderGraphAudit {id:$id, owner_id:$owner, idempotency_key:$sentinel})",
            id=audit_id, owner=owner, sentinel=f"sentinel-{uuid4().hex}",
        ).consume()
    return audit_id


def _remove_audit_id_collision(driver, owner: str, audit_id: str) -> None:
    with driver.session(database="neo4j") as session:
        deleted = session.run(
            "MATCH (a:FounderGraphAudit {id:$id, owner_id:$owner}) "
            "WHERE a.operation IS NULL DETACH DELETE a RETURN count(*) AS deleted",
            id=audit_id, owner=owner,
        ).single()["deleted"]
    assert deleted == 1


def test_real_neo4j_relation_assertion_atomicity_and_family_races():
    if not is_opted_in(os.environ, OPT_IN):
        pytest.skip(f"set {OPT_IN}=1 only after independent review and explicit run approval")
    docker = fixed_docker()
    if docker is None:
        pytest.skip("supported Docker CLI is unavailable; no container created")
    try:
        docker.call("version", "--format", "{{.Server.Version}}")
        docker.call("image", "inspect", IMAGE)
    except HarnessError:
        pytest.skip("Docker daemon or preloaded Neo4j image unavailable; no pull attempted")

    run_id = uuid4().hex
    disposable = DisposableNeo4j(docker, run_id, role=ROLE, name_prefix=NAME_PREFIX)
    driver = None
    try:
        port = disposable.start()
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(f"bolt://127.0.0.1:{port}", auth=None)
        assert _poll_until_ready(driver), "disposable Neo4j did not pass bounded readiness queries"
        owner = f"owner-{run_id[:12]}"
        source_id, target_id, evidence_id = _fixture(driver, owner, run_id[:12])
        gateway = Neo4jGraphGateway(driver, owner)
        gateway.migrate()
        writer = Neo4jGraphWriteService(gateway)

        first = _assertion(owner, source_id, target_id, evidence_id,
                           suffix=f"first-{run_id[:12]}", family=f"family-{run_id[:12]}")
        first_receipt = writer.save_relation_assertion(
            first, expected_family_revision=None, idempotency_key=f"initial-{run_id}",
        )
        assert first_receipt.revision == 1 and not first_receipt.replayed
        after_first = _snapshot(driver, owner)
        assert len(after_first["assertions"]) == 1
        assert len(after_first["structural_edges"]) == 3
        assert len(after_first["audits"]) == len(after_first["receipts"]) == 1

        replay = writer.save_relation_assertion(
            first, expected_family_revision=None, idempotency_key=f"initial-{run_id}",
        )
        assert replay.replayed and replay.target_id == first.id and _snapshot(driver, owner) == after_first

        successor = replace(
            first, id=f"assertion-successor-{run_id[:12]}", revision=2, supersedes_id=first.id,
        )
        correction = writer.save_relation_assertion(
            successor, expected_family_revision=1, idempotency_key=f"correction-{run_id}",
        )
        assert correction.revision == 2 and not correction.replayed
        after_correction = _snapshot(driver, owner)
        assert len(after_correction["assertions"]) == 2
        assert len(after_correction["structural_edges"]) == 7
        assert len(after_correction["audits"]) == len(after_correction["receipts"]) == 2
        assert any(row[0] == first.id and row[3] == RelationshipStatus.SUPERSEDED.value
                   for row in after_correction["assertions"])
        assert any(row[1] == "SUPERSEDES" and row[2] == first.id
                   for row in after_correction["structural_edges"])

        race_a = _assertion(owner, source_id, target_id, evidence_id,
                            suffix=f"race-a-{run_id[:10]}", family=f"race-family-{run_id[:12]}")
        race_b = _assertion(owner, source_id, target_id, evidence_id,
                            suffix=f"race-b-{run_id[:10]}", family=f"race-family-{run_id[:12]}")
        run_tag = uuid4().hex
        acquired, release, requested = Event(), Event(), Event()
        first_writer = _tagged_relation_gateway(
            driver, run_tag, "writer-a", owner, acquired=acquired, release=release,
        )
        second_writer = _tagged_relation_gateway(
            driver, run_tag, "writer-b", owner, requested=requested,
        )
        race_keys = (f"race-a-{run_id}", f"race-b-{run_id}")

        def race_write(race_gateway, assertion: RelationAssertion, key: str):
            return race_gateway.save_relation_assertion(
                assertion, expected_family_revision=None, idempotency_key=key,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(race_write, first_writer, race_a, race_keys[0])
            try:
                assert acquired.wait(15), "writer A did not acquire the RelationAssertion family lock"
                second_future = pool.submit(race_write, second_writer, race_b, race_keys[1])
                assert requested.wait(5), "writer B did not reach the RelationAssertion family lock"
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and not _assert_blocked_relation_writer(driver, run_id=run_tag):
                    Event().wait(0.1)
                assert _assert_blocked_relation_writer(driver, run_id=run_tag), (
                    "Neo4j did not report writer B blocked on the RelationAssertion family lock"
                )
            finally:
                release.set()
            first_receipt = first_future.result(timeout=20)
            with pytest.raises(RevisionConflictError):
                second_future.result(timeout=20)
        assert first_receipt.target_id == race_a.id and first_receipt.revision == 1
        after_race = _snapshot(driver, owner)
        race_assertions = tuple(row for row in after_race["assertions"] if row[1] == race_a.assertion_family_id)
        race_audits = tuple(row for row in after_race["audits"] if row[1] in set(race_keys))
        assert len(race_assertions) == len(race_audits) == 1
        assert len(after_race["receipts"]) == len(after_correction["receipts"]) + 1

        late_key = f"late-audit-{run_id}"
        late = _assertion(owner, source_id, target_id, evidence_id,
                          suffix=f"late-{run_id[:12]}", family=f"late-family-{run_id[:12]}")
        late_gateway = _AuditObservedGateway(driver, owner)
        late_writer = Neo4jGraphWriteService(late_gateway)
        collision_id = _install_audit_id_collision(driver, owner, late_key)
        before_late_failure = _snapshot(driver, owner)
        try:
            with pytest.raises(Neo4jUnavailableError) as failure:
                late_writer.save_relation_assertion(
                    late, expected_family_revision=None, idempotency_key=late_key,
                )
            assert late_gateway.audit_query_attempted.is_set()
            assert isinstance(failure.value, Neo4jUnavailableError)
            assert _snapshot(driver, owner) == before_late_failure
        finally:
            _remove_audit_id_collision(driver, owner, collision_id)

        retried = late_writer.save_relation_assertion(
            late, expected_family_revision=None, idempotency_key=late_key,
        )
        assert retried.revision == 1 and not retried.replayed
        after_retry = _snapshot(driver, owner)
        assert len(after_retry["assertions"]) == len(before_late_failure["assertions"]) + 1
        assert len(after_retry["structural_edges"]) == len(before_late_failure["structural_edges"]) + 3
        assert len(after_retry["receipts"]) == len(before_late_failure["receipts"]) + 1
        assert not any(row[1] for row in after_retry["family_locks"])
    finally:
        try:
            if driver is not None:
                driver.close()
        finally:
            disposable.close()
