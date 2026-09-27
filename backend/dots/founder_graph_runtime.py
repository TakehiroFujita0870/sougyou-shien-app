"""Explicit runtime composition for persistent Founder Graph services."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import shutil
import subprocess
from typing import Any
from urllib.parse import urlsplit

from .founder_graph_neo4j import Neo4jGraphGateway
from .founder_graph_neo4j_read import Neo4jGraphReadService
from .founder_graph_neo4j_write import Neo4jGraphWriteService
from .founder_graph_local_models import LocalSearchModels


_SYNTHETIC_SEARCH_PROFILE = "e5base-synthetic"
_NORMAL_SEARCH_PROFILE = "base"
_SYNTHETIC_OWNER_ID = "dots-synthetic-test"
_SYNTHETIC_CONTAINER = "dots-chatgpt-synthetic-db"
_SYNTHETIC_VOLUME = "dots-chatgpt-synthetic-neo4j-v2"
_SYNTHETIC_BOLT_PORT = "7688"
_LIVE_CONNECTION_PROFILE = "live"
_LIVE_OWNER_ID = "owner-mvp"
_LIVE_PROJECT = "founder-graph-local"
_LIVE_CONTAINER = "founder-graph-local-neo4j-1"
_LIVE_VOLUME = "founder-graph-local_founder_graph_neo4j_data"


@dataclass(frozen=True, slots=True)
class Neo4jGraphComposition:
    """The read and write ports bound to one owner and one driver."""

    gateway: Neo4jGraphGateway
    writes: Neo4jGraphWriteService
    reads: Neo4jGraphReadService


def resolve_graph_backend() -> str:
    """Resolve one storage backend for all local composition roots.

    An explicit ``DOTS_GRAPH_BACKEND`` wins.  When it is absent, a configured
    password or protected auth file selects Neo4j; without credentials
    the isolated in-memory path remains available for tests.
    """

    configured = os.environ.get("DOTS_GRAPH_BACKEND")
    if configured is not None and configured.strip():
        backend = configured.strip().lower()
        if backend not in {"memory", "neo4j"}:
            raise ValueError("DOTS_GRAPH_BACKEND must be memory or neo4j")
        return backend
    password = os.environ.get("DOTS_NEO4J_PASSWORD", "").strip()
    auth_file = os.environ.get("DOTS_NEO4J_AUTH_FILE", "").strip()
    return "neo4j" if password or auth_file else "memory"


def _validate_live_auth_stat(file_stat: os.stat_result) -> None:
    get_effective_uid = getattr(os, "geteuid", None)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or get_effective_uid is None
        or file_stat.st_uid != get_effective_uid()
        or file_stat.st_mode & 0o077
    ):
        raise RuntimeError(
            "DOTS_NEO4J_AUTH_FILE must be a current-user-owned, owner-only regular file"
        )


def _read_neo4j_auth_file() -> tuple[str, str] | None:
    """Read one protected ``username/password`` line without exposing it."""

    _validate_live_auth_configuration()
    configured_path = os.environ.get("DOTS_NEO4J_AUTH_FILE", "").strip()
    if not configured_path:
        return None
    path = Path(configured_path).expanduser()
    if not path.is_absolute():
        raise RuntimeError("DOTS_NEO4J_AUTH_FILE must be an absolute path")
    if path.is_symlink():
        raise RuntimeError(
            "DOTS_NEO4J_AUTH_FILE must reference a readable, non-symlink regular file"
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RuntimeError(
            "DOTS_NEO4J_AUTH_FILE must reference a readable, non-symlink regular file"
        ) from None

    try:
        file_stat = os.fstat(descriptor)
        if os.environ.get("DOTS_CONNECTION_PROFILE") == _LIVE_CONNECTION_PROFILE:
            _validate_live_auth_stat(file_stat)
        elif not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(
                "DOTS_NEO4J_AUTH_FILE must reference a readable, non-symlink regular file"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as auth_stream:
            descriptor = -1
            value = auth_stream.read(4097)
    except (OSError, UnicodeDecodeError):
        raise RuntimeError("DOTS_NEO4J_AUTH_FILE could not be read as UTF-8") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if len(value) > 4096:
        raise RuntimeError("DOTS_NEO4J_AUTH_FILE exceeds the 4096-character limit")
    value = value.rstrip("\r\n")
    if "\r" in value or "\n" in value:
        raise RuntimeError("DOTS_NEO4J_AUTH_FILE must contain exactly one credential line")
    username, separator, password = value.partition("/")
    if not separator or not username or not password:
        raise RuntimeError("DOTS_NEO4J_AUTH_FILE must contain username/password")
    return username, password


def _validate_live_auth_configuration() -> None:
    """Require file-based auth for live without reading its contents here."""

    if os.environ.get("DOTS_CONNECTION_PROFILE") != _LIVE_CONNECTION_PROFILE:
        return
    if "DOTS_NEO4J_PASSWORD" in os.environ:
        raise RuntimeError("live connection forbids DOTS_NEO4J_PASSWORD; configure DOTS_NEO4J_AUTH_FILE")
    auth_file = os.environ.get("DOTS_NEO4J_AUTH_FILE", "").strip()
    if not auth_file or not Path(auth_file).is_absolute():
        raise RuntimeError("live connection requires an absolute DOTS_NEO4J_AUTH_FILE path")
    try:
        file_stat = Path(auth_file).lstat()
    except OSError:
        raise RuntimeError("live connection requires a protected DOTS_NEO4J_AUTH_FILE") from None
    _validate_live_auth_stat(file_stat)


def create_neo4j_driver_from_env() -> Any:
    """Create the local driver from explicit environment settings.

    ``DOTS_GRAPH_BACKEND=neo4j`` explicitly selects Neo4j.  The configured
    local password also selects Neo4j when the backend variable is absent.
    No fallback to an in-memory store is performed when the persistent
    configuration is incomplete, because silently losing writes would be
    worse than stopping.  ``DOTS_NEO4J_AUTH_FILE`` may point to a protected
    file containing one ``username/password`` line when an environment secret
    is not available.
    """

    _validate_live_auth_configuration()
    uri = os.environ.get("DOTS_NEO4J_URI", "bolt://127.0.0.1:7687").strip()
    username = os.environ.get("DOTS_NEO4J_USERNAME", "neo4j").strip()
    password = os.environ.get("DOTS_NEO4J_PASSWORD", "")
    if not password:
        file_credentials = _read_neo4j_auth_file()
        if file_credentials is not None:
            file_username, password = file_credentials
            configured_username = os.environ.get("DOTS_NEO4J_USERNAME", "").strip()
            if configured_username and configured_username != file_username:
                raise RuntimeError(
                    "DOTS_NEO4J_USERNAME must match the username in DOTS_NEO4J_AUTH_FILE"
                )
            username = file_username
    if not uri or not username or not password:
        raise RuntimeError(
            "DOTS_GRAPH_BACKEND=neo4j requires DOTS_NEO4J_PASSWORD or DOTS_NEO4J_AUTH_FILE; "
            "DOTS_NEO4J_URI and DOTS_NEO4J_USERNAME may also be set"
        )
    try:
        from neo4j import GraphDatabase
    except ImportError as error:  # pragma: no cover - dependency is project-required
        raise RuntimeError("the Neo4j Python driver is not installed") from error
    return GraphDatabase.driver(uri, auth=(username, password))


def close_neo4j_driver(driver: Any) -> None:
    """Close an owned Neo4j driver when its owner reaches shutdown."""

    close = getattr(driver, "close", None)
    if callable(close):
        close()


def create_neo4j_graph_composition(
    driver: Any,
    owner_id: str,
    *,
    database: str = "neo4j",
) -> Neo4jGraphComposition:
    """Build persistent graph ports without connecting or migrating implicitly."""
    connection_profile = os.environ.get("DOTS_CONNECTION_PROFILE", "local").strip() or "local"
    search_profile = os.environ.get("DOTS_SEARCH_PROFILE", _NORMAL_SEARCH_PROFILE).strip() or _NORMAL_SEARCH_PROFILE
    if connection_profile not in {"local", _LIVE_CONNECTION_PROFILE}:
        raise RuntimeError("DOTS_CONNECTION_PROFILE must be local or live")
    if connection_profile == _LIVE_CONNECTION_PROFILE:
        configured_rerank = os.environ.get("DOTS_SEARCH_RERANK_ENABLED", "").strip()
        configured_limit = os.environ.get("DOTS_SEARCH_RERANK_CANDIDATE_LIMIT", "").strip()
        if (
            search_profile != _NORMAL_SEARCH_PROFILE
            or configured_rerank not in {"", "1"}
            or configured_limit not in {"", "40"}
        ):
            raise RuntimeError("live search profile requires E5-base embeddings and reranker enabled with limit 40")
        _validate_live_search_target(owner_id=owner_id, database=database)
    if search_profile not in {_NORMAL_SEARCH_PROFILE, _SYNTHETIC_SEARCH_PROFILE}:
        raise RuntimeError("DOTS_SEARCH_PROFILE must be base or e5base-synthetic")
    if search_profile == _SYNTHETIC_SEARCH_PROFILE:
        _validate_synthetic_search_target(owner_id=owner_id, database=database)
        search_models = LocalSearchModels(embedding_profile="base")
        vector_index_name = "dots_founder_graph_vector_e5base_synthetic"
        rerank_enabled = True
        rerank_candidate_limit = 40
    else:
        configured_rerank = os.environ.get("DOTS_SEARCH_RERANK_ENABLED", "").strip()
        configured_limit = os.environ.get("DOTS_SEARCH_RERANK_CANDIDATE_LIMIT")
        if configured_rerank not in {"", "1"}:
            raise RuntimeError("normal search requires the local reranker to be enabled")
        if configured_limit is not None and configured_limit.strip() not in {"", "40"}:
            raise RuntimeError("normal search requires rerank candidate limit 40")
        search_models = LocalSearchModels(embedding_profile="base")
        vector_index_name = "dots_founder_graph_vector_e5base"
        rerank_enabled = True
        rerank_candidate_limit = 40
    gateway = Neo4jGraphGateway(driver, owner_id, database=database, search_models=search_models)
    reads = Neo4jGraphReadService(
        gateway,
        search_models=search_models,
        rerank_enabled=rerank_enabled,
        rerank_candidate_limit=rerank_candidate_limit,
        _vector_index_name=vector_index_name,
    )
    return Neo4jGraphComposition(
        gateway=gateway,
        writes=Neo4jGraphWriteService(gateway),
        reads=reads,
    )


def _validate_live_search_target(*, owner_id: str, database: str) -> None:
    """Fail closed unless live identity, rotation, review, and Docker target match."""

    _validate_live_auth_configuration()
    synthetic_environment = [name for name in os.environ if name.startswith("DOTS_SYNTHETIC_")]
    if synthetic_environment:
        raise RuntimeError("live search refuses synthetic environment settings")
    if (
        os.environ.get("DOTS_SEARCH_PROFILE", _NORMAL_SEARCH_PROFILE).strip() not in {"", _NORMAL_SEARCH_PROFILE}
        or os.environ.get("DOTS_SEARCH_RERANK_ENABLED", "").strip() not in {"", "1"}
        or os.environ.get("DOTS_SEARCH_RERANK_CANDIDATE_LIMIT", "").strip()
        not in {"", "40"}
    ):
        raise RuntimeError("live search requires the promoted E5-base search configuration")
    if (
        os.environ.get("DOTS_CONNECTION_PROFILE") != _LIVE_CONNECTION_PROFILE
        or os.environ.get("DOTS_GRAPH_BACKEND") != "neo4j"
        or owner_id != _LIVE_OWNER_ID
        or os.environ.get("DOTS_LOCAL_OWNER_ID") != _LIVE_OWNER_ID
        or database != "neo4j"
    ):
        raise RuntimeError("live search requires the reserved live owner and neo4j database")
    if os.environ.get("DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED") != "1":
        raise RuntimeError("live search requires credential rotation confirmation")
    if os.environ.get("DOTS_LIVE_EGRESS_REVIEW_CONFIRMED") != "1":
        raise RuntimeError("live search requires private projection security review confirmation")
    if os.environ.get("DOTS_NEO4J_URI", "").strip() != "bolt://127.0.0.1:7687":
        raise RuntimeError("live search requires the exact loopback Bolt URI")

    configured_docker = os.environ.get("DOTS_DOCKER_CLI", "").strip()
    if configured_docker:
        docker_path = Path(configured_docker).expanduser()
        if not docker_path.is_absolute() or not docker_path.is_file() or not os.access(docker_path, os.X_OK):
            raise RuntimeError("DOTS_DOCKER_CLI must reference an executable absolute path")
        docker = str(docker_path)
    else:
        docker = shutil.which("docker.exe") or shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI is required to verify the live graph volume")

    try:
        container_result = subprocess.run(
            [
                docker,
                "inspect",
                "--format",
                "{{json .Config.Labels}}|{{json .Mounts}}|{{json .HostConfig.Tmpfs}}|{{json .HostConfig.PortBindings}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                _LIVE_CONTAINER,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        labels_json, mounts_json, tmpfs_json, bindings_json, state, health = container_result.stdout.strip().split("|", maxsplit=5)
        labels = json.loads(labels_json)
        mounts = json.loads(mounts_json)
        tmpfs = json.loads(tmpfs_json)
        bindings = json.loads(bindings_json)
        volume_result = subprocess.run(
            [docker, "volume", "inspect", "--format", "{{json .Labels}}", _LIVE_VOLUME],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        volume_labels = json.loads(volume_result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        raise RuntimeError("the exact live graph container and volume could not be verified") from None

    data_mounts = [
        mount for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == "/data"
    ] if isinstance(mounts, list) else []
    auth_mounts = [
        mount for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == "/run/secrets/founder_graph_auth"
    ] if isinstance(mounts, list) else []
    expected_bindings = {
        "7474/tcp": "7474",
        "7687/tcp": "7687",
    }
    bindings_match = isinstance(bindings, dict) and set(bindings) == set(expected_bindings)
    if bindings_match:
        for container_port, host_port in expected_bindings.items():
            values = bindings.get(container_port)
            if (
                not isinstance(values, list)
                or len(values) != 1
                or not isinstance(values[0], dict)
                or values[0].get("HostIp") != "127.0.0.1"
                or values[0].get("HostPort") != host_port
            ):
                bindings_match = False
                break
    if (
        not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != _LIVE_PROJECT
        or labels.get("com.docker.compose.service") != "neo4j"
        or state != "running"
        or health != "healthy"
        or not isinstance(mounts, list)
        or len(mounts) != 2
        or len(data_mounts) != 1
        or data_mounts[0].get("Type") != "volume"
        or data_mounts[0].get("Name") != _LIVE_VOLUME
        or tmpfs != {"/logs": ""}
        or len(auth_mounts) != 1
        or auth_mounts[0].get("Type") != "bind"
        or auth_mounts[0].get("RW") is not False
        or not bindings_match
        or not isinstance(volume_labels, dict)
        or volume_labels.get("com.openai.founder_graph.role") != "live"
        or volume_labels.get("com.openai.founder_graph.database") != "neo4j"
    ):
        raise RuntimeError("live search requires the exact healthy live graph volume and loopback ports")


def _validate_synthetic_search_target(*, owner_id: str, database: str) -> None:
    """Fail closed unless E5-base is bound to the dedicated synthetic volume."""

    uri = os.environ.get("DOTS_NEO4J_URI", "bolt://127.0.0.1:7687").strip()
    if (
        os.environ.get("DOTS_GRAPH_BACKEND") != "neo4j"
        or owner_id != _SYNTHETIC_OWNER_ID
        or os.environ.get("DOTS_LOCAL_OWNER_ID") != _SYNTHETIC_OWNER_ID
        or database != "neo4j"
    ):
        raise RuntimeError("e5base-synthetic search requires the reserved owner and neo4j database")
    try:
        parsed_uri = urlsplit(uri)
        uri_port = parsed_uri.port
    except ValueError as error:
        raise RuntimeError("e5base-synthetic search requires the dedicated loopback Bolt URI") from error
    if (
        parsed_uri.scheme != "bolt"
        or parsed_uri.hostname != "127.0.0.1"
        or parsed_uri.username
        or parsed_uri.password
        or str(uri_port) != _SYNTHETIC_BOLT_PORT
    ):
        raise RuntimeError("e5base-synthetic search requires the dedicated loopback Bolt URI")
    configured_docker = os.environ.get("DOTS_DOCKER_CLI", "").strip()
    if configured_docker:
        docker_path = Path(configured_docker).expanduser()
        if not docker_path.is_absolute() or not docker_path.is_file() or not os.access(docker_path, os.X_OK):
            raise RuntimeError("DOTS_DOCKER_CLI must reference an executable absolute path")
        docker = str(docker_path)
    else:
        docker = shutil.which("docker.exe") or shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI is required to verify the synthetic graph volume")
    try:
        result = subprocess.run(
            [docker, "inspect", "--format", "{{json .Mounts}}|{{json .HostConfig.PortBindings}}|{{.State.Status}}", _SYNTHETIC_CONTAINER],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        mounts_json, bindings_json, state = result.stdout.strip().split("|", maxsplit=2)
        mounts = json.loads(mounts_json)
        bindings = json.loads(bindings_json)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("the dedicated synthetic graph container could not be verified") from error
    data_mounts = [
        mount for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == "/data"
    ] if isinstance(mounts, list) else []
    bolt_bindings = bindings.get("7687/tcp") if isinstance(bindings, dict) else None
    if (
        state != "running"
        or len(data_mounts) != 1
        or data_mounts[0].get("Type") != "volume"
        or data_mounts[0].get("Name") != _SYNTHETIC_VOLUME
        or not isinstance(bolt_bindings, list)
        or not any(
            isinstance(binding, dict)
            and binding.get("HostIp") == "127.0.0.1"
            and binding.get("HostPort") == _SYNTHETIC_BOLT_PORT
            for binding in bolt_bindings
        )
    ):
        raise RuntimeError("e5base-synthetic search requires the dedicated synthetic graph volume and port")
__all__ = [
    "Neo4jGraphComposition",
    "create_neo4j_driver_from_env",
    "create_neo4j_graph_composition",
    "resolve_graph_backend",
]
