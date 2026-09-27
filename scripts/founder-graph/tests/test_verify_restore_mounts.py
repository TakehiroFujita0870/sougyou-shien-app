from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIRECTORY))

import verify_restore  # noqa: E402 - the script directory is added for this standalone helper test


def test_restore_volume_input_rejects_commas() -> None:
    with pytest.raises(verify_restore.ContractError, match="restore volume names must not contain commas"):
        verify_restore.validate_restore_volume_name("founder-graph-restore-bad,name")


def test_secret_file_input_rejects_commas_before_access() -> None:
    with pytest.raises(verify_restore.ContractError, match="Docker --mount paths must not contain commas"):
        verify_restore._validate_secret_file(Path("C:/private/bad,name.secret"))


def test_verify_live_allows_docker_mount_option_commas(monkeypatch: pytest.MonkeyPatch) -> None:
    docker_arguments: list[list[str]] = []

    monkeypatch.setattr(verify_restore, "validate_restore_volume_name", lambda _volume: None)
    monkeypatch.setattr(verify_restore, "validate_manifest_data", lambda manifest: manifest)
    monkeypatch.setattr(
        verify_restore,
        "_validate_secret_file",
        lambda _path: Path("C:/private/auth.secret"),
    )
    monkeypatch.setattr(verify_restore, "_require_docker", lambda: None)
    monkeypatch.setattr(verify_restore, "_require_restore_label", lambda _volume, _manifest: None)

    def fake_run(arguments: list[str], *, timeout: int = 30) -> SimpleNamespace:
        del timeout
        docker_arguments.append(arguments)
        return SimpleNamespace(returncode=1 if arguments[1] == "run" else 0, stdout="")

    monkeypatch.setattr(verify_restore, "_run", fake_run)

    with pytest.raises(RuntimeError, match="could not boot the isolated restore container"):
        verify_restore.verify_live(
            "founder-graph-restore-mount-test",
            {},
            Path("C:/private/auth.secret"),
        )

    assert docker_arguments[0][1:5] == ["network", "create", "--driver", "bridge"]
    assert "--internal" in docker_arguments[0]
    run_call = next(call for call in docker_arguments if call[1] == "run")
    arguments = run_call
    environment = [arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == "--env"]
    assert "NEO4J_db_logs_query_parameter__logging__enabled=false" in environment
    assert "NEO4J_db_logs_query_parameter__logging_enabled=false" not in environment
    mounts = [arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == "--mount"]
    assert mounts == [
        "type=volume,source=founder-graph-restore-mount-test,target=/data",
        "type=bind,source=C:/private/auth.secret,target=/run/secrets/founder_graph_auth,readonly",
    ]
    assert arguments[arguments.index("--network") + 1].startswith("founder-graph-restore-net-")
    assert "--publish" not in arguments and "-p" not in arguments


def _configure_verifier_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    restored_node_count: int = 1,
    container_status: str | None = None,
) -> list[list[str]]:
    docker_calls: list[list[str]] = []
    state: dict[str, str] = {}

    monkeypatch.setattr(verify_restore, "validate_restore_volume_name", lambda _volume: None)
    monkeypatch.setattr(verify_restore, "validate_manifest_data", lambda manifest: manifest)
    monkeypatch.setattr(verify_restore, "_validate_secret_file", lambda _path: Path("C:/private/auth.secret"))
    monkeypatch.setattr(verify_restore, "_require_docker", lambda: None)
    monkeypatch.setattr(verify_restore, "_require_restore_label", lambda _volume, _manifest: None)

    def fake_query(_container: str, _secret_path: str, query: str, timeout: int = 30) -> str:
        del timeout
        if query == verify_restore.NODE_COUNT_QUERY:
            return f"{restored_node_count}\n"
        if query == verify_restore.RELATIONSHIP_COUNT_QUERY:
            return "1\n"
        return "1\n"

    monkeypatch.setattr(verify_restore, "_exec_query", fake_query)

    def fake_run(arguments: list[str], *, timeout: int = 30) -> SimpleNamespace:
        del timeout
        docker_calls.append(arguments)
        command = arguments[1]
        if command == "network":
            if arguments[2] == "create":
                state["network"] = arguments[-1]
            return SimpleNamespace(returncode=0, stdout="")
        if command == "run":
            state["container"] = arguments[arguments.index("--name") + 1]
            return SimpleNamespace(returncode=0, stdout="")
        if command == "stop":
            return SimpleNamespace(returncode=1, stdout="")
        if command == "ps":
            stdout = f"{state['container']}|{container_status}\n" if container_status else ""
            return SimpleNamespace(returncode=0, stdout=stdout)
        if command == "network" and arguments[2] == "rm":
            return SimpleNamespace(returncode=0, stdout="")
        raise AssertionError(f"unexpected Docker command: {command}")

    monkeypatch.setattr(verify_restore, "_run", fake_run)
    return docker_calls


def _matching_manifest() -> dict[str, object]:
    return {
        "node_count": 1,
        "relationship_count": 1,
        "representative_queries": [],
        "query_hashes": [],
    }


def test_verify_live_accepts_auto_removed_container_after_stop_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker_calls = _configure_verifier_cleanup(monkeypatch)

    verify_restore.verify_live(
        "founder-graph-restore-mount-test",
        _matching_manifest(),
        Path("C:/private/auth.secret"),
    )

    assert [call[1] for call in docker_calls] == ["network", "run", "stop", "ps", "network"]


def test_verify_live_blocks_if_verifier_container_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker_calls = _configure_verifier_cleanup(monkeypatch, container_status="Up 2 seconds")

    with pytest.raises(RuntimeError, match="isolated restore verifier container remains"):
        verify_restore.verify_live(
            "founder-graph-restore-mount-test",
            _matching_manifest(),
            Path("C:/private/auth.secret"),
        )

    assert [call[1] for call in docker_calls] == ["network", "run", "stop", "ps"]


def test_verify_live_preserves_original_error_if_container_was_auto_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker_calls = _configure_verifier_cleanup(monkeypatch, restored_node_count=2)

    with pytest.raises(RuntimeError, match="restored node count did not match the manifest"):
        verify_restore.verify_live(
            "founder-graph-restore-mount-test",
            _matching_manifest(),
            Path("C:/private/auth.secret"),
        )

    assert [call[1] for call in docker_calls] == ["network", "run", "stop", "ps", "network"]
