"""Bounded subprocess runner for trusted local-control adapters.

Commands are passed as literal argv tokens to an allowlisted executable. This
module never invokes a shell and discards stderr rather than exposing command
diagnostics that may contain sensitive values.
"""
from __future__ import annotations

import math
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Sequence
from typing import Callable

from nebula.local_control_adapters import CommandResult


class SubprocessCommandError(RuntimeError):
    """A trusted local command could not be started safely."""


class SubprocessCommandTimeout(SubprocessCommandError):
    """A trusted local command exceeded its configured deadline."""


class SubprocessCommandRunner:
    """Run allowlisted executables with a deadline and bounded stdout capture."""

    def __init__(
        self,
        allowed_executables: Sequence[str],
        *,
        timeout_seconds: float = 15,
        max_stdout_bytes: int = 65_536,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(allowed_executables, (str, bytes)):
            raise ValueError("allowed_executables must be a sequence of executable names")
        approved = tuple(allowed_executables)
        if not approved or any(not isinstance(item, str) or not item or "\x00" in item for item in approved):
            raise ValueError("at least one valid executable must be allowlisted")
        if len(set(approved)) != len(approved):
            raise ValueError("allowed_executables cannot contain duplicates")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if isinstance(max_stdout_bytes, bool) or not isinstance(max_stdout_bytes, int) or max_stdout_bytes <= 0:
            raise ValueError("max_stdout_bytes must be a positive integer")
        self._allowed_executables = frozenset(approved)
        self._timeout_seconds = timeout_seconds
        self._max_stdout_bytes = max_stdout_bytes
        self._monotonic = monotonic

    def run(self, argv: Sequence[str]) -> CommandResult:
        command = self._validate_argv(argv)
        try:
            process = subprocess.Popen(
                command,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                bufsize=0,
                start_new_session=(os.name == "posix"),
            )
        except (OSError, ValueError):
            raise SubprocessCommandError("Approved command could not be started") from None

        captured_stdout = bytearray()
        timed_out = False
        deadline = self._monotonic() + self._timeout_seconds
        try:
            with selectors.DefaultSelector() as selector:
                assert process.stdout is not None
                assert process.stderr is not None
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map() or process.poll() is None:
                    if not timed_out and self._monotonic() >= deadline:
                        timed_out = True
                        self._kill_process_group(process)
                    events = selector.select(timeout=0.05) if selector.get_map() else ()
                    if not events and not selector.get_map() and process.poll() is None:
                        time.sleep(0.01)
                    for key, _ in events:
                        try:
                            chunk = os.read(key.fd, 8192)
                        except OSError:
                            chunk = b""
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if key.data == "stdout" and len(captured_stdout) < self._max_stdout_bytes:
                            remaining = self._max_stdout_bytes - len(captured_stdout)
                            captured_stdout.extend(chunk[:remaining])
                        # stderr is drained to prevent a child pipe deadlock, then discarded.
            return_code = process.wait()
        except BaseException:
            self._kill_process_group(process)
            process.wait()
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

        if timed_out:
            raise SubprocessCommandTimeout("Approved command exceeded its deadline")
        return CommandResult(
            returncode=return_code,
            stdout=captured_stdout.decode("utf-8", errors="replace"),
            stderr="",
        )

    def _validate_argv(self, argv: Sequence[str]) -> tuple[str, ...]:
        if isinstance(argv, (str, bytes)):
            raise ValueError("argv must be a sequence of argument strings")
        command = tuple(argv)
        if (
            not command
            or any(not isinstance(argument, str) or "\x00" in argument for argument in command)
            or command[0] not in self._allowed_executables
        ):
            raise ValueError("argv must start with an allowlisted executable and contain valid strings")
        return command

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
                return
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
