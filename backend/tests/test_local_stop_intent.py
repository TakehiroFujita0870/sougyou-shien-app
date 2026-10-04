from __future__ import annotations

from collections.abc import Sequence

import pytest

from nebula.local_stop_intent import (
    POWERSHELL_EXE,
    STOP_INTENT_SCRIPT,
    CommandResult,
    StopIntentError,
    WindowsStopIntentAdapter,
)
from nebula.local_control_runner import SubprocessCommandRunner


class FakeRunner:
    def __init__(self, results: list[CommandResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str]) -> CommandResult:
        self.calls.append(tuple(argv))
        return self.results.pop(0)


def test_stop_uses_fixed_helper_and_sets_intent_first() -> None:
    runner = FakeRunner([CommandResult(0, "ok\n")])

    WindowsStopIntentAdapter(runner).stop()

    assert runner.calls == [
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
            "Set",
        )
    ]


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [("stopped=true\n", "stopped"), ("stopped=false\n", "running")],
)
def test_status_accepts_only_safe_marker_values(stdout: str, expected: str) -> None:
    adapter = WindowsStopIntentAdapter(FakeRunner([CommandResult(0, stdout)]))

    assert adapter.status() == expected


def test_start_clears_only_through_fixed_action() -> None:
    runner = FakeRunner([CommandResult(0, "ok\n")])

    WindowsStopIntentAdapter(runner).start()

    assert runner.calls[0][-2:] == ("-Action", "Clear")


@pytest.mark.parametrize(
    "result",
    [
        CommandResult(1, "", "private path details"),
        CommandResult(0, "unexpected output"),
    ],
)
def test_operation_fails_closed_without_exposing_helper_output(result: CommandResult) -> None:
    adapter = WindowsStopIntentAdapter(FakeRunner([result]))

    with pytest.raises(StopIntentError) as error:
        adapter.stop()

    assert str(error.value) == "The fixed Windows stop-intent operation failed"
    assert "private path" not in str(error.value)


def test_status_rejects_arbitrary_helper_output() -> None:
    adapter = WindowsStopIntentAdapter(FakeRunner([CommandResult(0, "marker path is C:\\secret")]))

    with pytest.raises(StopIntentError, match="status was invalid"):
        adapter.status()


def test_default_runner_is_bounded_and_allowlists_only_fixed_powershell() -> None:
    adapter = WindowsStopIntentAdapter()
    runner = adapter._runner

    assert isinstance(runner, SubprocessCommandRunner)
    assert runner._allowed_executables == {POWERSHELL_EXE}
    assert runner._timeout_seconds == 15
    assert runner._max_stdout_bytes == 1024
    assert runner._validate_argv((POWERSHELL_EXE, "-Action", "Set")) == (
        POWERSHELL_EXE,
        "-Action",
        "Set",
    )
    with pytest.raises(ValueError, match="allowlisted executable"):
        runner._validate_argv(("bash", "-c", "unsafe"))
