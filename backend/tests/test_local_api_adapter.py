from __future__ import annotations

import pytest

from dots.local_api_adapter import FixedSystemdUserApiAdapter, LocalApiServiceError
from dots.local_control_adapters import CommandResult


class FakeRunner:
    def __init__(self):
        self.calls: list[tuple[str, ...]] = []
        self.unit_id = "dots-live-api.service"
        self.active = "inactive"
        self.ignore_start = False

    def run(self, argv):
        args = tuple(argv)
        self.calls.append(args)
        if args[:4] == ("systemctl", "--user", "show", "--property=Id"):
            return CommandResult(0, self.unit_id)
        if args == ("systemctl", "--user", "is-active", "dots-live-api.service"):
            return CommandResult(0 if self.active == "active" else 3, self.active)
        if args == ("systemctl", "--user", "start", "dots-live-api.service"):
            if not self.ignore_start:
                self.active = "active"
            return CommandResult(0)
        if args == ("systemctl", "--user", "stop", "dots-live-api.service"):
            self.active = "inactive"
            return CommandResult(0)
        return CommandResult(1)


def test_controls_only_the_fixed_api_unit():
    runner = FakeRunner()
    adapter = FixedSystemdUserApiAdapter(runner)
    assert adapter.status() == "stopped"
    adapter.start()
    assert adapter.status() == "running"
    adapter.stop()
    assert adapter.status() == "stopped"
    assert all("dots-live-api.service" in call for call in runner.calls)


def test_rejects_a_unit_identity_mismatch_before_start():
    runner = FakeRunner()
    runner.unit_id = "other.service"
    with pytest.raises(LocalApiServiceError):
        FixedSystemdUserApiAdapter(runner).start()
    assert not any(call[:3] == ("systemctl", "--user", "start") for call in runner.calls)


def test_start_requires_systemd_to_activate_the_unit():
    runner = FakeRunner()
    runner.ignore_start = True
    with pytest.raises(LocalApiServiceError, match="did not become active"):
        FixedSystemdUserApiAdapter(runner).start()
