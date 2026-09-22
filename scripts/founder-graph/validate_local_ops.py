"""Validate the local Founder Graph Neo4j operations contract without Docker.

The validator intentionally performs static checks only. It never starts a
container, resolves a registry, opens a socket, or reads a credential.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


EXPECTED_PORTS = {
    "127.0.0.1:7474:7474",
    "127.0.0.1:7687:7687",
}
REQUIRED_FILES = (
    Path("compose.founder-graph.yml"),
    Path("scripts/founder-graph/founder-graph.ps1"),
    Path("scripts/founder-graph/founder-graph.sh"),
    Path("scripts/founder-graph/validate_local_ops.py"),
    Path("scripts/founder-graph/verify_restore.py"),
    Path("scripts/founder-graph/capture_manifest.py"),
    Path("scripts/founder-graph/verify_export_backup.py"),
    Path("scripts/founder-graph/migrate_schema.py"),
    Path("docs/operations/founder-graph-local.md"),
    Path("backend/tests/test_founder_graph_local_ops.py"),
    Path("backend/tests/test_founder_graph_backup_manifest.py"),
)


def _section(text: str, start: str, end: str | None = None) -> str:
    """Return the indented YAML section beginning at *start*."""

    match = re.search(rf"(?m)^{re.escape(start)}\s*$", text)
    if not match:
        return ""
    remainder = text[match.end() :]
    if end is None:
        return remainder
    end_match = re.search(rf"(?m)^{re.escape(end)}\s*$", remainder)
    return remainder[: end_match.start()] if end_match else remainder


def _append_missing(issues: list[str], text: str, tokens: tuple[str, ...], scope: str) -> None:
    for token in tokens:
        if token not in text:
            issues.append(f"{scope} is missing {token!r}")


def validate(root: Path) -> list[str]:
    """Return deterministic contract violations for *root*."""

    issues: list[str] = []
    for relative_path in REQUIRED_FILES:
        if not (root / relative_path).is_file():
            issues.append(f"missing required file: {relative_path}")
    if issues:
        return issues

    compose = (root / REQUIRED_FILES[0]).read_text(encoding="utf-8")
    runbook = (root / Path("docs/operations/founder-graph-local.md")).read_text(encoding="utf-8")
    powershell = (root / Path("scripts/founder-graph/founder-graph.ps1")).read_text(encoding="utf-8")
    bash = (root / Path("scripts/founder-graph/founder-graph.sh")).read_text(encoding="utf-8")
    schema_migrator = (root / Path("scripts/founder-graph/migrate_schema.py")).read_text(encoding="utf-8")

    if "services:" not in compose or "neo4j:" not in compose:
        issues.append("Compose must define a neo4j service")
    if "image: neo4j:5.26-community" not in compose:
        issues.append("Compose image must be the pinned Neo4j Community image")

    ports = _section(compose, "    ports:", "    volumes:")
    declared_ports = set(re.findall(r'^\s*-\s*["\']([^"\']+)["\']\s*$', ports, flags=re.MULTILINE))
    if declared_ports != EXPECTED_PORTS:
        issues.append(f"ports must be exactly {sorted(EXPECTED_PORTS)}, got {sorted(declared_ports)}")
    if "0.0.0.0:" in ports or ":::" in ports:
        issues.append("published ports must not bind wildcard interfaces")
    if "internal: true" not in compose:
        issues.append("Compose network must be internal")
    if "external: true" in compose.lower():
        issues.append("Compose must not depend on an external network")
    if "name: founder_graph_local" in compose:
        issues.append("Compose network must not use a global fixed name")

    _append_missing(
        issues,
        compose,
        (
            "name: ${FOUNDER_GRAPH_COMPOSE_PROJECT:-founder-graph-local}",
            "pull_policy: never",
            "NEO4J_AUTH_FILE: /run/secrets/founder_graph_auth",
            "FOUNDER_GRAPH_NEO4J_AUTH_FILE",
            "founder_graph_neo4j_data:/data",
            "com.openai.founder_graph.role: live",
            "com.openai.founder_graph.database: neo4j",
            "secrets:",
            "founder_graph_auth:",
            "healthcheck:",
            "cypher-shell",
            '"RETURN 1"',
            "start_period:",
            "retries:",
        ),
        "Compose",
    )
    if re.search(r"(?m)^\s+NEO4J_AUTH\s*:", compose):
        issues.append("Compose must use NEO4J_AUTH_FILE, not inline NEO4J_AUTH")
    if "--password" in compose or re.search(r"NEO4J_AUTH\s*=\s*neo4j/", compose):
        issues.append("Compose must not expose credentials in argv or inline values")

    _append_missing(
        issues,
        schema_migrator,
        ("--validate-only", "migration_queries", "schema_manifest", "Docker-free"),
        "schema migrator",
    )

    for name, helper in (("PowerShell helper", powershell), ("bash helper", bash)):
        _append_missing(
            issues,
            helper,
            (
                "database dump neo4j",
                "database dump system",
                "database load neo4j",
                "database load system",
                "start",
                "stop",
                "status",
                "founder_graph_neo4j_data",
                "founder-graph-restore-",
                "com.openai.founder_graph.role=restore",
                "com.openai.founder_graph.database=neo4j",
                "com.openai.founder_graph.project",
                "com.openai.founder_graph.source",
                "--overwrite-destination=true",
                "network none",
                "/backups",
                "capture-manifest",
                "secret",
                "healthy",
            ),
            name,
        )
        backup_section = helper.split("Restore-Database", 1)[0].split("restore()", 1)[0]
        if "overwrite-destination" in backup_section:
            issues.append(f"{name} must not overwrite an existing backup dump")
        for forbidden in ("down -v", "docker volume rm", "volume prune", "rm -rf", "Remove-Item -Recurse"):
            if forbidden.lower() in helper.lower():
                issues.append(f"{name} contains forbidden destructive command {forbidden!r}")
        if "FOUNDER_GRAPH_NEO4J_AUTH" not in helper:
            issues.append(f"{name} must require FOUNDER_GRAPH_NEO4J_AUTH")
        if "--password" in helper or re.search(r"NEO4J_AUTH\s*=\s*neo4j/", helper):
            issues.append(f"{name} must not expose credentials in argv")
        if "wait_for_healthy" not in helper and "Wait-ForHealthy" not in helper:
            issues.append(f"{name} must wait for health after restart")

    verifier = (root / Path("scripts/founder-graph/verify_restore.py")).read_text(encoding="utf-8")
    _append_missing(
        issues,
        verifier,
        (
            "READ_CLAUSE_KEYWORDS",
            "REJECTED_TOP_LEVEL_KEYWORDS",
            "EXPRESSION_CONNECTORS",
            "ALLOWED_FUNCTION_NAMES",
            "FORBIDDEN_NAMESPACE_NAMES",
            "def _tokenize_read_query",
            "def _top_level_clause_positions",
            "def _validate_read_query",
            "must not contain comments",
            "one statement without semicolons",
            "subquery expressions or map braces",
            "query function is not allowed",
            "unknown top-level clause",
            "--validate-only",
            "--secret-file",
            "query_hashes",
            "representative_queries",
            "NODE_COUNT_QUERY",
            "RELATIONSHIP_COUNT_QUERY",
            '"--network"',
            '"none"',
            "secret_mount",
            "com.openai.founder_graph.role",
            "com.openai.founder_graph.database",
            "expected_project",
            "expected_source",
            "shutil.which(\"docker\")",
            "canonicalize_result",
            "--access-mode read",
        ),
        "restore verifier",
    )
    if "--password" in verifier or "NEO4J_AUTH=" in verifier:
        issues.append("restore verifier must not expose credentials in argv or inspect")
    if "MUTATING_QUERY_PATTERN" in verifier:
        issues.append("restore verifier must use a positive query contract, not a mutating keyword blacklist")

    capturer = (root / Path("scripts/founder-graph/capture_manifest.py")).read_text(encoding="utf-8")
    _append_missing(
        issues,
        capturer,
        (
            "READ_CLAUSE_KEYWORDS",
            "REJECTED_TOP_LEVEL_KEYWORDS",
            "EXPRESSION_CONNECTORS",
            "ALLOWED_FUNCTION_NAMES",
            "FORBIDDEN_NAMESPACE_NAMES",
            "def _tokenize_read_query",
            "def _top_level_clause_positions",
            "def _validate_read_query",
            "must not contain comments",
            "one statement without semicolons",
            "subquery expressions or map braces",
            "query function is not allowed",
            "unknown top-level clause",
            "--validate-only",
            "representative_queries",
            "query_hashes",
            "--secret-container-path",
            "O_EXCL",
            "0o600",
            "canonicalize_result",
            "shutil.which(\"docker\")",
            "--access-mode read",
        ),
        "manifest capturer",
    )
    if "--password" in capturer or "NEO4J_AUTH=" in capturer:
        issues.append("manifest capturer must not expose credentials in argv or inspect")
    if "MUTATING_QUERY_PATTERN" in capturer:
        issues.append("manifest capturer must use a positive query contract, not a mutating keyword blacklist")

    backup_verifier = (root / Path("scripts/founder-graph/verify_export_backup.py")).read_text(encoding="utf-8")
    _append_missing(
        issues,
        backup_verifier,
        (
            "MANIFEST_SCHEMA_VERSION",
            "EXPORT_SCHEMA_VERSION",
            "def build_manifest",
            "def verify_backup",
            "def dry_run_restore",
            "def validate_manifest_data",
            "canonical",
            "O_EXCL",
            "relative POSIX path",
            "--root",
            "dry-run",
        ),
        "offline backup verifier",
    )
    if re.search(r"(?m)^\s*(?:import|from)\s+(?:subprocess|socket)\b", backup_verifier):
        issues.append("offline backup verifier must not start processes or open sockets")
    if "docker" not in backup_verifier.lower():
        issues.append("offline backup verifier must document its Docker-free boundary")

    _append_missing(
        issues,
        runbook,
        (
            "127.0.0.1:7474",
            "127.0.0.1:7687",
            "FOUNDER_GRAPH_NEO4J_AUTH",
            "FOUNDER_GRAPH_NEO4J_AUTH_FILE",
            "founder_graph_neo4j_data",
            "FOUNDER_GRAPH_COMPOSE_PROJECT",
            "health",
            "backup",
            "neo4j.dump",
            "system.dump",
            "restore",
            "verify-restore",
            "capture-manifest",
            "verify-export-backup",
            "founder-graph-backup-manifest-v1",
            "dry-run",
            "query_hashes",
            "count(...)",
            "type(...)",
            "subquery expression",
            "literal",
            "world-readable",
            "symlink",
            "comma",
            "隔離",
            "live smoke",
            "実際のDocker smoke",
            "利用できない",
            "T-FG-01",
            "T-FG-03",
            "before-stop.json",
            "after-restart.json",
            "cmp --",
            "実機未検査",
            "static検査済み",
        ),
        "Runbook",
    )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root to inspect (no Docker access is performed)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    issues = validate(root)
    if issues:
        print("Founder Graph local contract: FAIL")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Founder Graph local contract: PASS (static, Docker-free)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
