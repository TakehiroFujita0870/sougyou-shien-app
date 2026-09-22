"""Verify a Founder Graph restore inside an isolated, offline container.

``--validate-only`` validates the manifest without Docker. Live verification
boots only the explicitly labeled restore volume on ``--network none`` and
reads credentials from a read-only secret file, never from Docker argv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


RESTORE_VOLUME_PATTERN = re.compile(r"^founder-graph-restore-[a-z0-9][a-z0-9_.-]{0,180}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
READ_CLAUSE_KEYWORDS = frozenset("MATCH OPTIONAL WHERE WITH RETURN ORDER SKIP LIMIT".split())
REJECTED_TOP_LEVEL_KEYWORDS = frozenset(
    "CALL USE CREATE MERGE DELETE DETACH SET REMOVE DROP FOREACH LOAD UNWIND UNION YIELD "
    "SHOW GRANT DENY REVOKE TERMINATE TRANSACTION START STOP ALTER RENAME CONSTRAINT INDEX "
    "DATABASE DBMS EXPLAIN PROFILE"
    .split()
)
# The legacy constant name is retained; its tokens are rejected at every depth.
EXPRESSION_CONNECTORS = frozenset(
    "AS AND OR NOT IN IS NULL TRUE FALSE CASE WHEN THEN ELSE END DISTINCT ASC DESC BY ALL ANY NONE SINGLE".split()
)
ALLOWED_FUNCTION_NAMES = frozenset("COUNT TYPE".split())
FORBIDDEN_NAMESPACE_NAMES = frozenset("APOC CYPHER DB DBMS".split())
_OPENING = frozenset("([{")
_CLOSING = frozenset(")]}")
NODE_COUNT_QUERY = "MATCH (n) RETURN count(n) AS count"
RELATIONSHIP_COUNT_QUERY = "MATCH ()-[r]->() RETURN count(r) AS count"
LIVE_VOLUME_ALIASES = (
    "founder_graph_neo4j_data",
    "founder-graph-neo4j-data",
    "founder_graph_local_neo4j_data",
    "founder-graph-local_neo4j_data",
    "founder-graph-local-founder_graph_neo4j_data",
    "founder-graph-restore-live",
    "founder-graph-restore-production",
)

# The secret is mounted in the verification container. Neo4j's supported
# NEO4J_USERNAME/NEO4J_PASSWORD environment variables are populated inside
# the shell, so the password is never an argv value or Docker inspect field.
QUERY_SHELL = r'''set -eu
secret_path="$1"
query="$2"
auth="$(cat "$secret_path")"
case "$auth" in
  neo4j/*) ;;
  *) exit 64 ;;
esac
export NEO4J_USERNAME="${auth%%/*}"
export NEO4J_PASSWORD="${auth#*/}"
test -n "$NEO4J_PASSWORD"
exec cypher-shell --address localhost:7687 --database neo4j --format plain --access-mode read "$query"
'''


class ContractError(ValueError):
    """A safe, user-facing contract failure."""


def _tokenize_read_query(query: str) -> list[tuple[str, str]]:
    """Tokenize the bounded read contract without evaluating Cypher."""

    if not isinstance(query, str) or not query.strip():
        raise ContractError("representative queries must be non-empty strings")
    if ";" in query:
        raise ContractError("representative queries must contain one statement without semicolons")

    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(query):
        char = query[index]
        if char.isspace():
            index += 1
            continue
        if query.startswith("//", index) or query.startswith("/*", index):
            raise ContractError("representative queries must not contain comments")
        if char in "'\"`":
            quote = char
            start = index
            index += 1
            while index < len(query):
                if query[index] == "\\" and quote != "`":
                    index += 2
                    continue
                if query[index] == quote:
                    if index + 1 < len(query) and query[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                raise ContractError("representative queries contain an unterminated quoted value")
            tokens.append(("literal", query[start:index]))
            continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(query) and (query[index].isalnum() or query[index] == "_"):
                index += 1
            tokens.append(("word", query[start:index]))
            continue
        if char.isdigit():
            start = index
            index += 1
            while index < len(query) and (query[index].isalnum() or query[index] in ".+-"):
                index += 1
            tokens.append(("number", query[start:index]))
            continue
        tokens.append(("symbol", char))
        index += 1
    return tokens


def _top_level_clause_positions(tokens: list[tuple[str, str]]) -> list[tuple[int, str]]:
    for index, (kind, value) in enumerate(tokens):
        if kind == "symbol" and value in "{}":
            raise ContractError(
                "representative queries must not contain subquery expressions or map braces"
            )
        if kind != "word":
            continue
        upper = value.upper()
        if upper in REJECTED_TOP_LEVEL_KEYWORDS:
            raise ContractError(f"representative query token is not read-only: {upper}")
        if upper in FORBIDDEN_NAMESPACE_NAMES:
            raise ContractError(f"representative query namespace is not allowed: {upper}")
        if (
            upper not in READ_CLAUSE_KEYWORDS | EXPRESSION_CONNECTORS
            and index + 1 < len(tokens)
            and tokens[index + 1] == ("symbol", "(")
        ):
            if upper not in ALLOWED_FUNCTION_NAMES:
                raise ContractError(f"representative query function is not allowed: {value}")

    positions: list[tuple[int, str]] = []
    depth = 0
    for index, (kind, value) in enumerate(tokens):
        if kind == "symbol" and value in _OPENING:
            depth += 1
        elif kind == "symbol" and value in _CLOSING:
            depth -= 1
            if depth < 0:
                raise ContractError("representative queries contain unbalanced delimiters")
        if depth != 0 or kind != "word":
            continue
        upper = value.upper()
        previous = tokens[index - 1][1] if index else ""
        if upper in READ_CLAUSE_KEYWORDS and previous not in {".", ":"}:
            positions.append((index, upper))
    if depth:
        raise ContractError("representative queries contain unbalanced delimiters")
    return positions


def _validate_read_query(query: Any) -> str:
    """Accept exactly one bounded MATCH/OPTIONAL MATCH read statement."""

    if not isinstance(query, str):
        raise ContractError("representative queries must be non-empty strings")
    tokens = _tokenize_read_query(query)
    if not tokens:
        raise ContractError("representative queries must be non-empty strings")

    positions = _top_level_clause_positions(tokens)
    first = tokens[0][1].upper() if tokens[0][0] == "word" else ""
    if first == "OPTIONAL":
        if len(tokens) < 2 or tokens[1][0] != "word" or tokens[1][1].upper() != "MATCH":
            raise ContractError("representative query must start with MATCH or OPTIONAL MATCH")
        if positions[:2] != [(0, "OPTIONAL"), (1, "MATCH")]:
            raise ContractError("representative query must start with MATCH or OPTIONAL MATCH")
        clause_positions = positions[1:]
    elif first == "MATCH":
        if positions[:1] != [(0, "MATCH")]:
            raise ContractError("representative query must start with MATCH or OPTIONAL MATCH")
        clause_positions = positions
    else:
        raise ContractError("representative query must start with MATCH or OPTIONAL MATCH")

    if not clause_positions or clause_positions[0][1] != "MATCH":
        raise ContractError("representative query must contain a MATCH clause")
    if any(clause in {"MATCH", "OPTIONAL"} for _, clause in clause_positions[1:]):
        raise ContractError("representative query must contain one MATCH clause")

    allowed_next = {
        "MATCH": {"WHERE", "WITH", "RETURN"},
        "WHERE": {"WITH", "RETURN"},
        "WITH": {"WHERE", "WITH", "RETURN"},
        "RETURN": {"ORDER", "SKIP", "LIMIT"},
        "ORDER": {"SKIP", "LIMIT"},
        "SKIP": {"LIMIT"},
        "LIMIT": set(),
    }
    phase = "MATCH"
    seen: set[str] = {"MATCH"}
    for _, clause in clause_positions[1:]:
        if clause not in allowed_next[phase]:
            raise ContractError(f"representative query clause order is not allowed: {clause}")
        if clause in seen and clause not in {"WITH", "WHERE"}:
            raise ContractError(f"representative query clause may appear only once: {clause}")
        seen.add(clause)
        phase = clause
    if "RETURN" not in seen:
        raise ContractError("representative query must contain a RETURN clause")

    for entry, (index, clause) in enumerate(clause_positions):
        end = clause_positions[entry + 1][0] if entry + 1 < len(clause_positions) else len(tokens)
        body = tokens[index + 1 : end]
        if clause == "ORDER":
            if not body or body[0][0] != "word" or body[0][1].upper() != "BY":
                raise ContractError("representative ORDER clause must contain BY")
            body = body[1:]
        if not body:
            raise ContractError(f"representative {clause} clause must not be empty")

    recognized = {index: clause for index, clause in clause_positions}
    if first == "OPTIONAL":
        recognized[positions[0][0]] = "OPTIONAL"
    current_clause = "MATCH"
    depth = 0
    for index, (kind, value) in enumerate(tokens):
        if kind == "symbol" and value in _OPENING:
            depth += 1
            continue
        if kind == "symbol" and value in _CLOSING:
            depth -= 1
            continue
        if depth != 0:
            continue
        if kind == "word" and index in recognized:
            current_clause = recognized[index]
        if kind != "word" or index in recognized:
            continue
        previous_kind, previous_value = tokens[index - 1] if index else ("", "")
        upper = value.upper()
        if current_clause == "MATCH":
            raise ContractError(f"representative query contains an unknown top-level clause: {value}")
        if previous_value in {".", ":"} or upper in EXPRESSION_CONNECTORS:
            continue
        if previous_kind == "word" and previous_value.upper() not in READ_CLAUSE_KEYWORDS | EXPRESSION_CONNECTORS:
            raise ContractError(f"representative query contains an unknown top-level clause: {value}")
        if previous_value in _CLOSING or previous_kind in {"number", "literal"}:
            raise ContractError(f"representative query contains an unknown top-level clause: {value}")
    return query


def _contains_live_alias(value: str) -> bool:
    return value.casefold() in {alias.casefold() for alias in LIVE_VOLUME_ALIASES}


def validate_restore_volume_name(volume: str) -> str:
    """Validate a new restore volume name and reject live-volume aliases."""

    if "," in volume:
        raise ContractError("restore volume names must not contain commas")
    if not RESTORE_VOLUME_PATTERN.fullmatch(volume):
        raise ContractError(
            "restore volume must match founder-graph-restore-<lowercase-suffix>"
        )
    if _contains_live_alias(volume):
        raise ContractError("restore volume name aliases the live volume")
    return volume


def _validate_query(query: Any) -> str:
    return _validate_read_query(query)


def validate_manifest_data(data: Any) -> dict[str, Any]:
    """Validate the deterministic count/hash comparison manifest."""

    if not isinstance(data, dict):
        raise ContractError("restore manifest must be a JSON object")
    for key in ("node_count", "relationship_count"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContractError(f"{key} must be a non-negative integer")

    queries = data.get("representative_queries")
    hashes = data.get("query_hashes")
    if not isinstance(queries, list) or len(queries) != 3:
        raise ContractError("representative_queries must contain exactly 3 queries")
    if not isinstance(hashes, list) or len(hashes) != 3:
        raise ContractError("query_hashes must contain exactly 3 hashes")
    for query in queries:
        _validate_query(query)
    for digest in hashes:
        if not isinstance(digest, str) or digest != digest.lower() or not SHA256_PATTERN.fullmatch(digest):
            raise ContractError("query_hashes must contain lowercase SHA-256 digests")
    for key in ("expected_project", "expected_source"):
        if key in data and (not isinstance(data[key], str) or not data[key]):
            raise ContractError(f"{key} must be a non-empty string when supplied")
    return data


def load_manifest(path: Path) -> dict[str, Any]:
    """Read a non-symlink JSON manifest and validate it."""

    if path.is_symlink() or not path.is_file():
        raise ContractError("restore manifest must be a regular file, not a symlink")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("restore manifest is not readable UTF-8 JSON") from exc
    return validate_manifest_data(data)


def canonicalize_result(output: str) -> str:
    """Normalize only newline encoding; preserve all result whitespace."""

    return output.replace("\r\n", "\n").replace("\r", "\n")


def result_hash(output: str) -> str:
    return hashlib.sha256(canonicalize_result(output).encode("utf-8")).hexdigest()


def _run(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run Docker argv without a shell and without printing its output."""

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI is unavailable; use --validate-only for static checks")
    result = _run(["docker", "compose", "version"])
    if result.returncode != 0:
        raise RuntimeError("Docker Compose v2 is unavailable")


def _validate_secret_file(path: Path) -> Path:
    if "," in str(path):
        raise ContractError("Docker --mount paths must not contain commas")
    if path.is_symlink() or not path.is_file():
        raise ContractError("secret file must be a regular non-symlink file")
    try:
        auth = path.read_text(encoding="utf-8")
        mode = path.stat().st_mode & 0o777
    except (OSError, UnicodeError) as exc:
        raise ContractError("secret file is not readable") from exc
    if os.name != "nt" and mode & 0o077:
        raise ContractError("secret file must not be group/world readable")
    if not auth.startswith("neo4j/") or not auth.split("/", 1)[1]:
        raise ContractError("secret file must contain neo4j/<password>")
    return path


def _require_restore_label(volume: str, manifest: dict[str, Any]) -> None:
    result = _run(["docker", "volume", "inspect", volume])
    if result.returncode != 0:
        raise RuntimeError("restore volume does not exist")
    try:
        payload = json.loads(result.stdout)
        labels = payload[0].get("Labels") or {}
    except (ValueError, IndexError, AttributeError, TypeError) as exc:
        raise RuntimeError("restore volume labels could not be read") from exc
    if _contains_live_alias(volume) or any(
        _contains_live_alias(str(key)) or _contains_live_alias(str(value))
        for key, value in labels.items()
        if value is not None
    ):
        raise RuntimeError("live Founder Graph volume or alias cannot be verified")
    if labels.get("com.openai.founder_graph.role") != "restore":
        raise RuntimeError("restore volume must have role=restore")
    if labels.get("com.openai.founder_graph.database") != "neo4j":
        raise RuntimeError("restore volume must have database=neo4j")
    expected_project = manifest.get("expected_project")
    if expected_project is not None and labels.get("com.openai.founder_graph.project") != expected_project:
        raise RuntimeError("restore volume project label did not match the manifest")
    expected_source = manifest.get("expected_source")
    if expected_source is not None and labels.get("com.openai.founder_graph.source") != expected_source:
        raise RuntimeError("restore volume source label did not match the manifest")


def _extract_count(output: str) -> int:
    values = [line.strip() for line in output.splitlines() if line.strip()]
    for value in reversed(values):
        if value.isdecimal():
            return int(value)
    raise RuntimeError("count query returned no integer")


def _exec_query(container: str, secret_container_path: str, query: str, timeout: int) -> str:
    if "," in secret_container_path:
        raise ContractError("Docker --mount paths must not contain commas")
    result = _run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            QUERY_SHELL,
            "founder-graph-query",
            secret_container_path,
            query,
        ],
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError("restore verification query failed")
    return result.stdout


def verify_live(
    volume: str,
    manifest: dict[str, Any],
    secret_file: str | Path,
    image: str = "neo4j:5.26-community",
    timeout: int = 60,
) -> None:
    """Boot the labeled restore volume and compare counts plus three hashes."""

    validate_restore_volume_name(volume)
    manifest = validate_manifest_data(manifest)
    if "," in image:
        raise ContractError("image names must not contain commas")
    secret_path = _validate_secret_file(Path(secret_file))
    _require_docker()
    _require_restore_label(volume, manifest)

    container = f"founder-graph-restore-verify-{uuid.uuid4().hex[:12]}"
    mount = f"type=volume,source={volume},target=/data"
    secret_mount = f"type=bind,source={secret_path},target=/run/secrets/founder_graph_auth,readonly"
    if "," in mount or "," in secret_mount:
        raise ContractError("Docker --mount values must not contain commas from inputs")
    run_result = _run(
        [
            "docker",
            "run",
            "--pull",
            "never",
            "--detach",
            "--rm",
            "--network",
            "none",
            "--name",
            container,
            "--env",
            "NEO4J_AUTH_FILE=/run/secrets/founder_graph_auth",
            "--mount",
            mount,
            "--mount",
            secret_mount,
            image,
        ],
        timeout=timeout,
    )
    if run_result.returncode != 0:
        raise RuntimeError("could not boot the isolated restore container")

    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                _exec_query(container, "/run/secrets/founder_graph_auth", "RETURN 1", timeout=10)
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("isolated restore container did not become ready")
                time.sleep(1)

        node_count = _extract_count(
            _exec_query(container, "/run/secrets/founder_graph_auth", NODE_COUNT_QUERY, timeout)
        )
        relationship_count = _extract_count(
            _exec_query(container, "/run/secrets/founder_graph_auth", RELATIONSHIP_COUNT_QUERY, timeout)
        )
        if node_count != manifest["node_count"]:
            raise RuntimeError("restored node count did not match the manifest")
        if relationship_count != manifest["relationship_count"]:
            raise RuntimeError("restored relationship count did not match the manifest")

        for query, expected_hash in zip(
            manifest["representative_queries"], manifest["query_hashes"], strict=True
        ):
            actual_hash = result_hash(
                _exec_query(container, "/run/secrets/founder_graph_auth", query, timeout)
            )
            if actual_hash != expected_hash:
                raise RuntimeError("representative restore query hash did not match the manifest")
    finally:
        # --rm removes only this short-lived container; the labeled data volume remains.
        _run(["docker", "stop", container], timeout=30)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--volume")
    parser.add_argument("--secret-file", type=Path)
    parser.add_argument("--image", default="neo4j:5.26-community")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        if args.validate_only:
            print("Restore manifest contract: PASS (static, Docker-free)")
            return 0
        if not args.volume:
            raise ContractError("live verification requires --volume")
        if args.secret_file is None:
            raise ContractError("live verification requires --secret-file")
        verify_live(args.volume, manifest, args.secret_file, args.image, args.timeout)
    except (ContractError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Restore verification: FAIL: {exc}", file=sys.stderr)
        return 1
    print("Restore verification: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
