from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

from patchpilot.process import ProcessRunner


def test_process_runner_times_out_and_terminates_process(tmp_path: Path) -> None:
    runner = ProcessRunner(max_output_bytes=1_024)

    result = runner.run(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(10)"],
        cwd=tmp_path,
        timeout_seconds=0.2,
    )

    assert result.timed_out is True
    assert result.exit_code is not None
    assert result.duration_seconds < 5
    assert "started" in result.stdout
    assert result.infrastructure_error is None


def test_process_runner_truncates_retained_output_by_bytes(tmp_path: Path) -> None:
    runner = ProcessRunner(max_output_bytes=64)

    result = runner.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('o' * 100); sys.stderr.write('e' * 80)",
        ],
        cwd=tmp_path,
        timeout_seconds=5,
    )

    assert result.exit_code == 0
    assert result.stdout == "o" * 64
    assert result.stderr == "e" * 64
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert result.stdout_bytes_seen == 100
    assert result.stderr_bytes_seen == 80
    assert result.stdout_sha256 == hashlib.sha256(b"o" * 100).hexdigest()
    assert result.stderr_sha256 == hashlib.sha256(b"e" * 80).hexdigest()


def test_process_runner_reports_missing_executable(tmp_path: Path) -> None:
    runner = ProcessRunner()

    result = runner.run(
        ["patchpilot-command-that-does-not-exist-7d9c0e"],
        cwd=tmp_path,
        timeout_seconds=5,
    )

    assert result.exit_code is None
    assert result.timed_out is False
    assert result.infrastructure_error is not None
    assert "executable_not_found" in result.infrastructure_error


def test_process_runner_reports_other_startup_failures(tmp_path: Path) -> None:
    not_executable = tmp_path / "not-an-executable"
    not_executable.write_text("plain text", encoding="utf-8")

    result = ProcessRunner().run(
        [str(not_executable)],
        cwd=tmp_path,
        timeout_seconds=5,
    )

    assert result.exit_code is None
    assert result.timed_out is False
    assert result.infrastructure_error is not None
    assert "process_start_failed" in result.infrastructure_error


def test_process_runner_delivers_bounded_binary_stdin_without_shell(tmp_path: Path) -> None:
    content = b"frozen-patch-bytes\x00remain-data"
    runner = ProcessRunner(max_input_bytes=len(content))

    result = runner.run(
        [
            sys.executable,
            "-c",
            "import hashlib, sys; data=sys.stdin.buffer.read(); "
            "print(len(data)); print(hashlib.sha256(data).hexdigest())",
        ],
        cwd=tmp_path,
        timeout_seconds=5,
        input_bytes=content,
    )

    assert result.succeeded
    assert result.stdout.splitlines() == [
        str(len(content)),
        hashlib.sha256(content).hexdigest(),
    ]


def test_process_runner_rejects_input_above_limit_before_start(tmp_path: Path) -> None:
    runner = ProcessRunner(max_input_bytes=3)

    try:
        runner.run(
            [sys.executable, "-c", "raise SystemExit(99)"],
            cwd=tmp_path,
            timeout_seconds=5,
            input_bytes=b"four",
        )
    except ValueError as exc:
        assert "input exceeds" in str(exc)
    else:
        raise AssertionError("oversized process input was accepted")


def test_timeout_terminates_descendant_even_when_it_ignores_soft_signal(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "descendant-survived.txt"
    helper = Path(__file__).parent / "helpers/process_tree_parent.py"
    runner = ProcessRunner(max_output_bytes=1_024)

    result = runner.run(
        [sys.executable, str(helper), str(marker)],
        cwd=tmp_path,
        timeout_seconds=0.5,
    )
    time.sleep(2.25)

    assert result.timed_out is True
    assert result.infrastructure_error is None
    assert "descendant-started" in result.stdout
    assert not marker.exists(), "a timed-out descendant process was left running"
