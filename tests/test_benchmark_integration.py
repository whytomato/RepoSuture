from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from benchmarks.bootstrap_fixture import bootstrap_fixture
from patchpilot.agent import (
    AgentMessage,
    AgentResponse,
    FakeLLM,
    ProviderContinuation,
    ToolCall,
    ToolSpec,
)
from patchpilot.benchmark import run_benchmark, validate_benchmark
from patchpilot.benchmark_reporting import BenchmarkExecutionMode
from patchpilot.benchmark_spec import BenchmarkSuiteError, LoadedBenchmarkCase
from patchpilot.process import ProcessRunner
from patchpilot.reporting import FinalStatus, RunReport, TestOutcome

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITE = PROJECT_ROOT / "benchmarks" / "suites" / "mvp.yaml"
FIXTURE_REPOSITORY = PROJECT_ROOT / "benchmarks" / "fixtures" / "null-email-repo"


def _require_java(tmp_path: Path) -> None:
    result = ProcessRunner().run(["java", "-version"], cwd=tmp_path, timeout_seconds=15)
    if result.infrastructure_error is not None:
        pytest.skip(f"Java is unavailable: {result.infrastructure_error}")


def _git(*arguments: str) -> str:
    return _git_at(FIXTURE_REPOSITORY, *arguments)


def _git_at(repository: Path, *arguments: str) -> str:
    result = ProcessRunner().run(
        ["git", *arguments],
        cwd=repository,
        timeout_seconds=30,
    )
    assert result.succeeded, result.infrastructure_error or result.stderr
    return result.stdout.strip()


class CapturingStopLLM:
    def __init__(self) -> None:
        self.messages: list[AgentMessage] = []

    def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        continuation: ProviderContinuation | None = None,
    ) -> AgentResponse:
        del tools, continuation
        self.messages.extend(messages)
        return AgentResponse.finish("No verified repair candidate.")


@pytest.mark.integration
def test_all_six_cases_validate_through_real_maven_and_junit(tmp_path: Path) -> None:
    _require_java(tmp_path)
    bootstrap_fixture(FIXTURE_REPOSITORY)
    before_head = _git("rev-parse", "HEAD")
    before_status = _git("status", "--porcelain=v1", "--untracked-files=all")

    summary = validate_benchmark(SUITE, tmp_path / "validation")

    assert summary.all_valid
    assert summary.total_cases == summary.valid_cases == 6
    assert all(result.baseline_result is TestOutcome.FAIL for result in summary.results)
    assert all(
        result.patched_target_result is TestOutcome.PASS for result in summary.results
    )
    assert all(result.regression_result is TestOutcome.PASS for result in summary.results)
    assert all(result.original_repository_unchanged for result in summary.results)
    assert all(result.worktree_cleanup_verified for result in summary.results)
    assert _git("rev-parse", "HEAD") == before_head
    assert _git("status", "--porcelain=v1", "--untracked-files=all") == before_status


@pytest.mark.integration
def test_benchmark_entry_points_reject_artifacts_inside_fixture_before_writing(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "benchmarks"
    shutil.copytree(
        PROJECT_ROOT / "benchmarks",
        benchmark_root,
        ignore=shutil.ignore_patterns(".git", "target", "__pycache__"),
    )
    repository = benchmark_root / "fixtures/null-email-repo"
    suite = benchmark_root / "suites/mvp.yaml"
    bootstrap_fixture(repository)
    before_head = _git_at(repository, "rev-parse", "HEAD")
    before_status = _git_at(repository, "status", "--porcelain=v1", "--untracked-files=all")
    validation_artifacts = repository / ".artifacts-boundary-validation"
    benchmark_artifacts = repository / ".artifacts-boundary-benchmark"

    with pytest.raises(BenchmarkSuiteError, match="outside every fixture repository"):
        validate_benchmark(suite, validation_artifacts)
    with pytest.raises(BenchmarkSuiteError, match="outside every fixture repository"):
        run_benchmark(
            suite,
            benchmark_artifacts,
            provider="scripted",
            runs_per_case=1,
        )

    assert not validation_artifacts.exists()
    assert not benchmark_artifacts.exists()
    assert _git_at(repository, "rev-parse", "HEAD") == before_head
    assert (
        _git_at(repository, "status", "--porcelain=v1", "--untracked-files=all")
        == before_status
    )


@pytest.mark.integration
def test_scripted_regression_trap_uses_real_tools_and_repairs_after_regression(
    tmp_path: Path,
) -> None:
    _require_java(tmp_path)
    bootstrap_fixture(FIXTURE_REPOSITORY)

    summary = run_benchmark(
        SUITE,
        tmp_path / "benchmark",
        provider="scripted",
        case_ids=["quota-regression-trap"],
        runs_per_case=1,
    )

    assert summary.execution_mode is BenchmarkExecutionMode.SCRIPTED_OFFLINE
    assert summary.resolved_attempts == 1
    run = summary.runs[0]
    assert run.final_status is FinalStatus.RESOLVED
    assert run.patch_attempts == 2
    assert run.target_test_executions == 3
    assert run.regression_executions == 2
    assert run.target_pass_regression_fail_observed
    assert run.original_repository_unchanged
    assert Path(run.report_path).is_file()
    assert Path(run.trace_path).is_file()
    assert Path(run.final_patch_path).read_text(encoding="utf-8").startswith("diff --git")


@pytest.mark.integration
def test_failed_case_does_not_stop_later_case_and_runs_are_isolated(
    tmp_path: Path,
) -> None:
    _require_java(tmp_path)
    bootstrap_fixture(FIXTURE_REPOSITORY)
    capturer = CapturingStopLLM()

    def factory(loaded: LoadedBenchmarkCase, run_number: int):
        assert run_number == 1
        if loaded.reference.id == "null-input-validation":
            return capturer
        patch = loaded.scripted_patch_paths[0].read_text(encoding="utf-8")
        return FakeLLM(
            [
                AgentResponse.request_tool(
                    ToolCall(
                        call_id="later-case-patch",
                        name="apply_patch",
                        arguments={"patch": patch},
                    )
                )
            ]
        )

    summary = run_benchmark(
        SUITE,
        tmp_path / "benchmark",
        provider="scripted",
        case_ids=["null-input-validation", "pagination-boundary"],
        runs_per_case=1,
        llm_factory=factory,
    )

    assert summary.total_attempts == 2
    assert [run.final_status for run in summary.runs] == [
        FinalStatus.MODEL_STOPPED,
        FinalStatus.RESOLVED,
    ]
    report_paths = [Path(run.report_path) for run in summary.runs]
    assert report_paths[0].parent != report_paths[1].parent
    reports = [
        RunReport.model_validate_json(path.read_text(encoding="utf-8"))
        for path in report_paths
    ]
    assert reports[0].worktree_path != reports[1].worktree_path
    assert all(report.worktree_path is not None for report in reports)
    assert all(not report.worktree_path.exists() for report in reports if report.worktree_path)
    assert all(report.original_repository_unchanged for report in reports)

    prompt = "\n".join(message.content for message in capturer.messages)
    hidden_patch = (
        PROJECT_ROOT
        / "benchmarks"
        / "validation"
        / "patches"
        / "null-input-validation.patch"
    )
    assert "golden" not in prompt.casefold()
    assert str(hidden_patch) not in prompt
    assert hidden_patch.read_text(encoding="utf-8") not in prompt
    aggregate_payload = json.loads(
        Path(summary.artifacts["benchmark_summary_json"]).read_text(encoding="utf-8")
    )
    assert aggregate_payload["total_attempts"] == 2
