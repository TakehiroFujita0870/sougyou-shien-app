"""Windows-backed persistent stop intent for the fixed Nebula live services."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from nebula.local_control_adapters import CommandResult
from nebula.local_control_runner import SubprocessCommandRunner as BoundedCommandRunner


POWERSHELL_EXE = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
STOP_INTENT_SCRIPT = (
    r"\\wsl.localhost\Ubuntu\home\hp\projects\nebula-live"
    r"\scripts\powershell\Invoke-NebulaLiveStopIntent.ps1"
)


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


class StopIntentError(RuntimeError):
    """The fixed Windows stop-intent operation could not be verified."""


class WindowsStopIntentAdapter:
    """Call the fixed Windows helper using a closed action set and argv only."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or BoundedCommandRunner(
            (POWERSHELL_EXE,),
            timeout_seconds=15,
            max_stdout_bytes=1024,
        )

    def status(self) -> str:
        result = self._invoke("Test")
        if result.stdout.strip() == "stopped=true":
            return "stopped"
        if result.stdout.strip() == "stopped=false":
            return "running"
        raise StopIntentError("The fixed Windows stop-intent status was invalid")

    def start(self) -> None:
        self._invoke("Clear", expected="ok")

    def stop(self) -> None:
        self._invoke("Set", expected="ok")

    def _invoke(self, action: str, *, expected: str | None = None) -> CommandResult:
        if action not in {"Test", "Set", "Clear"}:
            raise StopIntentError("Unsupported stop-intent operation")
        result = self._runner.run(
            (
                POWERSHELL_EXE,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                STOP_INTENT_SCRIPT,
                "-Action",
                action,
            )
        )
        if result.returncode != 0 or (expected is not None and result.stdout.strip() != expected):
            raise StopIntentError("The fixed Windows stop-intent operation failed")
        return result
