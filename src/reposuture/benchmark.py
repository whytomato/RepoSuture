"""Sequential benchmark validation and Agent evaluation orchestration."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reposuture import __version__
from reposuture.agent import AgentResponse, FakeLLM, LLMClient, ToolCall
from reposuture.benchmark_reporting import (
    BenchmarkExecutionMode,
    BenchmarkRunRecord,
    BenchmarkSummary,
    ReproducibilityMetadata,
    ValidationCaseRecord,
    ValidationSummary,
    aggregate_benchmark_runs,
    classify_failure,
    final_patch_line_counts,
    finite_nonnegative,
    write_benchmark_summary,
    write_validation_summary,
)
from reposuture.benchmark_spec import (
    BenchmarkSuiteError,
    LoadedBenchmarkCase,
    LoadedBenchmarkSuite,
    load_benchmark_suite,
)
from reposuture.process import ProcessRunner
from reposuture.repair import ProgressCallback, repair_case
from reposuture.reporting import FinalStatus, RunReport, TestOutcome
from reposuture.runner import verify_case
from reposuture.workspace import (
    ArtifactContainmentError,
    WorkspaceError,
    validate_artifacts_outside_git_root,
)

BenchmarkLLMFactory = Callable[[LoadedBenchmarkCase, int], LLMClient]


@dataclass(frozen=True, slots=True)
class TraceObservations:
    target_pass_regression_fail: bool = False
    policy_rejected: bool = False
    budget_exhausted: bool = False
    model_stopped_without_verification: bool = False
    infrastructure_failure: bool = False
    search_failure: bool = False
    discarded_extra_tool_calls: int = 0


def _prepare_artifacts_root(root: Path, *, aggregate_names: Sequence[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise BenchmarkSuiteError(f"artifacts path is not a directory: {resolved}")
    existing = [name for name in aggregate_names if (resolved / name).exists()]
    if existing:
        raise BenchmarkSuiteError(
            "refusing to overwrite existing aggregate artifacts: " + ", ".join(existing)
        )
    return resolved


def _ensure_artifacts_outside_repositories(
    artifacts_root: Path,
    suite: LoadedBenchmarkSuite,
    runner: ProcessRunner,
) -> None:
    for loaded in suite.cases:
        try:
            validate_artifacts_outside_git_root(
                loaded.agent_case.repository,
                artifacts_root,
                runner,
            )
        except ArtifactContainmentError as exc:
            raise BenchmarkSuiteError(
                "benchmark artifacts directory must be outside every fixture repository"
            ) from exc
        except WorkspaceError as exc:
            raise BenchmarkSuiteError(str(exc)) from exc


def _safe_identifier(value: str, maximum: int) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", value).strip("-.")[:maximum] or "item"


def _validation_run_id(suite: LoadedBenchmarkSuite, case_id: str) -> str:
    return (
        f"val-{_safe_identifier(suite.manifest.suite_id, 12)}-"
        f"{_safe_identifier(case_id, 28)}-{suite.fingerprint.value[:8]}"
    )


def _benchmark_run_id(
    suite: LoadedBenchmarkSuite,
    case_id: str,
    run_number: int,
    mode: BenchmarkExecutionMode,
) -> str:
    mode_label = "s" if mode is BenchmarkExecutionMode.SCRIPTED_OFFLINE else "l"
    return (
        f"bn-{_safe_identifier(suite.manifest.suite_id, 12)}-{mode_label}-"
        f"{_safe_identifier(case_id, 28)}-r{run_number:03d}-"
        f"{suite.fingerprint.value[:8]}"
    )


def _version_line(result_stdout: str, result_stderr: str, fallback: str) -> str:
    lines = [
        line.strip()
        for line in (result_stdout + "\n" + result_stderr).splitlines()
        if line.strip()
    ]
    return lines[0][:500] if lines else fallback


def _maven_wrapper_version(repository: Path) -> str:
    properties = repository / ".mvn" / "wrapper" / "maven-wrapper.properties"
    wrapper = repository / "mvnw"
    try:
        properties_text = properties.read_text(encoding="utf-8")
        wrapper_text = wrapper.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "unavailable"
    maven_match = re.search(r"apache-maven/([^/]+)/", properties_text)
    wrapper_match = re.search(r"version ([0-9]+(?:\.[0-9]+)+)", wrapper_text)
    maven = maven_match.group(1) if maven_match else "unknown"
    wrapper_version = wrapper_match.group(1) if wrapper_match else "unknown"
    return f"Maven {maven} via Maven Wrapper {wrapper_version} (pinned)"


def _git_metadata(runner: ProcessRunner, project_root: Path) -> tuple[str, bool]:
    commit = runner.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=project_root,
        timeout_seconds=30,
    )
    status = runner.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_root,
        timeout_seconds=30,
    )
    commit_value = commit.stdout.strip() if commit.succeeded else "unavailable"
    dirty = not status.succeeded or bool(status.stdout)
    return commit_value[:128], dirty


def _reproducibility_metadata(
    *,
    suite: LoadedBenchmarkSuite,
    artifacts_root: Path,
    provider: str,
    model: str,
    cli_arguments: Sequence[str],
    budget_values: dict[str, int],
    random_seed: int | None,
    runner: ProcessRunner,
) -> ReproducibilityMetadata:
    project_root = Path(__file__).resolve().parents[2]
    commit, dirty = _git_metadata(runner, project_root)
    java = runner.run(["java", "-version"], cwd=artifacts_root, timeout_seconds=15)
    java_version = (
        _version_line(java.stdout, java.stderr, "unavailable")
        if java.infrastructure_error is None
        else "unavailable"
    )
    try:
        openai_version = (
            importlib.metadata.version("openai")
            if provider in {"openai", "openrouter"}
            else None
        )
    except importlib.metadata.PackageNotFoundError:
        openai_version = (
            "not installed" if provider in {"openai", "openrouter"} else None
        )
    repository = suite.cases[0].agent_case.repository
    return ReproducibilityMetadata(
        project_git_commit=commit,
        project_worktree_dirty=dirty,
        project_version=__version__,
        operating_system=platform.platform()[:500] or sys.platform,
        python_version=platform.python_version(),
        java_version=java_version,
        maven_version=_maven_wrapper_version(repository),
        openai_sdk_version=openai_version,
        provider=provider,
        model=model,
        run_timestamp_utc=datetime.now(UTC),
        cli_arguments=[str(argument)[:2_000] for argument in cli_arguments[:100]],
        budget_values=dict(sorted(budget_values.items())),
        random_seed=random_seed,
    )


def _validation_failure_reason(report: RunReport, checks: list[str]) -> str | None:
    if checks:
        return "; ".join(checks)[:4_000]
    return report.failure_reason


def _validation_record(case_id: str, report: RunReport) -> ValidationCaseRecord:
    baseline_observed = (
        report.baseline_test_result.outcome is TestOutcome.FAIL
        and report.baseline_test_result.test_observed
        and report.baseline_test_result.target_found
    )
    production_only = bool(report.affected_files) and set(
        report.file_classifications.values()
    ) == {"production"}
    cleanup = (
        report.worktree_path is not None
        and not report.worktree_retained
        and not report.worktree_exists_at_report
        and not report.worktree_path.exists()
    )
    checks: list[str] = []
    if not baseline_observed:
        checks.append("baseline target failure was not observed")
    if not report.patch_applied or report.patch_size <= 0:
        checks.append("golden Patch was empty or not applied")
    if not production_only:
        checks.append("golden Patch did not change production code only")
    if report.modifies_tests:
        checks.append("golden Patch modified tests")
    if report.modifies_build:
        checks.append("golden Patch modified build files")
    if report.modifies_maven_wrapper:
        checks.append("golden Patch modified Maven Wrapper files")
    if report.modifies_ci:
        checks.append("golden Patch modified CI files")
    if report.patched_target_test_result.outcome is not TestOutcome.PASS:
        checks.append("patched target test did not pass")
    if report.regression_result.outcome is not TestOutcome.PASS:
        checks.append("configured regression suite did not pass")
    if not report.original_repository_unchanged:
        checks.append("original repository integrity check failed")
    if not cleanup:
        checks.append("worktree cleanup was not verified")
    valid = report.final_status is FinalStatus.RESOLVED and not checks
    return ValidationCaseRecord(
        case_id=case_id,
        valid=valid,
        final_status=report.final_status,
        baseline_result=report.baseline_test_result.outcome,
        baseline_target_observed=baseline_observed,
        patched_target_result=report.patched_target_test_result.outcome,
        regression_result=report.regression_result.outcome,
        golden_patch_nonempty=report.patch_applied and report.patch_size > 0,
        production_only=production_only,
        original_repository_unchanged=report.original_repository_unchanged,
        worktree_cleanup_verified=cleanup,
        report_path=report.artifacts["report"],
        failure_reason=_validation_failure_reason(report, checks),
    )


def validate_benchmark(
    suite_file: Path,
    artifacts_dir: Path,
    *,
    process_runner: ProcessRunner | None = None,
    progress: ProgressCallback | None = None,
    cli_arguments: Sequence[str] = (),
) -> ValidationSummary:
    """Run real baseline/golden/target/regression validation for every suite Case."""

    emit = progress or (lambda _message: None)
    runner = process_runner or ProcessRunner(max_output_bytes=10 * 1024 * 1024)
    suite = load_benchmark_suite(suite_file, process_runner=runner)
    _ensure_artifacts_outside_repositories(artifacts_dir, suite, runner)
    root = _prepare_artifacts_root(
        artifacts_dir,
        aggregate_names=(
            "validation-summary.json",
            "validation-summary.csv",
            "validation-report.md",
        ),
    )
    per_case_root = root / "cases"
    per_case_root.mkdir(exist_ok=True)
    emit(f"Suite: {suite.manifest.suite_id}")
    records: list[ValidationCaseRecord] = []
    for loaded in suite.cases:
        case_id = loaded.reference.id
        emit(f"Case: {case_id}")
        report = verify_case(
            loaded.validation_case_path,
            per_case_root,
            process_runner=runner,
            run_id=_validation_run_id(suite, case_id),
        )
        record = _validation_record(case_id, report)
        records.append(record)
        emit(f"  Baseline: {record.baseline_result.value}")
        emit(f"  Target: {record.patched_target_result.value}")
        emit(f"  Regression: {record.regression_result.value}")
        emit(f"  Validation: {'VALID' if record.valid else 'INVALID'}")
    artifacts = {
        "validation_summary_json": str(root / "validation-summary.json"),
        "validation_summary_csv": str(root / "validation-summary.csv"),
        "validation_report_markdown": str(root / "validation-report.md"),
    }
    reproducibility = _reproducibility_metadata(
        suite=suite,
        artifacts_root=root,
        provider="deterministic",
        model="golden-patch-validator",
        cli_arguments=cli_arguments,
        budget_values=suite.manifest.default_agent_budgets.model_dump(),
        random_seed=None,
        runner=runner,
    )
    valid_count = sum(record.valid for record in records)
    summary = ValidationSummary(
        suite_id=suite.manifest.suite_id,
        benchmark_fingerprint=suite.fingerprint,
        total_cases=len(records),
        valid_cases=valid_count,
        invalid_cases=len(records) - valid_count,
        all_valid=valid_count == len(records),
        results=records,
        reproducibility=reproducibility,
        artifacts=artifacts,
    )
    write_validation_summary(summary, root)
    emit(f"Aggregate report: {root / 'validation-report.md'}")
    return summary


def _scripted_llm(loaded: LoadedBenchmarkCase) -> FakeLLM:
    if loaded.scripted_case is None:
        raise BenchmarkSuiteError(
            f"Case {loaded.reference.id} has no scripted provider fixture"
        )
    responses: list[AgentResponse] = []
    call_number = 0

    def request(name: str, arguments: dict[str, object]) -> None:
        nonlocal call_number
        call_number += 1
        responses.append(
            AgentResponse.request_tool(
                ToolCall(
                    call_id=f"script-{call_number}",
                    name=name,
                    arguments=arguments,
                )
            )
        )

    request("list_files", {"path": "src/main/java", "max_depth": 8})
    request(
        "search_code",
        {
            "query": loaded.scripted_case.search_query,
            "path": "src/main/java",
            "file_type": "java",
        },
    )
    for path in loaded.scripted_case.read_files:
        request("read_file", {"path": path, "start_line": 1, "end_line": 160})
    for patch_path in loaded.scripted_patch_paths:
        request("apply_patch", {"patch": patch_path.read_text(encoding="utf-8")})
    return FakeLLM(responses)


def _trace_observations(path: Path) -> TraceObservations:
    target_regression = False
    policy = False
    budget = False
    stopped = False
    infrastructure = False
    search_failure = False
    discarded_extra_tool_calls = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return TraceObservations(infrastructure_failure=True)
    for line in lines[:10_000]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            infrastructure = True
            continue
        if not isinstance(event, dict):
            infrastructure = True
            continue
        event_type = event.get("event_type")
        status = event.get("status")
        metadata = event.get("metadata")
        tool_name = metadata.get("tool_name") if isinstance(metadata, dict) else None
        if event_type == "regression_test_completed" and status == "FAIL":
            target_regression = True
        if status == "POLICY_REJECTED":
            policy = True
        if event_type == "budget_exhausted":
            budget = True
        if event_type == "model_stopped":
            stopped = True
        if status == "INFRASTRUCTURE_ERROR":
            infrastructure = True
        if tool_name == "search_code" and status == "EXECUTION_ERROR":
            search_failure = True
        if event_type == "provider_tool_calls_sequentialized" and isinstance(
            metadata, dict
        ):
            discarded = metadata.get("discarded_tool_calls")
            if isinstance(discarded, int) and not isinstance(discarded, bool):
                discarded_extra_tool_calls += max(discarded, 0)
    return TraceObservations(
        target_pass_regression_fail=target_regression,
        policy_rejected=policy,
        budget_exhausted=budget,
        model_stopped_without_verification=stopped,
        infrastructure_failure=infrastructure,
        search_failure=search_failure,
        discarded_extra_tool_calls=discarded_extra_tool_calls,
    )


def _run_record(
    *,
    suite: LoadedBenchmarkSuite,
    loaded: LoadedBenchmarkCase,
    run_number: int,
    mode: BenchmarkExecutionMode,
    requested_provider: str,
    report: RunReport,
) -> BenchmarkRunRecord:
    trace_path = Path(report.artifacts["trace"])
    observations = _trace_observations(trace_path)
    final_patch = Path(report.artifacts["final_patch"])
    inserted, deleted = final_patch_line_counts(final_patch)
    baseline_reproduced = (
        report.baseline_test_result.outcome is TestOutcome.FAIL
        and report.baseline_test_result.test_observed
        and report.baseline_test_result.target_found
    )
    category = classify_failure(
        report,
        search_failure_observed=observations.search_failure,
    )
    return BenchmarkRunRecord(
        suite_id=suite.manifest.suite_id,
        benchmark_fingerprint=suite.fingerprint.value,
        case_id=loaded.reference.id,
        run_number=run_number,
        run_id=report.run_id,
        execution_mode=mode,
        agent_execution_mode=report.execution_mode,
        provider=report.provider or requested_provider,
        model=report.model or "unavailable",
        final_status=report.final_status,
        terminal_status=report.terminal_status,
        primary_failure=report.primary_failure,
        observed_failures=report.observed_failures,
        failure_category=category,
        failure_reason=report.failure_reason,
        baseline_reproduced=baseline_reproduced,
        baseline_result=report.baseline_test_result.outcome,
        target_test_result=report.patched_target_test_result.outcome,
        regression_result=report.regression_result.outcome,
        total_model_turns=report.total_model_turns,
        tool_calls_by_name=report.tool_calls_by_name,
        total_tool_calls=report.total_tool_calls,
        generated_tool_calls=(
            report.total_tool_calls + observations.discarded_extra_tool_calls
        ),
        executed_tool_calls=report.total_tool_calls,
        discarded_extra_tool_calls=observations.discarded_extra_tool_calls,
        patch_attempts=report.total_patch_attempts,
        rejected_patch_attempts=sum(
            not attempt.accepted for attempt in report.patch_attempts
        ),
        normalization_used=any(
            attempt.normalization_occurred for attempt in report.patch_attempts
        ),
        recount_used=any(attempt.recount_used for attempt in report.patch_attempts),
        target_test_executions=report.target_test_execution_count,
        regression_executions=report.regression_execution_count,
        input_tokens=report.input_token_usage,
        output_tokens=report.output_token_usage,
        reasoning_tokens=report.reasoning_token_usage,
        total_tokens=report.input_token_usage + report.output_token_usage,
        model_request_count=report.model_request_count,
        api_error_count=report.api_error_count,
        provider_accepted=report.provider_accepted,
        provider_rejected=report.provider_rejected,
        model_executed=report.model_executed,
        model_tool_call_observed=report.model_tool_call_observed,
        wall_clock_duration_seconds=finite_nonnegative(report.total_duration),
        model_latency_seconds=finite_nonnegative(report.model_latency_seconds),
        test_execution_duration_seconds=finite_nonnegative(
            report.test_execution_duration_seconds
        ),
        modified_file_count=len(report.affected_files),
        inserted_lines=inserted,
        deleted_lines=deleted,
        patch_size_bytes=report.patch_size,
        final_patch_path=str(final_patch),
        report_path=report.artifacts["report"],
        trace_path=str(trace_path),
        original_repository_unchanged=report.original_repository_unchanged,
        target_pass_regression_fail_observed=(
            observations.target_pass_regression_fail
        ),
        policy_rejected_observed=observations.policy_rejected,
        budget_exhausted_observed=observations.budget_exhausted,
        model_stopped_without_verification=(
            observations.model_stopped_without_verification
        ),
        infrastructure_failure=(
            observations.infrastructure_failure
            or report.final_status is FinalStatus.INFRASTRUCTURE_ERROR
        ),
    )


def _select_cases(
    suite: LoadedBenchmarkSuite,
    case_ids: Sequence[str] | None,
) -> list[LoadedBenchmarkCase]:
    if case_ids is None or not case_ids:
        return list(suite.cases)
    requested = list(case_ids)
    if len(requested) != len(set(requested)):
        raise BenchmarkSuiteError("case filters must not contain duplicate ids")
    known = {loaded.reference.id: loaded for loaded in suite.cases}
    unknown = [case_id for case_id in requested if case_id not in known]
    if unknown:
        raise BenchmarkSuiteError("unknown benchmark case ids: " + ", ".join(unknown))
    requested_set = set(requested)
    return [loaded for loaded in suite.cases if loaded.reference.id in requested_set]


def _effective_budgets(
    suite: LoadedBenchmarkSuite,
    *,
    max_turns: int | None,
    max_tool_calls: int | None,
    max_patch_attempts: int | None,
    max_target_test_executions: int | None,
    max_regression_executions: int | None,
    max_wall_clock_seconds: int | None,
) -> dict[str, int]:
    values = suite.manifest.default_agent_budgets.model_dump()
    overrides = {
        "max_model_turns": max_turns,
        "max_tool_calls": max_tool_calls,
        "max_patch_attempts": max_patch_attempts,
        "max_target_test_executions": max_target_test_executions,
        "max_regression_executions": max_regression_executions,
        "max_wall_clock_seconds": max_wall_clock_seconds,
    }
    for name, value in overrides.items():
        if value is not None:
            values[name] = value
    return values


def run_benchmark(
    suite_file: Path,
    artifacts_dir: Path,
    *,
    provider: str,
    model_override: str | None = None,
    runs_per_case: int | None = None,
    case_ids: Sequence[str] | None = None,
    continue_on_failure: bool = True,
    random_seed: int | None = None,
    max_turns: int | None = None,
    max_tool_calls: int | None = None,
    max_patch_attempts: int | None = None,
    max_target_test_executions: int | None = None,
    max_regression_executions: int | None = None,
    max_wall_clock_seconds: int | None = None,
    process_runner: ProcessRunner | None = None,
    progress: ProgressCallback | None = None,
    llm_factory: BenchmarkLLMFactory | None = None,
    cli_arguments: Sequence[str] = (),
) -> BenchmarkSummary:
    """Execute fresh sequential Agent runs and emit aggregate benchmark evidence."""

    if provider not in {"openai", "scripted"}:
        raise BenchmarkSuiteError("provider must be either 'openai' or 'scripted'")
    emit = progress or (lambda _message: None)
    runner = process_runner or ProcessRunner(max_output_bytes=10 * 1024 * 1024)
    suite = load_benchmark_suite(suite_file, process_runner=runner)
    selected = _select_cases(suite, case_ids)
    effective_runs = runs_per_case or suite.manifest.default_runs_per_case
    if isinstance(effective_runs, bool) or not 1 <= effective_runs <= 20:
        raise BenchmarkSuiteError("runs_per_case must be an integer between 1 and 20")
    mode = (
        BenchmarkExecutionMode.SCRIPTED_OFFLINE
        if provider == "scripted"
        else BenchmarkExecutionMode.LIVE_MODEL
    )
    _ensure_artifacts_outside_repositories(artifacts_dir, suite, runner)
    root = _prepare_artifacts_root(
        artifacts_dir,
        aggregate_names=(
            "benchmark-summary.json",
            "benchmark-runs.csv",
            "benchmark-report.md",
        ),
    )
    run_root = root / "runs"
    run_root.mkdir(exist_ok=True)
    emit(f"Suite: {suite.manifest.suite_id}")
    records: list[BenchmarkRunRecord] = []
    stop = False
    for loaded in selected:
        for run_number in range(1, effective_runs + 1):
            case_id = loaded.reference.id
            emit(f"Case: {case_id}; run: {run_number}/{effective_runs}")
            active_llm: LLMClient | None
            if llm_factory is not None:
                active_llm = llm_factory(loaded, run_number)
            elif provider == "scripted":
                active_llm = _scripted_llm(loaded)
            else:
                active_llm = None

            def case_progress(message: str, prefix: str = case_id) -> None:
                emit(f"  {prefix}: {message}")

            report = repair_case(
                loaded.agent_case_path,
                run_root,
                model_override=model_override,
                max_turns=max_turns,
                max_tool_calls=max_tool_calls,
                max_patch_attempts=max_patch_attempts,
                max_target_test_executions=max_target_test_executions,
                max_regression_executions=max_regression_executions,
                max_wall_clock_seconds=max_wall_clock_seconds,
                llm_client=active_llm,
                injected_provider="scripted" if active_llm is not None else None,
                injected_model=(
                    "deterministic-script-v1" if provider == "scripted" else None
                ),
                process_runner=runner,
                progress=case_progress,
                run_id=_benchmark_run_id(suite, case_id, run_number, mode),
            )
            record = _run_record(
                suite=suite,
                loaded=loaded,
                run_number=run_number,
                mode=mode,
                requested_provider=provider,
                report=report,
            )
            records.append(record)
            emit(f"  Baseline: {record.baseline_result.value}")
            emit(f"  Target: {record.target_test_result.value}")
            emit(f"  Regression: {record.regression_result.value}")
            emit(f"  Final: {record.final_status.value}")
            if not continue_on_failure and record.final_status is not FinalStatus.RESOLVED:
                stop = True
                break
        if stop:
            break
    summary_provider_values = sorted({record.provider for record in records})
    summary_provider = (
        summary_provider_values[0]
        if len(summary_provider_values) == 1
        else ",".join(summary_provider_values)[:64]
        if summary_provider_values
        else provider
    )
    summary_model_values = sorted({record.model for record in records})
    summary_model = (
        summary_model_values[0]
        if len(summary_model_values) == 1
        else ",".join(summary_model_values)[:256]
        if summary_model_values
        else model_override or "unavailable"
    )
    artifacts = {
        "benchmark_summary_json": str(root / "benchmark-summary.json"),
        "benchmark_runs_csv": str(root / "benchmark-runs.csv"),
        "benchmark_report_markdown": str(root / "benchmark-report.md"),
    }
    budgets = _effective_budgets(
        suite,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        max_patch_attempts=max_patch_attempts,
        max_target_test_executions=max_target_test_executions,
        max_regression_executions=max_regression_executions,
        max_wall_clock_seconds=max_wall_clock_seconds,
    )
    reproducibility = _reproducibility_metadata(
        suite=suite,
        artifacts_root=root,
        provider=summary_provider,
        model=summary_model,
        cli_arguments=cli_arguments,
        budget_values=budgets,
        random_seed=random_seed,
        runner=runner,
    )
    summary = aggregate_benchmark_runs(
        suite_id=suite.manifest.suite_id,
        fingerprint=suite.fingerprint,
        execution_mode=mode,
        provider=summary_provider,
        model=summary_model,
        runs_per_case=effective_runs,
        selected_case_ids=[loaded.reference.id for loaded in selected],
        runs=records,
        reproducibility=reproducibility,
        artifacts=artifacts,
    )
    write_benchmark_summary(summary, root)
    emit(f"Aggregate report: {root / 'benchmark-report.md'}")
    return summary


def benchmark_exit_code(summary: BenchmarkSummary) -> int:
    """Zero requires at least one deterministic resolution; no executable run is infra."""

    if summary.resolved_attempts > 0:
        return 0
    if summary.executable_attempts == 0:
        return 3
    return 4
