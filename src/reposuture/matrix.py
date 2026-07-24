"""Sequential, resumable cross-model benchmark matrix orchestration."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import statistics
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    BenchmarkSummary,
    DescriptiveWilsonInterval,
    FailureCategory,
    PerCaseAggregate,
    aggregate_benchmark_runs,
    aggregate_csv_metrics,
    wilson_interval,
    write_benchmark_summary,
)
from reposuture.benchmark_spec import (
    BenchmarkFingerprint,
    BenchmarkSuiteError,
    LoadedBenchmarkCase,
    LoadedBenchmarkSuite,
    load_benchmark_suite,
)
from reposuture.process import ProcessRunner
from reposuture.repair import ProgressCallback, repair_case
from reposuture.reporting import FinalStatus, ObservedFailure, PrimaryFailure, RunReport
from reposuture.trajectory import load_replay_run

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
MatrixLLMFactory = Callable[[str, LoadedBenchmarkCase, int], LLMClient]


class MatrixPlanItem(BaseModel):
    """One immutable position in a deterministic sequential matrix schedule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    case_id: str
    run_number: int = Field(ge=1)
    model: str
    run_id: str
    artifact_directory: str


class MatrixPlan(BaseModel):
    """Complete execution plan recorded before the first model request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 2
    suite_id: str
    benchmark_fingerprint: Sha256
    execution_mode: BenchmarkExecutionMode
    provider: str
    models: list[str] = Field(min_length=2)
    selected_case_ids: list[str] = Field(min_length=1)
    runs_per_case: int = Field(ge=1, le=20)
    case_run_counts: dict[str, int] = Field(default_factory=dict)
    schedule: Literal["interleaved"] = "interleaved"
    total_attempts: int = Field(ge=1)
    budget_values: dict[str, int]
    project_git_commit: str
    project_worktree_dirty: bool
    random_seed: int | None = None
    items: list[MatrixPlanItem] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_case_counts(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        updated = dict(value)
        if not updated.get("case_run_counts"):
            selected = updated.get("selected_case_ids", [])
            runs = updated.get("runs_per_case", 1)
            updated["case_run_counts"] = {case_id: runs for case_id in selected}
        return updated

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if len(self.models) != len(set(self.models)):
            raise ValueError("matrix models must be unique")
        if set(self.case_run_counts) != set(self.selected_case_ids):
            raise ValueError("matrix case-run counts must cover selected Cases exactly")
        if any(not 1 <= count <= 20 for count in self.case_run_counts.values()):
            raise ValueError("matrix per-Case run counts must be between 1 and 20")
        if self.runs_per_case != max(self.case_run_counts.values()):
            raise ValueError("runs_per_case must equal the maximum per-Case run count")
        expected = len(self.models) * sum(self.case_run_counts.values())
        if self.total_attempts != expected or len(self.items) != expected:
            raise ValueError("matrix attempt total does not match models, Cases, and runs")
        if [item.sequence for item in self.items] != list(range(1, expected + 1)):
            raise ValueError("matrix schedule sequence must be contiguous")
        identities = {(item.case_id, item.run_number, item.model) for item in self.items}
        if len(identities) != expected:
            raise ValueError("matrix schedule contains duplicate attempts")
        return self


class MatrixAttemptManifest(BaseModel):
    """Integrity-bound identity for one complete resumable observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    schedule_sequence: int = Field(ge=1)
    suite_id: str
    benchmark_fingerprint: Sha256
    case_id: str
    run_number: int = Field(ge=1)
    run_id: str
    execution_mode: BenchmarkExecutionMode
    requested_provider: str
    runtime_provider: str
    model: str
    budget_values: dict[str, int]
    project_git_commit: str
    project_worktree_dirty: bool
    report_schema_version: int | None
    report_sha256: Sha256
    trace_sha256: Sha256
    final_status: FinalStatus


class MatrixCompletionManifest(BaseModel):
    """Integrity record written only after every aggregate report is complete."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 2
    suite_id: str
    benchmark_fingerprint: Sha256
    execution_mode: BenchmarkExecutionMode
    requested_provider: str
    models: list[str] = Field(min_length=2)
    runs_per_case: int = Field(ge=1, le=20)
    case_run_counts: dict[str, int] = Field(default_factory=dict)
    project_git_commit: str
    project_worktree_dirty: bool
    artifact_sha256: dict[str, Sha256] = Field(min_length=7)


WilsonInterval = DescriptiveWilsonInterval


class MatrixModelMetrics(BaseModel):
    """Descriptive per-model comparison metrics; not a pass@k estimator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    total_attempts: int = Field(ge=0)
    assigned_attempts: int = Field(default=0, ge=0)
    provider_accepted_attempts: int = Field(default=0, ge=0)
    model_executed_attempts: int = Field(default=0, ge=0)
    model_tool_call_attempts: int = Field(default=0, ge=0)
    provider_rejected_attempts: int = Field(default=0, ge=0)
    infrastructure_failed_attempts: int = Field(default=0, ge=0)
    resolved_attempts: int = Field(ge=0)
    empirical_resolution_rate: float = Field(ge=0, le=1)
    descriptive_wilson_95: WilsonInterval | None
    system_end_to_end_resolution_rate: float = Field(default=0.0, ge=0, le=1)
    provider_acceptance_rate: float = Field(default=0.0, ge=0, le=1)
    capability_resolution_rate: float | None = Field(default=None, ge=0, le=1)
    system_descriptive_wilson_95: WilsonInterval | None = None
    capability_descriptive_wilson_95: WilsonInterval | None = None
    cases_resolved_at_least_once: int = Field(ge=0)
    cases_resolved_all_runs: int = Field(ge=0)
    per_case: list[PerCaseAggregate]
    failure_counts_by_category: dict[FailureCategory, int]
    terminal_status_distribution: dict[FinalStatus, int] = Field(default_factory=dict)
    primary_failure_distribution: dict[PrimaryFailure, int] = Field(
        default_factory=dict
    )
    observed_failure_occurrence_counts: dict[ObservedFailure, int] = Field(
        default_factory=dict
    )
    target_test_pass_count: int = Field(ge=0)
    regression_pass_count: int = Field(ge=0)
    total_model_turns: int = Field(ge=0)
    total_model_requests: int = Field(ge=0)
    generated_tool_calls: int = Field(ge=0)
    executed_tool_calls: int = Field(ge=0)
    discarded_extra_tool_calls: int = Field(ge=0)
    tool_call_discard_rate: float = Field(ge=0, le=1)
    tool_calls_by_name: dict[str, int]
    patch_attempts: int = Field(ge=0)
    rejected_patch_attempts: int = Field(ge=0)
    normalization_used_attempts: int = Field(ge=0)
    recount_used_attempts: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    average_model_turns: float = Field(ge=0)
    average_tool_calls: float = Field(ge=0)
    average_patch_attempts: float = Field(ge=0)
    average_model_latency_seconds: float = Field(ge=0)
    average_test_duration_seconds: float = Field(ge=0)
    average_wall_clock_duration_seconds: float = Field(ge=0)
    average_patch_size_bytes: float = Field(ge=0)
    original_repository_integrity_count: int = Field(ge=0)
    benchmark_summary_path: str


class MatrixSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 2
    suite_id: str
    benchmark_fingerprint: BenchmarkFingerprint
    execution_mode: BenchmarkExecutionMode
    requested_provider: str
    provider: str
    models: list[str]
    runs_per_case: int = Field(ge=1)
    case_run_counts: dict[str, int] = Field(default_factory=dict)
    total_attempts: int = Field(ge=0)
    schedule: list[MatrixPlanItem]
    budget_values: dict[str, int]
    project_git_commit: str
    project_worktree_dirty: bool
    generated_at_utc: datetime
    per_model: list[MatrixModelMetrics]
    runs: list[BenchmarkRunRecord]
    artifacts: dict[str, str]

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_case_counts(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        updated = dict(value)
        if not updated.get("case_run_counts"):
            case_ids = {
                item.get("case_id")
                for item in updated.get("schedule", [])
                if isinstance(item, dict) and isinstance(item.get("case_id"), str)
            }
            updated["case_run_counts"] = {
                case_id: updated.get("runs_per_case", 1) for case_id in case_ids
            }
        return updated

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.generated_at_utc.utcoffset() != UTC.utcoffset(self.generated_at_utc):
            raise ValueError("matrix timestamp must use timezone-aware UTC")
        if self.total_attempts != len(self.runs):
            raise ValueError("matrix total does not equal serialized run observations")
        if {run.model for run in self.runs} - set(self.models):
            raise ValueError("matrix contains an unplanned model")
        if any(run.execution_mode is not self.execution_mode for run in self.runs):
            raise ValueError("matrix cannot mix scripted and live observations")
        return self


def _model_directory(model: str) -> str:
    digest = hashlib.sha256(model.encode("utf-8")).hexdigest()[:8]
    return f"{_safe_identifier(model, 24)}-{digest}"


def _matrix_run_id(
    suite: LoadedBenchmarkSuite,
    *,
    case_id: str,
    run_number: int,
    model: str,
    mode: BenchmarkExecutionMode,
) -> str:
    # Keep deterministic artifact paths comfortably below the legacy Windows MAX_PATH
    # limit even when pytest or CI supplies a long temporary root. Full identities remain
    # in the plan and report; compact path components are collision-bound by hashes.
    mode_label = "s" if mode is BenchmarkExecutionMode.SCRIPTED_OFFLINE else "l"
    model_digest = hashlib.sha256(model.encode("utf-8")).hexdigest()[:8]
    return (
        f"mx-{_safe_identifier(suite.manifest.suite_id, 12)}-{mode_label}-"
        f"{_safe_identifier(case_id, 28)}-r{run_number:03d}-{model_digest}-"
        f"{suite.fingerprint.value[:8]}"
    )


def build_matrix_plan(
    suite: LoadedBenchmarkSuite,
    *,
    selected_cases: Sequence[LoadedBenchmarkCase],
    models: Sequence[str],
    runs_per_case: int,
    case_run_counts: dict[str, int] | None = None,
    provider: str,
    budget_values: dict[str, int],
    project_git_commit: str,
    project_worktree_dirty: bool,
    random_seed: int | None,
) -> MatrixPlan:
    """Build an alternating model schedule without creating artifacts or requests."""

    normalized_models = [model.strip() for model in models]
    if len(normalized_models) < 2 or any(not model for model in normalized_models):
        raise BenchmarkSuiteError("benchmark-matrix requires at least two explicit models")
    if len(normalized_models) != len(set(normalized_models)):
        raise BenchmarkSuiteError("benchmark-matrix model identifiers must be unique")
    if not 1 <= runs_per_case <= 20:
        raise BenchmarkSuiteError("runs_per_case must be between 1 and 20")
    selected_ids = [loaded.reference.id for loaded in selected_cases]
    effective_counts = {case_id: runs_per_case for case_id in selected_ids}
    overrides = dict(case_run_counts or {})
    unknown_overrides = set(overrides) - set(selected_ids)
    if unknown_overrides:
        raise BenchmarkSuiteError(
            "per-Case run count references an unselected Case: "
            + ", ".join(sorted(unknown_overrides))
        )
    effective_counts.update(overrides)
    if any(
        isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20
        for count in effective_counts.values()
    ):
        raise BenchmarkSuiteError("per-Case run counts must be between 1 and 20")
    maximum_runs = max(effective_counts.values())
    mode = (
        BenchmarkExecutionMode.SCRIPTED_OFFLINE
        if provider == "scripted"
        else BenchmarkExecutionMode.LIVE_MODEL
    )
    items: list[MatrixPlanItem] = []
    for run_number in range(1, maximum_runs + 1):
        for case_index, loaded in enumerate(selected_cases):
            if run_number > effective_counts[loaded.reference.id]:
                continue
            ordered_models = list(normalized_models)
            if (run_number + case_index) % 2 == 1:
                ordered_models.reverse()
            for model in ordered_models:
                run_id = _matrix_run_id(
                    suite,
                    case_id=loaded.reference.id,
                    run_number=run_number,
                    model=model,
                    mode=mode,
                )
                items.append(
                    MatrixPlanItem(
                        sequence=len(items) + 1,
                        case_id=loaded.reference.id,
                        run_number=run_number,
                        model=model,
                        run_id=run_id,
                        artifact_directory=(
                            Path("models") / _model_directory(model) / "runs" / run_id
                        ).as_posix(),
                    )
                )
    return MatrixPlan(
        suite_id=suite.manifest.suite_id,
        benchmark_fingerprint=suite.fingerprint.value,
        execution_mode=mode,
        provider=provider,
        models=normalized_models,
        selected_case_ids=selected_ids,
        runs_per_case=maximum_runs,
        case_run_counts=effective_counts,
        total_attempts=len(items),
        budget_values=budget_values,
        project_git_commit=project_git_commit,
        project_worktree_dirty=project_worktree_dirty,
        random_seed=random_seed,
        items=items,
    )


def prepare_matrix_plan(
    suite_file: Path,
    *,
    provider: str,
    models: Sequence[str],
    runs_per_case: int,
    case_run_counts: dict[str, int] | None = None,
    case_ids: Sequence[str] | None = None,
    random_seed: int | None = None,
    max_turns: int | None = None,
    max_tool_calls: int | None = None,
    max_patch_attempts: int | None = None,
    max_target_test_executions: int | None = None,
    max_regression_executions: int | None = None,
    max_wall_clock_seconds: int | None = None,
    process_runner: ProcessRunner | None = None,
) -> tuple[LoadedBenchmarkSuite, list[LoadedBenchmarkCase], MatrixPlan]:
    if provider not in {"openai", "scripted"}:
        raise BenchmarkSuiteError("provider must be either 'openai' or 'scripted'")
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
    project_root = Path(__file__).resolve().parents[2]
    commit, dirty = _git_metadata(runner, project_root)
    return suite, selected, build_matrix_plan(
        suite,
        selected_cases=selected,
        models=models,
        runs_per_case=runs_per_case,
        case_run_counts=case_run_counts,
        provider=provider,
        budget_values=budgets,
        project_git_commit=commit,
        project_worktree_dirty=dirty,
        random_seed=random_seed,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".mx-{uuid.uuid4().hex[:12]}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_json(path: Path, value: BaseModel) -> None:
    _atomic_write(path, value.model_dump_json(indent=2) + "\n")


def _aggregate_artifact_paths(root: Path, plan: MatrixPlan) -> list[Path]:
    paths = [
        root / "matrix-plan.json",
        root / "matrix-summary.json",
        root / "matrix-runs.csv",
        root / "matrix-report.md",
    ]
    for model in plan.models:
        model_root = root / "models" / _model_directory(model)
        paths.extend(
            [
                model_root / "benchmark-summary.json",
                model_root / "benchmark-runs.csv",
                model_root / "benchmark-report.md",
            ]
        )
    return paths


def _completion_manifest(root: Path, plan: MatrixPlan) -> MatrixCompletionManifest:
    artifacts: dict[str, str] = {}
    resolved_root = root.resolve(strict=True)
    for path in _aggregate_artifact_paths(root, plan):
        resolved = path.resolve(strict=True)
        if resolved.parent != resolved_root and not resolved.is_relative_to(resolved_root):
            raise BenchmarkSuiteError("matrix aggregate artifact escaped its root")
        artifacts[resolved.relative_to(resolved_root).as_posix()] = _file_sha256(resolved)
    return MatrixCompletionManifest(
        suite_id=plan.suite_id,
        benchmark_fingerprint=plan.benchmark_fingerprint,
        execution_mode=plan.execution_mode,
        requested_provider=plan.provider,
        models=plan.models,
        runs_per_case=plan.runs_per_case,
        case_run_counts=plan.case_run_counts,
        project_git_commit=plan.project_git_commit,
        project_worktree_dirty=plan.project_worktree_dirty,
        artifact_sha256=artifacts,
    )


def _validate_completion_manifest(root: Path, plan: MatrixPlan) -> None:
    path = root / "matrix-completion.json"
    aggregate_paths = _aggregate_artifact_paths(root, plan)[1:]
    if not path.exists():
        if any(candidate.exists() for candidate in aggregate_paths):
            raise BenchmarkSuiteError(
                "resume aggregate artifacts lack a completion integrity manifest"
            )
        return
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise BenchmarkSuiteError("matrix completion manifest is missing or oversized")
    try:
        manifest = MatrixCompletionManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise BenchmarkSuiteError("matrix completion manifest is malformed") from exc
    expected_identity = (
        plan.suite_id,
        plan.benchmark_fingerprint,
        plan.execution_mode,
        plan.provider,
        plan.models,
        plan.runs_per_case,
        plan.case_run_counts,
        plan.project_git_commit,
        plan.project_worktree_dirty,
    )
    actual_identity = (
        manifest.suite_id,
        manifest.benchmark_fingerprint,
        manifest.execution_mode,
        manifest.requested_provider,
        manifest.models,
        manifest.runs_per_case,
        manifest.case_run_counts,
        manifest.project_git_commit,
        manifest.project_worktree_dirty,
    )
    if actual_identity != expected_identity:
        raise BenchmarkSuiteError("matrix completion identity does not match this invocation")
    expected_paths = {
        path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()
        for path in _aggregate_artifact_paths(root, plan)
    }
    if set(manifest.artifact_sha256) != expected_paths:
        raise BenchmarkSuiteError("matrix completion artifact set is inconsistent")
    resolved_root = root.resolve(strict=True)
    for relative, expected_sha256 in manifest.artifact_sha256.items():
        candidate = (resolved_root / relative).resolve(strict=True)
        if not candidate.is_file() or not candidate.is_relative_to(resolved_root):
            raise BenchmarkSuiteError("matrix completion artifact escapes its root")
        if _file_sha256(candidate) != expected_sha256:
            raise BenchmarkSuiteError(
                f"matrix completion artifact hash mismatch: {relative}"
            )


def _attempt_manifest(
    *,
    item: MatrixPlanItem,
    plan: MatrixPlan,
    report: RunReport,
    run_directory: Path,
) -> MatrixAttemptManifest:
    return MatrixAttemptManifest(
        schedule_sequence=item.sequence,
        suite_id=plan.suite_id,
        benchmark_fingerprint=plan.benchmark_fingerprint,
        case_id=item.case_id,
        run_number=item.run_number,
        run_id=item.run_id,
        execution_mode=plan.execution_mode,
        requested_provider=plan.provider,
        runtime_provider=report.provider or plan.provider,
        model=report.model or item.model,
        budget_values=plan.budget_values,
        project_git_commit=plan.project_git_commit,
        project_worktree_dirty=plan.project_worktree_dirty,
        report_schema_version=report.schema_version,
        report_sha256=_file_sha256(run_directory / "report.json"),
        trace_sha256=_file_sha256(run_directory / "trace.jsonl"),
        final_status=report.final_status,
    )


def _load_resumable_record(
    *,
    root: Path,
    item: MatrixPlanItem,
    plan: MatrixPlan,
    suite: LoadedBenchmarkSuite,
    loaded: LoadedBenchmarkCase,
) -> BenchmarkRunRecord | None:
    run_directory = root / item.artifact_directory
    manifest_path = run_directory / "matrix-attempt.json"
    if not manifest_path.is_file():
        return None
    if manifest_path.stat().st_size > 1024 * 1024:
        raise BenchmarkSuiteError(f"resume manifest is oversized for {item.run_id}")
    try:
        manifest = MatrixAttemptManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise BenchmarkSuiteError(f"resume manifest is malformed for {item.run_id}") from exc
    expected = {
        "schedule_sequence": item.sequence,
        "suite_id": plan.suite_id,
        "benchmark_fingerprint": plan.benchmark_fingerprint,
        "case_id": item.case_id,
        "run_number": item.run_number,
        "run_id": item.run_id,
        "execution_mode": plan.execution_mode,
        "requested_provider": plan.provider,
        "model": item.model,
        "budget_values": plan.budget_values,
        "project_git_commit": plan.project_git_commit,
        "project_worktree_dirty": False,
    }
    actual = manifest.model_dump()
    mismatches = [name for name, value in expected.items() if actual.get(name) != value]
    if mismatches:
        raise BenchmarkSuiteError(
            f"resume identity mismatch for {item.run_id}: {', '.join(mismatches)}"
        )
    if plan.execution_mode is not BenchmarkExecutionMode.LIVE_MODEL:
        raise BenchmarkSuiteError("resume accepts complete live-model observations only")
    try:
        replay = load_replay_run(run_directory)
    except ValueError as exc:
        raise BenchmarkSuiteError(
            f"resume artifact integrity failed for {item.run_id}: {exc}"
        ) from exc
    report = replay.report
    if report.run_id != item.run_id:
        raise BenchmarkSuiteError(f"resume report identity mismatch for {item.run_id}")
    if (report.provider or plan.provider) != manifest.runtime_provider:
        raise BenchmarkSuiteError(f"resume report provider mismatch for {item.run_id}")
    if report.model != item.model or report.final_status is not manifest.final_status:
        raise BenchmarkSuiteError(f"resume report model/status mismatch for {item.run_id}")
    if _file_sha256(replay.report_path) != manifest.report_sha256:
        raise BenchmarkSuiteError(f"resume report hash mismatch for {item.run_id}")
    if _file_sha256(replay.trace_path) != manifest.trace_sha256:
        raise BenchmarkSuiteError(f"resume trace hash mismatch for {item.run_id}")
    return _run_record(
        suite=suite,
        loaded=loaded,
        run_number=item.run_number,
        mode=plan.execution_mode,
        requested_provider=plan.provider,
        report=report,
    )


def _average(values: Sequence[int | float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def _model_metrics(
    model: str,
    summary: BenchmarkSummary,
    *,
    model_root: Path,
    case_run_counts: dict[str, int] | None = None,
    runs_per_case: int | None = None,
) -> MatrixModelMetrics:
    runs = summary.runs
    effective_case_runs = case_run_counts or {
        item.case_id: runs_per_case or summary.runs_per_case
        for item in summary.per_case
    }
    resolved = summary.resolved_attempts
    generated = sum(run.generated_tool_calls for run in runs)
    discarded = sum(run.discarded_extra_tool_calls for run in runs)
    tools: Counter[str] = Counter()
    for run in runs:
        tools.update(run.tool_calls_by_name)
    return MatrixModelMetrics(
        model=model,
        total_attempts=len(runs),
        assigned_attempts=summary.assigned_attempts,
        provider_accepted_attempts=summary.provider_accepted_attempts,
        model_executed_attempts=summary.model_executed_attempts,
        model_tool_call_attempts=summary.model_tool_call_attempts,
        provider_rejected_attempts=summary.provider_rejected_attempts,
        infrastructure_failed_attempts=summary.infrastructure_failed_attempts,
        resolved_attempts=resolved,
        empirical_resolution_rate=resolved / len(runs) if runs else 0.0,
        descriptive_wilson_95=wilson_interval(resolved, len(runs)),
        system_end_to_end_resolution_rate=summary.system_end_to_end_resolution_rate,
        provider_acceptance_rate=summary.provider_acceptance_rate,
        capability_resolution_rate=summary.capability_resolution_rate,
        system_descriptive_wilson_95=summary.system_descriptive_wilson_95,
        capability_descriptive_wilson_95=summary.capability_descriptive_wilson_95,
        cases_resolved_at_least_once=summary.cases_resolved_at_least_once,
        cases_resolved_all_runs=sum(
            item.attempt_count == effective_case_runs[item.case_id]
            and item.success_count == effective_case_runs[item.case_id]
            for item in summary.per_case
        ),
        per_case=summary.per_case,
        failure_counts_by_category=summary.failure_counts_by_category,
        terminal_status_distribution=summary.terminal_status_distribution,
        primary_failure_distribution=summary.primary_failure_distribution,
        observed_failure_occurrence_counts=(
            summary.observed_failure_occurrence_counts
        ),
        target_test_pass_count=summary.target_test_pass_count,
        regression_pass_count=summary.regression_pass_count,
        total_model_turns=sum(run.total_model_turns for run in runs),
        total_model_requests=sum(run.model_request_count for run in runs),
        generated_tool_calls=generated,
        executed_tool_calls=sum(run.executed_tool_calls for run in runs),
        discarded_extra_tool_calls=discarded,
        tool_call_discard_rate=discarded / generated if generated else 0.0,
        tool_calls_by_name=dict(sorted(tools.items())),
        patch_attempts=sum(run.patch_attempts for run in runs),
        rejected_patch_attempts=sum(run.rejected_patch_attempts for run in runs),
        normalization_used_attempts=sum(run.normalization_used for run in runs),
        recount_used_attempts=sum(run.recount_used for run in runs),
        input_tokens=sum(run.input_tokens for run in runs),
        output_tokens=sum(run.output_tokens for run in runs),
        reasoning_tokens=sum(run.reasoning_tokens for run in runs),
        average_model_turns=_average([run.total_model_turns for run in runs]),
        average_tool_calls=_average([run.total_tool_calls for run in runs]),
        average_patch_attempts=_average([run.patch_attempts for run in runs]),
        average_model_latency_seconds=_average(
            [run.model_latency_seconds for run in runs]
        ),
        average_test_duration_seconds=_average(
            [run.test_execution_duration_seconds for run in runs]
        ),
        average_wall_clock_duration_seconds=_average(
            [run.wall_clock_duration_seconds for run in runs]
        ),
        average_patch_size_bytes=_average([run.patch_size_bytes for run in runs]),
        original_repository_integrity_count=sum(
            run.original_repository_unchanged for run in runs
        ),
        benchmark_summary_path=str(model_root / "benchmark-summary.json"),
    )


MATRIX_CSV_FIELDS = ("schedule_sequence", *BENCHMARK_CSV_FIELDS)


def _matrix_csv(summary: MatrixSummary) -> str:
    sequence_by_run = {item.run_id: item.sequence for item in summary.schedule}
    metrics_by_model = {item.model: item for item in summary.per_model}
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=MATRIX_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for run in summary.runs:
        values = run.model_dump(mode="json")
        values["schedule_sequence"] = sequence_by_run[run.run_id]
        values["tool_calls_by_name"] = json.dumps(
            values["tool_calls_by_name"], sort_keys=True, separators=(",", ":")
        )
        values["observed_failures"] = json.dumps(
            values["observed_failures"], separators=(",", ":")
        )
        metrics = metrics_by_model[run.model]
        values.update(
            aggregate_csv_metrics(
                assigned_attempts=metrics.assigned_attempts,
                provider_accepted_attempts=metrics.provider_accepted_attempts,
                model_executed_attempts=metrics.model_executed_attempts,
                model_tool_call_attempts=metrics.model_tool_call_attempts,
                resolved_attempts=metrics.resolved_attempts,
            )
        )
        writer.writerow({name: values.get(name) for name in MATRIX_CSV_FIELDS})
    return stream.getvalue()


def matrix_markdown(summary: MatrixSummary) -> str:
    lines = [
        f"# RepoSuture Cross-Model Matrix: {summary.suite_id}",
        "",
        f"- Attempts: {summary.total_attempts}",
        "- Runs per Case/model: "
        + ", ".join(
            f"`{case_id}`={count}"
            for case_id, count in summary.case_run_counts.items()
        ),
        f"- Provider selector: `{summary.requested_provider}`; runtime provider: "
        f"`{summary.provider}`",
        f"- Benchmark fingerprint: `{summary.benchmark_fingerprint.value}`",
        f"- RepoSuture commit: `{summary.project_git_commit}` "
        f"(dirty: {str(summary.project_worktree_dirty).lower()})",
        "- Schedule: deterministic, sequential, interleaved",
        "- Intervals: separate descriptive 95% Wilson intervals for system and "
        "model-capability denominators; this is not pass@k.",
        "",
        "## Side-by-side descriptive comparison",
        "",
        "| Model | System resolved | System Wilson 95% | Provider accepted | "
        "Model executed | Capability rate | Capability Wilson 95% | Cases >=1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model_metrics in summary.per_model:
        interval = model_metrics.capability_descriptive_wilson_95
        system_interval = model_metrics.system_descriptive_wilson_95
        capability_rate = (
            f"{model_metrics.capability_resolution_rate:.3f}"
            if model_metrics.capability_resolution_rate is not None
            else "N/A"
        )
        interval_text = (
            f"[{interval.lower:.3f}, {interval.upper:.3f}]"
            if interval is not None
            else "N/A"
        )
        system_interval_text = (
            f"[{system_interval.lower:.3f}, {system_interval.upper:.3f}]"
            if system_interval is not None
            else "N/A"
        )
        lines.append(
            f"| `{model_metrics.model}` | "
            f"{model_metrics.resolved_attempts}/{model_metrics.assigned_attempts} | "
            f"{system_interval_text} | "
            f"{model_metrics.provider_accepted_attempts}/"
            f"{model_metrics.assigned_attempts} | "
            f"{model_metrics.model_executed_attempts}/"
            f"{model_metrics.assigned_attempts} | "
            f"{capability_rate} | {interval_text} | "
            f"{model_metrics.cases_resolved_at_least_once} |"
        )
    lines.extend(
        [
            "",
            "## Efficiency and protocol metrics",
            "",
            "| Model | Turns | Requests | Tools generated/executed/discarded | "
            "Patches/rejected | Normalize/recount | Tokens in/out/reasoning | "
            "Avg model/test/wall seconds |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model_metrics in summary.per_model:
        lines.append(
            f"| `{model_metrics.model}` | {model_metrics.total_model_turns} | "
            f"{model_metrics.total_model_requests} | "
            f"{model_metrics.generated_tool_calls}/"
            f"{model_metrics.executed_tool_calls}/"
            f"{model_metrics.discarded_extra_tool_calls} | "
            f"{model_metrics.patch_attempts}/"
            f"{model_metrics.rejected_patch_attempts} | "
            f"{model_metrics.normalization_used_attempts}/"
            f"{model_metrics.recount_used_attempts} | "
            f"{model_metrics.input_tokens}/{model_metrics.output_tokens}/"
            f"{model_metrics.reasoning_tokens} | "
            f"{model_metrics.average_model_latency_seconds:.2f}/"
            f"{model_metrics.average_test_duration_seconds:.2f}/"
            f"{model_metrics.average_wall_clock_duration_seconds:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Per-Case outcomes",
            "",
            "| Model | Case | Successes | Attempts | Empirical rate |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for model in summary.per_model:
        for case in model.per_case:
            lines.append(
                f"| `{model.model}` | `{case.case_id}` | {case.success_count} | "
                f"{case.attempt_count} | {case.empirical_success_rate:.3f} |"
            )
    lines.extend(
        [
            "",
            "## Attempt evidence",
            "",
            "| Seq | Model | Case | Run | Status | Target | Regression | Failure |",
            "|---:|---|---|---:|---|---|---|---|",
        ]
    )
    run_by_id = {run.run_id: run for run in summary.runs}
    for plan_item in summary.schedule:
        run = run_by_id.get(plan_item.run_id)
        if run is None:
            continue
        lines.append(
            f"| {plan_item.sequence} | `{plan_item.model}` | "
            f"`{plan_item.case_id}` | {plan_item.run_number} | "
            f"{run.final_status.value} | "
            f"{run.target_test_result.value} | {run.regression_result.value} | "
            f"{run.primary_failure.value if run.primary_failure else 'none'} |"
        )
    lines.extend(["", "## Failure distributions", ""])
    for model_metrics in summary.per_model:
        terminal = ", ".join(
            f"{key.value}={value}"
            for key, value in model_metrics.terminal_status_distribution.items()
            if value
        ) or "none"
        primary = ", ".join(
            f"{key.value}={value}"
            for key, value in model_metrics.primary_failure_distribution.items()
            if value
        ) or "none"
        observed = ", ".join(
            f"{key.value}={value}"
            for key, value in model_metrics.observed_failure_occurrence_counts.items()
            if value
        ) or "none"
        lines.extend(
            [
                f"- `{model_metrics.model}` terminal: {terminal}",
                f"- `{model_metrics.model}` primary: {primary}",
                f"- `{model_metrics.model}` observed (non-exclusive): {observed}",
            ]
        )
    lines.extend(
        [
            "",
            "Repeated original Cases have only three attempts and new breadth Cases have "
            "one. These comparisons are descriptive, not statistically conclusive, and "
            "do not establish universal Java repair capability.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_matrix_summary(summary: MatrixSummary, root: Path) -> None:
    _write_json(root / "matrix-summary.json", summary)
    _atomic_write(root / "matrix-runs.csv", _matrix_csv(summary))
    _atomic_write(root / "matrix-report.md", matrix_markdown(summary))


def run_benchmark_matrix(
    suite_file: Path,
    artifacts_dir: Path,
    *,
    provider: str,
    models: Sequence[str],
    runs_per_case: int,
    case_run_counts: dict[str, int] | None = None,
    case_ids: Sequence[str] | None = None,
    resume: bool = False,
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
    llm_factory: MatrixLLMFactory | None = None,
    cli_arguments: Sequence[str] = (),
) -> MatrixSummary:
    """Execute a fair sequential matrix while preserving complete failed observations."""

    emit = progress or (lambda _message: None)
    runner = process_runner or ProcessRunner(max_output_bytes=10 * 1024 * 1024)
    suite, selected, plan = prepare_matrix_plan(
        suite_file,
        provider=provider,
        models=models,
        runs_per_case=runs_per_case,
        case_run_counts=case_run_counts,
        case_ids=case_ids,
        random_seed=random_seed,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        max_patch_attempts=max_patch_attempts,
        max_target_test_executions=max_target_test_executions,
        max_regression_executions=max_regression_executions,
        max_wall_clock_seconds=max_wall_clock_seconds,
        process_runner=runner,
    )
    if plan.execution_mode is BenchmarkExecutionMode.LIVE_MODEL and plan.project_worktree_dirty:
        raise BenchmarkSuiteError("live benchmark-matrix requires a clean project worktree")
    if resume and plan.execution_mode is not BenchmarkExecutionMode.LIVE_MODEL:
        raise BenchmarkSuiteError("--resume accepts complete live-model observations only")
    _ensure_artifacts_outside_repositories(artifacts_dir, suite, runner)
    root = artifacts_dir.expanduser().resolve(strict=False)
    if root.exists() and not root.is_dir():
        raise BenchmarkSuiteError(f"matrix artifacts path is not a directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "matrix-plan.json"
    completed_matrix = False
    if plan_path.exists():
        if not resume:
            raise BenchmarkSuiteError("matrix artifacts already contain a plan; use --resume")
        try:
            existing_plan = MatrixPlan.model_validate_json(
                plan_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise BenchmarkSuiteError("existing matrix plan is malformed") from exc
        if existing_plan != plan:
            raise BenchmarkSuiteError("existing matrix plan does not match this invocation")
        _validate_completion_manifest(root, plan)
        completed_matrix = (root / "matrix-completion.json").is_file()
    else:
        if any(root.iterdir()):
            message = (
                "resume directory contains no trustworthy matrix plan"
                if resume
                else "fresh matrix artifacts directory must be empty"
            )
            raise BenchmarkSuiteError(message)
        _write_json(plan_path, plan)

    by_case = {loaded.reference.id: loaded for loaded in selected}
    records: list[BenchmarkRunRecord] = []
    emit(
        f"Matrix: {len(selected)} Cases, {sum(plan.case_run_counts.values())} "
        f"Case-runs x {len(plan.models)} models = {plan.total_attempts} attempts"
    )
    stopped = False
    for item in plan.items:
        loaded = by_case[item.case_id]
        if resume:
            reused = _load_resumable_record(
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
            if completed_matrix:
                raise BenchmarkSuiteError(
                    f"completed matrix is missing attempt evidence for {item.run_id}"
                )
        emit(
            f"[{item.sequence}/{plan.total_attempts}] {item.case_id} "
            f"run={item.run_number} model={item.model}"
        )
        model_root = root / "models" / _model_directory(item.model)
        run_root = model_root / "runs"
        run_root.mkdir(parents=True, exist_ok=True)
        active_llm: LLMClient | None
        if llm_factory is not None:
            active_llm = llm_factory(item.model, loaded, item.run_number)
        elif provider == "scripted":
            active_llm = _scripted_llm(loaded)
        else:
            active_llm = None

        def case_progress(message: str, prefix: str = item.case_id) -> None:
            emit(f"  {prefix}: {message}")

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
            injected_provider=(
                provider if llm_factory is not None else "scripted"
            )
            if active_llm is not None
            else None,
            injected_model=item.model if active_llm is not None else None,
            process_runner=runner,
            progress=case_progress,
            run_id=item.run_id,
        )
        run_directory = run_root / item.run_id
        manifest = _attempt_manifest(
            item=item,
            plan=plan,
            report=report,
            run_directory=run_directory,
        )
        _write_json(run_directory / "matrix-attempt.json", manifest)
        record = _run_record(
            suite=suite,
            loaded=loaded,
            run_number=item.run_number,
            mode=plan.execution_mode,
            requested_provider=provider,
            report=report,
        )
        records.append(record)
        emit(
            f"  target={record.target_test_result.value} "
            f"regression={record.regression_result.value} "
            f"final={record.final_status.value}"
        )
        if not continue_on_failure and report.final_status is not FinalStatus.RESOLVED:
            stopped = True
            break

    if completed_matrix:
        try:
            existing_summary = MatrixSummary.model_validate_json(
                (root / "matrix-summary.json").read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise BenchmarkSuiteError("completed matrix summary is malformed") from exc
        if (
            [run.run_id for run in existing_summary.runs]
            != [run.run_id for run in records]
            or existing_summary.requested_provider != plan.provider
            or existing_summary.models != plan.models
            or existing_summary.total_attempts != len(records)
        ):
            raise BenchmarkSuiteError("completed matrix summary disagrees with run evidence")
        emit(f"Matrix report: {root / 'matrix-report.md'}")
        return existing_summary

    per_model_metrics: list[MatrixModelMetrics] = []
    runtime_providers = sorted({run.provider for run in records})
    runtime_provider = (
        runtime_providers[0]
        if len(runtime_providers) == 1
        else ",".join(runtime_providers)[:64]
        if runtime_providers
        else provider
    )
    for model in plan.models:
        model_runs = [run for run in records if run.model == model]
        model_root = root / "models" / _model_directory(model)
        model_artifacts = {
            "benchmark_summary_json": str(model_root / "benchmark-summary.json"),
            "benchmark_runs_csv": str(model_root / "benchmark-runs.csv"),
            "benchmark_report_markdown": str(model_root / "benchmark-report.md"),
        }
        reproducibility = _reproducibility_metadata(
            suite=suite,
            artifacts_root=root,
            provider=runtime_provider,
            model=model,
            cli_arguments=cli_arguments,
            budget_values=plan.budget_values,
            random_seed=random_seed,
            runner=runner,
        )
        model_summary = aggregate_benchmark_runs(
            suite_id=suite.manifest.suite_id,
            fingerprint=suite.fingerprint,
            execution_mode=plan.execution_mode,
            provider=runtime_provider,
            model=model,
            runs_per_case=plan.runs_per_case,
            selected_case_ids=plan.selected_case_ids,
            case_run_counts=plan.case_run_counts,
            runs=model_runs,
            reproducibility=reproducibility,
            artifacts=model_artifacts,
        )
        model_root.mkdir(parents=True, exist_ok=True)
        write_benchmark_summary(model_summary, model_root)
        per_model_metrics.append(
            _model_metrics(
                model,
                model_summary,
                model_root=model_root,
                case_run_counts=plan.case_run_counts,
            )
        )
    artifacts = {
        "matrix_plan_json": str(plan_path),
        "matrix_summary_json": str(root / "matrix-summary.json"),
        "matrix_runs_csv": str(root / "matrix-runs.csv"),
        "matrix_report_markdown": str(root / "matrix-report.md"),
        "matrix_completion_json": str(root / "matrix-completion.json"),
    }
    summary = MatrixSummary(
        suite_id=suite.manifest.suite_id,
        benchmark_fingerprint=suite.fingerprint,
        execution_mode=plan.execution_mode,
        requested_provider=provider,
        provider=runtime_provider,
        models=plan.models,
        runs_per_case=plan.runs_per_case,
        case_run_counts=plan.case_run_counts,
        total_attempts=len(records),
        schedule=plan.items,
        budget_values=plan.budget_values,
        project_git_commit=plan.project_git_commit,
        project_worktree_dirty=plan.project_worktree_dirty,
        generated_at_utc=datetime.now(UTC),
        per_model=per_model_metrics,
        runs=records,
        artifacts=artifacts,
    )
    _write_matrix_summary(summary, root)
    _write_json(root / "matrix-completion.json", _completion_manifest(root, plan))
    emit(f"Matrix report: {root / 'matrix-report.md'}")
    if stopped:
        emit("Matrix stopped at the first unresolved attempt by request")
    return summary
