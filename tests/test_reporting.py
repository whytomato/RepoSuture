from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from reposuture.reporting import (
    FinalStatus,
    ObservedFailure,
    PatchAttemptReport,
    PrimaryFailure,
    RunReport,
    SanitizedTraceEvent,
    TestOutcome,
    TestResultReport,
    TraceWriter,
    classify_run_failures,
    collect_artifact_metadata,
    create_artifact_paths,
    write_report,
)


def artifact_mapping(tmp_path: Path) -> dict[str, str]:
    return {
        "report": str(tmp_path / "report.json"),
        "trace": str(tmp_path / "trace.jsonl"),
        "final_patch": str(tmp_path / "final.patch"),
        "baseline_target_test_log": str(tmp_path / "baseline.log"),
        "patched_target_test_log": str(tmp_path / "patched.log"),
        "regression_test_log": str(tmp_path / "regression.log"),
    }


def repository_state(commit: str) -> dict[str, object]:
    return {
        "head_commit": commit,
        "index_sha256": "1" * 64,
        "index_bytes": 10,
        "git_status_sha256": "2" * 64,
        "git_status_bytes": 0,
        "content_sha256": "3" * 64,
    }


def artifact_metadata(tmp_path: Path) -> dict[str, dict[str, object]]:
    mapping = artifact_mapping(tmp_path)
    return {
        name: {
            "path": path,
            "size_bytes": 10 if name == "final_patch" else 0,
            "sha256": "4" * 64,
            "output_truncated": False,
        }
        for name, path in mapping.items()
        if name != "report"
    }


def test_report_serializes_required_fields(tmp_path: Path) -> None:
    started = datetime.now(UTC)
    report = RunReport(
        run_id="run-123",
        task_id="null-email",
        schema_version=1,
        base_commit="a" * 40,
        start_time=started,
        end_time=started + timedelta(seconds=3),
        total_duration=3.0,
        original_repository=tmp_path / "repo",
        worktree_path=tmp_path / "worktree",
        baseline_test_result=TestResultReport(
            outcome=TestOutcome.FAIL,
            command=["mvnw", "-q", "-Dtest=ExampleTest#fails", "test"],
            exit_code=1,
            duration=1.0,
            timed_out=False,
            test_observed=True,
            tests_executed=1,
            test_failures=1,
            target_found=True,
        ),
        patched_target_test_result=TestResultReport(
            outcome=TestOutcome.PASS,
            command=["mvnw", "-q", "-Dtest=ExampleTest#fails", "test"],
            exit_code=0,
            duration=1.0,
            timed_out=False,
            test_observed=True,
            tests_executed=1,
            target_found=True,
        ),
        regression_result=TestResultReport(
            outcome=TestOutcome.PASS,
            command=["mvnw", "-q", "test"],
            exit_code=0,
            duration=1.0,
            timed_out=False,
            test_observed=True,
            tests_executed=3,
        ),
        affected_files=["src/main/java/Example.java"],
        file_classifications={"src/main/java/Example.java": "production"},
        patch_size=123,
        patch_sha256="5" * 64,
        patch_applied=True,
        modifies_tests=False,
        modifies_build=False,
        modifies_maven_wrapper=False,
        modifies_ci=False,
        original_repository_unchanged=True,
        original_repository_before=repository_state("a" * 40),
        original_repository_after=repository_state("a" * 40),
        keep_worktree_requested=False,
        worktree_retained=False,
        worktree_exists_at_report=False,
        final_status=FinalStatus.RESOLVED,
        failure_reason=None,
        artifacts=artifact_mapping(tmp_path),
        artifact_metadata=artifact_metadata(tmp_path),
    )
    report_path = tmp_path / "report.json"

    write_report(report, report_path)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["final_status"] == "RESOLVED"
    assert payload["baseline_test_result"]["outcome"] == "FAIL"
    assert payload["original_repository"] == str(tmp_path / "repo")
    assert payload["artifacts"]["report"] == "report.json"
    assert payload["artifacts"]["trace"] == "trace.jsonl"
    assert payload["artifact_metadata"]["trace"]["path"] == "trace.jsonl"


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("patch_applied", False),
        ("original_repository_unchanged", False),
        (
            "baseline_test_result",
            TestResultReport.not_run(),
        ),
        (
            "patched_target_test_result",
            TestResultReport.not_run(),
        ),
        ("regression_result", TestResultReport.not_run()),
    ],
)
def test_illegal_resolved_state_is_rejected(
    tmp_path: Path, override: str, value: object
) -> None:
    started = datetime.now(UTC)
    values: dict[str, object] = {
        "run_id": "run-123",
        "task_id": "case",
        "schema_version": 1,
        "base_commit": "b" * 40,
        "start_time": started,
        "end_time": started,
        "total_duration": 0.0,
        "original_repository": tmp_path / "repo",
        "worktree_path": tmp_path / "worktree",
        "baseline_test_result": TestResultReport.failed_observed(),
        "patched_target_test_result": TestResultReport.passed_observed(),
        "regression_result": TestResultReport.passed_observed(),
        "affected_files": ["src/main/java/App.java"],
        "file_classifications": {"src/main/java/App.java": "production"},
        "patch_size": 1,
        "patch_sha256": "5" * 64,
        "patch_applied": True,
        "modifies_tests": False,
        "modifies_build": False,
        "modifies_maven_wrapper": False,
        "modifies_ci": False,
        "original_repository_unchanged": True,
        "original_repository_before": repository_state("b" * 40),
        "original_repository_after": repository_state("b" * 40),
        "keep_worktree_requested": False,
        "worktree_retained": False,
        "worktree_exists_at_report": False,
        "final_status": FinalStatus.RESOLVED,
        "failure_reason": None,
        "artifacts": artifact_mapping(tmp_path),
        "artifact_metadata": artifact_metadata(tmp_path),
    }
    values[override] = value

    with pytest.raises(
        ValidationError, match=r"RESOLVED|patch|classifications|artifact"
    ):
        RunReport.model_validate(values)


def test_trace_writer_records_monotonic_sequence_and_limits_metadata(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceWriter(trace_path, max_metadata_value_chars=10)

    trace.emit("run_started", status="STARTED", metadata={"description": "x" * 50})
    trace.emit("run_finished", status="OK", duration=1.25)

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [event["sequence"] for event in events] == [1, 2]
    assert events[0]["metadata"]["description"] == "xxxxxxxxxx…"
    assert events[1]["duration"] == 1.25


def resolved_report_values(tmp_path: Path) -> dict[str, object]:
    started = datetime.now(UTC)
    return {
        "run_id": "run-secure",
        "task_id": "case",
        "schema_version": 1,
        "base_commit": "c" * 40,
        "start_time": started,
        "end_time": started,
        "total_duration": 0.0,
        "original_repository": tmp_path / "repo",
        "worktree_path": tmp_path / "worktree",
        "baseline_test_result": TestResultReport.failed_observed(),
        "patched_target_test_result": TestResultReport.passed_observed(),
        "regression_result": TestResultReport.passed_observed(),
        "affected_files": ["src/main/java/App.java"],
        "file_classifications": {"src/main/java/App.java": "production"},
        "patch_size": 10,
        "patch_sha256": "5" * 64,
        "patch_applied": True,
        "modifies_tests": False,
        "modifies_build": False,
        "modifies_maven_wrapper": False,
        "modifies_ci": False,
        "original_repository_unchanged": True,
        "original_repository_before": repository_state("c" * 40),
        "original_repository_after": repository_state("c" * 40),
        "keep_worktree_requested": False,
        "worktree_retained": False,
        "worktree_exists_at_report": False,
        "final_status": FinalStatus.RESOLVED,
        "failure_reason": None,
        "artifacts": artifact_mapping(tmp_path),
        "artifact_metadata": artifact_metadata(tmp_path),
    }


def test_primary_failure_preserves_regression_evidence_after_later_search_error(
    tmp_path: Path,
) -> None:
    values = resolved_report_values(tmp_path)
    values.update(
        {
            "final_status": FinalStatus.AGENT_BUDGET_EXHAUSTED,
            "terminal_status": FinalStatus.AGENT_BUDGET_EXHAUSTED,
            "failure_reason": "maximum model turns reached",
            "workflow": "agent_repair",
            "patch_applied": False,
            "regression_result": TestResultReport.failed_observed(),
            "total_patch_attempts": 1,
            "patch_attempts": [
                PatchAttemptReport(
                    attempt_id=1,
                    patch_sha256="7" * 64,
                    patch_size=10,
                    affected_files=["src/main/java/App.java"],
                    file_classifications={"src/main/java/App.java": "production"},
                    accepted=True,
                )
            ],
            "provider_accepted": True,
            "model_executed": True,
            "model_tool_call_observed": True,
        }
    )
    report = RunReport.model_validate(values)
    now = datetime.now(UTC)
    events = [
        SanitizedTraceEvent(
            sequence=1,
            timestamp=now,
            event_type="regression_test_completed",
            status="FAIL",
        ),
        SanitizedTraceEvent(
            sequence=2,
            timestamp=now,
            event_type="candidate_reverted",
            status="REVERTED",
        ),
        SanitizedTraceEvent(
            sequence=3,
            timestamp=now,
            event_type="tool_execution_completed",
            status="FAILED",
            metadata={"tool_name": "search_code"},
        ),
        SanitizedTraceEvent(
            sequence=4,
            timestamp=now,
            event_type="budget_exhausted",
            status="MODEL_TURNS",
        ),
    ]

    classification = classify_run_failures(report, events)

    assert classification.terminal_status is FinalStatus.AGENT_BUDGET_EXHAUSTED
    assert classification.primary_failure is PrimaryFailure.REGRESSION_UNRESOLVED
    assert classification.observed_failures == [
        ObservedFailure.REGRESSION_FAILED,
        ObservedFailure.CANDIDATE_REVERTED,
        ObservedFailure.SEARCH_TOOL_ERROR,
        ObservedFailure.BUDGET_EXHAUSTED,
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("patch_size", 0),
        ("affected_files", []),
        ("file_classifications", {}),
        ("artifacts", {}),
    ],
)
def test_resolved_rejects_empty_patch_or_incomplete_evidence(
    tmp_path: Path, field: str, value: object
) -> None:
    values = resolved_report_values(tmp_path)
    values[field] = value

    with pytest.raises(
        ValidationError, match=r"RESOLVED|patch|classifications|artifact"
    ):
        RunReport.model_validate(values)


def test_trace_writer_rejects_negative_duration(tmp_path: Path) -> None:
    trace = TraceWriter(tmp_path / "trace.jsonl")

    with pytest.raises(ValueError, match="duration"):
        trace.emit("bad", status="FAILED", duration=-0.01)


def test_trace_writer_redacts_sensitive_metadata_keys(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceWriter(trace_path)

    trace.emit(
        "safe",
        status="OK",
        metadata={
            "api_token": "must-not-appear",
            "detail": "allowed",
            "nested": {"password": "also-must-not-appear"},
            "environment": {"SAFE": "still-not-recorded"},
        },
    )

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["api_token"] == "<redacted>"
    assert "must-not-appear" not in trace_path.read_text(encoding="utf-8")
    assert payload["metadata"]["nested"]["password"] == "<redacted>"
    assert payload["metadata"]["environment"] == "<redacted>"


def test_trace_observer_receives_the_exact_sanitized_event_written_to_disk(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    observed: list[SanitizedTraceEvent] = []
    trace = TraceWriter(trace_path, run_id="observer-run", observer=observed.append)

    trace.emit(
        "tool_call_requested",
        status="REQUESTED",
        metadata={"tool_name": "search_code", "api_token": "must-not-appear"},
    )

    written = SanitizedTraceEvent.model_validate_json(
        trace_path.read_text(encoding="utf-8")
    )
    assert observed == [written]
    assert observed[0].metadata["api_token"] == "<redacted>"


def test_trace_observer_failure_is_disabled_without_interrupting_trace(
    tmp_path: Path,
) -> None:
    calls = 0

    def fail_presentation(_event: SanitizedTraceEvent) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError(
            "renderer failed Authorization: Bearer sk-or-v1-secretmaterial"
        )

    trace_path = tmp_path / "trace.jsonl"
    trace = TraceWriter(trace_path, run_id="observer-run", observer=fail_presentation)

    trace.emit("run_started", status="STARTED")
    trace.emit("run_finished", status="RESOLVED")

    events = [
        SanitizedTraceEvent.model_validate_json(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event.sequence for event in events] == [1, 2]
    assert events[-1].status == "RESOLVED"
    assert calls == 1
    assert trace.observer is None
    assert trace.observer_warning is not None
    assert "renderer failed" in trace.observer_warning
    assert "secretmaterial" not in trace.observer_warning
    assert "Authorization: Bearer" not in trace.observer_warning


def test_trace_writer_redacts_credential_shapes_inside_safe_string_values(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceWriter(trace_path, run_id="credential-shape-run")

    trace.emit(
        "presentation_warning",
        status="WARNING",
        metadata={
            "detail": (
                "Authorization: Bearer sk-or-v1-"
                + "credentialmaterialthatmustnotappear"
            )
        },
    )

    serialized = trace_path.read_text(encoding="utf-8")
    assert "credentialmaterialthatmustnotappear" not in serialized
    assert "Authorization: Bearer" not in serialized
    assert "<redacted>" in serialized


def test_atomic_report_failure_leaves_no_temporary_json(
    tmp_path: Path,
) -> None:
    report = RunReport.model_validate(resolved_report_values(tmp_path))
    report_path = tmp_path / "report.json"
    report_path.mkdir()

    with pytest.raises(OSError):
        write_report(report, report_path)

    assert list(tmp_path.glob(".report.json.*.tmp")) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("worktree_exists_at_report", True),
        ("worktree_retained", True),
        ("original_repository_after", None),
        ("patch_sha256", None),
    ],
)
def test_resolved_rejects_cleanup_snapshot_and_patch_evidence_gaps(
    tmp_path: Path, field: str, value: object
) -> None:
    values = resolved_report_values(tmp_path)
    values[field] = value

    with pytest.raises(ValidationError, match=r"RESOLVED|patch"):
        RunReport.model_validate(values)


@pytest.mark.parametrize(
    ("status", "override", "value"),
    [
        (FinalStatus.INVALID_CASE, "baseline_test_result", TestResultReport.failed_observed()),
        (
            FinalStatus.BASELINE_NOT_REPRODUCED,
            "baseline_test_result",
            TestResultReport.failed_observed(),
        ),
        (FinalStatus.PATCH_REJECTED, "baseline_test_result", TestResultReport.not_run()),
        (
            FinalStatus.TARGET_TEST_FAILED,
            "patched_target_test_result",
            TestResultReport.not_run(),
        ),
        (
            FinalStatus.REGRESSION_FAILED,
            "regression_result",
            TestResultReport.not_run(),
        ),
    ],
)
def test_failure_status_rejects_inconsistent_phase_evidence(
    tmp_path: Path,
    status: FinalStatus,
    override: str,
    value: object,
) -> None:
    values = resolved_report_values(tmp_path)
    values.update(
        {
            "final_status": status,
            "failure_reason": "deliberate failure",
        }
    )
    values[override] = value

    with pytest.raises(ValidationError, match="evidence"):
        RunReport.model_validate(values)


def test_resolved_rejects_empty_final_patch_metadata(tmp_path: Path) -> None:
    values = resolved_report_values(tmp_path)
    metadata = artifact_metadata(tmp_path)
    metadata["final_patch"]["size_bytes"] = 0
    values["artifact_metadata"] = metadata

    with pytest.raises(ValidationError, match="RESOLVED"):
        RunReport.model_validate(values)


def test_collect_artifact_metadata_matches_disk_and_truncation(tmp_path: Path) -> None:
    artifacts = create_artifact_paths(tmp_path / "artifacts", "case")
    artifacts.trace.write_text('{"sequence":1}\n', encoding="utf-8")
    artifacts.final_patch.write_bytes(b"diff --git\n")
    artifacts.baseline_log.write_bytes(b"baseline")
    artifacts.patched_target_log.write_bytes(b"patched")
    artifacts.regression_log.write_bytes(b"regression")

    records = collect_artifact_metadata(
        artifacts,
        output_truncation={"baseline_target_test_log": True},
    )

    assert set(records) == {
        "trace",
        "final_patch",
        "baseline_target_test_log",
        "patched_target_test_log",
        "regression_test_log",
    }
    for name, record in records.items():
        content = Path(artifacts.as_report_mapping()[name]).read_bytes()
        assert record.size_bytes == len(content)
        assert record.sha256 == hashlib.sha256(content).hexdigest()
    assert records["baseline_target_test_log"].output_truncated is True


def test_agent_trajectory_is_opt_in_and_hashed_as_artifact(tmp_path: Path) -> None:
    artifacts = create_artifact_paths(tmp_path / "artifacts", "agent-case")
    artifacts.trace.write_text("", encoding="utf-8")
    artifacts.trajectory.write_bytes(b"# Agent Trajectory\n")

    records = collect_artifact_metadata(artifacts, include_trajectory=True)
    mapping = artifacts.as_report_mapping(include_trajectory=True)

    assert mapping["trajectory"] == str(artifacts.trajectory)
    assert records["trajectory"].size_bytes == len(b"# Agent Trajectory\n")
    assert records["trajectory"].sha256 == hashlib.sha256(
        b"# Agent Trajectory\n"
    ).hexdigest()
    assert "trajectory" not in artifacts.as_report_mapping()


def test_artifact_run_directories_never_overwrite_existing_run(tmp_path: Path) -> None:
    first = create_artifact_paths(tmp_path / "artifacts", "same-case")
    second = create_artifact_paths(tmp_path / "artifacts", "same-case")

    assert first.run_id != second.run_id
    assert first.directory != second.directory
    assert first.directory.is_dir()
    assert second.directory.is_dir()


def test_schema_two_resolved_report_requires_agent_telemetry(tmp_path: Path) -> None:
    values = resolved_report_values(tmp_path)
    values.update(
        {
            "schema_version": 2,
            "workflow": "agent_repair",
            "provider": "fake",
            "model": "FakeLLM",
            "total_model_turns": 3,
            "total_tool_calls": 3,
            "tool_calls_by_name": {
                "search_code": 1,
                "read_file": 1,
                "apply_patch": 1,
            },
            "total_patch_attempts": 1,
            "patch_attempts": [
                {
                    "attempt_id": 1,
                    "patch_sha256": "5" * 64,
                    "patch_size": 10,
                    "affected_files": ["src/main/java/App.java"],
                    "file_classifications": {
                        "src/main/java/App.java": "production"
                    },
                    "accepted": True,
                }
            ],
            "target_test_execution_count": 2,
            "regression_execution_count": 1,
            "final_deterministic_status": FinalStatus.RESOLVED,
        }
    )

    report = RunReport.model_validate(values)

    assert report.final_status is FinalStatus.RESOLVED
    assert report.schema_version == 2


def test_schema_two_resolved_report_rejects_model_text_without_verifier_evidence(
    tmp_path: Path,
) -> None:
    values = resolved_report_values(tmp_path)
    values.update(
        {
            "schema_version": 2,
            "workflow": "agent_repair",
            "provider": "openai",
            "model": "configured-model",
            "final_visible_model_message": "I fixed it.",
            "total_model_turns": 1,
            "total_tool_calls": 0,
            "total_patch_attempts": 0,
            "patch_attempts": [],
            "target_test_execution_count": 1,
            "regression_execution_count": 0,
            "final_deterministic_status": FinalStatus.RESOLVED,
            "patch_applied": False,
            "affected_files": [],
            "file_classifications": {},
            "patch_size": 0,
            "patch_sha256": None,
            "patched_target_test_result": TestResultReport.not_run(),
            "regression_result": TestResultReport.not_run(),
        }
    )

    with pytest.raises(ValidationError, match="RESOLVED"):
        RunReport.model_validate(values)
