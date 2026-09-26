"""Safety-bound Docker lifecycle helpers for opt-in Neo4j tests only."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping


OPT_IN = "DOTS_NEO4J_REVISION_LOCK_REAL"
IMAGE = "neo4j:5.26-community"
ROLE_LABEL = "com.openai.dots.test"
RUN_LABEL = "com.openai.dots.test_run"
DOCKER_CLI_CANDIDATES = (
    Path("/mnt/c/Users/hp/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"),
    Path("/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"),
)
_RUN_RE = re.compile(r"^[0-9a-f]{32}$")
_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_PREFIX_RE = re.compile(r"^dots-[a-z0-9-]{1,32}$")


class HarnessError(RuntimeError):
    pass


def is_opted_in(environ: Mapping[str, str], variable: str = OPT_IN) -> bool:
    return environ.get(variable) == "1"


def safe_container_identity(
    record: Mapping[str, Any], *, name: str, run_id: str,
    volume_names: set[str], network_name: str, role: str = "neo4j-revision-lock",
) -> bool:
    labels = (record.get("Config") or {}).get("Labels") or {}
    mounts = record.get("Mounts") or []
    published = ((record.get("HostConfig") or {}).get("PortBindings") or {}).get("7687/tcp") or []
    return (
        record.get("Name") == f"/{name}"
        and labels.get(ROLE_LABEL) == role
        and labels.get(RUN_LABEL) == run_id
        and (record.get("Config") or {}).get("Image") == IMAGE
        and (record.get("HostConfig") or {}).get("NetworkMode") == network_name
        and len(published) == 1 and published[0].get("HostIp") == "127.0.0.1"
        and all(mount.get("Type") == "volume" for mount in mounts)
        and {mount.get("Name") for mount in mounts} == volume_names
    )


def safe_labeled_resource(
    record: Mapping[str, Any], *, name: str, run_id: str,
    role: str = "neo4j-revision-lock",
) -> bool:
    labels = record.get("Labels") or {}
    return (
        record.get("Name") == name
        and labels.get(ROLE_LABEL) == role
        and labels.get(RUN_LABEL) == run_id
    )


def safe_network(
    record: Mapping[str, Any], *, name: str, run_id: str,
    role: str = "neo4j-revision-lock",
) -> bool:
    return (
        safe_labeled_resource(record, name=name, run_id=run_id, role=role)
        and record.get("Driver") == "bridge"
        and record.get("Internal") is False
    )


def loopback_bolt_port(port_map: Any) -> int:
    """Require an actual single IPv4-loopback Bolt publication."""
    if not isinstance(port_map, Mapping):
        raise HarnessError("Docker returned invalid published-port metadata")
    bindings = port_map.get("7687/tcp")
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise HarnessError("Neo4j Bolt port is not published exactly once")
    binding = bindings[0]
    if not isinstance(binding, Mapping) or binding.get("HostIp") != "127.0.0.1":
        raise HarnessError("Neo4j host port is not bound to loopback")
    host_port = binding.get("HostPort")
    if not isinstance(host_port, str) or not host_port.isdecimal():
        raise HarnessError("Neo4j loopback port is invalid")
    port = int(host_port)
    if not 1 <= port <= 65535:
        raise HarnessError("Neo4j loopback port is outside the valid range")
    return port


class Docker:
    def __init__(self, executable: Path, run: Callable[..., subprocess.CompletedProcess[str]] | None = None):
        self.executable = executable
        self._run = run or subprocess.run

    def call(self, *args: str, allow_missing: bool = False) -> str | None:
        try:
            result = self._run(
                [str(self.executable), *args], capture_output=True, text=True,
                errors="replace", timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise HarnessError(f"Docker {args[0]} could not be completed") from error
        if result.returncode:
            diagnostic = result.stderr.lower()
            resource_kind = args[0] if args[0] in {"container", "volume", "network"} else "object"
            if allow_missing and ("no such object" in diagnostic or f"no such {resource_kind}" in diagnostic):
                return None
            raise HarnessError(f"Docker {args[0]} failed with exit code {result.returncode}")
        return result.stdout.strip()


def fixed_docker() -> Docker | None:
    executable = next((path for path in DOCKER_CLI_CANDIDATES if path.is_file()), None)
    return Docker(executable) if executable else None


def json_result(value: str | None) -> Mapping[str, Any]:
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError) as error:
        raise HarnessError("Docker returned invalid JSON metadata") from error
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    if not isinstance(parsed, Mapping):
        raise HarnessError("Docker returned invalid JSON metadata")
    return parsed


class DisposableNeo4j:
    def __init__(
        self, docker: Docker, run_id: str, *,
        role: str = "neo4j-revision-lock", name_prefix: str = "dots-rplock",
    ):
        if not _ROLE_RE.fullmatch(role) or not _PREFIX_RE.fullmatch(name_prefix):
            raise HarnessError("disposable Neo4j role or name prefix is invalid")
        self.docker = docker
        self.run_id = run_id
        self.role = role
        self.name = f"{name_prefix}-{run_id[:16]}"
        self.network_name = f"{self.name}-net"
        self.volume_names: dict[str, str] = {}
        self.container_id: str | None = None

    def _labels(self) -> tuple[str, ...]:
        return ("--label", f"{ROLE_LABEL}={self.role}", "--label", f"{RUN_LABEL}={self.run_id}")

    def _image_volumes(self) -> tuple[str, ...]:
        raw = self.docker.call("image", "inspect", "--format", "{{json .Config.Volumes}}", IMAGE)
        try:
            volumes = json.loads(raw or "null")
        except ValueError as error:
            raise HarnessError("Neo4j image volume metadata is invalid") from error
        if not isinstance(volumes, Mapping) or not volumes:
            raise HarnessError("Neo4j image declares no inspectable volume targets")
        targets = tuple(sorted(volumes))
        if any(not isinstance(target, str) or not target.startswith("/") or ".." in target.split("/") for target in targets):
            raise HarnessError("Neo4j image volume targets are outside the expected contract")
        return targets

    def start(self, *, auth: str = "none") -> int:
        if not _RUN_RE.fullmatch(self.run_id):
            raise HarnessError("run identifier is invalid")
        if auth != "none" and not re.fullmatch(r"neo4j/[A-Za-z0-9_-]{16,128}", auth):
            raise HarnessError("disposable Neo4j authentication value is invalid")
        server_version = self.docker.call("version", "--format", "{{.Server.Version}}")
        if not server_version or server_version == "<no value>":
            raise HarnessError("Docker server version is unavailable")
        targets = self._image_volumes()  # inspect only; docker create never pulls
        self.docker.call("network", "create", "--driver", "bridge", *self._labels(), self.network_name)
        for target in targets:
            slug = re.sub(r"[^a-z0-9]+", "-", target.strip("/").lower()).strip("-")
            if not slug:
                raise HarnessError("Neo4j image volume target cannot be safely named")
            volume_name = f"{self.name}-{slug}"
            # Record the exact candidate first so finally-cleanup can inspect it
            # even if Docker returns an unexpected result after creating it.
            self.volume_names[target] = volume_name
            created_volume = self.docker.call("volume", "create", *self._labels(), volume_name)
            if created_volume != volume_name:
                raise HarnessError("Docker did not return the expected named volume")
        command = [
            "container", "create", "--name", self.name, *self._labels(),
            "--network", self.network_name, "--publish", "127.0.0.1::7687", "--pull=never",
            "--env", f"NEO4J_AUTH={auth}",
            "--env", "NEO4J_dbms_usage__report_enabled=false",
            "--env", "NEO4J_server_bolt_telemetry_enabled=false",
        ]
        for target, volume_name in sorted(self.volume_names.items()):
            command.extend(("--mount", f"type=volume,src={volume_name},dst={target}"))
        command.append(IMAGE)
        created = self.docker.call(*command)
        if not isinstance(created, str) or not _ID_RE.fullmatch(created):
            raise HarnessError("Docker did not return a valid disposable container identity")
        self.container_id = created
        self.docker.call("container", "start", created)
        info = json_result(self.docker.call("container", "inspect", "--format", "{{json .NetworkSettings.Ports}}", created))
        return loopback_bolt_port(info)

    def restart(self) -> int:
        """Restart this exact owned container without replacing its volumes."""
        if not isinstance(self.container_id, str) or not _ID_RE.fullmatch(self.container_id):
            raise HarnessError("refusing restart without the exact disposable container id")
        record = self._inspect_exact("container", self.container_id)
        if record is None or not safe_container_identity(
            record, name=self.name, run_id=self.run_id, role=self.role,
            volume_names=set(self.volume_names.values()), network_name=self.network_name,
        ):
            raise HarnessError("refusing to restart a container outside this test run")
        if record.get("Id") != self.container_id or (record.get("State") or {}).get("Running") is not True:
            raise HarnessError("refusing restart unless the exact disposable container is running")
        self.docker.call("container", "stop", self.container_id)
        self.docker.call("container", "start", self.container_id)
        restarted = self._inspect_exact("container", self.container_id)
        if restarted is None or not safe_container_identity(
            restarted, name=self.name, run_id=self.run_id, role=self.role,
            volume_names=set(self.volume_names.values()), network_name=self.network_name,
        ) or restarted.get("Id") != self.container_id or (restarted.get("State") or {}).get("Running") is not True:
            raise HarnessError("disposable container identity changed during restart")
        return loopback_bolt_port((restarted.get("NetworkSettings") or {}).get("Ports"))

    def _inspect_exact(self, kind: str, name: str) -> Mapping[str, Any] | None:
        raw = self.docker.call(kind, "inspect", "--format", "{{json .}}", name, allow_missing=True)
        return None if raw is None else json_result(raw)

    def _remove_owned_container(self) -> None:
        record = self._inspect_exact("container", self.container_id or self.name)
        if record is None:
            return
        if not safe_container_identity(
            record, name=self.name, run_id=self.run_id, role=self.role,
            volume_names=set(self.volume_names.values()), network_name=self.network_name,
        ):
            raise HarnessError("refusing to remove a container outside this test run")
        identity = record.get("Id")
        if not isinstance(identity, str) or not _ID_RE.fullmatch(identity) or (self.container_id and identity != self.container_id):
            raise HarnessError("refusing cleanup without an exact inspected container id")
        self.docker.call("container", "rm", "--force", identity)

    def _remove_owned_resource(self, kind: str, name: str) -> None:
        record = self._inspect_exact(kind, name)
        if record is None:
            return
        owned = (
            safe_network(record, name=name, run_id=self.run_id, role=self.role)
            if kind == "network"
            else safe_labeled_resource(record, name=name, run_id=self.run_id, role=self.role)
        )
        if not owned:
            raise HarnessError(f"refusing to remove an unowned {kind}")
        self.docker.call(kind, "rm", name)

    def close(self) -> None:
        errors: list[str] = []
        try:
            self._remove_owned_container()
        except HarnessError as error:
            errors.append(str(error))
        for volume_name in self.volume_names.values():
            try:
                self._remove_owned_resource("volume", volume_name)
            except HarnessError as error:
                errors.append(str(error))
        try:
            self._remove_owned_resource("network", self.network_name)
        except HarnessError as error:
            errors.append(str(error))
        filters = ("--filter", f"label={ROLE_LABEL}={self.role}", "--filter", f"label={RUN_LABEL}={self.run_id}")
        try:
            containers = self.docker.call("container", "ls", "--all", "--quiet", *filters) or ""
            volumes = self.docker.call("volume", "ls", "--quiet", *filters) or ""
            networks = self.docker.call("network", "ls", "--quiet", *filters) or ""
            if containers.strip() or volumes.strip() or networks.strip():
                errors.append("test-run Docker resources remain after exact cleanup")
        except HarnessError as error:
            errors.append(str(error))
        if errors:
            raise HarnessError("; ".join(errors))
