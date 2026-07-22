from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from patchpilot.cli import app
from patchpilot.process import ProcessRunner
from patchpilot.reporting import (
    ArtifactMetadata,
    FinalStatus,
    RunReport,
    TestResultReport,
    TraceWriter,
    write_report,
)
from patchpilot.trajectory import (
    TrajectoryView,
    load_replay_run,
    render_replay,
    render_trajectory_markdown,
    render_trajectory_text,
)


def _completed_run(tmp_path: Path, *, run_id: str = "replay-run") -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    trace_path = run_dir / "trace.jsonl"
    trace = TraceWriter(trace_path, run_id=run_id)
    trace.emit("run_started", status="STARTED")
    trace.emit(
        "agent_finished",
        status="MODEL_STOPPED",
        metadata={"model_turns": 1, "tool_calls": 0, "patch_attempts": 0},
    )
    trace.emit("run_finished", status="MODEL_STOPPED")
    content = trace_path.read_bytes()
    started = datetime.now(UTC)
    report_path = run_dir / "report.json"
    report = RunReport(
        run_id=run_id,
        task_id="example-case",
        schema_version=2,
        base_commit="a" * 40,
        start_time=started,
        end_time=started,
        total_duration=0,
        original_repository=None,
        worktree_path=None,
        baseline_test_result=TestResultReport.not_run(),
        patched_target_test_result=TestResultReport.not_run(),
        regression_result=TestResultReport.not_run(),
        affected_files=[],
        file_classifications={},
        patch_size=0,
        patch_sha256=None,
        patch_applied=False,
        modifies_tests=False,
        modifies_build=False,
        modifies_maven_wrapper=False,
        modifies_ci=False,
        original_repository_unchanged=False,
        final_status=FinalStatus.MODEL_STOPPED,
        failure_reason="model stopped without deterministic success",
        artifacts={"report": str(report_path), "trace": str(trace_path)},
        artifact_metadata={
            "trace": ArtifactMetadata(
                path=trace_path,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        },
        workflow="agent_repair",
        provider="scripted",
        model="scripted-test",
        total_model_turns=1,
        model_request_count=1,
        final_deterministic_status=FinalStatus.MODEL_STOPPED,
        issue_title="Example issue",
        issue_description="Demonstrate replay without a model client.",
    )
    write_report(report, report_path)
    return run_dir


def _directory_link(link: Path, target: Path, *, cwd: Path) -> None:
    if os.name == "nt":
        result = ProcessRunner().run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            cwd=cwd,
            timeout_seconds=10,
        )
        assert result.succeeded, result.infrastructure_error or result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


def _rewrite_trace(run_dir: Path, payloads: list[dict[str, object]]) -> None:
    (run_dir / "trace.jsonl").write_text(
        "".join(json.dumps(payload) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _trace_payloads(run_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.parametrize("entry_name", [None, "report.json", "trace.jsonl"])
def test_replay_accepts_run_directory_report_or_trace(
    tmp_path: Path, entry_name: str | None
) -> None:
    run_dir = _completed_run(tmp_path)
    entry = run_dir if entry_name is None else run_dir / entry_name

    replay = load_replay_run(entry)

    assert replay.run_directory == run_dir.resolve()
    assert replay.report.run_id == "replay-run"
    assert render_replay(replay, view=TrajectoryView.COMPACT, markdown=False) == (
        render_trajectory_text(replay.events, view=TrajectoryView.COMPACT)
    )


def test_generated_report_serializes_portable_relative_artifact_references(
    tmp_path: Path,
) -> None:
    run_dir = _completed_run(tmp_path)
    payload = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

    assert payload["artifacts"] == {
        "report": "report.json",
        "trace": "trace.jsonl",
    }
    assert payload["artifact_metadata"]["trace"]["path"] == "trace.jsonl"


def test_replay_succeeds_after_complete_run_directory_is_moved(tmp_path: Path) -> None:
    original_parent = tmp_path / "original"
    original_parent.mkdir()
    original = _completed_run(original_parent)
    moved = tmp_path / "relocated-run"

    shutil.move(str(original), moved)

    replay = load_replay_run(moved)
    assert replay.run_directory == moved.resolve()
    assert replay.report.final_status is FinalStatus.MODEL_STOPPED
    assert replay.events[-1].status == "MODEL_STOPPED"


def test_replay_remaps_coherent_legacy_absolute_report_after_move(tmp_path: Path) -> None:
    original_parent = tmp_path / "legacy-original"
    original_parent.mkdir()
    original = _completed_run(original_parent)
    report_path = original / "report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    for name, configured in list(payload["artifacts"].items()):
        payload["artifacts"][name] = str((original / configured).resolve())
    for name, metadata in payload["artifact_metadata"].items():
        metadata["path"] = payload["artifacts"][name]
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    moved = tmp_path / "legacy-relocated"
    shutil.move(str(original), moved)

    replay = load_replay_run(moved)

    assert replay.run_directory == moved.resolve()
    assert replay.report.artifacts["trace"] == "trace.jsonl"


def test_relocated_replay_rejects_tampered_artifact(tmp_path: Path) -> None:
    original_parent = tmp_path / "tamper-original"
    original_parent.mkdir()
    original = _completed_run(original_parent)
    moved = tmp_path / "tampered-relocated"
    shutil.move(str(original), moved)
    trace_path = moved / "trace.jsonl"
    trace_text = trace_path.read_text(encoding="utf-8")
    trace_path.write_text(trace_text.replace("\n", " \n", 1), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum"):
        load_replay_run(moved)


def test_replay_rejects_relative_parent_traversal(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    report_path = run_dir / "report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["artifacts"]["trace"] = "../trace.jsonl"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes run directory"):
        load_replay_run(run_dir)


def test_replay_rejects_artifact_symlink_escape(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copy2(run_dir / "trace.jsonl", outside / "trace.jsonl")
    _directory_link(run_dir / "outside-link", outside, cwd=tmp_path)
    report_path = run_dir / "report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["artifacts"]["trace"] = "outside-link/trace.jsonl"
    payload["artifact_metadata"]["trace"]["path"] = "outside-link/trace.jsonl"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes run directory"):
        load_replay_run(run_dir)


def test_replay_cli_requires_no_model_git_maven_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _completed_run(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("replay attempted an execution or network operation")

    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("patchpilot.process.ProcessRunner.run", forbidden)
    monkeypatch.setattr("patchpilot.maven.MavenRunner.run_target", forbidden)
    monkeypatch.setattr("patchpilot.models.OpenAIResponsesClient.__init__", forbidden)

    result = CliRunner().invoke(
        app,
        ["replay-run", str(run_dir), "--view", "verbose", "--no-color"],
    )

    assert result.exit_code == 0
    assert "[FINISH]  MODEL_STOPPED" in result.stdout


def test_markdown_replay_redacts_credentials_and_omits_patch_body(
    tmp_path: Path,
) -> None:
    run_dir = _completed_run(tmp_path)
    replay = load_replay_run(run_dir)
    secret = "sk-or-v1-credentialmaterial"
    report = replay.report.model_copy(
        update={
            "issue_description": f"Authorization: Bearer {secret}",
        }
    )

    rendered = render_trajectory_markdown(report, replay.events)

    assert secret not in rendered
    assert "Authorization: Bearer" not in rendered
    assert "diff --git" not in rendered


def test_replay_rejects_malformed_jsonl(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    (run_dir / "trace.jsonl").write_text("not-json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed"):
        load_replay_run(run_dir)


def test_replay_rejects_duplicate_sequence_numbers(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    payloads = _trace_payloads(run_dir)
    payloads[1]["sequence"] = 1
    _rewrite_trace(run_dir, payloads)

    with pytest.raises(ValueError, match="duplicate sequence"):
        load_replay_run(run_dir)


def test_replay_rejects_non_monotonic_sequence_numbers(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    payloads = _trace_payloads(run_dir)
    payloads[1]["sequence"] = 4
    _rewrite_trace(run_dir, payloads)

    with pytest.raises(ValueError, match="non-monotonic"):
        load_replay_run(run_dir)


def test_replay_rejects_mismatched_run_ids(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    payloads = _trace_payloads(run_dir)
    payloads[1]["run_id"] = "different-run"
    _rewrite_trace(run_dir, payloads)

    with pytest.raises(ValueError, match="run id"):
        load_replay_run(run_dir)


def test_replay_rejects_artifact_path_escape(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    report_path = run_dir / "report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["artifacts"]["trace"] = str(tmp_path / "outside.jsonl")
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes run directory"):
        load_replay_run(run_dir)


def test_replay_rejects_report_trace_status_inconsistency(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    payloads = _trace_payloads(run_dir)
    payloads[-1]["status"] = "RESOLVED"
    _rewrite_trace(run_dir, payloads)

    with pytest.raises(ValueError, match="final status"):
        load_replay_run(run_dir)


def test_replay_output_cannot_overwrite_original_artifacts(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "replay-run",
            str(run_dir),
            "--format",
            "markdown",
            "--output",
            str(run_dir / "trajectory.md"),
        ],
    )

    assert result.exit_code == 2
    assert "inside the replay run directory" in result.stderr
    assert not (run_dir / "trajectory.md").exists()


def test_replay_writes_markdown_outside_run_without_mutating_source(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    before_report = (run_dir / "report.json").read_bytes()
    before_trace = (run_dir / "trace.jsonl").read_bytes()
    output = tmp_path / "exported-trajectory.md"

    result = CliRunner().invoke(
        app,
        [
            "replay-run",
            str(run_dir / "trace.jsonl"),
            "--view",
            "verbose",
            "--format",
            "markdown",
            "--output",
            str(output),
            "--no-color",
        ],
    )

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8").startswith("# Agent Trajectory\n")
    assert (run_dir / "report.json").read_bytes() == before_report
    assert (run_dir / "trace.jsonl").read_bytes() == before_trace


@pytest.mark.parametrize("missing", ["report.json", "trace.jsonl"])
def test_replay_rejects_missing_run_files(tmp_path: Path, missing: str) -> None:
    run_dir = _completed_run(tmp_path)
    (run_dir / missing).unlink()

    with pytest.raises(ValueError, match=f"missing {missing}"):
        load_replay_run(run_dir)
