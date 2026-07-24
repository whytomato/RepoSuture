"""Controlled feedback-loop ablation built on the existing repair runtime."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reposuture.agent import LLMClient
from reposuture.benchmark import (
    _effective_budgets,
    _ensure_artifacts_outside_repositories,
    _git_metadata,
    _reproducibility_metadata,
    _run_record,
    _safe_identifier,
    _scripted_llm,
    _select_cases,
)
from reposuture.benchmark_reporting import (
    BENCHMARK_CSV_FIELDS,
    BenchmarkExecutionMode,
    BenchmarkRunRecord,
    aggregate_benchmark_runs,
    aggregate_csv_metrics,
    write_benchmark_summary,
)
from reposuture.benchmark_spec import (
    BenchmarkSuiteError,
    LoadedBenchmarkCase,
    LoadedBenchmarkSuite,
    load_benchmark_suite,
)
from reposuture.process import ProcessRunner
from reposuture.repair import ProgressCallback, repair_case
from reposuture.reporting import AgentExecutionMode, FinalStatus, RunReport
from reposuture.trajectory import load_replay_run

AblationLLMFactory = Callable[[AgentExecutionMode, LoadedBenchmarkCase], LLMClient]
_ALLOWED_MODES = {
    AgentExecutionMode.FULL_AGENT,
    AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK,
}


class AblationPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    case_id: str
    model: str
    execution_mode: AgentExecutionMode
    run_id: str
    artifact_directory: str


class AblationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    suite_id: str
    benchmark_fingerprint: str
    benchmark_execution_mode: BenchmarkExecutionMode
    provider: str
    model: str
    execution_modes: list[AgentExecutionMode] = Field(min_length=2)
    selected_case_ids: list[str] = Field(min_length=1)
    schedule: Literal["interleaved"] = "interleaved"
    total_attempts: int = Field(ge=1)
    budget_values: dict[str, int]
    project_git_commit: str
    project_worktree_dirty: bool
    items: list[AblationPlanItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if set(self.execution_modes) != _ALLOWED_MODES:
            raise ValueError("ablation requires full-agent and single-candidate modes")
        expected = len(self.selected_case_ids) * len(self.execution_modes)
        if self.total_attempts != expected or len(self.items) != expected:
            raise ValueError("ablation attempt count is inconsistent")
        if [item.sequence for item in self.items] != list(range(1, expected + 1)):
            raise ValueError("ablation sequence must be contiguous")
        identities = {(item.case_id, item.execution_mode) for item in self.items}
        if len(identities) != expected:
            raise ValueError("ablation schedule contains duplicate attempts")
        return self


class AblationAttemptManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    sequence: int = Field(ge=1)
    suite_id: str
    benchmark_fingerprint: str
    case_id: str
    run_id: str
    benchmark_execution_mode: BenchmarkExecutionMode
    agent_execution_mode: AgentExecutionMode
    requested_provider: str
    runtime_provider: str
    model: str
    budget_values: dict[str, int]
    project_git_commit: str
    project_worktree_dirty: bool
    report_sha256: str
    trace_sha256: str
    terminal_status: FinalStatus


class AblationModeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_mode: AgentExecutionMode
    assigned_attempts: int = Field(ge=0)
    provider_accepted_attempts: int = Field(ge=0)
    model_executed_attempts: int = Field(ge=0)
    model_tool_call_attempts: int = Field(ge=0)
    resolved_attempts: int = Field(ge=0)
    target_pass_count: int = Field(ge=0)
    regression_pass_count: int = Field(ge=0)
    target_only_false_repairs: int = Field(ge=0)
    patch_attempts: int = Field(ge=0)
    rejected_patch_attempts: int = Field(ge=0)
    total_model_turns: int = Field(ge=0)
    total_tool_calls: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    total_model_latency_seconds: float = Field(ge=0)
    primary_failure_distribution: dict[str, int]
    observed_failure_occurrence_counts: dict[str, int]


class AblationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    suite_id: str
    benchmark_fingerprint: str
    benchmark_execution_mode: BenchmarkExecutionMode
    provider: str
    model: str
    execution_modes: list[AgentExecutionMode]
    selected_case_ids: list[str]
    total_attempts: int = Field(ge=0)
    project_git_commit: str
    project_worktree_dirty: bool
    generated_at_utc: datetime
    schedule: list[AblationPlanItem]
    per_mode: list[AblationModeMetrics]
    runs: list[BenchmarkRunRecord]
    artifacts: dict[str, str]

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.generated_at_utc.utcoffset() != UTC.utcoffset(self.generated_at_utc):
            raise ValueError("ablation timestamp must be timezone-aware UTC")
        if self.total_attempts != len(self.runs):
            raise ValueError("ablation total must equal serialized observations")
        if {run.agent_execution_mode for run in self.runs} - set(
            self.execution_modes
        ):
            raise ValueError("ablation contains an unplanned execution mode")
        return self


def _mode_directory(mode: AgentExecutionMode) -> str:
    return mode.value


def _run_id(
    suite: LoadedBenchmarkSuite,
    case_id: str,
    mode: AgentExecutionMode,
    benchmark_mode: BenchmarkExecutionMode,
) -> str:
    live = "l" if benchmark_mode is BenchmarkExecutionMode.LIVE_MODEL else "s"
    mode_label = "full" if mode is AgentExecutionMode.FULL_AGENT else "single"
    return (
        f"ab-{_safe_identifier(suite.manifest.suite_id, 12)}-{live}-"
        f"{_safe_identifier(case_id, 28)}-{mode_label}-"
        f"{suite.fingerprint.value[:8]}"
    )


def build_ablation_plan(
    suite: LoadedBenchmarkSuite,
    *,
    selected_cases: Sequence[LoadedBenchmarkCase],
    provider: str,
    model: str,
    execution_modes: Sequence[AgentExecutionMode],
    budget_values: dict[str, int],
    project_git_commit: str,
    project_worktree_dirty: bool,
) -> AblationPlan:
    modes = list(execution_modes)
    if set(modes) != _ALLOWED_MODES or len(modes) != 2:
        raise BenchmarkSuiteError(
            "benchmark-ablation requires exactly full-agent and "
            "single-candidate-no-feedback"
        )
    benchmark_mode = (
        BenchmarkExecutionMode.SCRIPTED_OFFLINE
        if provider == "scripted"
        else BenchmarkExecutionMode.LIVE_MODEL
    )
    items: list[AblationPlanItem] = []
    for case_index, loaded in enumerate(selected_cases):
        ordered = list(modes)
        if case_index % 2:
            ordered.reverse()
        for mode in ordered:
            run_id = _run_id(suite, loaded.reference.id, mode, benchmark_mode)
            items.append(
                AblationPlanItem(
                    sequence=len(items) + 1,
                    case_id=loaded.reference.id,
                    model=model,
                    execution_mode=mode,
                    run_id=run_id,
                    artifact_directory=(
                        Path("modes") / _mode_directory(mode) / "runs" / run_id
                    ).as_posix(),
                )
            )
    return AblationPlan(
        suite_id=suite.manifest.suite_id,
        benchmark_fingerprint=suite.fingerprint.value,
        benchmark_execution_mode=benchmark_mode,
        provider=provider,
        model=model,
        execution_modes=modes,
        selected_case_ids=[loaded.reference.id for loaded in selected_cases],
        total_attempts=len(items),
        budget_values=budget_values,
        project_git_commit=project_git_commit,
        project_worktree_dirty=project_worktree_dirty,
        items=items,
    )


def prepare_ablation_plan(
    suite_file: Path,
    *,
    provider: str,
    model: str,
    execution_modes: Sequence[AgentExecutionMode],
    case_ids: Sequence[str] | None = None,
    max_turns: int | None = None,
    max_tool_calls: int | None = None,
    max_patch_attempts: int | None = None,
    max_target_test_executions: int | None = None,
    max_regression_executions: int | None = None,
    max_wall_clock_seconds: int | None = None,
    process_runner: ProcessRunner | None = None,
) -> tuple[LoadedBenchmarkSuite, list[LoadedBenchmarkCase], AblationPlan]:
    if provider not in {"openai", "scripted"}:
        raise BenchmarkSuiteError("provider must be either 'openai' or 'scripted'")
    if not model.strip():
        raise BenchmarkSuiteError("benchmark-ablation requires an explicit model")
    runner = process_runner or ProcessRunner(max_output_bytes=10 * 1024 * 1024)
    suite = load_benchmark_suite(suite_file, process_runner=runner)
    selected = _select_cases(suite, case_ids)
    budgets = _effective_budgets(
        suite,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        max_patch_attempts=max_patch_attempts,
        max_target_test_executions=max_target_test_executions,
        max_regression_executions=max_regression_executions,
        max_wall_clock_seconds=max_wall_clock_seconds,
    )
    commit, dirty = _git_metadata(runner, Path(__file__).resolve().parents[2])
    return suite, selected, build_ablation_plan(
        suite,
        selected_cases=selected,
        provider=provider,
        model=model,
        execution_modes=execution_modes,
        budget_values=budgets,
        project_git_commit=commit,
        project_worktree_dirty=dirty,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".ab-{uuid.uuid4().hex[:12]}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, model: BaseModel) -> None:
    _atomic_write(path, model.model_dump_json(indent=2) + "\n")


def _attempt_manifest(
    item: AblationPlanItem,
    plan: AblationPlan,
    report: RunReport,
    run_directory: Path,
) -> AblationAttemptManifest:
    return AblationAttemptManifest(
        sequence=item.sequence,
        suite_id=plan.suite_id,
        benchmark_fingerprint=plan.benchmark_fingerprint,
        case_id=item.case_id,
        run_id=item.run_id,
        benchmark_execution_mode=plan.benchmark_execution_mode,
        agent_execution_mode=item.execution_mode,
        requested_provider=plan.provider,
        runtime_provider=report.provider or plan.provider,
        model=report.model or item.model,
        budget_values=plan.budget_values,
        project_git_commit=plan.project_git_commit,
        project_worktree_dirty=plan.project_worktree_dirty,
        report_sha256=_sha256(run_directory / "report.json"),
        trace_sha256=_sha256(run_directory / "trace.jsonl"),
        terminal_status=report.terminal_status,
    )


def _load_resumable(
    *,
    root: Path,
    item: AblationPlanItem,
    plan: AblationPlan,
    suite: LoadedBenchmarkSuite,
    loaded: LoadedBenchmarkCase,
) -> BenchmarkRunRecord | None:
    run_directory = root / item.artifact_directory
    manifest_path = run_directory / "ablation-attempt.json"
    if not manifest_path.is_file():
        return None
    if plan.benchmark_execution_mode is not BenchmarkExecutionMode.LIVE_MODEL:
        raise BenchmarkSuiteError("ablation resume accepts live observations only")
    try:
        manifest = AblationAttemptManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        replay = load_replay_run(run_directory)
    except Exception as exc:
        raise BenchmarkSuiteError(
            f"ablation resume integrity failed for {item.run_id}"
        ) from exc
    expected = (
        item.sequence,
        plan.suite_id,
        plan.benchmark_fingerprint,
        item.case_id,
        item.run_id,
        plan.benchmark_execution_mode,
        item.execution_mode,
        plan.provider,
        item.model,
        plan.budget_values,
        plan.project_git_commit,
        False,
    )
    actual = (
        manifest.sequence,
        manifest.suite_id,
        manifest.benchmark_fingerprint,
        manifest.case_id,
        manifest.run_id,
        manifest.benchmark_execution_mode,
        manifest.agent_execution_mode,
        manifest.requested_provider,
        manifest.model,
        manifest.budget_values,
        manifest.project_git_commit,
        manifest.project_worktree_dirty,
    )
    if actual != expected:
        raise BenchmarkSuiteError(f"ablation resume identity mismatch for {item.run_id}")
    report = replay.report
    if (
        report.run_id != item.run_id
        or report.model != item.model
        or report.execution_mode is not item.execution_mode
        or report.terminal_status is not manifest.terminal_status
        or _sha256(replay.report_path) != manifest.report_sha256
        or _sha256(replay.trace_path) != manifest.trace_sha256
    ):
        raise BenchmarkSuiteError(f"ablation resume evidence mismatch for {item.run_id}")
    return _run_record(
        suite=suite,
        loaded=loaded,
        run_number=1,
        mode=plan.benchmark_execution_mode,
        requested_provider=plan.provider,
        report=report,
    )


def _mode_metrics(
    mode: AgentExecutionMode,
    runs: list[BenchmarkRunRecord],
) -> AblationModeMetrics:
    primary: dict[str, int] = {}
    observed: dict[str, int] = {}
    for run in runs:
        if run.primary_failure is not None:
            key = run.primary_failure.value
            primary[key] = primary.get(key, 0) + 1
        for failure in run.observed_failures:
            key = failure.value
            observed[key] = observed.get(key, 0) + 1
    return AblationModeMetrics(
        execution_mode=mode,
        assigned_attempts=len(runs),
        provider_accepted_attempts=sum(run.provider_accepted for run in runs),
        model_executed_attempts=sum(run.model_executed for run in runs),
        model_tool_call_attempts=sum(run.model_tool_call_observed for run in runs),
        resolved_attempts=sum(
            run.terminal_status is FinalStatus.RESOLVED for run in runs
        ),
        target_pass_count=sum(
            run.target_test_result.value == "PASS" for run in runs
        ),
        regression_pass_count=sum(
            run.regression_result.value == "PASS" for run in runs
        ),
        target_only_false_repairs=sum(
            run.target_test_result.value == "PASS"
            and run.regression_result.value != "PASS"
            for run in runs
        ),
        patch_attempts=sum(run.patch_attempts for run in runs),
        rejected_patch_attempts=sum(run.rejected_patch_attempts for run in runs),
        total_model_turns=sum(run.total_model_turns for run in runs),
        total_tool_calls=sum(run.total_tool_calls for run in runs),
        total_tokens=sum(run.total_tokens for run in runs),
        total_model_latency_seconds=sum(run.model_latency_seconds for run in runs),
        primary_failure_distribution=dict(sorted(primary.items())),
        observed_failure_occurrence_counts=dict(sorted(observed.items())),
    )


def _csv(summary: AblationSummary) -> str:
    sequence = {item.run_id: item.sequence for item in summary.schedule}
    metrics_by_mode = {item.execution_mode: item for item in summary.per_mode}
    fields = ("schedule_sequence", *BENCHMARK_CSV_FIELDS)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for run in summary.runs:
        row = run.model_dump(mode="json")
        row["schedule_sequence"] = sequence[run.run_id]
        row["tool_calls_by_name"] = json.dumps(
            row["tool_calls_by_name"], sort_keys=True, separators=(",", ":")
        )
        row["observed_failures"] = json.dumps(
            row["observed_failures"], separators=(",", ":")
        )
        metrics = metrics_by_mode[run.agent_execution_mode]
        row.update(
            aggregate_csv_metrics(
                assigned_attempts=metrics.assigned_attempts,
                provider_accepted_attempts=metrics.provider_accepted_attempts,
                model_executed_attempts=metrics.model_executed_attempts,
                model_tool_call_attempts=metrics.model_tool_call_attempts,
                resolved_attempts=metrics.resolved_attempts,
            )
        )
        writer.writerow({field: row.get(field) for field in fields})
    return stream.getvalue()


def ablation_markdown(summary: AblationSummary) -> str:
    lines = [
        f"# RepoSuture Feedback Ablation: {summary.suite_id}",
        "",
        f"- Model: `{summary.model}`",
        f"- Attempts: {summary.total_attempts}",
        "- Schedule: deterministic, sequential, interleaved",
        "- Correctness is determined only by target and regression verification.",
        "",
        "| Mode | Resolved | Target PASS | Regression PASS | Target-only | "
        "Patches | Rejected | Turns | Tools | Tokens | Model latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metrics in summary.per_mode:
        lines.append(
            f"| `{metrics.execution_mode.value}` | "
            f"{metrics.resolved_attempts}/{metrics.assigned_attempts} | "
            f"{metrics.target_pass_count} | {metrics.regression_pass_count} | "
            f"{metrics.target_only_false_repairs} | {metrics.patch_attempts} | "
            f"{metrics.rejected_patch_attempts} | {metrics.total_model_turns} | "
            f"{metrics.total_tool_calls} | {metrics.total_tokens} | "
            f"{metrics.total_model_latency_seconds:.2f}s |"
        )
    lines.extend(
        [
            "",
            "| Seq | Case | Mode | Status | Target | Regression | Primary failure |",
            "|---:|---|---|---|---|---|---|",
        ]
    )
    by_id = {run.run_id: run for run in summary.runs}
    for item in summary.schedule:
        run = by_id.get(item.run_id)
        if run is None:
            continue
        lines.append(
            f"| {item.sequence} | `{item.case_id}` | `{item.execution_mode.value}` | "
            f"{run.terminal_status.value} | {run.target_test_result.value} | "
            f"{run.regression_result.value} | "
            f"{run.primary_failure.value if run.primary_failure else 'none'} |"
        )
    lines.extend(["", "## Failure distributions", ""])
    for metrics in summary.per_mode:
        primary = ", ".join(
            f"{key}={value}"
            for key, value in metrics.primary_failure_distribution.items()
        ) or "none"
        observed = ", ".join(
            f"{key}={value}"
            for key, value in metrics.observed_failure_occurrence_counts.items()
        ) or "none"
        lines.extend(
            [
                f"- `{metrics.execution_mode.value}` primary: {primary}",
                f"- `{metrics.execution_mode.value}` observed (non-exclusive): "
                f"{observed}",
            ]
        )
    lines.extend(
        [
            "",
            "One run per Case/mode is a controlled engineering ablation, not a causal "
            "or statistically conclusive model-capability estimate.",
            "",
        ]
    )
    return "\n".join(lines)


def run_benchmark_ablation(
    suite_file: Path,
    artifacts_dir: Path,
    *,
    provider: str,
    model: str,
    execution_modes: Sequence[AgentExecutionMode],
    case_ids: Sequence[str] | None = None,
    resume: bool = False,
    max_turns: int | None = None,
    max_tool_calls: int | None = None,
    max_patch_attempts: int | None = None,
    max_target_test_executions: int | None = None,
    max_regression_executions: int | None = None,
    max_wall_clock_seconds: int | None = None,
    process_runner: ProcessRunner | None = None,
    progress: ProgressCallback | None = None,
    llm_factory: AblationLLMFactory | None = None,
    cli_arguments: Sequence[str] = (),
) -> AblationSummary:
    """Execute the locked feedback ablation without duplicating the Agent loop."""

    emit = progress or (lambda _message: None)
    runner = process_runner or ProcessRunner(max_output_bytes=10 * 1024 * 1024)
    suite, selected, plan = prepare_ablation_plan(
        suite_file,
        provider=provider,
        model=model,
        execution_modes=execution_modes,
        case_ids=case_ids,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        max_patch_attempts=max_patch_attempts,
        max_target_test_executions=max_target_test_executions,
        max_regression_executions=max_regression_executions,
        max_wall_clock_seconds=max_wall_clock_seconds,
        process_runner=runner,
    )
    if (
        plan.benchmark_execution_mode is BenchmarkExecutionMode.LIVE_MODEL
        and plan.project_worktree_dirty
    ):
        raise BenchmarkSuiteError("live benchmark-ablation requires a clean worktree")
    if resume and plan.benchmark_execution_mode is not BenchmarkExecutionMode.LIVE_MODEL:
        raise BenchmarkSuiteError("--resume accepts complete live observations only")
    _ensure_artifacts_outside_repositories(artifacts_dir, suite, runner)
    root = artifacts_dir.expanduser().resolve(strict=False)
    if root.exists() and not root.is_dir():
        raise BenchmarkSuiteError("ablation artifacts path is not a directory")
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "ablation-plan.json"
    if plan_path.exists():
        if not resume:
            raise BenchmarkSuiteError("ablation plan exists; use --resume")
        try:
            existing = AblationPlan.model_validate_json(
                plan_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise BenchmarkSuiteError("existing ablation plan is malformed") from exc
        if existing != plan:
            raise BenchmarkSuiteError("existing ablation plan does not match invocation")
    else:
        if any(root.iterdir()):
            raise BenchmarkSuiteError("fresh ablation artifacts directory must be empty")
        _write_json(plan_path, plan)

    by_case = {loaded.reference.id: loaded for loaded in selected}
    records: list[BenchmarkRunRecord] = []
    for item in plan.items:
        loaded = by_case[item.case_id]
        if resume:
            reused = _load_resumable(
                root=root,
                item=item,
                plan=plan,
                suite=suite,
                loaded=loaded,
            )
            if reused is not None:
                records.append(reused)
                emit(f"[{item.sequence}/{plan.total_attempts}] resumed {item.run_id}")
                continue
        emit(
            f"[{item.sequence}/{plan.total_attempts}] {item.case_id} "
            f"mode={item.execution_mode.value}"
        )
        run_root = root / "modes" / _mode_directory(item.execution_mode) / "runs"
        run_root.mkdir(parents=True, exist_ok=True)
        active_llm = (
            llm_factory(item.execution_mode, loaded)
            if llm_factory is not None
            else _scripted_llm(loaded)
            if provider == "scripted"
            else None
        )
        def case_progress(message: str, case: str = item.case_id) -> None:
            emit(f"  {case}: {message}")

        report = repair_case(
            loaded.agent_case_path,
            run_root,
            model_override=item.model,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_patch_attempts=max_patch_attempts,
            max_target_test_executions=max_target_test_executions,
            max_regression_executions=max_regression_executions,
            max_wall_clock_seconds=max_wall_clock_seconds,
            llm_client=active_llm,
            injected_provider=provider if active_llm is not None else None,
            injected_model=item.model if active_llm is not None else None,
            process_runner=runner,
            progress=case_progress,
            run_id=item.run_id,
            execution_mode=item.execution_mode,
        )
        run_directory = run_root / item.run_id
        _write_json(
            run_directory / "ablation-attempt.json",
            _attempt_manifest(item, plan, report, run_directory),
        )
        records.append(
            _run_record(
                suite=suite,
                loaded=loaded,
                run_number=1,
                mode=plan.benchmark_execution_mode,
                requested_provider=provider,
                report=report,
            )
        )

    runtime_providers = sorted({run.provider for run in records})
    runtime_provider = ",".join(runtime_providers)[:64] if runtime_providers else provider
    per_mode: list[AblationModeMetrics] = []
    for mode in plan.execution_modes:
        mode_runs = [run for run in records if run.agent_execution_mode is mode]
        mode_root = root / "modes" / _mode_directory(mode)
        mode_summary = aggregate_benchmark_runs(
            suite_id=plan.suite_id,
            fingerprint=suite.fingerprint,
            execution_mode=plan.benchmark_execution_mode,
            provider=runtime_provider,
            model=plan.model,
            runs_per_case=1,
            selected_case_ids=plan.selected_case_ids,
            runs=mode_runs,
            reproducibility=_reproducibility_metadata(
                suite=suite,
                artifacts_root=root,
                provider=runtime_provider,
                model=plan.model,
                cli_arguments=cli_arguments,
                budget_values=plan.budget_values,
                random_seed=None,
                runner=runner,
            ),
            artifacts={
                "benchmark_summary_json": str(mode_root / "benchmark-summary.json"),
                "benchmark_runs_csv": str(mode_root / "benchmark-runs.csv"),
                "benchmark_report_markdown": str(mode_root / "benchmark-report.md"),
            },
        )
        write_benchmark_summary(mode_summary, mode_root)
        per_mode.append(_mode_metrics(mode, mode_runs))

    artifacts = {
        "ablation_plan_json": str(plan_path),
        "ablation_summary_json": str(root / "ablation-summary.json"),
        "ablation_runs_csv": str(root / "ablation-runs.csv"),
        "ablation_report_markdown": str(root / "ablation-report.md"),
    }
    summary = AblationSummary(
        suite_id=plan.suite_id,
        benchmark_fingerprint=plan.benchmark_fingerprint,
        benchmark_execution_mode=plan.benchmark_execution_mode,
        provider=runtime_provider,
        model=plan.model,
        execution_modes=plan.execution_modes,
        selected_case_ids=plan.selected_case_ids,
        total_attempts=len(records),
        project_git_commit=plan.project_git_commit,
        project_worktree_dirty=plan.project_worktree_dirty,
        generated_at_utc=datetime.now(UTC),
        schedule=plan.items,
        per_mode=per_mode,
        runs=records,
        artifacts=artifacts,
    )
    _write_json(root / "ablation-summary.json", summary)
    _atomic_write(root / "ablation-runs.csv", _csv(summary))
    _atomic_write(root / "ablation-report.md", ablation_markdown(summary))
    emit(f"Ablation report: {root / 'ablation-report.md'}")
    return summary
