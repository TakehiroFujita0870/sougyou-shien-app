"""Offline, Docker-free contracts for Founder Graph export backups."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "founder-graph" / "verify_export_backup.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("founder_graph_export_backup", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export_payload(*, owner: str | None = None, relation: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "founder-graph-export-v1",
        "nodes": [
            {
                "id": "idea-1",
                "kind": "idea",
                "fields": {"title": "名刺管理の先の体験"},
                "provenance_ids": ["source-1"],
            },
            {
                "id": "person-1",
                "kind": "person_asset",
                "fields": {"display_name": "Founder"},
                "provenance_ids": [],
            },
        ],
        "provenance_ids": ["source-1"],
        "next_cursor": None,
        "omitted_count": 0,
    }
    if owner is not None:
        payload["owner_id"] = owner
    if relation:
        payload["relations"] = [
            {"id": "rel-1", "kind": "knows", "source_id": "person-1", "target_id": "idea-1"}
        ]
    return payload


def write_export(root: Path, payload: dict[str, object]) -> Path:
    path = root / "export.json"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(encoded)
    return path


def test_build_and_verify_manifest_is_deterministic_and_owner_scoped(tmp_path: Path) -> None:
    helper = load_helper()
    write_export(tmp_path, export_payload())

    first = helper.build_manifest(tmp_path, "export.json", "owner-1")
    second = helper.build_manifest(tmp_path, "export.json", "owner-1")

    assert first == second
    assert first == {
        "manifest_schema_version": "founder-graph-backup-manifest-v1",
        "export_schema_version": "founder-graph-export-v1",
        "owner_id": "owner-1",
        "export_path": "export.json",
        "byte_count": first["byte_count"],
        "sha256": first["sha256"],
        "node_count": 2,
        "relation_count": 1,
    }
    manifest_path = helper.write_manifest(tmp_path, "manifest.json", first)
    result = helper.dry_run_restore(tmp_path, manifest_path, expected_owner="owner-1")
    assert result["status"] == "verified"
    assert result["owner_id"] == "owner-1"
    assert result["node_count"] == 2
    assert result["relation_count"] == 1
    assert result["verified_path"] == "export.json"


def test_export_envelope_owner_is_checked_when_present(tmp_path: Path) -> None:
    helper = load_helper()
    write_export(tmp_path, export_payload(owner="owner-1"))
    manifest = helper.build_manifest(tmp_path, "export.json", "owner-1")
    assert manifest["owner_id"] == "owner-1"
    with pytest.raises(helper.ContractError, match="owner"):
        helper.build_manifest(tmp_path, "export.json", "owner-2")


def test_manifest_rejects_owner_hash_schema_and_count_changes(tmp_path: Path) -> None:
    helper = load_helper()
    export_path = write_export(tmp_path, export_payload())
    manifest = helper.build_manifest(tmp_path, "export.json", "owner-1")
    manifest_path = helper.write_manifest(tmp_path, "manifest.json", manifest)

    with pytest.raises(helper.ContractError, match="owner"):
        helper.verify_backup(tmp_path, manifest_path, expected_owner="owner-2")

    export_path.write_bytes(export_path.read_bytes() + b" ")
    with pytest.raises(helper.ContractError, match="canonical|hash|byte"):
        helper.verify_backup(tmp_path, manifest_path, expected_owner="owner-1")

    export_path.write_bytes(
        json.dumps(
            {**export_payload(), "schema_version": "wrong-schema"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    with pytest.raises(helper.ContractError, match="schema|hash|byte"):
        helper.verify_backup(tmp_path, manifest_path, expected_owner="owner-1")


@pytest.mark.parametrize("export_path", ["../export.json", "/tmp/export.json", "folder\\export.json", ""])
def test_manifest_rejects_absolute_traversal_and_non_posix_export_paths(tmp_path: Path, export_path: str) -> None:
    helper = load_helper()
    write_export(tmp_path, export_payload())
    with pytest.raises(helper.ContractError):
        helper.build_manifest(tmp_path, export_path, "owner-1")


def test_manifest_rejects_forbidden_export_fields_and_duplicate_ids(tmp_path: Path) -> None:
    helper = load_helper()
    forbidden = export_payload()
    forbidden["nodes"] = [
        {
            "id": "idea-1",
            "kind": "idea",
            "fields": {"private_notes": "do not export"},
            "provenance_ids": [],
        }
    ]
    write_export(tmp_path, forbidden)
    with pytest.raises(helper.ContractError, match="forbidden"):
        helper.build_manifest(tmp_path, "export.json", "owner-1")

    duplicate = export_payload()
    duplicate["nodes"] = [duplicate["nodes"][0], duplicate["nodes"][0]]  # type: ignore[index]
    write_export(tmp_path, duplicate)
    with pytest.raises(helper.ContractError, match="unique"):
        helper.build_manifest(tmp_path, "export.json", "owner-1")


def test_dry_run_does_not_change_files_and_rejects_symlink_export(tmp_path: Path) -> None:
    helper = load_helper()
    write_export(tmp_path, export_payload())
    manifest = helper.build_manifest(tmp_path, "export.json", "owner-1")
    helper.write_manifest(tmp_path, "manifest.json", manifest)
    before = sorted((path.relative_to(tmp_path).as_posix(), path.read_bytes()) for path in tmp_path.iterdir())

    result = helper.dry_run_restore(tmp_path, "manifest.json", expected_owner="owner-1")
    after = sorted((path.relative_to(tmp_path).as_posix(), path.read_bytes()) for path in tmp_path.iterdir())
    assert result["dry_run"] is True
    assert before == after

    link = tmp_path / "export-link.json"
    try:
        link.symlink_to(tmp_path / "export.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")
    symlink_manifest = {**manifest, "export_path": "export-link.json"}
    with pytest.raises(helper.ContractError, match="symlink"):
        helper.verify_backup(tmp_path, symlink_manifest, expected_owner="owner-1")


def test_cli_create_verify_and_dry_run_are_docker_free(tmp_path: Path) -> None:
    helper = load_helper()
    write_export(tmp_path, export_payload())
    create = subprocess.run(
        [sys.executable, str(SCRIPT), "create", "--root", str(tmp_path), "--export", "export.json", "--owner-id", "owner-1", "--output", "manifest.json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 0, create.stdout + create.stderr
    verify = subprocess.run(
        [sys.executable, str(SCRIPT), "dry-run", "--root", str(tmp_path), "--manifest", "manifest.json", "--owner-id", "owner-1", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert json.loads(verify.stdout)["status"] == "verified"
    assert "docker" not in (create.stdout + create.stderr + verify.stdout + verify.stderr).lower()
    assert helper.load_manifest(tmp_path / "manifest.json")["owner_id"] == "owner-1"
