"""Fixed-target adapter for the local Dots. FastAPI user service."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class CommandResult(Protocol):
    returncode: int
    stdout: str


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


class LocalApiServiceError(RuntimeError):
    """The fixed Dots. API unit could not be safely controlled."""


class FixedSystemdUserApiAdapter:
    """Control only the dormant live API user unit."""

    service_name = "dots-live-api.service"

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def status(self) -> str:
        self._validate_identity()
        result = self._runner.run(("systemctl", "--user", "is-active", self.service_name))
        if result.returncode == 0 and result.stdout.strip() == "active":
            return "running"
        if result.returncode in {3, 4} and result.stdout.strip() in {"inactive", "unknown"}:
            return "stopped"
        raise LocalApiServiceError("The fixed local API service status could not be read")

    def start(self) -> None:
        self._validate_identity()
        self._run_action("start")
        if self.status() != "running":
            raise LocalApiServiceError("The fixed local API service did not become active")

    def stop(self) -> None:
        self._validate_identity()
        self._run_action("stop")

    def _validate_identity(self) -> None:
        result = self._runner.run(("systemctl", "--user", "show", "--property=Id", "--value", self.service_name))
        if result.returncode != 0 or result.stdout.strip() != self.service_name:
            raise LocalApiServiceError("The approved local API unit was not found")

    def _run_action(self, action: str) -> None:
        result = self._runner.run(("systemctl", "--user", action, self.service_name))
        if result.returncode != 0:
            raise LocalApiServiceError("The fixed local API service operation failed")
