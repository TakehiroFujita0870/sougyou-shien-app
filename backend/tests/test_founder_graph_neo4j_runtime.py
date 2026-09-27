from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
from unittest.mock import patch

import pytest
import dots.main as main_module
import dots.founder_graph_mcp_stdio as stdio_module
from fastapi.testclient import TestClient
from dots.founder_graph import Idea, NodeType, PersonAsset, RelationType, Relationship, ResearchCampaign, ResearchRun
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService, PersistedNodeReference
from dots.founder_graph_write import IdempotencyConflictError
from dots.founder_graph_neo4j_read import Neo4jGraphReadService
from dots.founder_graph_runtime import (
    create_neo4j_driver_from_env,
    create_neo4j_graph_composition,
    resolve_graph_backend,
)
from dots.main import create_app, create_configured_app, create_neo4j_app
from dots.founder_graph_mcp_stdio import create_neo4j_stdio_server


@dataclass
class _Result:
    row: dict[str, object] | None = None

    def single(self, **_kwargs):
        if isinstance(self.row, (list, tuple)):
            return self.row[0] if self.row else None
        return self.row

    def __iter__(self):
        if isinstance(self.row, (list, tuple)):
            return iter(self.row)
        return iter(() if self.row is None else (self.row,))


class _Session:
    def __init__(self, records: dict[str, dict[str, object]]) -> None:
        self.records = records
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.audit_record: dict[str, object] | None = None

    def close(self) -> None:
        return None

    def execute_read(self, callback):
        return callback(self)

    def execute_write(self, callback):
        return callback(self)

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (n {id: $node_id, owner_id: $owner_id})" in query:
            return _Result(self.records.get(params["node_id"]))
        if "MATCH (i:Idea" in query and "RETURN i.id AS id" in query:
            if "SET i._dots_idea_write_lock" in query:
                return _Result(self.records.get(params["id"]))
            if "{id: $id, owner_id: $owner_id}" in query:
                return _Result(self.records.get(params["id"]))
            return _Result(tuple({
                **record,
                "supersedes_id": json.loads(str(record["payload_json"])).get("supersedes_id"),
            } for record in self.records.values()))
        if "FounderGraphAudit" in query and query.startswith("MATCH"):
            return _Result(self.audit_record)
        if "MATCH (n {id: $id})" in query:
            return _Result()
        if "MATCH (a {id: $source_id}), (b {id: $target_id})" in query:
            return _Result({
                "source_owner": "owner-1",
                "target_owner": "owner-1",
                "source_type": NodeType.PERSON.value,
                "target_type": NodeType.IDEA.value,
            })
        if "MATCH (s:Source" in query or "MATCH (r:SourceRevision" in query:
            return _Result()
        return _Result()


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_value = session

    def session(self, *, database: str):
        assert database == "neo4j"
        return self.session_value


class _UnavailableDriver:
    def session(self, *, database: str):
        assert database == "neo4j"
        raise OSError("Neo4j is stopped")


def test_composition_binds_one_gateway_without_implicit_connection() -> None:
    session = _Session({})
    composition = create_neo4j_graph_composition(_Driver(session), "owner-1")

    assert composition.gateway.owner_id == "owner-1"
    assert composition.writes.owner_id == composition.reads.owner_id == "owner-1"
    assert session.calls == []


def test_normal_search_defaults_to_base_and_reranks_forty_candidates(monkeypatch) -> None:
    session = _Session({})
    monkeypatch.delenv("DOTS_SEARCH_PROFILE", raising=False)
    monkeypatch.delenv("DOTS_SEARCH_RERANK_ENABLED", raising=False)
    monkeypatch.delenv("DOTS_SEARCH_RERANK_CANDIDATE_LIMIT", raising=False)

    composition = create_neo4j_graph_composition(_Driver(session), "owner-1")

    assert composition.gateway.search_models.embedding_profile == "base"
    assert composition.gateway.search_models.embedding_dimensions == 768
    assert composition.reads._vector_index_name == "dots_founder_graph_vector_e5base"
    assert composition.reads._rerank_enabled is True
    assert composition.reads._rerank_candidate_limit == 40


def test_normal_graph_writes_store_the_pinned_base_vector() -> None:
    from dots.founder_graph_local_models import E5_BASE_DIMENSIONS, E5_BASE_MODEL_ID, E5_BASE_MODEL_REVISION

    class SearchModels:
        embedding_model_id = E5_BASE_MODEL_ID
        embedding_model_revision = E5_BASE_MODEL_REVISION
        embedding_dimensions = E5_BASE_DIMENSIONS

        def embed_documents(self, texts):
            assert len(texts) == 1
            return [[0.25] * E5_BASE_DIMENSIONS]

    gateway = Neo4jGraphGateway(_Driver(_Session({})), "owner-1", search_models=SearchModels())
    properties = gateway._properties_for_node(Idea(owner_id="owner-1", title="Founder idea"))

    assert len(properties["search_embedding_e5base"]) == E5_BASE_DIMENSIONS
    assert properties["embedding_e5base_model_id"] == E5_BASE_MODEL_ID
    assert properties["embedding_e5base_model_revision"] == E5_BASE_MODEL_REVISION
    assert properties["embedding_e5base_dimensions"] == E5_BASE_DIMENSIONS
    assert "search_embedding" not in properties


def test_normal_reindex_backfills_the_base_property_and_model_provenance() -> None:
    from dots.founder_graph_local_models import E5_BASE_DIMENSIONS, E5_BASE_MODEL_ID, E5_BASE_MODEL_REVISION

    class SearchModels:
        embedding_model_id = E5_BASE_MODEL_ID
        embedding_model_revision = E5_BASE_MODEL_REVISION
        embedding_dimensions = E5_BASE_DIMENSIONS

        def embed_documents(self, texts):
            return [[0.5] * E5_BASE_DIMENSIONS for _ in texts]

    class ReindexSession(_Session):
        def __init__(self):
            super().__init__({})
            self.pending = True
            self.update_params = None

        def run(self, query: str, **params):
            self.calls.append((query, params))
            if "RETURN n.id AS id, n.search_text AS search_text" in query:
                if self.pending:
                    self.pending = False
                    return _Result({"id": "idea-1", "search_text": "Founder idea"})
                return _Result()
            if "SET n.search_embedding_e5base" in query:
                self.update_params = params
            return _Result()

    session = ReindexSession()
    gateway = Neo4jGraphGateway(_Driver(session), "owner-1", search_models=SearchModels())

    assert gateway.reindex_search_embeddings(batch_size=1) == 1
    assert session.update_params["model_id"] == E5_BASE_MODEL_ID
    assert session.update_params["model_revision"] == E5_BASE_MODEL_REVISION
    assert session.update_params["dimensions"] == E5_BASE_DIMENSIONS
    assert len(session.update_params["updates"][0]["embedding"]) == E5_BASE_DIMENSIONS


def test_normal_search_rejects_legacy_or_disabled_configuration(monkeypatch) -> None:
    session = _Session({})
    monkeypatch.setenv("DOTS_SEARCH_PROFILE", "small")
    with pytest.raises(RuntimeError, match="DOTS_SEARCH_PROFILE must be base"):
        create_neo4j_graph_composition(_Driver(session), "owner-1")

    monkeypatch.setenv("DOTS_SEARCH_PROFILE", "base")
    monkeypatch.setenv("DOTS_SEARCH_RERANK_ENABLED", "0")
    with pytest.raises(RuntimeError, match="local reranker to be enabled"):
        create_neo4j_graph_composition(_Driver(session), "owner-1")


def test_synthetic_profile_selects_base_index_and_rerank_cap_40(monkeypatch) -> None:
    session = _Session({})
    monkeypatch.setenv("DOTS_SEARCH_PROFILE", "e5base-synthetic")
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "dots-synthetic-test")
    monkeypatch.setenv("DOTS_NEO4J_URI", "bolt://127.0.0.1:7688")
    monkeypatch.setenv("DOTS_SEARCH_RERANK_ENABLED", "1")
    monkeypatch.setattr("dots.founder_graph_runtime._validate_synthetic_search_target", lambda **_kwargs: None)

    composition = create_neo4j_graph_composition(_Driver(session), "dots-synthetic-test")

    assert composition.gateway.search_models.embedding_profile == "base"
    assert composition.reads._vector_index_name == "dots_founder_graph_vector_e5base_synthetic"
    assert composition.reads._rerank_enabled is True
    assert composition.reads._rerank_candidate_limit == 40


@pytest.mark.parametrize(
    ("owner_id", "database", "uri", "backend_owner"),
    [
        ("normal-owner", "neo4j", "bolt://127.0.0.1:7688", "dots-synthetic-test"),
        ("dots-synthetic-test", "neo4j", "bolt://127.0.0.1:7687", "dots-synthetic-test"),
        ("dots-synthetic-test", "system", "bolt://127.0.0.1:7688", "dots-synthetic-test"),
        ("dots-synthetic-test", "neo4j", "bolt://localhost:7688", "dots-synthetic-test"),
        ("dots-synthetic-test", "neo4j", "bolt://127.0.0.1:7688", "normal-owner"),
    ],
)
def test_synthetic_profile_rejects_wrong_owner_database_or_uri(monkeypatch, owner_id, database, uri, backend_owner) -> None:
    from dots.founder_graph_runtime import _validate_synthetic_search_target

    monkeypatch.setenv("DOTS_SEARCH_PROFILE", "e5base-synthetic")
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", backend_owner)
    monkeypatch.setenv("DOTS_NEO4J_URI", uri)
    with pytest.raises(RuntimeError, match="synthetic"):
        _validate_synthetic_search_target(owner_id=owner_id, database=database)


@pytest.mark.parametrize("volume", ["dots-chatgpt-synthetic-neo4j-v2", "normal-dots-volume"])
def test_synthetic_profile_requires_exact_container_volume_and_loopback_binding(monkeypatch, volume) -> None:
    from types import SimpleNamespace
    from dots.founder_graph_runtime import _validate_synthetic_search_target

    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "dots-synthetic-test")
    monkeypatch.setenv("DOTS_NEO4J_URI", "bolt://127.0.0.1:7688")
    monkeypatch.setattr("dots.founder_graph_runtime.shutil.which", lambda _binary: "/usr/bin/docker")
    mounts = [{"Type": "volume", "Name": volume, "Destination": "/data"}]
    bindings = {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7688"}]}
    monkeypatch.setattr(
        "dots.founder_graph_runtime.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=f"{json.dumps(mounts)}|{json.dumps(bindings)}|running"
        ),
    )
    if volume != "dots-chatgpt-synthetic-neo4j-v2":
        with pytest.raises(RuntimeError, match="synthetic graph volume"):
            _validate_synthetic_search_target(owner_id="dots-synthetic-test", database="neo4j")
    else:
        _validate_synthetic_search_target(owner_id="dots-synthetic-test", database="neo4j")


def test_synthetic_profile_uses_explicit_docker_cli_without_systemd_path(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from dots.founder_graph_runtime import _validate_synthetic_search_target

    cli = tmp_path / "docker.exe"
    cli.write_text("", encoding="utf-8")
    cli.chmod(0o700)
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "dots-synthetic-test")
    monkeypatch.setenv("DOTS_NEO4J_URI", "bolt://127.0.0.1:7688")
    monkeypatch.setenv("DOTS_DOCKER_CLI", str(cli))
    monkeypatch.setattr("dots.founder_graph_runtime.shutil.which", lambda _binary: None)
    mounts = [{"Type": "volume", "Name": "dots-chatgpt-synthetic-neo4j-v2", "Destination": "/data"}]
    bindings = {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7688"}]}
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=f"{json.dumps(mounts)}|{json.dumps(bindings)}|running")

    monkeypatch.setattr("dots.founder_graph_runtime.subprocess.run", fake_run)
    _validate_synthetic_search_target(owner_id="dots-synthetic-test", database="neo4j")

    assert calls[0][0] == str(cli)


def test_synthetic_profile_rejects_invalid_explicit_docker_cli(monkeypatch, tmp_path) -> None:
    from dots.founder_graph_runtime import _validate_synthetic_search_target

    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "dots-synthetic-test")
    monkeypatch.setenv("DOTS_NEO4J_URI", "bolt://127.0.0.1:7688")
    monkeypatch.setenv("DOTS_DOCKER_CLI", str(tmp_path / "missing-docker.exe"))
    monkeypatch.setattr("dots.founder_graph_runtime.shutil.which", lambda _binary: "/usr/bin/docker")

    with pytest.raises(RuntimeError, match="DOTS_DOCKER_CLI"):
        _validate_synthetic_search_target(owner_id="dots-synthetic-test", database="neo4j")


def _live_inspect_result(
    *,
    project: str = "founder-graph-local",
    service: str = "neo4j",
    volume: str = "founder-graph-local_founder_graph_neo4j_data",
    role: str = "live",
    volume_database: str = "neo4j",
    host_ip: str = "127.0.0.1",
    host_port: str = "7687",
    http_host_port: str = "7474",
    state: str = "running",
    health: str = "healthy",
    extra_mount: bool = False,
    logs_tmpfs_options: str = "",
    include_logs_tmpfs: bool = True,
    secret_mount_type: str = "bind",
    secret_mount_read_write: bool = False,
    include_secret_mount: bool = True,
):
    from types import SimpleNamespace

    labels = {"com.docker.compose.project": project, "com.docker.compose.service": service}
    mounts = [{"Type": "volume", "Name": volume, "Destination": "/data"}]
    tmpfs = {"/logs": logs_tmpfs_options} if include_logs_tmpfs else None
    if include_secret_mount:
        mounts.append({
            "Type": secret_mount_type,
            "Name": "",
            "Destination": "/run/secrets/founder_graph_auth",
            "RW": secret_mount_read_write,
        })
    if extra_mount:
        mounts.append({"Type": "volume", "Name": "unexpected-volume", "Destination": "/logs"})
    bindings = {
        "7474/tcp": [{"HostIp": host_ip, "HostPort": http_host_port}],
        "7687/tcp": [{"HostIp": host_ip, "HostPort": host_port}],
    }
    volume_labels = {
        "com.openai.founder_graph.role": role,
        "com.openai.founder_graph.database": volume_database,
    }
    return [
        SimpleNamespace(stdout=f"{json.dumps(labels)}|{json.dumps(mounts)}|{json.dumps(tmpfs)}|{json.dumps(bindings)}|{state}|{health}"),
        SimpleNamespace(stdout=json.dumps(volume_labels)),
    ]


def _configure_live_guard(
    monkeypatch, tmp_path, *, owner: str = "owner-mvp", uri: str = "bolt://127.0.0.1:7687", results=None
):
    auth_file = tmp_path / "live-auth-file"
    auth_file.touch()
    auth_file.chmod(0o600)
    monkeypatch.setenv("DOTS_CONNECTION_PROFILE", "live")
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", owner)
    monkeypatch.setenv("DOTS_NEO4J_URI", uri)
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", str(auth_file))
    monkeypatch.setenv("DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED", "1")
    monkeypatch.setenv("DOTS_LIVE_EGRESS_REVIEW_CONFIRMED", "1")
    monkeypatch.delenv("DOTS_DOCKER_CLI", raising=False)
    monkeypatch.setattr("dots.founder_graph_runtime.shutil.which", lambda _binary: "/usr/bin/docker")
    queue = list(results if results is not None else _live_inspect_result())
    monkeypatch.setattr("dots.founder_graph_runtime.subprocess.run", lambda *_args, **_kwargs: queue.pop(0))


def test_live_profile_requires_both_pre_activation_gates(monkeypatch, tmp_path) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path)
    monkeypatch.setenv("DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED", "0")
    with pytest.raises(RuntimeError, match="rotation"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")

    monkeypatch.setenv("DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED", "1")
    monkeypatch.delenv("DOTS_LIVE_EGRESS_REVIEW_CONFIRMED")
    with pytest.raises(RuntimeError, match="security review"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")


@pytest.mark.parametrize(
    ("auth_file", "password_env"),
    [("", None), ("relative/live-auth", None), ("/tmp/live-auth", "test-only-not-a-secret"), ("/tmp/live-auth", "")],
)
def test_live_profile_requires_absolute_auth_file_and_rejects_password_env(
    monkeypatch, tmp_path, auth_file, password_env
) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path)
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", auth_file)
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)
    if password_env is not None:
        monkeypatch.setenv("DOTS_NEO4J_PASSWORD", password_env)
    with pytest.raises(RuntimeError, match="DOTS_NEO4J_AUTH_FILE|DOTS_NEO4J_PASSWORD"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")


@pytest.mark.parametrize(
    ("auth_file", "password_env"),
    [
        ("", None),
        ("relative/live-auth", None),
        ("/tmp/dots-live-neo4j-auth", "test-only-not-a-secret"),
        ("/tmp/dots-live-neo4j-auth", ""),
    ],
)
def test_live_driver_requires_absolute_auth_file_and_rejects_password_env(monkeypatch, auth_file, password_env) -> None:
    monkeypatch.setenv("DOTS_CONNECTION_PROFILE", "live")
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", auth_file)
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)
    if password_env is not None:
        monkeypatch.setenv("DOTS_NEO4J_PASSWORD", password_env)

    with pytest.raises(RuntimeError, match="DOTS_NEO4J_AUTH_FILE|DOTS_NEO4J_PASSWORD"):
        create_neo4j_driver_from_env()


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o777])
def test_live_auth_file_rejects_group_or_other_permissions(monkeypatch, tmp_path, mode) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path)
    auth_file = tmp_path / "live-auth-file"
    auth_file.chmod(mode)
    with pytest.raises(RuntimeError, match="owner-only"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")


def test_live_auth_file_rejects_symlink_and_non_regular_file(monkeypatch, tmp_path) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path)
    target = tmp_path / "auth-target"
    target.touch()
    target.chmod(0o600)
    link = tmp_path / "auth-link"
    link.symlink_to(target)
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", str(link))
    with pytest.raises(RuntimeError, match="owner-only"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")

    directory = tmp_path / "auth-directory"
    directory.mkdir()
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", str(directory))
    with pytest.raises(RuntimeError, match="owner-only"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")


def test_live_auth_file_requires_current_user_ownership(monkeypatch, tmp_path) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path)
    current_uid = __import__("os").geteuid()
    monkeypatch.setattr("dots.founder_graph_runtime.os.geteuid", lambda: current_uid + 1)
    with pytest.raises(RuntimeError, match="owner-only"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")


def test_live_auth_reader_rechecks_open_file_metadata_before_read(monkeypatch, tmp_path) -> None:
    import os
    from dots.founder_graph_runtime import _read_neo4j_auth_file

    _configure_live_guard(monkeypatch, tmp_path)
    auth_file = tmp_path / "live-auth-file"
    real_open = os.open

    def make_permissions_unsafe_then_open(path, flags, *args, **kwargs):
        auth_file.chmod(0o640)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("dots.founder_graph_runtime.os.open", make_permissions_unsafe_then_open)
    with pytest.raises(RuntimeError, match="owner-only"):
        _read_neo4j_auth_file()


def test_live_profile_rejects_synthetic_environment_prefix(monkeypatch, tmp_path) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path)
    monkeypatch.setenv("DOTS_SYNTHETIC_PROFILE", "enabled")
    with pytest.raises(RuntimeError, match="synthetic"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")


def test_live_profile_accepts_only_exact_read_only_container_and_volume_inspects(monkeypatch, tmp_path) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path)
    calls = []
    results = _live_inspect_result()

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return results.pop(0)

    monkeypatch.setattr("dots.founder_graph_runtime.subprocess.run", fake_run)
    _validate_live_search_target(owner_id="owner-mvp", database="neo4j")

    assert [call[0][1:3] for call in calls] == [["inspect", "--format"], ["volume", "inspect"]]
    assert calls[0][0][-1] == "founder-graph-local-neo4j-1"
    assert calls[1][0][-1] == "founder-graph-local_founder_graph_neo4j_data"
    assert all(call[1]["check"] and call[1]["capture_output"] for call in calls)


@pytest.mark.parametrize(
    ("owner", "database", "uri"),
    [
        ("dots-synthetic-test", "neo4j", "bolt://127.0.0.1:7687"),
        ("owner-mvp", "system", "bolt://127.0.0.1:7687"),
        ("owner-mvp", "neo4j", "bolt://127.0.0.1:7688"),
        ("owner-mvp", "neo4j", "bolt://localhost:7687"),
        ("owner-mvp", "neo4j", "bolt://user:pass@127.0.0.1:7687"),
    ],
)
def test_live_profile_rejects_wrong_owner_database_or_uri(monkeypatch, tmp_path, owner, database, uri) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path, owner=owner, uri=uri)
    with pytest.raises(RuntimeError, match="live"):
        _validate_live_search_target(owner_id=owner, database=database)


@pytest.mark.parametrize(
    "result_kwargs",
    [
        {"project": "dots-chatgpt-synthetic"},
        {"service": "synthetic-neo4j"},
        {"volume": "dots-chatgpt-synthetic-neo4j"},
        {"role": "synthetic"},
        {"volume_database": "synthetic"},
        {"host_ip": "0.0.0.0"},
        {"host_port": "7688"},
        {"http_host_port": "7475"},
        {"extra_mount": True},
        {"logs_tmpfs_options": "rw"},
        {"include_logs_tmpfs": False},
        {"include_secret_mount": False},
        {"secret_mount_type": "volume"},
        {"secret_mount_read_write": True},
        {"state": "exited"},
        {"health": "unhealthy"},
    ],
)
def test_live_profile_rejects_container_or_volume_identity_mismatch(monkeypatch, tmp_path, result_kwargs) -> None:
    from dots.founder_graph_runtime import _validate_live_search_target

    _configure_live_guard(monkeypatch, tmp_path, results=_live_inspect_result(**result_kwargs))
    with pytest.raises(RuntimeError, match="live"):
        _validate_live_search_target(owner_id="owner-mvp", database="neo4j")


def test_live_profile_uses_base_index_and_reranker(monkeypatch) -> None:
    session = _Session({})
    monkeypatch.setenv("DOTS_CONNECTION_PROFILE", "live")
    monkeypatch.setenv("DOTS_SEARCH_PROFILE", "base")
    monkeypatch.setenv("DOTS_SEARCH_RERANK_ENABLED", "1")
    monkeypatch.setenv("DOTS_SEARCH_RERANK_CANDIDATE_LIMIT", "40")
    monkeypatch.setattr("dots.founder_graph_runtime._validate_live_search_target", lambda **_kwargs: None)

    composition = create_neo4j_graph_composition(_Driver(session), "owner-mvp")

    assert composition.gateway.search_models.embedding_profile == "base"
    assert composition.reads._vector_index_name == "dots_founder_graph_vector_e5base"
    assert composition.reads._rerank_enabled is True
    assert composition.reads._rerank_candidate_limit == 40


def test_live_service_template_is_separate_and_inactive_by_default() -> None:
    from pathlib import Path

    service_path = Path(__file__).resolve().parents[2] / "scripts/founder-graph/dots-live-mcp-tunnel.service"
    service = service_path.read_text(encoding="utf-8")

    assert "DOTS_CONNECTION_PROFILE=live" in service
    assert "DOTS_LOCAL_OWNER_ID=owner-mvp" in service
    assert "DOTS_NEO4J_URI=bolt://127.0.0.1:7687" in service
    assert "DOTS_SEARCH_PROFILE=base" in service
    assert "DOTS_SEARCH_RERANK_ENABLED=1" in service
    assert "DOTS_SEARCH_RERANK_CANDIDATE_LIMIT=40" in service
    assert "DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED=0" in service
    assert "DOTS_LIVE_EGRESS_REVIEW_CONFIRMED=0" in service
    assert "DOTS_SEARCH_PROFILE=e5base-synthetic" not in service


@pytest.mark.parametrize(
    ("search_profile", "rerank_enabled", "candidate_limit"),
    [("e5base-synthetic", "1", "40"), ("small", "1", "40"), ("base", "0", "40"), ("base", "1", "20")],
)
def test_live_profile_rejects_synthetic_search_settings_before_target_inspection(
    monkeypatch, search_profile, rerank_enabled, candidate_limit
) -> None:
    called = False

    def validator(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setenv("DOTS_CONNECTION_PROFILE", "live")
    monkeypatch.setenv("DOTS_SEARCH_PROFILE", search_profile)
    monkeypatch.setenv("DOTS_SEARCH_RERANK_ENABLED", rerank_enabled)
    monkeypatch.setenv("DOTS_SEARCH_RERANK_CANDIDATE_LIMIT", candidate_limit)
    monkeypatch.setattr("dots.founder_graph_runtime._validate_live_search_target", validator)

    with pytest.raises(RuntimeError, match="live search profile"):
        create_neo4j_graph_composition(_Driver(_Session({})), "owner-mvp")
    assert called is False


def test_live_profile_accepts_promoted_base_search_settings(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_CONNECTION_PROFILE", "live")
    monkeypatch.setenv("DOTS_SEARCH_PROFILE", "base")
    monkeypatch.setenv("DOTS_SEARCH_RERANK_ENABLED", "1")
    monkeypatch.setenv("DOTS_SEARCH_RERANK_CANDIDATE_LIMIT", "40")
    monkeypatch.setattr("dots.founder_graph_runtime._validate_live_search_target", lambda **_kwargs: None)

    composition = create_neo4j_graph_composition(_Driver(_Session({})), "owner-mvp")

    assert composition.gateway.search_models.embedding_profile == "base"
    assert composition.reads._vector_index_name == "dots_founder_graph_vector_e5base"
    assert composition.reads._rerank_enabled is True
    assert composition.reads._rerank_candidate_limit == 40


def test_app_rejects_persistent_write_without_matching_persistent_read() -> None:
    session = _Session({})
    composition = create_neo4j_graph_composition(_Driver(session), "owner-1")

    try:
        create_app(founder_graph_write_service=composition.writes, founder_graph_owner_id="owner-1")
    except ValueError as error:
        assert "explicit founder_graph_read_service" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("persistent write must not silently use an in-memory read service")


def test_backend_resolution_prefers_explicit_memory_for_isolated_tests(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")
    monkeypatch.delenv("DOTS_NEO4J_AUTH_FILE", raising=False)
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "memory")

    assert resolve_graph_backend() == "memory"
    assert create_configured_app().title == "Dots. API"


def test_backend_resolution_uses_configured_neo4j_without_backend_flag(monkeypatch) -> None:
    monkeypatch.delenv("DOTS_GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("DOTS_NEO4J_AUTH_FILE", raising=False)
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")

    assert resolve_graph_backend() == "neo4j"


def test_backend_resolution_uses_auth_file_when_password_is_not_in_environment(
    monkeypatch, tmp_path
) -> None:
    auth_file = tmp_path / "neo4j-auth"
    auth_file.write_text("neo4j/synthetic-only-secret\n", encoding="utf-8")
    monkeypatch.delenv("DOTS_GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", str(auth_file))

    assert resolve_graph_backend() == "neo4j"


def test_neo4j_driver_reads_username_and_password_from_auth_file(
    monkeypatch, tmp_path
) -> None:
    auth_file = tmp_path / "neo4j-auth"
    auth_file.write_text("neo4j/synthetic-only-secret\n", encoding="utf-8")
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", str(auth_file))
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("DOTS_NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("DOTS_NEO4J_URI", raising=False)

    with patch("neo4j.GraphDatabase.driver", return_value="driver") as driver_factory:
        assert create_neo4j_driver_from_env() == "driver"

    driver_factory.assert_called_once_with(
        "bolt://127.0.0.1:7687", auth=("neo4j", "synthetic-only-secret")
    )


def test_neo4j_auth_file_rejects_symlinks_without_leaking_content(monkeypatch, tmp_path) -> None:
    secret = "synthetic-only-secret"
    source = tmp_path / "source"
    alias = tmp_path / "alias"
    source.write_text(f"neo4j/{secret}\n", encoding="utf-8")
    alias.symlink_to(source)
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", str(alias))
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)

    try:
        create_neo4j_driver_from_env()
    except RuntimeError as error:
        assert "non-symlink regular file" in str(error)
        assert secret not in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("auth symlinks must be rejected")


def test_neo4j_auth_file_rejects_malformed_content_without_leaking_content(
    monkeypatch, tmp_path
) -> None:
    secret = "synthetic-only-secret"
    auth_file = tmp_path / "neo4j-auth"
    auth_file.write_text(f"malformed/{secret}/extra\nsecond-line", encoding="utf-8")
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_AUTH_FILE", str(auth_file))
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)

    try:
        create_neo4j_driver_from_env()
    except RuntimeError as error:
        assert "exactly one credential line" in str(error)
        assert secret not in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("malformed auth files must be rejected")


def test_configured_app_wires_neo4j_when_selected(monkeypatch) -> None:
    session = _Session({})
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "owner-persistent")
    monkeypatch.setattr(main_module, "create_neo4j_driver_from_env", lambda: _Driver(session))

    app = create_configured_app()

    assert app.title == "Dots. API"
    assert session.calls == []


def test_configured_app_closes_only_its_owned_driver_on_shutdown(monkeypatch) -> None:
    class ClosableDriver(_Driver):
        def __init__(self):
            super().__init__(_Session({}))
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    driver = ClosableDriver()
    monkeypatch.setattr(main_module, "create_neo4j_driver_from_env", lambda: driver)

    app = create_configured_app()
    assert driver.close_calls == 0
    with TestClient(app):
        pass
    assert driver.close_calls == 1

    borrowed = ClosableDriver()
    injected_app = create_neo4j_app(borrowed, "owner-injected")
    with TestClient(injected_app):
        pass
    assert borrowed.close_calls == 0


def test_configured_app_closes_driver_if_app_composition_fails(monkeypatch) -> None:
    class ClosableDriver:
        close_calls = 0

        def close(self):
            self.close_calls += 1

    driver = ClosableDriver()
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setattr(main_module, "create_neo4j_driver_from_env", lambda: driver)
    monkeypatch.setattr(main_module, "create_neo4j_app", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("composition failed")))

    with pytest.raises(ValueError, match="composition failed"):
        create_configured_app()
    assert driver.close_calls == 1


def test_configured_neo4j_outage_fails_closed_for_fastapi_and_stdio(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.setenv("DOTS_NEO4J_PASSWORD", "local-only-test")
    monkeypatch.setenv("DOTS_LOCAL_OWNER_ID", "owner-persistent")
    monkeypatch.setattr(main_module, "create_neo4j_driver_from_env", _UnavailableDriver)
    monkeypatch.setattr(stdio_module, "create_neo4j_driver_from_env", _UnavailableDriver)

    api = TestClient(create_configured_app())
    headers = {"X-Local-Owner-Id": "owner-persistent"}
    read = api.post("/v1/founder-graph/mcp/read/search", headers=headers, json={"query": "idea"})
    write = api.post(
        "/v1/founder-graph/mcp/write/capture_idea",
        headers=headers,
        json={"title": "must not be stored in memory", "idempotency_key": "outage-write"},
    )
    with pytest.raises(RuntimeError, match="Neo4j read-only preflight failed"):
        stdio_module.create_stdio_server()

    assert read.status_code == write.status_code == 503
    assert read.json()["detail"]["code"] == write.json()["detail"]["code"] == "unavailable"


def test_unknown_backend_fails_closed_before_app_creation(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "unknown")

    try:
        create_configured_app()
    except ValueError as error:
        assert "memory or neo4j" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("unknown backend must fail closed")


def test_selected_neo4j_without_password_does_not_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("DOTS_GRAPH_BACKEND", "neo4j")
    monkeypatch.delenv("DOTS_NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("DOTS_NEO4J_AUTH_FILE", raising=False)

    try:
        create_configured_app()
    except RuntimeError as error:
        assert "DOTS_NEO4J_PASSWORD or DOTS_NEO4J_AUTH_FILE" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("Neo4j configuration errors must not fall back to memory")


def test_neo4j_app_factory_wires_matching_ports_without_connecting() -> None:
    session = _Session({})

    app = create_neo4j_app(_Driver(session), "owner-1")

    assert app.title == "Dots. API"
    assert session.calls == []


def test_neo4j_stdio_factory_uses_same_composition_without_connecting() -> None:
    session = _Session({})

    server = create_neo4j_stdio_server(_Driver(session), "owner-1")
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

    tools = response["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "search", "fetch", "fetch_idea_brief", "capture_idea", "capture_source", "capture_asset", "capture_person",
        "capture_organization", "append_claim", "capture_evidence", "link_entities", "retract_relation_assertion", "save_research_report",
        "record_decision", "record_correction", "confirm_person_merge", "save_idea_brief",
        "create_research_campaign", "approve_research_campaign", "revoke_research_campaign",
        "record_research_run", "save_researched_idea_brief",
        "capture_facet", "classify_entity", "relate_facets", "search_facets", "facet_region",
    }
    assert len(tools) == 27
    tool_by_name = {tool["name"]: tool for tool in tools}
    assert "capture_evidence" in tool_by_name
    assert tool_by_name["capture_source"]["annotations"] == {
        "readOnlyHint": False, "destructiveHint": False, "openWorldHint": False,
    }
    assert tool_by_name["capture_source"]["inputSchema"]["additionalProperties"] is False
    assert "save_idea_brief" in {tool["name"] for tool in tools}
    campaign_tools = {tool["name"]: tool for tool in tools if tool["name"].endswith("research_campaign")}
    assert set(campaign_tools) == {"create_research_campaign", "approve_research_campaign", "revoke_research_campaign"}
    assert campaign_tools["approve_research_campaign"]["annotations"]["destructiveHint"] is True
    assert campaign_tools["create_research_campaign"]["annotations"]["destructiveHint"] is False
    assert "record_research_run" in {tool["name"] for tool in tools}
    assert "save_researched_idea_brief" in {tool["name"] for tool in tools}
    assert session.calls == []


def test_neo4j_search_has_bounded_model_cold_load_budget() -> None:
    default = inspect.signature(Neo4jGraphReadService.search).parameters["timeout_ms"].default

    assert default == 30_000


def _record(node: object) -> dict[str, object]:
    props = _node_properties(node)
    record = {
        "id": props["id"],
        "owner_id": props["owner_id"],
        "node_type": props["node_type"],
        "revision": props["revision"],
        "payload_json": props["payload_json"],
    }
    if isinstance(node, Idea):
        record["supersedes_id"] = node.supersedes_id
    return record


def test_persistent_adapter_hydrates_correction_node_and_keeps_owner_bound() -> None:
    idea = Idea(owner_id="owner-1", id="idea-1", title="Persisted", revision=2)
    session = _Session({idea.id: _record(idea)})
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))

    loaded = service.get_node("idea-1")

    assert isinstance(loaded, Idea)
    assert loaded.title == "Persisted"
    assert loaded.revision == 2
    assert service.get_node("missing") is None


def test_persistent_adapter_returns_minimal_endpoint_projection_and_delegates_link() -> None:
    person = PersonAsset(owner_id="owner-1", id="person-1", name="Founder")
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea")
    session = _Session({person.id: _record(person), idea.id: _record(idea)})
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))
    relationship = Relationship.from_entities(
        source=service.get_node(person.id),
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target=service.get_node(idea.id),
        status="proposed",
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        evidence_ids=("evidence-1",),
    )

    receipt = service.link_entities(relationship, idempotency_key="link-1")

    assert isinstance(service.get_node(person.id), PersistedNodeReference)
    assert receipt.target_type == "relationship"
    assert any("CREATE (a)-[r:CAN_CONTRIBUTE_TO" in query for query, _ in session.calls)


def test_persistent_adapter_correction_uses_gateway_and_revision_guard() -> None:
    idea = Idea(owner_id="owner-1", id="idea-1", title="Before", revision=1)
    session = _Session({idea.id: _record(idea)})
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))
    replacement = idea.revise(title="After")

    receipt = service.record_correction(
        idea.id,
        replacement,
        idempotency_key="correction-1",
        expected_revision=1,
    )

    assert receipt.operation == "record_correction"
    assert receipt.revision == 2
    assert any("CREATE (n:Idea)" in query and "SET n:FounderGraphSearchable" in query for query, _ in session.calls)


def test_persistent_adapter_hydrates_campaign_and_run_with_canonical_decoders() -> None:
    campaign = ResearchCampaign(owner_id="owner-1", id="campaign-typed", purpose="Bounded test")
    run = ResearchRun(
        owner_id="owner-1", id="run-typed", campaign_id=campaign.id,
        input_snapshot={"query": "fixture"}, model_snapshot="offline-fixture-v1",
    )
    session = _Session({campaign.id: _record(campaign), run.id: _record(run)})
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))

    assert service.get_node(campaign.id) == campaign
    assert service.get_node(run.id) == run


def test_persistent_adapter_reads_owner_scoped_audit_receipt_and_checks_operation() -> None:
    session = _Session({})
    session.audit_record = {
        "operation": "record_research_run",
        "target_id": "run-1",
        "target_type": NodeType.RESEARCH_RUN.value,
        "revision": 0,
    }
    service = Neo4jGraphWriteService(Neo4jGraphGateway(_Driver(session), "owner-1"))

    receipt = service.get_write_receipt("run-key", operation="record_research_run")

    assert receipt is not None
    assert receipt.target_id == "run-1"
    assert receipt.replayed is True
    with pytest.raises(IdempotencyConflictError):
        service.get_write_receipt("run-key", operation="save_idea_brief")
