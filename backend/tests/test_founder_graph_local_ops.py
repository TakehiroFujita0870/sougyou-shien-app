"""Daemon-free contracts for the local-only Founder Graph Neo4j substrate."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.founder-graph.yml"
RUNBOOK = ROOT / "docs" / "operations" / "founder-graph-local.md"
SCRIPT_DIR = ROOT / "scripts" / "founder-graph"
VALIDATOR = SCRIPT_DIR / "validate_local_ops.py"
POWERSHELL_HELPER = SCRIPT_DIR / "founder-graph.ps1"
BASH_HELPER = SCRIPT_DIR / "founder-graph.sh"
RESTORE_VERIFIER = SCRIPT_DIR / "verify_restore.py"
MANIFEST_CAPTURER = SCRIPT_DIR / "capture_manifest.py"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_restore_verifier():
    return load_module(RESTORE_VERIFIER, "founder_graph_restore_verifier")


def load_manifest_capturer():
    return load_module(MANIFEST_CAPTURER, "founder_graph_manifest_capturer")


def _query_contract_cases() -> tuple[str, ...]:
    return (
        "CALL db.createLabel('unsafe')",
        "CALL dbms.security.listUsers()",
        "USE system MATCH (n) RETURN n",
        "SHOW DATABASES",
        "CREATE (n:Unsafe)",
        "MATCH (n) SET n.unsafe = true RETURN n",
        "RETURN 1",
        "MATCH (n) RETURN n; MATCH (m) RETURN m",
    )


def _valid_query_contract_cases() -> tuple[str, ...]:
    return (
        "MATCH (n) WHERE n.name = 'x' WITH n RETURN n ORDER BY n.name SKIP 1 LIMIT 1",
        "OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m",
    )


def _nested_query_contract_cases() -> tuple[str, ...]:
    return (
        "MATCH (n) WHERE EXISTS { CALL { CREATE (:X) RETURN 1 AS x } RETURN true } RETURN n",
        "MATCH (n) WHERE EXISTS { LOAD CSV FROM 'file:///tmp/input.csv' AS row RETURN true } RETURN n",
        "MATCH (n) WHERE EXISTS { SHOW DATABASES RETURN true } RETURN n",
        "MATCH (n) WHERE EXISTS { UNION RETURN true } RETURN n",
        "MATCH (n) WHERE EXISTS { SET n.value = 1 RETURN true } RETURN n",
        "MATCH (n) WHERE EXISTS { DELETE n RETURN true } RETURN n",
        "MATCH (n) WHERE EXISTS { DROP INDEX example RETURN true } RETURN n",
        "MATCH (n) RETURN count { CALL apoc.foo() }",
        "MATCH (n) RETURN apoc.cypher.runFirstColumnSingle('CREATE (x:X)', {})",
        "MATCH (n) RETURN size(n)",
        "MATCH (n) RETURN customFunction(n)",
    )


def _quoted_literal_query_contract_cases() -> tuple[str, ...]:
    return (
        "MATCH (n) WHERE n.note = 'CALL // DROP' RETURN n",
        'MATCH (n) RETURN "SHOW /* DELETE */" AS note',
    )


def _assert_manifest_query_rejected(capturer, query: str) -> None:
    with pytest.raises(capturer.ContractError):
        capturer._validate_queries([query, _manifest()["representative_queries"][0], _manifest()["representative_queries"][1]])


def _assert_restore_query_rejected(verifier, query: str) -> None:
    with pytest.raises(verifier.ContractError):
        verifier._validate_query(query)


def test_manifest_query_contract_rejects_call_admin_use_and_semicolon() -> None:
    capturer = load_manifest_capturer()

    for query in _valid_query_contract_cases():
        capturer._validate_queries([query, query, query])
    for query in _query_contract_cases():
        _assert_manifest_query_rejected(capturer, query)


def test_restore_manifest_query_contract_rejects_call_admin_use_and_semicolon() -> None:
    verifier = load_restore_verifier()

    for query in _valid_query_contract_cases():
        verifier._validate_query(query)
    for query in _query_contract_cases():
        _assert_restore_query_rejected(verifier, query)


def test_manifest_query_contract_rejects_nested_clauses_and_dynamic_functions() -> None:
    capturer = load_manifest_capturer()

    for query in _nested_query_contract_cases():
        _assert_manifest_query_rejected(capturer, query)
    for query in _quoted_literal_query_contract_cases():
        capturer._validate_queries([query, query, query])


def test_restore_manifest_query_contract_rejects_nested_clauses_and_dynamic_functions() -> None:
    verifier = load_restore_verifier()

    for query in _nested_query_contract_cases():
        _assert_restore_query_rejected(verifier, query)
    for query in _quoted_literal_query_contract_cases():
        verifier._validate_query(query)


def test_manifest_query_contract_rejects_comments_and_multiple_statements() -> None:
    capturer = load_manifest_capturer()
    for query in (
        "// hidden statement\nMATCH (n) RETURN n",
        "/* hidden statement */ MATCH (n) RETURN n",
        "MATCH (n) RETURN n // trailing statement",
        "MATCH (n) RETURN n; MATCH (m) RETURN m",
    ):
        _assert_manifest_query_rejected(capturer, query)


def test_restore_manifest_query_contract_rejects_comments_and_multiple_statements() -> None:
    verifier = load_restore_verifier()
    for query in (
        "// hidden statement\nMATCH (n) RETURN n",
        "/* hidden statement */ MATCH (n) RETURN n",
        "MATCH (n) RETURN n // trailing statement",
        "MATCH (n) RETURN n; MATCH (m) RETURN m",
    ):
        _assert_restore_query_rejected(verifier, query)


def test_manifest_and_restore_query_shell_force_cypher_read_access_mode() -> None:
    capturer = read_text(MANIFEST_CAPTURER)
    verifier = read_text(RESTORE_VERIFIER)
    for source in (capturer, verifier):
        assert re.search(r"cypher-shell[^\n]*--access-mode\s+read", source)


def test_daemon_free_contract_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_compose_uses_loopback_ports_durable_volume_and_namespaced_network() -> None:
    compose = read_text(COMPOSE)

    assert '"127.0.0.1:7474:7474"' in compose
    assert '"127.0.0.1:7687:7687"' in compose
    assert "founder_graph_neo4j_data:/data" in compose
    assert "founder_graph_neo4j_data:" in compose
    assert "internal: true" in compose
    assert "0.0.0.0:" not in compose
    assert "name: ${FOUNDER_GRAPH_COMPOSE_PROJECT:-founder-graph-local}" in compose
    assert "com.openai.founder_graph.role: live" in compose
    assert "com.openai.founder_graph.database: neo4j" in compose
    assert "name: founder_graph_neo4j_data" not in compose
    assert "name: founder_graph_local" not in compose


def test_compose_healthcheck_uses_readonly_secret_file() -> None:
    compose = read_text(COMPOSE)

    assert "image: neo4j:5.26-community" in compose
    assert "pull_policy: never" in compose
    assert "healthcheck:" in compose
    assert "cypher-shell" in compose
    assert "RETURN 1" in compose
    assert "NEO4J_AUTH_FILE: /run/secrets/founder_graph_auth" in compose
    assert "FOUNDER_GRAPH_NEO4J_AUTH_FILE" in compose
    assert "secrets:" in compose
    assert "founder_graph_auth:" in compose
    assert not re.search(r"(?m)^\s+NEO4J_AUTH\s*:", compose)
    assert "--password" not in compose
    assert "neo4j/password" not in compose.lower()


def test_helpers_are_non_destructive_and_use_secret_file_health_and_capture() -> None:
    powershell = read_text(POWERSHELL_HELPER)
    bash = read_text(BASH_HELPER)
    for helper in (powershell, bash):
        assert "database dump neo4j" in helper
        assert "database dump system" in helper
        assert "database load neo4j" in helper
        assert "database load system" in helper
        assert "founder_graph_neo4j_data" in helper
        assert "founder-graph-restore-" in helper
        assert "com.openai.founder_graph.role=restore" in helper
        assert "com.openai.founder_graph.database=neo4j" in helper
        assert "com.openai.founder_graph.project" in helper
        assert "com.openai.founder_graph.source" in helper
        assert "--overwrite-destination=true" in helper
        assert "network none" in helper
        assert "--mount" in helper
        assert "backups" in helper
        assert "capture-manifest" in helper
        assert "secret" in helper.lower()
        assert "healthy" in helper.lower()
        assert "--password" not in helper
        assert not re.search(r"NEO4J_AUTH\s*=\s*neo4j/", helper)
        assert not any(
            token in helper
            for token in ("down -v", "docker volume rm", "volume prune", "rm -rf", "Remove-Item -Recurse")
        )

        backup_section = re.split(r"Restore-Database|restore\(\)", helper, maxsplit=1)[0]
        assert "overwrite-destination" not in backup_section

    assert "find -P" in bash
    assert "umask 077" in bash
    assert "world-readable" in bash
    assert "RESTART_REQUIRED=0" in bash
    assert "wait_for_healthy\n  RESTART_REQUIRED=0" in bash
    assert "Get-Acl" in powershell
    assert "ReparsePoint" in powershell
    assert "broadReaders" in powershell


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="Bash EXIT-trap contract")
def test_bash_exit_trap_cleans_auth_secret_when_restart_health_fails(tmp_path: Path) -> None:
    """A failed dump must not leave the temporary auth file behind."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *'compose version'*) exit 0;;\n"
        "  *'compose stop'*) exit 0;;\n"
        "  *'compose run'*) exit 42;;\n"
        "  *'compose start'*) exit 0;;\n"
        "  *'compose ps'*) printf 'unhealthy\\n'; exit 0;;\n"
        "  *) exit 0;;\n"
        "esac\n",
        encoding="utf-8",
    )
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(0o700)
    sleep.chmod(0o700)

    backup = tmp_path / "backup"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "TMPDIR": str(tmp_path),
            "FOUNDER_GRAPH_NEO4J_AUTH": "neo4j/test-secret",
            "FOUNDER_GRAPH_NEO4J_AUTH_FILE": str(tmp_path / "preexisting-auth"),
        }
    )
    result = subprocess.run(
        ["bash", str(BASH_HELPER), "backup", str(backup)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "test-secret" not in result.stdout + result.stderr
    assert not list(tmp_path.glob("founder-graph-auth.*"))


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="Bash EXIT-trap contract")
def test_bash_exit_trap_restores_preexisting_auth_file_when_restart_health_fails(tmp_path: Path) -> None:
    """The recovery path restores a pre-existing auth-file environment value."""

    # Load functions without executing the script's production main entrypoint.
    source = BASH_HELPER.read_text(encoding="utf-8").replace('\nmain "$@"\n', "\n")
    helper = tmp_path / "founder-graph-functions.sh"
    helper.write_text(source, encoding="utf-8")
    secret = tmp_path / "founder-graph-auth.secret"
    secret.write_text("neo4j/test-secret", encoding="utf-8")
    restored = tmp_path / "restored-auth-path.txt"
    marker = tmp_path / "exit-status.txt"

    command = f'''\
source "{helper}"\n
set +e\n
compose() {{ return 0; }}\n
wait_for_healthy() {{ return 1; }}\n
exit() {{ printf '%s' "$FOUNDER_GRAPH_NEO4J_AUTH_FILE" > "{marker}"; return 0; }}\n
AUTH_SECRET_FILE="{secret}"\n
AUTH_FILE_WAS_SET=1\n
AUTH_FILE_ORIGINAL="{restored}"\n
FOUNDER_GRAPH_NEO4J_AUTH_FILE="{secret}"\n
RESTART_REQUIRED=1\n
false\n
on_exit\n'''
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert marker.read_text(encoding="utf-8") == str(restored)
    assert not secret.exists()


def test_powershell_dispatches_restore_verification_and_manifest_capture() -> None:
    powershell = read_text(POWERSHELL_HELPER)
    assert "'verify-restore', 'capture-manifest'" in powershell
    assert "'verify-restore'" in powershell
    assert "'capture-manifest'" in powershell
    assert "--secret-file $script:authSecretFile" in powershell
    assert "Wait-ForHealthy" in powershell


def test_tfg01_lifecycle_static_contract_includes_restart_and_persistence_evidence() -> None:
    bash = read_text(BASH_HELPER)
    powershell = read_text(POWERSHELL_HELPER)
    runbook = read_text(RUNBOOK)

    for helper in (bash, powershell):
        assert "start" in helper
        assert "stop" in helper
        assert "status" in helper
        assert "founder_graph_neo4j_data" in helper

    bash_backup = bash[bash.index("backup()") : bash.index("restore()")]
    assert bash_backup.index("compose stop neo4j") < bash_backup.index("compose start neo4j")
    powershell_backup = powershell[
        powershell.index("function Backup-Database") : powershell.index("function Restore-Database")
    ]
    assert powershell_backup.index("Invoke-Compose @('stop', 'neo4j')") < powershell_backup.index(
        "Invoke-Compose @('start', 'neo4j')"
    )

    before = runbook.index("before-stop.json")
    stop = runbook.index("founder-graph.sh stop", before)
    restart = runbook.index("founder-graph.sh start", stop)
    after = runbook.index("after-restart.json", restart)
    assert before < stop < restart < after < runbook.index("cmp --", after)
    assert "同じlive volume" in runbook
    assert "実機未検査" in runbook


def test_tfg03_restore_static_contract_keeps_both_databases_and_three_hashes() -> None:
    bash = read_text(BASH_HELPER)
    powershell = read_text(POWERSHELL_HELPER)
    verifier = read_text(RESTORE_VERIFIER)
    runbook = read_text(RUNBOOK)

    for helper in (bash, powershell):
        assert "database dump neo4j" in helper
        assert "database dump system" in helper
        assert "database load neo4j" in helper
        assert "database load system" in helper
        assert "--network none" in helper or '"none"' in helper
        assert "com.openai.founder_graph.role" in helper
        assert "com.openai.founder_graph.database" in helper

    for token in ("NODE_COUNT_QUERY", "RELATIONSHIP_COUNT_QUERY", "query_hashes", "representative_queries", "--access-mode read"):
        assert token in verifier
    for token in ("neo4j.dump", "system.dump", "--network none", "3件", "static検査済み", "実機未検査"):
        assert token in runbook


def _manifest() -> dict[str, object]:
    return {
        "node_count": 2,
        "relationship_count": 1,
        "representative_queries": [
            "MATCH (n:Idea) RETURN n.id ORDER BY n.id",
            "MATCH (n:Person) RETURN n.id ORDER BY n.id",
            "MATCH (a)-[r]->(b) RETURN a.id, type(r), b.id ORDER BY a.id, b.id",
        ],
        "query_hashes": ["0" * 64, "1" * 64, "2" * 64],
    }


def test_restore_manifest_live_alias_labels_and_whitespace_contract(tmp_path: Path) -> None:
    verifier = load_restore_verifier()
    manifest = _manifest()
    assert verifier.validate_manifest_data(manifest) == manifest
    with pytest.raises(verifier.ContractError):
        verifier.validate_manifest_data({**manifest, "query_hashes": ["0" * 64, "A" * 64, "2" * 64]})
    with pytest.raises(verifier.ContractError):
        verifier.validate_manifest_data({**manifest, "expected_project": ""})
    for alias in (
        "founder_graph_neo4j_data",
        "founder-graph-neo4j-data",
        "founder-graph-restore-live",
    ):
        with pytest.raises(verifier.ContractError):
            verifier.validate_restore_volume_name(alias)

    assert verifier.canonicalize_result(" a \r\nb \r\n") == " a \nb \n"
    assert verifier.result_hash("a\r\nb") == verifier.result_hash("a\nb")
    assert verifier.result_hash("a b") != verifier.result_hash("ab")

    secret = tmp_path / "auth"
    secret.write_text("neo4j/local-only", encoding="utf-8")
    secret.chmod(0o600)
    verifier.shutil.which = lambda _: None
    with pytest.raises(RuntimeError, match="Docker CLI is unavailable"):
        verifier.verify_live("founder-graph-restore-test", manifest, secret)


def test_restore_verifier_requires_exact_labels_and_manifest_metadata(monkeypatch) -> None:
    verifier = load_restore_verifier()
    payload = [{"Labels": {
        "com.openai.founder_graph.role": "restore",
        "com.openai.founder_graph.database": "neo4j",
        "com.openai.founder_graph.project": "founder-graph-local",
        "com.openai.founder_graph.source": "/safe/backup",
    }}]
    monkeypatch.setattr(
        verifier,
        "_run",
        lambda args, timeout=30: subprocess.CompletedProcess(args, 0, json.dumps(payload), ""),
    )
    verifier._require_restore_label(
        "founder-graph-restore-test",
        {**_manifest(), "expected_project": "founder-graph-local", "expected_source": "/safe/backup"},
    )
    for labels in (
        {"com.openai.founder_graph.role": "restore", "com.openai.founder_graph.database": "live"},
        {"com.openai.founder_graph.role": "live", "com.openai.founder_graph.database": "neo4j"},
        {
            "com.openai.founder_graph.role": "restore",
            "com.openai.founder_graph.database": "neo4j",
            "founder_graph_neo4j_data": "restore",
        },
    ):
        monkeypatch.setattr(
            verifier,
            "_run",
            lambda args, labels=labels, timeout=30: subprocess.CompletedProcess(
                args, 0, json.dumps([{"Labels": labels}]), ""
            ),
        )
        with pytest.raises(RuntimeError):
            verifier._require_restore_label("founder-graph-restore-test", _manifest())


def test_restore_verifier_accepts_prod_tokens_in_project_and_source_labels(monkeypatch) -> None:
    verifier = load_restore_verifier()
    labels = {
        "com.openai.founder_graph.role": "restore",
        "com.openai.founder_graph.database": "neo4j",
        "com.openai.founder_graph.project": "safe-prod-project",
        "com.openai.founder_graph.source": "/safe/foo-prod/run",
    }
    monkeypatch.setattr(
        verifier,
        "_run",
        lambda args, timeout=30: subprocess.CompletedProcess(args, 0, json.dumps([{"Labels": labels}]), ""),
    )
    verifier._require_restore_label(
        "founder-graph-restore-foo-prod",
        {**_manifest(), "expected_project": "safe-prod-project", "expected_source": "/safe/foo-prod/run"},
    )


def test_restore_verifier_ignores_alias_tokens_in_unrelated_labels(monkeypatch) -> None:
    verifier = load_restore_verifier()
    labels = {
        "com.openai.founder_graph.role": "restore",
        "com.openai.founder_graph.database": "neo4j",
        "com.openai.founder_graph.project": "safe-project",
        "com.openai.founder_graph.source": "/safe/backup",
        "com.example.metadata": "live prod fixture",
    }
    monkeypatch.setattr(
        verifier,
        "_run",
        lambda args, timeout=30: subprocess.CompletedProcess(args, 0, json.dumps([{"Labels": labels}]), ""),
    )
    verifier._require_restore_label("founder-graph-restore-safe", _manifest())


def test_restore_volume_name_accepts_non_live_prod_suffix() -> None:
    verifier = load_restore_verifier()
    assert verifier.validate_restore_volume_name("founder-graph-restore-foo-prod") == "founder-graph-restore-foo-prod"


def test_powershell_restore_source_requires_absolute_path() -> None:
    powershell = read_text(POWERSHELL_HELPER)
    rooted_check = powershell.index("[System.IO.Path]::IsPathRooted($RequestedPath)")
    get_item = powershell.index("Get-Item -Force -LiteralPath $RequestedPath", rooted_check)
    assert rooted_check < get_item


def test_restore_verifier_static_contract_has_safe_secret_argv() -> None:
    verifier = read_text(RESTORE_VERIFIER)
    assert '"--network"' in verifier
    assert '"none"' in verifier
    assert '"--mount"' in verifier
    assert "--secret-file" in verifier
    assert "NEO4J_AUTH_FILE=/run/secrets/founder_graph_auth" in verifier
    assert "NODE_COUNT_QUERY" in verifier
    assert "RELATIONSHIP_COUNT_QUERY" in verifier
    assert "query_hashes" in verifier
    assert "representative_queries" in verifier
    assert "--validate-only" in verifier
    assert "shutil.which(\"docker\")" in verifier
    assert "--password" not in verifier
    assert "NEO4J_AUTH=" not in verifier


def test_manifest_capture_query_contract_is_docker_free(tmp_path: Path) -> None:
    capturer = load_manifest_capturer()
    query_file = tmp_path / "queries.json"
    query_file.write_text(json.dumps({"queries": _manifest()["representative_queries"]}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(MANIFEST_CAPTURER), "--queries", str(query_file), "--output", str(tmp_path / "manifest.json"), "--validate-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert capturer.canonicalize_result("a\r\nb") == "a\nb"
    with pytest.raises(capturer.ContractError):
        capturer._validate_queries(["MATCH (n) RETURN n", "MATCH (n) RETURN n", "CREATE (n)"])
    source = read_text(MANIFEST_CAPTURER)
    assert "O_EXCL" in source
    assert "0o600" in source
    assert "--password" not in source
    assert "NEO4J_AUTH=" not in source
    output = tmp_path / "private-manifest.json"
    capturer._write_manifest(output, {"queries": _manifest()["representative_queries"]})
    with pytest.raises(capturer.ContractError):
        capturer._write_manifest(output, {"queries": []})
    capturer.shutil.which = lambda _: None
    with pytest.raises(RuntimeError, match="Docker CLI is unavailable"):
        capturer.capture_manifest(
            "neo4j-container",
            list(_manifest()["representative_queries"]),
            tmp_path / "live.json",
            "/run/secrets/founder_graph_auth",
        )


def test_runbook_documents_local_ports_secrets_persistence_capture_and_drill() -> None:
    runbook = read_text(RUNBOOK)
    required_phrases = (
        "127.0.0.1:7474",
        "127.0.0.1:7687",
        "FOUNDER_GRAPH_NEO4J_AUTH",
        "FOUNDER_GRAPH_NEO4J_AUTH_FILE",
        "founder_graph_neo4j_data",
        "FOUNDER_GRAPH_COMPOSE_PROJECT",
        "health",
        "backup",
        "restore",
        "verify-restore",
        "capture-manifest",
        "隔離",
        "neo4j.dump",
        "system.dump",
        "query_hashes",
        "world-readable",
        "symlink",
        "comma",
        "Docker",
        "live smoke",
    )
    for phrase in required_phrases:
        assert phrase in runbook
    assert "実際のDocker smoke" in runbook
    assert "利用できない" in runbook
