from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reposuture.benchmark import benchmark_exit_code
from reposuture.benchmark_reporting import (
    BenchmarkExecutionMode,
    BenchmarkRunRecord,
    FailureCategory,
    ReproducibilityMetadata,
    aggregate_benchmark_runs,
    write_benchmark_summary,
)
from reposuture.benchmark_spec import BenchmarkFingerprint
from reposuture.reporting import FinalStatus, TestOutcome

HASH = "a" * 64


def _fingerprint() -> BenchmarkFingerprint:
    return BenchmarkFingerprint(
        value=HASH,
        suite_manifest_sha256="b" * 64,
        case_files_sha256={},
        support_files_sha256={},
        base_commits={},
        fixture_content_sha256={},
    )


def _reproducibility(
    mode: BenchmarkExecutionMode = BenchmarkExecutionMode.SCRIPTED_OFFLINE,
) -> ReproducibilityMetadata:
    provider = "scripted" if mode is BenchmarkExecutionMode.SCRIPTED_OFFLINE else "openai"
    return ReproducibilityMetadata(
        project_git_commit="c" * 40,
        project_worktree_dirty=False,
        operating_system="Test OS",
        python_version="3.11.15",
        java_version='openjdk version "17"',
        maven_version="Maven 3.9.9 via Maven Wrapper 3.3.4",
        openai_sdk_version=None if provider == "scripted" else "2.46.0",
        provider=provider,
        model="deterministic-script-v1" if provider == "scripted" else "test-model",
        run_timestamp_utc=datetime(2026, 7, 21, tzinfo=UTC),
        cli_arguments=["benchmark", "--provider", provider],
        budget_values={"max_model_turns": 12},
    )


def _run(
    *,
    case_id: str,
    run_id: str,
    status: FinalStatus,
    category: FailureCategory,
    mode: BenchmarkExecutionMode = BenchmarkExecutionMode.SCRIPTED_OFFLINE,
    turns: int,
    tools: int,
    patches: int,
    duration: float,
    baseline: TestOutcome = TestOutcome.FAIL,
) -> BenchmarkRunRecord:
    resolved = status is FinalStatus.RESOLVED
    provider = "scripted" if mode is BenchmarkExecutionMode.SCRIPTED_OFFLINE else "openai"
    return BenchmarkRunRecord(
        suite_id="mvp",
        benchmark_fingerprint=HASH,
        case_id=case_id,
        run_number=1,
        run_id=run_id,
        execution_mode=mode,
        provider=provider,
        model="deterministic-script-v1" if provider == "scripted" else "test-model",
        final_status=status,
        failure_category=category,
        failure_reason=None if resolved else "bounded failure",
        baseline_reproduced=baseline is TestOutcome.FAIL,
        baseline_result=baseline,
        target_test_result=TestOutcome.PASS if resolved else TestOutcome.FAIL,
        regression_result=TestOutcome.PASS if resolved else TestOutcome.NOT_RUN,
        total_model_turns=turns,
        tool_calls_by_name={"read_file": tools},
        total_tool_calls=tools,
        patch_attempts=patches,
        rejected_patch_attempts=0 if resolved or not patches else 1,
        target_test_executions=2,
        regression_executions=1 if resolved else 0,
        input_tokens=turns * 5,
        output_tokens=turns * 2,
        reasoning_tokens=turns,
        total_tokens=turns * 7,
        model_request_count=turns,
        api_error_count=0,
        wall_clock_duration_seconds=duration,
        model_latency_seconds=duration / 5,
        test_execution_duration_seconds=duration / 2,
        modified_file_count=1 if patches else 0,
        inserted_lines=2 if resolved else 0,
        deleted_lines=1 if resolved else 0,
        patch_size_bytes=patches * 100,
        final_patch_path=f"/artifacts/{run_id}/final.patch",
        report_path=f"/artifacts/{run_id}/report.json",
        trace_path=f"/artifacts/{run_id}/trace.jsonl",
        original_repository_unchanged=True,
        budget_exhausted_observed=category is FailureCategory.BUDGET_EXHAUSTED,
    )


def _aggregate(
    runs: list[BenchmarkRunRecord],
    tmp_path: Path,
    *,
    mode: BenchmarkExecutionMode = BenchmarkExecutionMode.SCRIPTED_OFFLINE,
):
    provider = "scripted" if mode is BenchmarkExecutionMode.SCRIPTED_OFFLINE else "openai"
    return aggregate_benchmark_runs(
        suite_id="mvp",
        fingerprint=_fingerprint(),
        execution_mode=mode,
        provider=provider,
        model="deterministic-script-v1" if provider == "scripted" else "test-model",
        runs_per_case=1,
        selected_case_ids=[run.case_id for run in runs],
        runs=runs,
        reproducibility=_reproducibility(mode),
        artifacts={
            "benchmark_summary_json": str(tmp_path / "benchmark-summary.json"),
            "benchmark_runs_csv": str(tmp_path / "benchmark-runs.csv"),
            "benchmark_report_markdown": str(tmp_path / "benchmark-report.md"),
        },
    )


def test_aggregate_metrics_average_median_and_failure_categories(tmp_path: Path) -> None:
    runs = [
        _run(
            case_id="resolved-case",
            run_id="resolved-1",
            status=FinalStatus.RESOLVED,
            category=FailureCategory.RESOLVED,
            turns=2,
            tools=3,
            patches=1,
            duration=10,
        ),
        _run(
            case_id="budget-case",
            run_id="budget-1",
            status=FinalStatus.AGENT_BUDGET_EXHAUSTED,
            category=FailureCategory.BUDGET_EXHAUSTED,
            turns=4,
            tools=5,
            patches=3,
            duration=20,
        ),
    ]

    summary = _aggregate(runs, tmp_path)

    assert summary.total_attempts == 2
    assert summary.resolved_attempts == 1
    assert summary.attempt_level_resolution_rate == 0.5
    assert summary.average_model_turns == summary.median_model_turns == 3
    assert summary.average_tool_calls == summary.median_tool_calls == 4
    assert summary.average_patch_attempts == summary.median_patch_attempts == 2
    assert summary.average_duration_seconds == summary.median_duration_seconds == 15
    assert summary.average_patch_size_bytes == 200
    assert summary.failure_counts_by_category[FailureCategory.RESOLVED] == 1
    assert summary.failure_counts_by_category[FailureCategory.BUDGET_EXHAUSTED] == 1
    assert summary.tool_usage_distribution == {"read_file": 8}
    assert summary.failure_analysis.budget_exhausted_runs == ["budget-1"]


def test_scripted_and_live_results_are_never_mixed(tmp_path: Path) -> None:
    scripted = _run(
        case_id="scripted",
        run_id="scripted-1",
        status=FinalStatus.RESOLVED,
        category=FailureCategory.RESOLVED,
        turns=1,
        tools=1,
        patches=1,
        duration=1,
    )
    live = _run(
        case_id="live",
        run_id="live-1",
        status=FinalStatus.MODEL_STOPPED,
        category=FailureCategory.MODEL_STOPPED,
        mode=BenchmarkExecutionMode.LIVE_MODEL,
        turns=1,
        tools=1,
        patches=1,
        duration=1,
    )

    with pytest.raises(ValueError, match="must not be mixed"):
        _aggregate([scripted, live], tmp_path)


def test_json_csv_consistency_markdown_and_secret_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-super-secret-key")
    run = _run(
        case_id="resolved-case",
        run_id="resolved-1",
        status=FinalStatus.RESOLVED,
        category=FailureCategory.RESOLVED,
        turns=2,
        tools=3,
        patches=1,
        duration=10,
    )
    summary = _aggregate([run], tmp_path)

    write_benchmark_summary(summary, tmp_path)

    json_payload = json.loads(
        (tmp_path / "benchmark-summary.json").read_text(encoding="utf-8")
    )
    with (tmp_path / "benchmark-runs.csv").open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    markdown = (tmp_path / "benchmark-report.md").read_text(encoding="utf-8")
    assert len(json_payload["runs"]) == len(csv_rows) == 1
    assert json_payload["runs"][0]["run_id"] == csv_rows[0]["run_id"]
    assert json_payload["runs"][0]["final_status"] == csv_rows[0]["final_status"]
    assert "| Case | Status | Turns | Tools | Patches |" in markdown
    assert "empirical" in markdown.lower()
    all_artifacts = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(tmp_path.iterdir())
    )
    assert "sentinel-super-secret-key" not in all_artifacts


def test_nonzero_exit_when_all_live_runs_fail(tmp_path: Path) -> None:
    failed = _run(
        case_id="live-case",
        run_id="live-1",
        status=FinalStatus.MODEL_STOPPED,
        category=FailureCategory.MODEL_STOPPED,
        mode=BenchmarkExecutionMode.LIVE_MODEL,
        turns=1,
        tools=0,
        patches=0,
        duration=1,
    )
    summary = _aggregate([failed], tmp_path, mode=BenchmarkExecutionMode.LIVE_MODEL)
    assert benchmark_exit_code(summary) == 4


def test_infrastructure_exit_when_no_live_run_executes(tmp_path: Path) -> None:
    failed = _run(
        case_id="live-case",
        run_id="live-1",
        status=FinalStatus.MODEL_CONFIGURATION_ERROR,
        category=FailureCategory.MODEL_CONFIGURATION,
        mode=BenchmarkExecutionMode.LIVE_MODEL,
        turns=0,
        tools=0,
        patches=0,
        duration=0,
        baseline=TestOutcome.NOT_RUN,
    )
    summary = _aggregate([failed], tmp_path, mode=BenchmarkExecutionMode.LIVE_MODEL)
    assert benchmark_exit_code(summary) == 3
