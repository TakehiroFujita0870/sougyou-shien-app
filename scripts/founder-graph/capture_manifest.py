"""Capture a deterministic Founder Graph restore-verification manifest.

The command reads queries from a JSON file and runs them in an already healthy
Compose container. The auth secret is read inside that container from the
Compose secret mount, so no credential is placed in Docker argv or output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


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
    """A safe, user-facing capture contract failure."""


def canonicalize_result(output: str) -> str:
    """Normalize only CRLF/CR to LF and preserve result whitespace."""

    return output.replace("\r\n", "\n").replace("\r", "\n")


def _result_hash(output: str) -> str:
    return hashlib.sha256(canonicalize_result(output).encode("utf-8")).hexdigest()


def _tokenize_read_query(query: str) -> list[tuple[str, str]]:
    """Tokenize the bounded read contract without evaluating Cypher."""

    if not isinstance(query, str) or not query.strip():
        raise ContractError("manifest queries must be non-empty strings")
    if ";" in query:
        raise ContractError("manifest queries must contain one statement without semicolons")

    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(query):
        char = query[index]
        if char.isspace():
            index += 1
            continue
        if query.startswith("//", index) or query.startswith("/*", index):
            raise ContractError("manifest queries must not contain comments")
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
                raise ContractError("manifest queries contain an unterminated quoted value")
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
                "manifest queries must not contain subquery expressions or map braces"
            )
        if kind != "word":
            continue
        upper = value.upper()
        if upper in REJECTED_TOP_LEVEL_KEYWORDS:
            raise ContractError(f"manifest query token is not read-only: {upper}")
        if upper in FORBIDDEN_NAMESPACE_NAMES:
            raise ContractError(f"manifest query namespace is not allowed: {upper}")
        if (
            upper not in READ_CLAUSE_KEYWORDS | EXPRESSION_CONNECTORS
            and index + 1 < len(tokens)
            and tokens[index + 1] == ("symbol", "(")
        ):
            if upper not in ALLOWED_FUNCTION_NAMES:
                raise ContractError(f"manifest query function is not allowed: {value}")

    positions: list[tuple[int, str]] = []
    depth = 0
    for index, (kind, value) in enumerate(tokens):
        if kind == "symbol" and value in _OPENING:
            depth += 1
        elif kind == "symbol" and value in _CLOSING:
            depth -= 1
            if depth < 0:
                raise ContractError("manifest queries contain unbalanced delimiters")
        if depth != 0 or kind != "word":
            continue
        upper = value.upper()
        previous = tokens[index - 1][1] if index else ""
        if upper in READ_CLAUSE_KEYWORDS and previous not in {".", ":"}:
            positions.append((index, upper))
    if depth:
        raise ContractError("manifest queries contain unbalanced delimiters")
    return positions


def _validate_read_query(query: Any) -> str:
    """Accept exactly one bounded MATCH/OPTIONAL MATCH read statement."""

    if not isinstance(query, str):
        raise ContractError("manifest queries must be non-empty strings")
    tokens = _tokenize_read_query(query)
    if not tokens:
        raise ContractError("manifest queries must be non-empty strings")

    positions = _top_level_clause_positions(tokens)
    first = tokens[0][1].upper() if tokens[0][0] == "word" else ""
    if first == "OPTIONAL":
        if len(tokens) < 2 or tokens[1][0] != "word" or tokens[1][1].upper() != "MATCH":
            raise ContractError("manifest query must start with MATCH or OPTIONAL MATCH")
        if positions[:2] != [(0, "OPTIONAL"), (1, "MATCH")]:
            raise ContractError("manifest query must start with MATCH or OPTIONAL MATCH")
        clause_positions = positions[1:]
    elif first == "MATCH":
        if positions[:1] != [(0, "MATCH")]:
            raise ContractError("manifest query must start with MATCH or OPTIONAL MATCH")
        clause_positions = positions
    else:
        raise ContractError("manifest query must start with MATCH or OPTIONAL MATCH")

    if not clause_positions or clause_positions[0][1] != "MATCH":
        raise ContractError("manifest query must contain a MATCH clause")
    if any(clause in {"MATCH", "OPTIONAL"} for _, clause in clause_positions[1:]):
        raise ContractError("manifest query must contain one MATCH clause")

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
            raise ContractError(f"manifest query clause order is not allowed: {clause}")
        if clause in seen and clause not in {"WITH", "WHERE"}:
            raise ContractError(f"manifest query clause may appear only once: {clause}")
        seen.add(clause)
        phase = clause
    if "RETURN" not in seen:
        raise ContractError("manifest query must contain a RETURN clause")

    for entry, (index, clause) in enumerate(clause_positions):
        end = clause_positions[entry + 1][0] if entry + 1 < len(clause_positions) else len(tokens)
        body = tokens[index + 1 : end]
        if clause == "ORDER":
            if not body or body[0][0] != "word" or body[0][1].upper() != "BY":
                raise ContractError("manifest ORDER clause must contain BY")
            body = body[1:]
        if not body:
            raise ContractError(f"manifest {clause} clause must not be empty")

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
            raise ContractError(f"manifest query contains an unknown top-level clause: {value}")
        if previous_value in {".", ":"} or upper in EXPRESSION_CONNECTORS:
            continue
        if previous_kind == "word" and previous_value.upper() not in READ_CLAUSE_KEYWORDS | EXPRESSION_CONNECTORS:
            raise ContractError(f"manifest query contains an unknown top-level clause: {value}")
        if previous_value in _CLOSING or previous_kind in {"number", "literal"}:
            raise ContractError(f"manifest query contains an unknown top-level clause: {value}")
    return query


def _validate_queries(data: Any) -> list[str]:
    if isinstance(data, dict):
        queries = data.get("queries")
    else:
        queries = data
    if not isinstance(queries, list) or len(queries) != 3:
        raise ContractError("queries JSON must contain exactly 3 queries")
    for query in queries:
        _validate_read_query(query)
    return queries


def load_queries(path: Path) -> list[str]:
    if path.is_symlink() or not path.is_file():
        raise ContractError("queries file must be a regular non-symlink file")
    try:
        return _validate_queries(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("queries file is not readable UTF-8 JSON") from exc


def _run(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _extract_count(output: str) -> int:
    for value in reversed([line.strip() for line in output.splitlines() if line.strip()]):
        if value.isdecimal():
            return int(value)
    raise RuntimeError("count query returned no integer")


def _exec_query(container: str, secret_container_path: str, query: str) -> str:
    if "," in container or "," in secret_container_path:
        raise ContractError("Docker argv and mount paths must not contain commas")
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
        ]
    )
    if result.returncode != 0:
        raise RuntimeError("manifest query failed")
    return result.stdout


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    if "," in str(path):
        raise ContractError("manifest output paths must not contain commas")
    if path.is_symlink() or path.exists():
        raise ContractError("manifest output must be a new regular file")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ContractError("manifest output parent must be an existing non-symlink directory")
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
    except FileExistsError as exc:
        raise ContractError("manifest output must be a new regular file") from exc
    except OSError as exc:
        raise ContractError("could not write the private manifest output") from exc


def capture_manifest(
    container: str,
    queries: list[str],
    output: Path,
    secret_container_path: str,
    expected_project: str | None = None,
    expected_source: str | None = None,
) -> dict[str, Any]:
    queries = _validate_queries(queries)
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI is unavailable; query capture requires live Docker")
    if not container or "," in container:
        raise ContractError("container must be a non-empty Docker id without commas")
    if not secret_container_path.startswith("/") or "," in secret_container_path:
        raise ContractError("secret container path must be absolute and comma-free")
    node_count = _extract_count(_exec_query(container, secret_container_path, NODE_COUNT_QUERY))
    relationship_count = _extract_count(
        _exec_query(container, secret_container_path, RELATIONSHIP_COUNT_QUERY)
    )
    hashes = [_result_hash(_exec_query(container, secret_container_path, query)) for query in queries]
    manifest: dict[str, Any] = {
        "node_count": node_count,
        "relationship_count": relationship_count,
        "representative_queries": queries,
        "query_hashes": hashes,
    }
    if expected_project is not None:
        manifest["expected_project"] = expected_project
    if expected_source is not None:
        manifest["expected_source"] = expected_source
    _write_manifest(output, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container")
    parser.add_argument("--secret-container-path", default="/run/secrets/founder_graph_auth")
    parser.add_argument("--expected-project")
    parser.add_argument("--expected-source")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        queries = load_queries(args.queries)
        if args.validate_only:
            print("Manifest query contract: PASS (static, Docker-free)")
            return 0
        if not args.container:
            raise ContractError("live capture requires --container")
        capture_manifest(
            args.container,
            queries,
            args.output,
            args.secret_container_path,
            args.expected_project,
            args.expected_source,
        )
    except (ContractError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Manifest capture: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"Manifest written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
