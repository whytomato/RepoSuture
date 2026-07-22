"""Safe, bounded subprocess execution without a shell."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

DEFAULT_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_INPUT_BYTES = 10 * 1024 * 1024
PROCESS_STOP_GRACE_SECONDS = 2.0
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
CREATE_NEW_PROCESS_GROUP = int(
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """A complete, structured record of one process invocation."""

    command: tuple[str, ...]
    cwd: Path
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_bytes_seen: int
    stderr_bytes_seen: int
    stdout_sha256: str = EMPTY_SHA256
    stderr_sha256: str = EMPTY_SHA256
    infrastructure_error: str | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and self.infrastructure_error is None
        )


class _BoundedBytes:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.bytes_seen = 0
        self.hasher = hashlib.sha256()

    def append(self, chunk: bytes) -> None:
        self.bytes_seen += len(chunk)
        self.hasher.update(chunk)
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])

    @property
    def truncated(self) -> bool:
        return self.bytes_seen > self.limit

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")

    @property
    def sha256(self) -> str:
        return self.hasher.hexdigest()


def _drain_pipe(
    pipe: BinaryIO,
    destination: _BoundedBytes,
    errors: list[BaseException],
) -> None:
    try:
        while chunk := pipe.read(65_536):
            destination.append(chunk)
    except BaseException as exc:  # surfaced in the structured result after joining
        errors.append(exc)
    finally:
        pipe.close()


def _write_stdin(
    pipe: BinaryIO,
    content: bytes,
    errors: list[BaseException],
) -> None:
    try:
        pipe.write(content)
        pipe.flush()
    except BrokenPipeError:
        pass
    except BaseException as exc:  # surfaced in the structured result after joining
        errors.append(exc)
    finally:
        pipe.close()


class ProcessRunner:
    """Run argument-array commands with bounded output and process-tree timeouts."""

    def __init__(
        self,
        *,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    ) -> None:
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        if max_input_bytes < 1:
            raise ValueError("max_input_bytes must be positive")
        self.max_output_bytes = max_output_bytes
        self.max_input_bytes = max_input_bytes

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        if not command:
            raise ValueError("command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if any(not isinstance(argument, str) or "\x00" in argument for argument in command):
            raise ValueError("every command argument must be a NUL-free string")
        if input_bytes is not None and not isinstance(input_bytes, bytes):
            raise TypeError("input_bytes must be bytes or None")
        if input_bytes is not None and len(input_bytes) > self.max_input_bytes:
            raise ValueError(
                f"input exceeds the configured {self.max_input_bytes}-byte limit"
            )

        command_tuple = tuple(command)
        started = time.monotonic()
        try:
            resolved_cwd = cwd.resolve(strict=True)
            if not resolved_cwd.is_dir():
                raise NotADirectoryError(str(resolved_cwd))
        except OSError as exc:
            return self._start_error(
                command_tuple,
                cwd,
                started,
                f"invalid_cwd: {type(exc).__name__}: {exc}",
            )

        try:
            if os.name == "nt":
                process = subprocess.Popen(
                    command_tuple,
                    cwd=resolved_cwd,
                    stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    creationflags=CREATE_NEW_PROCESS_GROUP,
                )
            else:
                process = subprocess.Popen(
                    command_tuple,
                    cwd=resolved_cwd,
                    stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    start_new_session=True,
                )
        except FileNotFoundError as exc:
            return self._start_error(
                command_tuple,
                resolved_cwd,
                started,
                f"executable_not_found: {command_tuple[0]}: {exc}",
            )
        except OSError as exc:
            return self._start_error(
                command_tuple,
                resolved_cwd,
                started,
                f"process_start_failed: {type(exc).__name__}: {exc}",
            )

        if process.stdout is None or process.stderr is None:
            raise RuntimeError("subprocess pipes were not created")

        stdout = _BoundedBytes(self.max_output_bytes)
        stderr = _BoundedBytes(self.max_output_bytes)
        pipe_errors: list[BaseException] = []
        stdout_thread = threading.Thread(
            target=_drain_pipe,
            args=(process.stdout, stdout, pipe_errors),
            name=f"patchpilot-stdout-{process.pid}",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_drain_pipe,
            args=(process.stderr, stderr, pipe_errors),
            name=f"patchpilot-stderr-{process.pid}",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        stdin_errors: list[BaseException] = []
        stdin_thread: threading.Thread | None = None
        if input_bytes is not None:
            if process.stdin is None:
                raise RuntimeError("subprocess stdin pipe was not created")
            stdin_thread = threading.Thread(
                target=_write_stdin,
                args=(process.stdin, input_bytes, stdin_errors),
                name=f"patchpilot-stdin-{process.pid}",
                daemon=True,
            )
            stdin_thread.start()

        timed_out = False
        termination_error: str | None = None
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            termination_error = self._terminate_process_tree(process, resolved_cwd)

        stdout_thread.join(timeout=PROCESS_STOP_GRACE_SECONDS)
        stderr_thread.join(timeout=PROCESS_STOP_GRACE_SECONDS)
        if stdin_thread is not None:
            stdin_thread.join(timeout=PROCESS_STOP_GRACE_SECONDS)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            termination_error = termination_error or "output_pipe_drain_did_not_finish"
        if stdin_thread is not None and stdin_thread.is_alive():
            termination_error = termination_error or "input_pipe_write_did_not_finish"

        infrastructure_error = termination_error
        if pipe_errors:
            first_error = pipe_errors[0]
            infrastructure_error = infrastructure_error or (
                f"output_capture_failed: {type(first_error).__name__}: {first_error}"
            )
        if stdin_errors:
            first_error = stdin_errors[0]
            infrastructure_error = infrastructure_error or (
                f"input_delivery_failed: {type(first_error).__name__}: {first_error}"
            )

        return ProcessResult(
            command=command_tuple,
            cwd=resolved_cwd,
            exit_code=process.returncode,
            duration_seconds=time.monotonic() - started,
            stdout=stdout.text(),
            stderr=stderr.text(),
            timed_out=timed_out,
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
            stdout_bytes_seen=stdout.bytes_seen,
            stderr_bytes_seen=stderr.bytes_seen,
            stdout_sha256=stdout.sha256,
            stderr_sha256=stderr.sha256,
            infrastructure_error=infrastructure_error,
        )

    @staticmethod
    def _start_error(
        command: tuple[str, ...],
        cwd: Path,
        started: float,
        message: str,
    ) -> ProcessResult:
        return ProcessResult(
            command=command,
            cwd=cwd,
            exit_code=None,
            duration_seconds=time.monotonic() - started,
            stdout="",
            stderr="",
            timed_out=False,
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_bytes_seen=0,
            stderr_bytes_seen=0,
            stdout_sha256=EMPTY_SHA256,
            stderr_sha256=EMPTY_SHA256,
            infrastructure_error=message,
        )

    @staticmethod
    def _terminate_process_tree(
        process: subprocess.Popen[bytes],
        cwd: Path,
    ) -> str | None:
        try:
            if os.name == "nt":
                completed = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=PROCESS_STOP_GRACE_SECONDS,
                    check=False,
                    shell=False,
                )
                if completed.returncode != 0:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
                    return (
                        "process_tree_termination_failed: "
                        f"taskkill returned {completed.returncode}"
                    )
            else:
                kill_process_group = cast(
                    Callable[[int, int], None],
                    getattr(os, "killpg"),  # noqa: B009 - absent from Windows type stubs
                )
                kill_process_group(process.pid, signal.SIGTERM)
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
                force_signal = cast(int, getattr(signal, "SIGKILL", signal.SIGTERM))
                with suppress(ProcessLookupError):
                    kill_process_group(process.pid, force_signal)
            process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
        except ProcessLookupError:
            return None
        except (OSError, subprocess.SubprocessError) as exc:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
            return f"process_tree_termination_failed: {type(exc).__name__}: {exc}"
        return None
