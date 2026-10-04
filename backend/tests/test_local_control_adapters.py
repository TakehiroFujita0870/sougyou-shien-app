from __future__ import annotations

import json
from pathlib import Path

import pytest

from nebula.local_control_adapters import (
    CommandResult,
    DockerNeo4jAdapter,
    FixedSystemdUserServiceAdapter,
    ServiceAdapterError,
    UnsafeServiceIdentity,
)


CONTAINER = "founder-graph-local-neo4j-1"
VOLUME = "founder-graph-local_founder_graph_neo4j_data"
PROJECT = "founder-graph-local"


def container_snapshot(*, status: str = "exited", health: str = "none", ports=None, volume=VOLUME, project=PROJECT):
    return [{
        "Name": f"/{CONTAINER}",
        "Config": {"Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.service": "neo4j",
        }},
        "State": {"Status": status, "Health": {"Status": health} if health != "none" else None},
        "Mounts": [{"Type": "volume", "Name": volume, "Destination": "/data"}],
        "HostConfig": {"PortBindings": ports or {
            "7474/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7474"}],
            "7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7687"}],
        }},
    }]


def volume_snapshot(*, name=VOLUME, role="live", database="neo4j"):
    return [{"Name": name, "Labels": {
        "com.openai.founder_graph.role": role,
        "com.openai.founder_graph.database": database,
    }}]


class FakeRunner:
    def __init__(self):
        self.calls: list[tuple[str, ...]] = []
        self.container = container_snapshot()
        self.volume = volume_snapshot()
        self.health_polls_before_ready: int | None = 0
        self.health_polls = 0
        self.database_started = False
        self.unit_id = "nebula-live-mcp-tunnel.service"
        self.active = "inactive"
        self.ignore_tunnel_start = False
        self.tunnel_health = {
            "result": "ok",
            "healthz": {"ok": True, "status": 200},
            "readyz": {"ok": True, "status": 200},
            "control_plane_poll": {"ok": True, "value": 1790403000},
        }
        self.tunnel_health_returncode = 0

    def run(self, argv):
        args = tuple(argv)
        self.calls.append(args)
        if args[:2] == ("docker", "inspect"):
            if self.database_started and self.health_polls_before_ready is not None:
                self.health_polls += 1
                if self.health_polls >= self.health_polls_before_ready:
                    self.container[0]["State"] = {"Status": "running", "Health": {"Status": "healthy"}}
            return CommandResult(0, json.dumps(self.container), "")
        if args[:3] == ("docker", "volume", "inspect"):
            return CommandResult(0, json.dumps(self.volume), "")
        if args == ("docker", "start", CONTAINER):
            self.database_started = True
            self.health_polls = 0
            self.container[0]["State"] = {"Status": "running", "Health": {"Status": "starting"}}
            return CommandResult(0, CONTAINER, "")
        if args[:3] == ("docker", "stop", "--time") and len(args) == 5:
            self.container[0]["State"] = {"Status": "exited"}
            return CommandResult(0, CONTAINER, "")
        if args[:4] == ("systemctl", "--user", "show", "--property=Id"):
            return CommandResult(0, self.unit_id, "")
        if args[:4] == ("systemctl", "--user", "is-active", "nebula-live-mcp-tunnel.service"):
            return CommandResult(0 if self.active == "active" else 3, self.active, "")
        if args[:4] == ("systemctl", "--user", "start", "nebula-live-mcp-tunnel.service"):
            if not self.ignore_tunnel_start:
                self.active = "active"
            return CommandResult(0, "", "")
        if args[:4] == ("systemctl", "--user", "stop", "nebula-live-mcp-tunnel.service"):
            self.active = "inactive"
            return CommandResult(0, "", "")
        if args == (str(Path.home() / ".local/bin/tunnel-client"), "health", "--port", "8082", "--require-control-plane-poll", "--json"):
            return CommandResult(self.tunnel_health_returncode, json.dumps(self.tunnel_health), "")
        raise AssertionError(f"unexpected command: {args!r}")


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration


def test_docker_start_checks_exact_existing_identity_and_starts_only_container():
    runner = FakeRunner()
    adapter = DockerNeo4jAdapter(runner)
    adapter.start()

    assert runner.container[0]["State"]["Status"] == "running"
    assert ("docker", "start", CONTAINER) in runner.calls
    assert not any("compose" in call for call in runner.calls)
    assert not any(call[:2] == ("docker", "run") for call in runner.calls)


def test_docker_start_waits_for_delayed_health():
    runner = FakeRunner()
    runner.health_polls_before_ready = 3
    clock = FakeClock()
    adapter = DockerNeo4jAdapter(
        runner,
        health_timeout_seconds=5,
        health_poll_interval_seconds=1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    adapter.start()

    assert runner.health_polls == 3
    assert clock.sleeps == [1, 1]
    assert adapter.status() == "running"


def test_docker_start_fails_at_health_deadline_without_unbounded_wait():
    runner = FakeRunner()
    runner.health_polls_before_ready = None
    clock = FakeClock()
    adapter = DockerNeo4jAdapter(
        runner,
        health_timeout_seconds=2,
        health_poll_interval_seconds=1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    with pytest.raises(ServiceAdapterError, match="before the deadline"):
        adapter.start()
    assert clock.now == 2
    assert clock.sleeps == [1, 1]


@pytest.mark.parametrize("mutation", [
    lambda data: data[0]["Config"]["Labels"].update({"com.docker.compose.project": "other-project"}),
    lambda data: data[0]["Mounts"][0].update({"Name": "other-volume"}),
    lambda data: data[0]["HostConfig"].update({"PortBindings": {"7687/tcp": [{"HostIp": "0.0.0.0", "HostPort": "7687"}]}}),
])
def test_docker_start_rejects_identity_mismatch_before_mutation(mutation):
    runner = FakeRunner()
    mutation(runner.container)
    adapter = DockerNeo4jAdapter(runner)

    with pytest.raises(UnsafeServiceIdentity):
        adapter.start()
    assert not any(call[:2] in {("docker", "start"), ("docker", "stop")} for call in runner.calls)


def test_docker_stop_rechecks_identity_and_stops_only_existing_container():
    runner = FakeRunner()
    runner.container = container_snapshot(status="running", health="healthy")
    DockerNeo4jAdapter(runner).stop()

    assert ("docker", "stop", "--time", "60", CONTAINER) in runner.calls
    assert runner.container[0]["State"]["Status"] == "exited"


def test_docker_already_stopped_is_idempotent_without_recreation():
    runner = FakeRunner()
    DockerNeo4jAdapter(runner).stop()
    assert not any(call[:2] == ("docker", "stop") for call in runner.calls)
    assert not any(call[:2] in {("docker", "run"), ("docker", "compose")} for call in runner.calls)


def test_docker_status_does_not_call_unsafe_states_stopped_or_starting():
    runner = FakeRunner()
    runner.container = container_snapshot(status="paused")
    assert DockerNeo4jAdapter(runner).status() == "unavailable"
    runner.container = container_snapshot(status="running", health="unhealthy")
    assert DockerNeo4jAdapter(runner).status() == "unavailable"


def test_tunnel_adapter_uses_only_the_fixed_user_unit():
    runner = FakeRunner()
    adapter = FixedSystemdUserServiceAdapter(runner, health_runner=runner)
    adapter.start()
    adapter.stop()

    assert ("systemctl", "--user", "start", "nebula-live-mcp-tunnel.service") in runner.calls
    assert ("systemctl", "--user", "stop", "nebula-live-mcp-tunnel.service") in runner.calls
    assert all("shell" not in call for call in runner.calls)


def test_tunnel_adapter_refuses_unexpected_unit_identity():
    runner = FakeRunner()
    runner.unit_id = "attacker.service"
    with pytest.raises(UnsafeServiceIdentity):
        FixedSystemdUserServiceAdapter(runner, health_runner=runner).start()
    assert not any(call[:3] == ("systemctl", "--user", "start") for call in runner.calls)


def test_tunnel_start_requires_active_postcondition():
    runner = FakeRunner()
    runner.ignore_tunnel_start = True
    with pytest.raises(ServiceAdapterError, match="did not become active"):
        FixedSystemdUserServiceAdapter(runner, health_runner=runner).start()
    assert ("systemctl", "--user", "start", "nebula-live-mcp-tunnel.service") in runner.calls


def test_tunnel_status_requires_health_ready_and_a_successful_control_plane_poll(monkeypatch, tmp_path):
    # Model another user's home directory without invoking a real tunnel.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    runner = FakeRunner()
    runner.active = "active"

    assert FixedSystemdUserServiceAdapter(runner, health_runner=runner).status() == "running"
    assert (str(tmp_path / ".local/bin/tunnel-client"), "health", "--port", "8082", "--require-control-plane-poll", "--json") in runner.calls


@pytest.mark.parametrize("mutation", [
    lambda health: health.update({"result": "failed"}),
    lambda health: health["healthz"].update({"ok": False}),
    lambda health: health["healthz"].update({"status": 503}),
    lambda health: health["readyz"].update({"ok": False}),
    lambda health: health["control_plane_poll"].update({"ok": False}),
    lambda health: health["control_plane_poll"].update({"value": 0}),
])
def test_tunnel_status_is_unavailable_without_verified_poll_readiness(mutation):
    runner = FakeRunner()
    runner.active = "active"
    mutation(runner.tunnel_health)

    assert FixedSystemdUserServiceAdapter(runner, health_runner=runner).status() == "unavailable"


def test_tunnel_status_is_unavailable_for_health_command_failure_or_malformed_json():
    runner = FakeRunner()
    runner.active = "active"
    runner.tunnel_health_returncode = 1
    adapter = FixedSystemdUserServiceAdapter(runner, health_runner=runner)
    assert adapter.status() == "unavailable"

    runner.tunnel_health_returncode = 0
    runner.tunnel_health = {"result": "ok", "healthz": "not-json-object"}
    assert adapter.status() == "unavailable"
