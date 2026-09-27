from __future__ import annotations

import sys

import pytest

from dots.local_control_runner import (
    SubprocessCommandRunner,
    SubprocessCommandTimeout,
)


def test_runner_passes_arguments_without_shell_interpretation(tmp_path):
    marker = tmp_path / "should-not-exist"
    literal_argument = f"value;touch {marker}"
    runner = SubprocessCommandRunner((sys.executable,), timeout_seconds=2)

    result = runner.run((sys.executable, "-c", "import sys; print(sys.argv[1])", literal_argument))

    assert result.returncode == 0
    assert result.stdout == literal_argument + "\n"
    assert result.stderr == ""
    assert not marker.exists()


def test_runner_bounds_stdout_and_discards_stderr():
    runner = SubprocessCommandRunner((sys.executable,), timeout_seconds=2, max_stdout_bytes=31)

    result = runner.run((
        sys.executable,
        "-c",
        "import sys; print('x' * 1000); print('private diagnostic', file=sys.stderr); sys.exit(7)",
    ))

    assert result.returncode == 7
    assert len(result.stdout.encode("utf-8")) == 31
    assert result.stderr == ""
    assert "private diagnostic" not in repr(result)


def test_runner_enforces_a_per_command_deadline():
    runner = SubprocessCommandRunner((sys.executable,), timeout_seconds=0.1)

    with pytest.raises(SubprocessCommandTimeout, match="deadline"):
        runner.run((sys.executable, "-c", "import time; time.sleep(5)"))
    with pytest.raises(SubprocessCommandTimeout, match="deadline"):
        runner.run((sys.executable, "-c", "import os, time; os.close(1); os.close(2); time.sleep(5)"))


def test_runner_rejects_commands_outside_the_trusted_executable_allowlist():
    runner = SubprocessCommandRunner((sys.executable,), timeout_seconds=2)

    with pytest.raises(ValueError, match="allowlisted"):
        runner.run(("untrusted-command", "arg"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allowed_executables": ()},
        {"allowed_executables": ("python",), "timeout_seconds": 0},
        {"allowed_executables": ("python",), "max_stdout_bytes": 0},
    ],
)
def test_runner_rejects_invalid_limits_or_allowlists(kwargs):
    with pytest.raises(ValueError):
        SubprocessCommandRunner(**kwargs)
