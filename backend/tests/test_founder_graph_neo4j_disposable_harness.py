"""Pure safety checks for the disposable Neo4j test harness."""

import json
from pathlib import Path
import subprocess

import pytest

from neo4j_disposable_harness import (
    IMAGE,
    RUN_LABEL,
    ROLE_LABEL,
    DisposableNeo4j,
    Docker,
    is_opted_in,
    safe_container_identity,
    safe_labeled_resource,
    safe_network,
    loopback_bolt_port,
)


def test_real_gate_requires_exact_opt_in_without_invoking_docker():
    assert not is_opted_in({}) and not is_opted_in({"DOTS_NEO4J_REVISION_LOCK_REAL": "true"})
    assert is_opted_in({"DOTS_NEO4J_REVISION_LOCK_REAL": "1"})
    assert not is_opted_in({"DOTS_NEO4J_RELATION_ASSERTION_REAL": "true"}, "DOTS_NEO4J_RELATION_ASSERTION_REAL")
    assert is_opted_in({"DOTS_NEO4J_RELATION_ASSERTION_REAL": "1"}, "DOTS_NEO4J_RELATION_ASSERTION_REAL")


def test_disposable_harness_can_use_a_distinct_relation_assertion_identity():
    helper = DisposableNeo4j(
        None, "a" * 32, role="neo4j-relation-assertion", name_prefix="dots-relassert",
    )
    assert helper.name == "dots-relassert-aaaaaaaaaaaaaaaa"
    assert helper.network_name == "dots-relassert-aaaaaaaaaaaaaaaa-net"
    assert helper._labels() == (
        "--label", f"{ROLE_LABEL}=neo4j-relation-assertion",
        "--label", f"{RUN_LABEL}={'a' * 32}",
    )
    assert not safe_labeled_resource(
        {"Name": helper.name, "Labels": {ROLE_LABEL: "neo4j-revision-lock", RUN_LABEL: "a" * 32}},
        name=helper.name, run_id="a" * 32, role="neo4j-relation-assertion",
    )


def test_container_identity_requires_exact_run_image_network_mounts_and_loopback():
    run_id = "a" * 32
    labels = {ROLE_LABEL: "neo4j-revision-lock", RUN_LABEL: run_id}
    container = {
        "Name": "/dots-rplock-a", "Config": {"Labels": labels, "Image": IMAGE},
        "Mounts": [{"Type": "volume", "Name": "dots-rplock-a-data"}],
        "HostConfig": {"NetworkMode": "dots-rplock-a-net",
                       "PortBindings": {"7687/tcp": [{"HostIp": "127.0.0.1"}]}},
    }
    expected = {"name": "dots-rplock-a", "run_id": run_id,
                "volume_names": {"dots-rplock-a-data"}, "network_name": "dots-rplock-a-net"}
    assert safe_container_identity(container, **expected)
    for changed in (
        {**container, "Name": "/other"},
        {**container, "Config": {"Labels": {**labels, RUN_LABEL: "b" * 32}, "Image": IMAGE}},
        {**container, "Config": {"Labels": labels, "Image": "unexpected:image"}},
        {**container, "Mounts": [{"Type": "bind", "Name": "dots-rplock-a-data"}]},
        {**container, "Mounts": [{"Type": "volume", "Name": "unexpected"}]},
        {**container, "HostConfig": {"NetworkMode": "other", "PortBindings": {"7687/tcp": [{"HostIp": "0.0.0.0"}]}}},
    ):
        assert not safe_container_identity(changed, **expected)


def test_cleanup_resource_guards_reject_wrong_labels_and_internal_networks():
    run_id = "a" * 32
    labels = {ROLE_LABEL: "neo4j-revision-lock", RUN_LABEL: run_id}
    assert safe_labeled_resource({"Name": "dots-rplock-a-data", "Labels": labels},
                                  name="dots-rplock-a-data", run_id=run_id)
    assert not safe_labeled_resource({"Name": "dots-rplock-a-data", "Labels": labels},
                                      name="dots-rplock-a-data", run_id="b" * 32)
    network = {"Name": "dots-rplock-a-net", "Labels": labels, "Driver": "bridge", "Internal": False}
    assert safe_network(network, name="dots-rplock-a-net", run_id=run_id)
    assert not safe_network({**network, "Internal": True}, name="dots-rplock-a-net", run_id=run_id)
    assert not safe_network({**network, "Driver": "overlay"}, name="dots-rplock-a-net", run_id=run_id)


def test_cleanup_refuses_unowned_container_or_resource_before_remove():
    class FakeDocker:
        def __init__(self, record):
            self.record, self.commands = record, []
        def call(self, *args, **_kwargs):
            self.commands.append(args)
            if args[1] == "inspect":
                return json.dumps(self.record)
            return ""

    run_id = "a" * 32
    docker = FakeDocker({"Name": "/dots-rplock-a", "Config": {"Labels": {}}, "Mounts": []})
    helper = DisposableNeo4j(docker, run_id)
    helper.name = "dots-rplock-a"
    with pytest.raises(RuntimeError, match="refusing to remove"):
        helper._remove_owned_container()
    with pytest.raises(RuntimeError, match="refusing to remove"):
        helper._remove_owned_resource("volume", "dots-rplock-a-data")
    assert all(command[1] != "rm" for command in docker.commands)


def test_cleanup_removes_only_an_exactly_inspected_owned_volume():
    run_id = "a" * 32
    name = "dots-rplock-a-data"
    record = {"Name": name, "Labels": {
        ROLE_LABEL: "neo4j-revision-lock", RUN_LABEL: run_id,
    }}

    class FakeDocker:
        def __init__(self):
            self.commands = []
        def call(self, *args, **_kwargs):
            self.commands.append(args)
            return json.dumps(record) if args[1] == "inspect" else ""

    docker = FakeDocker()
    DisposableNeo4j(docker, run_id)._remove_owned_resource("volume", name)
    assert docker.commands == [
        ("volume", "inspect", "--format", "{{json .}}", name),
        ("volume", "rm", name),
    ]


def test_cleanup_removes_owned_container_by_inspected_id_only():
    run_id = "a" * 32
    helper = DisposableNeo4j(None, run_id)
    volume_name = f"{helper.name}-data"
    identity = "b" * 64
    helper.volume_names = {"/data": volume_name}
    helper.container_id = identity
    record = {
        "Id": identity, "Name": f"/{helper.name}",
        "Config": {"Labels": {ROLE_LABEL: "neo4j-revision-lock", RUN_LABEL: run_id}, "Image": IMAGE},
        "Mounts": [{"Type": "volume", "Name": volume_name}],
        "HostConfig": {"NetworkMode": helper.network_name,
                       "PortBindings": {"7687/tcp": [{"HostIp": "127.0.0.1"}]}},
    }

    class FakeDocker:
        def __init__(self):
            self.commands = []
        def call(self, *args, **_kwargs):
            self.commands.append(args)
            return json.dumps(record) if args[1] == "inspect" else ""

    helper.docker = FakeDocker()
    helper._remove_owned_container()
    assert helper.docker.commands == [
        ("container", "inspect", "--format", "{{json .}}", identity),
        ("container", "rm", "--force", identity),
    ]


def test_start_requests_pull_never_and_only_uses_fixed_lifecycle_commands():
    run_id = "a" * 32
    commands = []
    def run(argv, **_kwargs):
        commands.append(argv)
        if argv[1:3] == ["version", "--format"]:
            stdout = "29.8.0"
        elif argv[1:3] == ["image", "inspect"]:
            stdout = json.dumps({"/data": {}, "/logs": {}})
        elif argv[1:3] == ["volume", "create"]:
            stdout = argv[-1]
        elif argv[1:3] == ["container", "create"]:
            stdout = "b" * 64
        elif argv[1:3] == ["container", "inspect"]:
            stdout = json.dumps({"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "43123"}]})
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    port = DisposableNeo4j(Docker(Path("/fixed/docker"), run), run_id).start()
    create = next(argv for argv in commands if argv[1:3] == ["container", "create"])
    network_create = next(argv for argv in commands if argv[1:3] == ["network", "create"])
    assert "--pull=never" in create
    assert "--publish" in create and "127.0.0.1::7687" in create
    assert "--internal" not in network_create and "--driver" in network_create and "bridge" in network_create
    assert "NEO4J_dbms_usage__report_enabled=false" in create
    assert "NEO4J_server_bolt_telemetry_enabled=false" in create
    assert port == 43123
    assert all(argv[1] != "pull" for argv in commands)


@pytest.mark.parametrize("port_map", [
    None,
    {},
    {"7687/tcp": None},
    {"7687/tcp": []},
    {"7687/tcp": [{"HostIp": "0.0.0.0", "HostPort": "43123"}]},
    {"7687/tcp": [{"HostIp": "192.0.2.1", "HostPort": "43123"}]},
    {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "not-a-port"}]},
    {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "0"}]},
    {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "65536"}]},
    {"7687/tcp": [
        {"HostIp": "127.0.0.1", "HostPort": "43123"},
        {"HostIp": "127.0.0.1", "HostPort": "43124"},
    ]},
])
def test_loopback_port_parser_rejects_absent_or_unsafe_mappings(port_map):
    with pytest.raises(RuntimeError):
        loopback_bolt_port(port_map)


@pytest.mark.parametrize("host_port,expected", [("1", 1), ("43123", 43123), ("65535", 65535)])
def test_loopback_port_parser_accepts_exact_single_mapping(host_port, expected):
    assert loopback_bolt_port({"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": host_port}]}) == expected


def test_partial_volume_create_failure_tracks_and_exactly_cleans_candidates():
    run_id = "a" * 32
    labels = {ROLE_LABEL: "neo4j-revision-lock", RUN_LABEL: run_id}

    class FakeDocker:
        def __init__(self):
            self.commands = []
            self.volumes = {}
            self.network = None
        def call(self, *args, allow_missing=False):
            self.commands.append(args)
            if args[:2] == ("version", "--format"):
                return "29.8.0"
            if args[:2] == ("image", "inspect"):
                return json.dumps({"/data": {}, "/logs": {}})
            if args[:2] == ("network", "create"):
                self.network = {"Name": args[-1], "Labels": labels, "Driver": "bridge", "Internal": False}
                return "network-id"
            if args[:2] == ("volume", "create"):
                name = args[-1]
                self.volumes[name] = {"Name": name, "Labels": labels}
                return name if name.endswith("-data") else "unexpected-response"
            if args[0] == "container" and args[1] == "inspect":
                if allow_missing:
                    return None
            if args[0] == "volume" and args[1] == "inspect":
                return json.dumps(self.volumes[args[-1]])
            if args[0] == "network" and args[1] == "inspect":
                return json.dumps(self.network)
            if args[:2] == ("volume", "rm"):
                self.volumes.pop(args[-1])
                return ""
            if args[:2] == ("network", "rm"):
                self.network = None
                return ""
            if args[:2] == ("container", "ls"):
                return ""
            if args[:2] == ("volume", "ls"):
                return "\n".join(self.volumes)
            if args[:2] == ("network", "ls"):
                return self.network["Name"] if self.network else ""
            raise AssertionError(f"unexpected fake Docker operation: {args[:2]}")

    docker = FakeDocker()
    helper = DisposableNeo4j(docker, run_id)
    with pytest.raises(RuntimeError, match="expected named volume"):
        helper.start()
    assert len(helper.volume_names) == 2
    assert not any(command[:2] == ("container", "create") for command in docker.commands)
    helper.close()
    assert docker.volumes == {}
    assert docker.network is None
    assert [command for command in docker.commands if command[:2] == ("volume", "rm")] == [
        ("volume", "rm", "dots-rplock-aaaaaaaaaaaaaaaa-data"),
        ("volume", "rm", "dots-rplock-aaaaaaaaaaaaaaaa-logs"),
    ]
    assert sum(command[:2] == ("network", "rm") for command in docker.commands) == 1
    inventories = [command for command in docker.commands if len(command) > 1 and command[1] == "ls"]
    assert {command[0] for command in inventories} == {"container", "volume", "network"}
    assert all(f"label={ROLE_LABEL}=neo4j-revision-lock" in command for command in inventories)
    assert all(f"label={RUN_LABEL}={run_id}" in command for command in inventories)


def test_docker_failures_do_not_echo_stderr_or_run_unbounded_commands():
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1, "", "secret-like docker diagnostic")

    with pytest.raises(RuntimeError, match="exit code 1") as error:
        Docker(Path("/fixed/docker"), run).call("container", "inspect", "fixture")
    assert "secret-like" not in str(error.value)
    assert calls[0][1]["timeout"] <= 15
    assert calls[0][1]["capture_output"] is True
