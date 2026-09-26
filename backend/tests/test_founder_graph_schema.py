from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dots.founder_graph import Evidence, Idea, NodeType, PersonAsset, RelationType, Relationship
from dots.founder_graph_schema import (
    migration_queries,
    migration_plan,
    rollback_queries,
    schema_manifest,
    validate_import_batch,
)


ROOT = Path(__file__).resolve().parents[2]


def _relation(person: PersonAsset, idea: Idea, evidence: Evidence) -> Relationship:
    return Relationship(
        owner_id="owner-1",
        source_id=person.id,
        source_kind=NodeType.PERSON,
        source_owner_id="owner-1",
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target_id=idea.id,
        target_kind=NodeType.IDEA,
        target_owner_id="owner-1",
        evidence_ids=(evidence.id,),
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )


def test_schema_plan_is_idempotent_and_versioned() -> None:
    assert migration_plan(0, 1) == migration_plan(0, 1)
    assert migration_plan(1, 1) == ()
    assert migration_plan(1, 2)
    assert all("IF NOT EXISTS" in query for query in migration_queries())
    assert schema_manifest()["version"] == 4
    assert schema_manifest()["rollback_query_count"] == 16


def test_schema_v4_adds_only_internal_assertion_family_lock_uniqueness() -> None:
    v4_queries = migration_queries(3, 4)
    rollback = rollback_queries(4, 3)

    assert schema_manifest()["version"] == 4
    assert len(v4_queries) == 1
    assert "FounderGraphAssertionFamilyLock" in v4_queries[0]
    assert "(node.owner_id, node.family_key) IS UNIQUE" in v4_queries[0]
    assert "IF NOT EXISTS" in v4_queries[0]
    assert "CREATE INDEX" not in v4_queries[0]
    assert len(rollback) == 1
    assert rollback[0] == "DROP CONSTRAINT dots_assertion_family_lock_owner_key IF EXISTS"
    assert "DELETE" not in rollback[0]
    assert "FounderGraphAssertionFamilyLock" not in " ".join(migration_queries(0, 3))
    assert all(node_type.value != "founder_graph_assertion_family_lock" for node_type in NodeType)


def test_schema_v2_adds_only_new_labels_and_rollback_keeps_data_contract() -> None:
    v1_queries = migration_queries(0, 1)
    v2_queries = migration_queries(1, 2)

    assert v1_queries
    assert all(label not in " ".join(v1_queries) for label in ("EntityRevision", "RelationAssertion", "ContentChunk", "Facet"))
    assert all("IF NOT EXISTS" in query for query in v2_queries)
    assert all(label in " ".join(v2_queries) for label in ("EntityRevision", "RelationAssertion", "ContentChunk", "Facet"))

    rollback = rollback_queries(2, 1)
    assert len(rollback) == 12
    assert all(query.startswith("DROP ") and "IF EXISTS" in query for query in rollback)
    assert all(label in " ".join(rollback) for label in ("entityrevision", "relationassertion", "contentchunk", "facet"))
    assert rollback_queries(1, 1) == ()


def test_import_batch_rejects_duplicate_ids_and_invalid_relation() -> None:
    person = PersonAsset(owner_id="owner-1", id="person-1", name="Person")
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea")
    evidence = Evidence(owner_id="owner-1", id="evidence-1", material_id="material-1", claim_id="claim-1")
    relation = _relation(person, idea, evidence)
    assert validate_import_batch((person, idea, evidence), (relation,)) == {"nodes": 3, "relationships": 1}
    with pytest.raises(ValueError, match="duplicate"):
        validate_import_batch((person, person), ())
    with pytest.raises(ValueError, match="missing"):
        validate_import_batch((person, evidence), (relation,))


def test_schema_script_is_docker_free_and_prints_plan() -> None:
    script = ROOT / "scripts" / "founder-graph" / "migrate_schema.py"
    result = subprocess.run(
        [sys.executable, str(script), "--validate-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert '"validate_only": true' in result.stdout
    assert "docker" not in result.stdout.lower()
