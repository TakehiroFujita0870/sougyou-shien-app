"""Fixed-target lifecycle adapters for the local Nebula control plane.

Commands are always passed as argument arrays to an injected trusted runner.
No request value is interpreted as a command, service name, or container name.
"""
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


class ServiceAdapterError(RuntimeError):
    """A fixed service could not safely complete an operation."""


class UnsafeServiceIdentity(ServiceAdapterError):
    """Observed service metadata did not match the approved target."""


class CommandFailed(ServiceAdapterError):
    """A fixed command returned an unsuccessful result."""


class DockerNeo4jAdapter:
    """Control only the existing live Neo4j container after revalidating it."""

    container_name = "founder-graph-local-neo4j-1"
    compose_project = "founder-graph-local"
    compose_service = "neo4j"
    volume_name = "founder-graph-local_founder_graph_neo4j_data"
    volume_role = "live"
    volume_database = "neo4j"
    expected_ports = {
        "7474/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7474"}],
        "7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7687"}],
    }

    def __init__(
        self,
        runner: CommandRunner,
        *,
        docker_cli: str = "docker",
        health_timeout_seconds: float = 120,
        health_poll_interval_seconds: float = 1,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not docker_cli:
            raise ValueError("docker_cli is required")
        if health_timeout_seconds <= 0 or health_poll_interval_seconds <= 0:
            raise ValueError("health wait durations must be positive")
        self._runner = runner
        self._docker_cli = docker_cli
        self._health_timeout_seconds = health_timeout_seconds
        self._health_poll_interval_seconds = health_poll_interval_seconds
        self._monotonic = monotonic
        self._sleep = sleep

    def status(self) -> str:
        container = self._validated_container()
        state = container.get("State", {})
        if state.get("Status") in {"created", "exited"}:
            return "stopped"
        if state.get("Status") != "running":
            return "unavailable"
        health = state.get("Health") or {}
        if health.get("Status") == "healthy":
            return "running"
        return "unavailable" if health.get("Status") == "unhealthy" else "starting"

    def start(self) -> None:
        container = self._validated_container()
        state = container.get("State", {}).get("Status")
        if state == "running":
            if (container.get("State", {}).get("Health") or {}).get("Status") != "healthy":
                raise ServiceAdapterError("The existing Neo4j container is not healthy")
            return
        if state not in {"created", "exited"}:
            raise ServiceAdapterError("The existing Neo4j container is in an unsafe state")
        self._run((self._docker_cli, "start", self.container_name))
        self._wait_until_healthy()

    def _wait_until_healthy(self) -> None:
        deadline = self._monotonic() + self._health_timeout_seconds
        while True:
            container = self._validated_container()
            state = container.get("State", {})
            status = state.get("Status")
            health = (state.get("Health") or {}).get("Status")
            if status == "running" and health == "healthy":
                return
            if status not in {"running", "created"} or health == "unhealthy":
                raise ServiceAdapterError("The existing Neo4j container failed before becoming healthy")
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise ServiceAdapterError("The existing Neo4j container did not become healthy before the deadline")
            self._sleep(min(self._health_poll_interval_seconds, remaining))

    def stop(self) -> None:
        container = self._validated_container()
        state = container.get("State", {}).get("Status")
        if state not in {"running", "paused"}:
            if state in {"created", "exited"}:
                return
            raise ServiceAdapterError("The existing Neo4j container is in an unsafe state")
        self._run((self._docker_cli, "stop", "--time", "60", self.container_name))
        stopped = self._validated_container()
        if stopped.get("State", {}).get("Status") not in {"exited", "created"}:
            raise ServiceAdapterError("The existing Neo4j container did not stop")

    def _validated_container(self) -> dict[str, object]:
        result = self._run((self._docker_cli, "inspect", self.container_name))
        payload = self._decode_array(result.stdout, "container")
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise UnsafeServiceIdentity("Expected exactly one existing Neo4j container")
        container = payload[0]
        if container.get("Name") != f"/{self.container_name}":
            raise UnsafeServiceIdentity("Neo4j container name did not match")
        labels = (container.get("Config") or {}).get("Labels") or {}
        if labels.get("com.docker.compose.project") != self.compose_project:
            raise UnsafeServiceIdentity("Neo4j Compose project did not match")
        if labels.get("com.docker.compose.service") != self.compose_service:
            raise UnsafeServiceIdentity("Neo4j Compose service did not match")
        mounts = container.get("Mounts") or []
        data_mounts = [mount for mount in mounts if mount.get("Destination") == "/data"]
        if len(data_mounts) != 1 or data_mounts[0].get("Type") != "volume" or data_mounts[0].get("Name") != self.volume_name:
            raise UnsafeServiceIdentity("Neo4j data volume did not match")
        if container.get("HostConfig", {}).get("PortBindings") != self.expected_ports:
            raise UnsafeServiceIdentity("Neo4j ports are not bound to the approved loopback addresses")
        self._validate_volume()
        return container

    def _validate_volume(self) -> None:
        result = self._run((self._docker_cli, "volume", "inspect", self.volume_name))
        payload = self._decode_array(result.stdout, "volume")
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise UnsafeServiceIdentity("Expected exactly one existing Neo4j data volume")
        volume = payload[0]
        if volume.get("Name") != self.volume_name:
            raise UnsafeServiceIdentity("Neo4j data volume name did not match")
        labels = volume.get("Labels") or {}
        if labels.get("com.openai.founder_graph.role") != self.volume_role or labels.get("com.openai.founder_graph.database") != self.volume_database:
            raise UnsafeServiceIdentity("Neo4j data volume labels did not match")

    def _run(self, argv: Sequence[str]) -> CommandResult:
        result = self._runner.run(argv)
        if result.returncode != 0:
            raise CommandFailed("A fixed Docker operation failed")
        return result

    @staticmethod
    def _decode_array(raw: str, description: str) -> list[object]:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise UnsafeServiceIdentity(f"Could not inspect the approved {description}") from error
        if not isinstance(value, list):
            raise UnsafeServiceIdentity(f"Could not inspect the approved {description}")
        return value


class FixedSystemdUserServiceAdapter:
    """Control exactly the approved live MCP tunnel user service."""

    service_name = "nebula-live-mcp-tunnel.service"
    health_port = "8082"

    def __init__(self, runner: CommandRunner, *, health_runner: CommandRunner | None = None) -> None:
        self._runner = runner
        self._health_runner = health_runner

    def status(self) -> str:
        self._validate_identity()
        result = self._runner.run(("systemctl", "--user", "is-active", self.service_name))
        if result.returncode == 0 and result.stdout.strip() == "active":
            try:
                health = self._tunnel_health_runner().run((
                    str(Path.home() / ".local/bin/tunnel-client"),
                    "health", "--port", self.health_port, "--require-control-plane-poll", "--json",
                ))
            except Exception:
                return "unavailable"
            if health.returncode == 0 and self._is_ready_with_control_plane_poll(health.stdout):
                return "running"
            return "unavailable"
        if result.returncode in {3, 4} and result.stdout.strip() in {"inactive", "unknown"}:
            return "stopped"
        raise CommandFailed("The fixed tunnel service status could not be read")

    def _tunnel_health_runner(self) -> CommandRunner:
        if self._health_runner is None:
            # Import lazily because the subprocess runner shares CommandResult
            # with this module. Its executable allowlist remains one fixed path.
            from nebula.local_control_runner import SubprocessCommandRunner

            self._health_runner = SubprocessCommandRunner(
                (str(Path.home() / ".local/bin/tunnel-client"),),
                timeout_seconds=5,
                max_stdout_bytes=16_384,
            )
        return self._health_runner

    @staticmethod
    def _is_ready_with_control_plane_poll(raw: str) -> bool:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("result") != "ok":
            return False
        for name in ("healthz", "readyz"):
            endpoint = payload.get(name)
            if not isinstance(endpoint, dict) or endpoint.get("ok") is not True or type(endpoint.get("status")) is not int or endpoint["status"] != 200:
                return False
        poll = payload.get("control_plane_poll")
        return (
            isinstance(poll, dict)
            and poll.get("ok") is True
            and type(poll.get("value")) is int
            and poll["value"] > 0
        )

    def start(self) -> None:
        self._validate_identity()
        self._run_action("start")
        if self.status() != "running":
            raise ServiceAdapterError("The fixed tunnel service did not become active")

    def stop(self) -> None:
        self._validate_identity()
        self._run_action("stop")

    def _validate_identity(self) -> None:
        result = self._runner.run(("systemctl", "--user", "show", "--property=Id", "--value", self.service_name))
        if result.returncode != 0 or result.stdout.strip() != self.service_name:
            raise UnsafeServiceIdentity("The approved live tunnel unit was not found")

    def _run_action(self, action: str) -> None:
        result = self._runner.run(("systemctl", "--user", action, self.service_name))
        if result.returncode != 0:
            raise CommandFailed("The fixed tunnel service operation failed")
