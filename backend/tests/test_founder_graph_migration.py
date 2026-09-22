from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from dots.founder_graph_migration import build_schema_v1_spike_fixture, convert_schema_v1_payload


ROOT = Path(__file__).resolve().parents[2]


def test_synthetic_fixture_is_previewable_without_blocking_findings() -> None:
    payload = build_schema_v1_spike_fixture()
    preview = convert_schema_v1_payload(payload)

    assert len([node for node in payload["nodes"] if node["node_type"] == "research_material"]) == 20
    assert len([node for node in payload["nodes"] if node["node_type"] == "person"]) == 10
    assert preview.is_ready_for_write
    assert preview.counts == {
        "input_nodes": 32,
        "input_relationships": 2,
        "anchors": 31,
        "revisions": 32,
        "assertions": 2,
        "duplicate_legacy_ids": 0,
        "missing_fields": 0,
        "missing_evidence": 0,
        "duplicate_anchors": 0,
        "orphan_relations": 0,
        "orphan_references": 0,
        "owner_boundary_violations": 0,
        "blocking_findings": 0,
    }
    assert len(preview.rollback_assumptions) == 5
    assert len(preview.parity_checks) == 5
    assert preview.converted["assertions"][0]["source_id"].startswith("anchor_")


def test_preview_reports_missing_fields_duplicates_orphans_and_owner_crossing() -> None:
    payload = deepcopy(build_schema_v1_spike_fixture())
    idea = next(node for node in payload["nodes"] if node["id"] == "idea-01")
    del idea["title"]
    payload["nodes"].append(
        {
            "id": "card-duplicate",
            "node_type": "person",
            "owner_id": "synthetic-owner",
            "name": "合成人物の重複",
            "stable_key": "synthetic-person-01",
            "revision": 1,
        }
    )
    payload["relationships"].extend(
        [
            {
                "id": "relation-orphan",
                "owner_id": "synthetic-owner",
                "source_id": "missing-source",
                "target_id": "idea-01",
                "relation": "CAN_CONTRIBUTE_TO",
                "evidence_ids": ["missing-evidence"],
            },
            {
                "id": "relation-cross-owner",
                "owner_id": "another-owner",
                "source_id": "card-01",
                "target_id": "idea-01",
                "relation": "CAN_CONTRIBUTE_TO",
                "evidence_ids": [],
            },
        ]
    )

    preview = convert_schema_v1_payload(payload)
    categories = {finding.category for finding in preview.blocking_findings}
    assert {"missing_fields", "duplicate_anchors", "orphan_relations", "owner_boundary"} <= categories
    assert preview.counts["missing_fields"] >= 1
    assert preview.counts["duplicate_anchors"] >= 1
    assert preview.counts["orphan_relations"] >= 2
    assert preview.counts["owner_boundary_violations"] == 1
    assert not preview.is_ready_for_write


def test_revisions_share_one_anchor_and_select_the_latest_revision() -> None:
    payload = {
        "schema_version": 1,
        "owner_id": "owner-1",
        "nodes": [
            {
                "id": "idea-old",
                "node_type": "idea",
                "owner_id": "owner-1",
                "stable_key": "idea-stable-1",
                "revision": 1,
                "title": "旧タイトル",
            },
            {
                "id": "idea-new",
                "node_type": "idea",
                "owner_id": "owner-1",
                "stable_key": "idea-stable-1",
                "revision": 2,
                "title": "新タイトル",
            },
        ],
        "relationships": [],
    }

    preview = convert_schema_v1_payload(payload)
    assert preview.is_ready_for_write
    assert len(preview.converted["anchors"]) == 1
    assert len(preview.converted["revisions"]) == 2
    assert preview.converted["anchors"][0]["current_revision_id"].endswith("_r2")
    assert preview.counts["duplicate_anchors"] == 0


def test_preview_does_not_mutate_input_and_has_stable_hash() -> None:
    payload = build_schema_v1_spike_fixture()
    before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    first = convert_schema_v1_payload(payload)
    second = convert_schema_v1_payload(payload)

    assert json.dumps(payload, ensure_ascii=False, sort_keys=True) == before
    assert first.input_sha256 == second.input_sha256
    assert first.as_dict() == second.as_dict()


def test_cli_default_fixture_is_strict_and_docker_free() -> None:
    script = ROOT / "scripts" / "founder-graph" / "schema_v2_spike.py"
    result = subprocess.run(
        [sys.executable, str(script), "--strict", "--summary"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ready=True" in result.stdout
    assert "nodes=32" in result.stdout
    assert "docker" not in result.stdout.lower()
