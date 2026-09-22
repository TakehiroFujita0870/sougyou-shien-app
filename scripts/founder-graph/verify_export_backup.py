"""Create and verify a deterministic, owner-scoped Founder Graph JSON backup.

This helper is deliberately offline.  It reads an existing safe JSON export,
creates a new manifest without overwriting files, and performs a non-destructive
restore dry-run.  It never starts Docker, opens a socket, calls Neo4j, or
contacts a model/provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


MANIFEST_SCHEMA_VERSION = "founder-graph-backup-manifest-v1"
EXPORT_SCHEMA_VERSION = "founder-graph-export-v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_OWNER_ID_LENGTH = 256
MAX_EXPORT_BYTES = 2_000_000
_MANIFEST_KEYS = frozenset(
    {
        "manifest_schema_version",
        "export_schema_version",
        "owner_id",
        "export_path",
        "byte_count",
        "sha256",
        "node_count",
        "relation_count",
    }
)
_EXPORT_KEYS = frozenset(
    {
        "schema_version",
        "owner_id",
        "nodes",
        "relations",
        "provenance_ids",
        "next_cursor",
        "omitted_count",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {
        "actor",
        "contact",
        "egress_policy",
        "idempotency_key",
        "instruction_artifact_path",
        "instruction_path",
        "local_only",
        "owner_id",
        "path",
        "private_notes",
        "source_path",
        "source_text",
    }
)


class ContractError(ValueError):
    """A safe, user-facing backup contract failure."""


def _text(value: object, label: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    result = value.strip()
    if max_length is not None and len(result) > max_length:
        raise ContractError(f"{label} is too long")
    return result


def _owner(value: object) -> str:
    return _text(value, "owner_id", max_length=MAX_OWNER_ID_LENGTH)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ContractError(f"JSON contains non-finite number: {value}")


def _parse_json(raw: bytes, *, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not valid UTF-8 JSON") from exc


def _is_forbidden_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _FORBIDDEN_KEYS or normalized.replace("_", "") in {
        "instructionartifactpath",
        "instructionpath",
        "privatenotes",
        "sourcetext",
    }


def _walk_safe_json(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{path} contains a non-string key")
            # The export envelope may carry the owner identity at its top
            # level for an explicit owner check.  The same key remains
            # forbidden in nodes, fields, relations, and nested metadata.
            if _is_forbidden_key(key) and not (path == "export" and key == "owner_id"):
                raise ContractError(f"{path}.{key} is forbidden in a safe export")
            _walk_safe_json(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_safe_json(item, path=f"{path}[{index}]")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_export_payload(payload: Any, raw: bytes) -> tuple[int, int, str]:
    if not isinstance(payload, dict):
        raise ContractError("export must be a JSON object")
    unknown = set(payload) - _EXPORT_KEYS
    if unknown:
        raise ContractError(f"export contains unsupported top-level keys: {sorted(unknown)}")
    if payload.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise ContractError("export schema_version does not match the supported schema")
    if raw != _canonical_json(payload):
        raise ContractError("export JSON must be canonical and deterministically ordered")
    _walk_safe_json(payload, path="export")

    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise ContractError("export nodes must be a list")
    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ContractError(f"export.nodes[{index}] must be an object")
        node_id = _text(node.get("id"), f"export.nodes[{index}].id")
        if node_id in node_ids:
            raise ContractError("export node ids must be unique")
        node_ids.add(node_id)
        _text(node.get("kind"), f"export.nodes[{index}].kind")
        if not isinstance(node.get("fields"), dict):
            raise ContractError(f"export.nodes[{index}].fields must be an object")
        provenance_ids = node.get("provenance_ids", [])
        if not isinstance(provenance_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in provenance_ids
        ):
            raise ContractError(f"export.nodes[{index}].provenance_ids must contain strings")

    relations = payload.get("relations", [])
    if not isinstance(relations, list):
        raise ContractError("export relations must be a list when supplied")
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            raise ContractError(f"export.relations[{index}] must be an object")
    top_owner = payload.get("owner_id")
    if top_owner is not None:
        _owner(top_owner)
    return len(nodes), len(relations), hashlib.sha256(raw).hexdigest()


def _validate_backup_root(root: str | Path) -> Path:
    path = Path(root)
    if not path.is_absolute():
        raise ContractError("backup root must be an absolute path")
    if path.is_symlink() or not path.is_dir():
        raise ContractError("backup root must be an existing non-symlink directory")
    return path


def _relative_parts(value: object, *, label: str) -> tuple[str, ...]:
    text = _text(value, label)
    if "\\" in text or text.startswith("/") or ":" in text or "\x00" in text:
        raise ContractError(f"{label} must be a relative POSIX path")
    raw_parts = text.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ContractError(f"{label} must not contain empty, dot, or traversal components")
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or parsed.parts != tuple(raw_parts):
        raise ContractError(f"{label} must be a normalized relative POSIX path")
    return tuple(raw_parts)


def _resolve_backup_file(root: Path, relative_path: object, *, label: str) -> Path:
    root_path = _validate_backup_root(root)
    parts = _relative_parts(relative_path, label=label)
    candidate = root_path.joinpath(*parts)
    current = root_path
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ContractError(f"{label} must not traverse symlinks")
    if not candidate.is_file() or candidate.is_symlink():
        raise ContractError(f"{label} must be a regular non-symlink file")
    try:
        resolved_root = root_path.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ContractError(f"{label} must remain inside the backup root") from exc
    return candidate


def _resolve_manifest_output(root: Path, output: str | Path) -> tuple[Path, str]:
    root_path = _validate_backup_root(root)
    output_path = Path(output)
    if output_path.is_absolute():
        try:
            relative = output_path.relative_to(root_path)
        except ValueError as exc:
            raise ContractError("manifest output must be inside the backup root") from exc
    else:
        relative = output_path
    parts = _relative_parts(relative.as_posix(), label="manifest output path")
    candidate = root_path.joinpath(*parts)
    if candidate.exists() or candidate.is_symlink():
        raise ContractError("manifest output must be a new regular file")
    if not candidate.parent.is_dir() or candidate.parent.is_symlink():
        raise ContractError("manifest output parent must be an existing non-symlink directory")
    return candidate, "/".join(parts)


def validate_manifest_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ContractError("backup manifest must be a JSON object")
    unknown = set(data) - _MANIFEST_KEYS
    if unknown:
        raise ContractError(f"manifest contains unsupported keys: {sorted(unknown)}")
    if data.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ContractError("manifest schema version is unsupported")
    if data.get("export_schema_version") != EXPORT_SCHEMA_VERSION:
        raise ContractError("manifest export schema version is unsupported")
    _owner(data.get("owner_id"))
    _relative_parts(data.get("export_path"), label="manifest export_path")
    for key in ("byte_count", "node_count", "relation_count"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContractError(f"manifest {key} must be a non-negative integer")
    digest = data.get("sha256")
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        raise ContractError("manifest sha256 must be a lowercase SHA-256 digest")
    return dict(data)


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ContractError("manifest must be a regular non-symlink file")
    try:
        data = _parse_json(manifest_path.read_bytes(), label="manifest")
    except OSError as exc:
        raise ContractError("manifest is not readable") from exc
    return validate_manifest_data(data)


def _read_export(root: Path, export_path: object, *, expected_owner: str | None) -> tuple[dict[str, Any], bytes, int, int, str, Path]:
    path = _resolve_backup_file(root, export_path, label="export path")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError("export is not readable") from exc
    if not raw or len(raw) > MAX_EXPORT_BYTES:
        raise ContractError("export byte count is outside the supported bound")
    payload = _parse_json(raw, label="export")
    node_count, relation_count, digest = _validate_export_payload(payload, raw)
    owner = expected_owner
    top_owner = payload.get("owner_id")
    if top_owner is not None:
        if owner is not None and _owner(top_owner) != owner:
            raise ContractError("export owner_id does not match the requested owner")
        owner = _owner(top_owner)
    return payload, raw, node_count, relation_count, digest, path


def build_manifest(root: str | Path, export_path: str, owner_id: str) -> dict[str, Any]:
    """Build a deterministic manifest without writing anything."""

    owner = _owner(owner_id)
    payload, raw, node_count, relation_count, digest, _ = _read_export(
        _validate_backup_root(root), export_path, expected_owner=owner
    )
    del payload
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "owner_id": owner,
        "export_path": "/".join(_relative_parts(export_path, label="export path")),
        "byte_count": len(raw),
        "sha256": digest,
        "node_count": node_count,
        "relation_count": relation_count,
    }
    return validate_manifest_data(manifest)


def create_manifest(root: str | Path, export_path: str, owner_id: str) -> dict[str, Any]:
    """Backward-friendly alias for :func:`build_manifest`."""

    return build_manifest(root, export_path, owner_id)


def write_manifest(root: str | Path, output: str | Path, manifest: dict[str, Any]) -> Path:
    """Write a new private manifest atomically and never overwrite a file."""

    data = validate_manifest_data(manifest)
    path, _ = _resolve_manifest_output(_validate_backup_root(root), output)
    encoded = (_canonical_json(data) + b"\n")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
    except FileExistsError as exc:
        raise ContractError("manifest output must be a new regular file") from exc
    except OSError as exc:
        raise ContractError("could not write the manifest") from exc
    return path


def _manifest_input(root: Path, manifest: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(manifest, dict):
        return validate_manifest_data(manifest)
    path = Path(manifest)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ContractError("manifest path must be inside the backup root") from exc
    safe_path = _resolve_backup_file(root, relative.as_posix(), label="manifest path")
    return load_manifest(safe_path)


def verify_backup(
    root: str | Path,
    manifest: str | Path | dict[str, Any],
    *,
    expected_owner: str | None = None,
) -> dict[str, Any]:
    """Verify an export and manifest using reads only."""

    root_path = _validate_backup_root(root)
    data = _manifest_input(root_path, manifest)
    owner = _owner(data["owner_id"])
    if expected_owner is not None and _owner(expected_owner) != owner:
        raise ContractError("manifest owner_id does not match the requested owner")
    _, raw, node_count, relation_count, digest, path = _read_export(
        root_path, data["export_path"], expected_owner=owner
    )
    if len(raw) != data["byte_count"]:
        raise ContractError("export byte count does not match the manifest")
    if digest != data["sha256"]:
        raise ContractError("export SHA-256 does not match the manifest")
    if node_count != data["node_count"]:
        raise ContractError("export node count does not match the manifest")
    if relation_count != data["relation_count"]:
        raise ContractError("export relation count does not match the manifest")
    return {
        "status": "verified",
        "owner_id": owner,
        "verified_path": data["export_path"],
        "absolute_verified_path": str(path),
        "byte_count": len(raw),
        "sha256": digest,
        "node_count": node_count,
        "relation_count": relation_count,
    }


def dry_run_restore(
    root: str | Path,
    manifest: str | Path | dict[str, Any],
    *,
    expected_owner: str | None = None,
) -> dict[str, Any]:
    """Verify a backup and explicitly mark that no restore was performed."""

    return {"dry_run": True, **verify_backup(root, manifest, expected_owner=expected_owner)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create a new deterministic manifest")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--export", dest="export_path", required=True)
    create.add_argument("--owner-id", required=True)
    create.add_argument("--output", required=True)

    for name in ("verify", "dry-run"):
        verify = subparsers.add_parser(name, help="verify a backup without changing files")
        verify.add_argument("--root", type=Path, required=True)
        verify.add_argument("--manifest", required=True)
        verify.add_argument("--owner-id", required=True)
        verify.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = build_manifest(args.root, args.export_path, args.owner_id)
            path = write_manifest(args.root, args.output, manifest)
            print(f"Backup manifest created: {path}")
            return 0
        result = dry_run_restore(args.root, args.manifest, expected_owner=args.owner_id)
        if args.command == "verify":
            result = {key: value for key, value in result.items() if key != "dry_run"}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        else:
            print(f"Backup verification: PASS ({args.command}, owner={result['owner_id']})")
        return 0
    except (ContractError, OSError) as exc:
        print(f"Backup verification: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
