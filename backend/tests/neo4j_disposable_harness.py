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


class HarnessError(RuntimeError):
    pass


def is_opted_in(environ: Mapping[str, str]) -> bool:
    return environ.get(OPT_IN) == "1"


def safe_container_identity(
    record: Mapping[str, Any], *, name: str, run_id: str,
    volume_names: set[str], network_name: str,
) -> bool:
    labels = (record.get("Config") or {}).get("Labels") or {}
    mounts = record.get("Mounts") or []
    published = ((record.get("HostConfig") or {}).get("PortBindings") or {}).get("7687/tcp") or []
    return (
        record.get("Name") == f"/{name}"
        and labels.get(ROLE_LABEL) == "neo4j-revision-lock"
        and labels.get(RUN_LABEL) == run_id
        and (record.get("Config") or {}).get("Image") == IMAGE
        and (record.get("HostConfig") or {}).get("NetworkMode") == network_name
        and len(published) == 1 and published[0].get("HostIp") == "127.0.0.1"
        and all(mount.get("Type") == "volume" for mount in mounts)
        and {mount.get("Name") for mount in mounts} == volume_names
    )


def safe_labeled_resource(record: Mapping[str, Any], *, name: str, run_id: str) -> bool:
    labels = record.get("Labels") or {}
    return (
        record.get("Name") == name
        and labels.get(ROLE_LABEL) == "neo4j-revision-lock"
        and labels.get(RUN_LABEL) == run_id
    )


def safe_network(record: Mapping[str, Any], *, name: str, run_id: str) -> bool:
    return (
        safe_labeled_resource(record, name=name, run_id=run_id)
        and record.get("Driver") == "bridge"
        and record.get("Internal") is True
    )


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
    def __init__(self, docker: Docker, run_id: str):
        self.docker = docker
        self.run_id = run_id
        self.name = f"dots-rplock-{run_id[:16]}"
        self.network_name = f"{self.name}-net"
        self.volume_names: dict[str, str] = {}
        self.container_id: str | None = None

    def _labels(self) -> tuple[str, ...]:
        return ("--label", f"{ROLE_LABEL}=neo4j-revision-lock", "--label", f"{RUN_LABEL}={self.run_id}")

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

    def start(self) -> int:
        if not _RUN_RE.fullmatch(self.run_id):
            raise HarnessError("run identifier is invalid")
        server_version = self.docker.call("version", "--format", "{{.Server.Version}}")
        if not server_version or server_version == "<no value>":
            raise HarnessError("Docker server version is unavailable")
        targets = self._image_volumes()  # inspect only; docker create never pulls
        self.docker.call("network", "create", "--driver", "bridge", "--internal", *self._labels(), self.network_name)
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
            "--env", "NEO4J_AUTH=none",
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
        bolt = info.get("7687/tcp")
        if not isinstance(bolt, list) or len(bolt) != 1 or bolt[0].get("HostIp") != "127.0.0.1":
            raise HarnessError("Neo4j host port is not bound to loopback")
        try:
            port = int(bolt[0].get("HostPort"))
        except (TypeError, ValueError) as error:
            raise HarnessError("Neo4j loopback port is invalid") from error
        if not 1 <= port <= 65535:
            raise HarnessError("Neo4j loopback port is outside the valid range")
        return port

    def _inspect_exact(self, kind: str, name: str) -> Mapping[str, Any] | None:
        raw = self.docker.call(kind, "inspect", "--format", "{{json .}}", name, allow_missing=True)
        return None if raw is None else json_result(raw)

    def _remove_owned_container(self) -> None:
        record = self._inspect_exact("container", self.container_id or self.name)
        if record is None:
            return
        if not safe_container_identity(
            record, name=self.name, run_id=self.run_id,
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
        owned = safe_network(record, name=name, run_id=self.run_id) if kind == "network" else safe_labeled_resource(record, name=name, run_id=self.run_id)
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
        filters = ("--filter", f"label={ROLE_LABEL}=neo4j-revision-lock", "--filter", f"label={RUN_LABEL}={self.run_id}")
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
