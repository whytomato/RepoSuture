"""Structured benchmark metrics, deterministic aggregation, and report rendering."""

from __future__ import annotations

import csv
import io
import math
import statistics
import uuid
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from patchpilot.benchmark_spec import BenchmarkFingerprint
from patchpilot.reporting import FinalStatus, RunReport, TestOutcome

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class BenchmarkExecutionMode(StrEnum):
    SCRIPTED_OFFLINE = "scripted/offline"
    LIVE_MODEL = "live model"


class FailureCategory(StrEnum):
    INVALID_CASE = "INVALID_CASE"
    BASELINE_NOT_REPRODUCED = "BASELINE_NOT_REPRODUCED"
    MODEL_CONFIGURATION = "MODEL_CONFIGURATION"
    MODEL_API = "MODEL_API"
    MODEL_STOPPED = "MODEL_STOPPED"
    SEARCH_FAILURE = "SEARCH_FAILURE"
    PATCH_REJECTED = "PATCH_REJECTED"
    TARGET_TEST_FAILED = "TARGET_TEST_FAILED"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    POLICY_REJECTED = "POLICY_REJECTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    RESOLVED = "RESOLVED"


class ReproducibilityMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patchpilot_git_commit: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=128)
    ]
    patchpilot_worktree_dirty: bool
    operating_system: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
    python_version: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)]
    java_version: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
    maven_version: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
    openai_sdk_version: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=100)
    ] | None
    provider: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]
    model: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
    run_timestamp_utc: datetime
    cli_arguments: list[
        Annotated[str, StringConstraints(strict=True, max_length=2_000)]
    ] = Field(max_length=100)
    budget_values: dict[str, int]
    random_seed: int | None = None

    @model_validator(mode="after")
    def validate_timestamp_and_budgets(self) -> Self:
        if self.run_timestamp_utc.utcoffset() != UTC.utcoffset(self.run_timestamp_utc):
            raise ValueError("reproducibility timestamp must use timezone-aware UTC")
        if any(value < 0 for value in self.budget_values.values()):
            raise ValueError("budget values must be nonnegative")
        return self


class BenchmarkRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    benchmark_fingerprint: Sha256
    case_id: str
    run_number: int = Field(ge=1)
    run_id: str
    execution_mode: BenchmarkExecutionMode
    provider: str
    model: str
    final_status: FinalStatus
    failure_category: FailureCategory
    failure_reason: str | None
    baseline_reproduced: bool
    baseline_result: TestOutcome
    target_test_result: TestOutcome
    regression_result: TestOutcome
    total_model_turns: int = Field(ge=0)
    tool_calls_by_name: dict[str, int]
    total_tool_calls: int = Field(ge=0)
    patch_attempts: int = Field(ge=0)
    rejected_patch_attempts: int = Field(ge=0)
    target_test_executions: int = Field(ge=0)
    regression_executions: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    model_request_count: int = Field(ge=0)
    api_error_count: int = Field(ge=0)
    wall_clock_duration_seconds: float = Field(ge=0)
    model_latency_seconds: float = Field(ge=0)
    test_execution_duration_seconds: float = Field(ge=0)
    modified_file_count: int = Field(ge=0)
    inserted_lines: int = Field(ge=0)
    deleted_lines: int = Field(ge=0)
    patch_size_bytes: int = Field(ge=0)
    final_patch_path: str
    report_path: str
    trace_path: str
    original_repository_unchanged: bool
    target_pass_regression_fail_observed: bool = False
    policy_rejected_observed: bool = False
    budget_exhausted_observed: bool = False
    model_stopped_without_verification: bool = False
    infrastructure_failure: bool = False

    @model_validator(mode="after")
    def validate_counters(self) -> Self:
        if sum(self.tool_calls_by_name.values()) != self.total_tool_calls:
            raise ValueError("tool-call distribution does not equal total tool calls")
        if self.rejected_patch_attempts > self.patch_attempts:
            raise ValueError("rejected Patch attempts exceed total Patch attempts")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        if (self.failure_category is FailureCategory.RESOLVED) != (
            self.final_status is FinalStatus.RESOLVED
        ):
            raise ValueError("RESOLVED category and deterministic final status disagree")
        return self


class PerCaseAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    success_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    empirical_success_rate: float = Field(ge=0, le=1)
    resolved_at_least_once: bool


class FailureAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    most_common_failure_categories: list[str]
    target_pass_regression_fail_runs: list[str]
    policy_rejected_runs: list[str]
    budget_exhausted_runs: list[str]
    model_stopped_without_verification_runs: list[str]
    infrastructure_failure_runs: list[str]


class BenchmarkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    suite_id: str
    benchmark_fingerprint: BenchmarkFingerprint
    execution_mode: BenchmarkExecutionMode
    provider: str
    model: str
    runs_per_case: int = Field(ge=1)
    requested_attempts: int = Field(ge=0)
    total_cases: int = Field(ge=0)
    total_attempts: int = Field(ge=0)
    executable_attempts: int = Field(ge=0)
    resolved_attempts: int = Field(ge=0)
    unresolved_attempts: int = Field(ge=0)
    attempt_level_resolution_rate: float = Field(ge=0, le=1)
    cases_resolved_at_least_once: int = Field(ge=0)
    baseline_reproduction_count: int = Field(ge=0)
    baseline_reproduction_rate: float = Field(ge=0, le=1)
    target_test_pass_count: int = Field(ge=0)
    regression_pass_count: int = Field(ge=0)
    failure_counts_by_category: dict[FailureCategory, int]
    average_model_turns: float = Field(ge=0)
    median_model_turns: float = Field(ge=0)
    average_tool_calls: float = Field(ge=0)
    median_tool_calls: float = Field(ge=0)
    average_patch_attempts: float = Field(ge=0)
    median_patch_attempts: float = Field(ge=0)
    average_duration_seconds: float = Field(ge=0)
    median_duration_seconds: float = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_reasoning_tokens: int = Field(ge=0)
    total_reported_tokens: int = Field(ge=0)
    average_reported_tokens: float = Field(ge=0)
    average_patch_size_bytes: float = Field(ge=0)
    tool_usage_distribution: dict[str, int]
    per_case: list[PerCaseAggregate]
    failure_analysis: FailureAnalysis
    reproducibility: ReproducibilityMetadata
    runs: list[BenchmarkRunRecord]
    artifacts: dict[str, str]

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.total_attempts != len(self.runs):
            raise ValueError("total_attempts does not equal serialized runs")
        if self.resolved_attempts + self.unresolved_attempts != self.total_attempts:
            raise ValueError("resolved and unresolved counts do not total attempts")
        if sum(self.failure_counts_by_category.values()) != self.total_attempts:
            raise ValueError("failure-category counts do not total attempts")
        if any(run.execution_mode is not self.execution_mode for run in self.runs):
            raise ValueError("scripted and live results must never be mixed")
        return self


class ValidationCaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    valid: bool
    final_status: FinalStatus
    baseline_result: TestOutcome
    baseline_target_observed: bool
    patched_target_result: TestOutcome
    regression_result: TestOutcome
    golden_patch_nonempty: bool
    production_only: bool
    original_repository_unchanged: bool
    worktree_cleanup_verified: bool
    report_path: str
    failure_reason: str | None


class ValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    suite_id: str
    benchmark_fingerprint: BenchmarkFingerprint
    total_cases: int = Field(ge=0)
    valid_cases: int = Field(ge=0)
    invalid_cases: int = Field(ge=0)
    all_valid: bool
    results: list[ValidationCaseRecord]
    reproducibility: ReproducibilityMetadata
    artifacts: dict[str, str]

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.total_cases != len(self.results):
            raise ValueError("validation total does not equal result rows")
        if self.valid_cases + self.invalid_cases != self.total_cases:
            raise ValueError("validation counts do not total cases")
        if self.all_valid != (self.invalid_cases == 0):
            raise ValueError("all_valid disagrees with invalid case count")
        return self


def classify_failure(report: RunReport, *, search_failure_observed: bool) -> FailureCategory:
    mapping = {
        FinalStatus.INVALID_CASE: FailureCategory.INVALID_CASE,
        FinalStatus.BASELINE_NOT_REPRODUCED: FailureCategory.BASELINE_NOT_REPRODUCED,
        FinalStatus.MODEL_CONFIGURATION_ERROR: FailureCategory.MODEL_CONFIGURATION,
        FinalStatus.MODEL_API_ERROR: FailureCategory.MODEL_API,
        FinalStatus.MODEL_STOPPED: FailureCategory.MODEL_STOPPED,
        FinalStatus.PATCH_REJECTED: FailureCategory.PATCH_REJECTED,
        FinalStatus.TARGET_TEST_FAILED: FailureCategory.TARGET_TEST_FAILED,
        FinalStatus.REGRESSION_FAILED: FailureCategory.REGRESSION_FAILED,
        FinalStatus.POLICY_REJECTED: FailureCategory.POLICY_REJECTED,
        FinalStatus.AGENT_BUDGET_EXHAUSTED: FailureCategory.BUDGET_EXHAUSTED,
        FinalStatus.INFRASTRUCTURE_ERROR: FailureCategory.INFRASTRUCTURE,
        FinalStatus.RESOLVED: FailureCategory.RESOLVED,
    }
    if search_failure_observed and report.final_status is not FinalStatus.RESOLVED:
        return FailureCategory.SEARCH_FAILURE
    if report.final_status is FinalStatus.UNRESOLVED:
        if report.regression_result.outcome in {TestOutcome.FAIL, TestOutcome.TIMEOUT}:
            return FailureCategory.REGRESSION_FAILED
        return FailureCategory.TARGET_TEST_FAILED
    return mapping[report.final_status]


def final_patch_line_counts(path: Path) -> tuple[int, int]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return 0, 0
    inserted = sum(
        line.startswith("+") and not line.startswith("+++")
        for line in content.splitlines()
    )
    deleted = sum(
        line.startswith("-") and not line.startswith("---")
        for line in content.splitlines()
    )
    return inserted, deleted


def _average(values: list[int | float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def _median(values: list[int | float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def aggregate_benchmark_runs(
    *,
    suite_id: str,
    fingerprint: BenchmarkFingerprint,
    execution_mode: BenchmarkExecutionMode,
    provider: str,
    model: str,
    runs_per_case: int,
    selected_case_ids: list[str],
    runs: list[BenchmarkRunRecord],
    reproducibility: ReproducibilityMetadata,
    artifacts: dict[str, str],
) -> BenchmarkSummary:
    if any(run.execution_mode is not execution_mode for run in runs):
        raise ValueError("scripted and live benchmark records must not be mixed")
    total_attempts = len(runs)
    resolved_attempts = sum(
        run.failure_category is FailureCategory.RESOLVED for run in runs
    )
    baseline_count = sum(run.baseline_reproduced for run in runs)
    failure_counts = {category: 0 for category in FailureCategory}
    for run in runs:
        failure_counts[run.failure_category] += 1
    tool_usage: Counter[str] = Counter()
    for run in runs:
        tool_usage.update(run.tool_calls_by_name)
    per_case: list[PerCaseAggregate] = []
    for case_id in selected_case_ids:
        attempts = [run for run in runs if run.case_id == case_id]
        successes = sum(
            run.failure_category is FailureCategory.RESOLVED for run in attempts
        )
        per_case.append(
            PerCaseAggregate(
                case_id=case_id,
                success_count=successes,
                attempt_count=len(attempts),
                empirical_success_rate=successes / len(attempts) if attempts else 0.0,
                resolved_at_least_once=successes > 0,
            )
        )
    failure_counter = Counter(
        run.failure_category.value
        for run in runs
        if run.failure_category is not FailureCategory.RESOLVED
    )
    most_common = [
        f"{category}: {count}"
        for category, count in sorted(
            failure_counter.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    total_input = sum(run.input_tokens for run in runs)
    total_output = sum(run.output_tokens for run in runs)
    total_reasoning = sum(run.reasoning_tokens for run in runs)
    total_reported = total_input + total_output
    return BenchmarkSummary(
        suite_id=suite_id,
        benchmark_fingerprint=fingerprint,
        execution_mode=execution_mode,
        provider=provider,
        model=model,
        runs_per_case=runs_per_case,
        requested_attempts=len(selected_case_ids) * runs_per_case,
        total_cases=len(selected_case_ids),
        total_attempts=total_attempts,
        executable_attempts=sum(
            run.baseline_result is not TestOutcome.NOT_RUN for run in runs
        ),
        resolved_attempts=resolved_attempts,
        unresolved_attempts=total_attempts - resolved_attempts,
        attempt_level_resolution_rate=(
            resolved_attempts / total_attempts if total_attempts else 0.0
        ),
        cases_resolved_at_least_once=sum(item.resolved_at_least_once for item in per_case),
        baseline_reproduction_count=baseline_count,
        baseline_reproduction_rate=(
            baseline_count / total_attempts if total_attempts else 0.0
        ),
        target_test_pass_count=sum(
            run.target_test_result is TestOutcome.PASS for run in runs
        ),
        regression_pass_count=sum(
            run.regression_result is TestOutcome.PASS for run in runs
        ),
        failure_counts_by_category=failure_counts,
        average_model_turns=_average([run.total_model_turns for run in runs]),
        median_model_turns=_median([run.total_model_turns for run in runs]),
        average_tool_calls=_average([run.total_tool_calls for run in runs]),
        median_tool_calls=_median([run.total_tool_calls for run in runs]),
        average_patch_attempts=_average([run.patch_attempts for run in runs]),
        median_patch_attempts=_median([run.patch_attempts for run in runs]),
        average_duration_seconds=_average(
            [run.wall_clock_duration_seconds for run in runs]
        ),
        median_duration_seconds=_median(
            [run.wall_clock_duration_seconds for run in runs]
        ),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_reasoning_tokens=total_reasoning,
        total_reported_tokens=total_reported,
        average_reported_tokens=(total_reported / total_attempts if total_attempts else 0.0),
        average_patch_size_bytes=_average([run.patch_size_bytes for run in runs]),
        tool_usage_distribution=dict(sorted(tool_usage.items())),
        per_case=per_case,
        failure_analysis=FailureAnalysis(
            most_common_failure_categories=most_common,
            target_pass_regression_fail_runs=[
                run.run_id for run in runs if run.target_pass_regression_fail_observed
            ],
            policy_rejected_runs=[
                run.run_id for run in runs if run.policy_rejected_observed
            ],
            budget_exhausted_runs=[
                run.run_id for run in runs if run.budget_exhausted_observed
            ],
            model_stopped_without_verification_runs=[
                run.run_id for run in runs if run.model_stopped_without_verification
            ],
            infrastructure_failure_runs=[
                run.run_id for run in runs if run.infrastructure_failure
            ],
        ),
        reproducibility=reproducibility,
        runs=runs,
        artifacts=artifacts,
    )


BENCHMARK_CSV_FIELDS = (
    "suite_id",
    "benchmark_fingerprint",
    "case_id",
    "run_number",
    "run_id",
    "execution_mode",
    "provider",
    "model",
    "final_status",
    "failure_category",
    "baseline_reproduced",
    "baseline_result",
    "target_test_result",
    "regression_result",
    "total_model_turns",
    "total_tool_calls",
    "patch_attempts",
    "rejected_patch_attempts",
    "target_test_executions",
    "regression_executions",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "model_request_count",
    "api_error_count",
    "wall_clock_duration_seconds",
    "model_latency_seconds",
    "test_execution_duration_seconds",
    "modified_file_count",
    "inserted_lines",
    "deleted_lines",
    "patch_size_bytes",
    "final_patch_path",
    "report_path",
    "trace_path",
    "original_repository_unchanged",
    "failure_reason",
)

VALIDATION_CSV_FIELDS = (
    "case_id",
    "valid",
    "final_status",
    "baseline_result",
    "baseline_target_observed",
    "patched_target_result",
    "regression_result",
    "golden_patch_nonempty",
    "production_only",
    "original_repository_unchanged",
    "worktree_cleanup_verified",
    "report_path",
    "failure_reason",
)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _csv_text(rows: list[dict[str, object]], fields: tuple[str, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fields})
    return stream.getvalue()


def _display_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def benchmark_markdown(summary: BenchmarkSummary) -> str:
    lines = [
        f"# PatchPilot Benchmark Report: {summary.suite_id}",
        "",
        f"- Execution mode: `{summary.execution_mode.value}`",
        f"- Provider/model: `{summary.provider}` / `{summary.model}`",
        f"- Benchmark fingerprint: `{summary.benchmark_fingerprint.value}`",
        f"- Attempts: {summary.total_attempts} ({summary.resolved_attempts} resolved, "
        f"{summary.unresolved_attempts} unresolved)",
        f"- Empirical attempt-level resolution rate: "
        f"{summary.attempt_level_resolution_rate:.3f}",
        "",
        "The empirical rate is a raw observed rate, not a statistically rigorous pass@k estimate.",
        "",
        "## Runs",
        "",
        "| Case | Status | Turns | Tools | Patches | Target | Regression | Failure |",
        "|------|--------|------:|------:|--------:|--------|------------|---------|",
    ]
    for run in summary.runs:
        lines.append(
            f"| {run.case_id} | {run.final_status.value} | {run.total_model_turns} | "
            f"{run.total_tool_calls} | {run.patch_attempts} | "
            f"{run.target_test_result.value} | {run.regression_result.value} | "
            f"{run.failure_category.value} |"
        )
    lines.extend(
        [
            "",
            "## Per-case empirical results",
            "",
            "| Case | Successes | Attempts | Empirical rate | Resolved at least once |",
            "|------|----------:|---------:|---------------:|------------------------|",
        ]
    )
    for case in summary.per_case:
        lines.append(
            f"| {case.case_id} | {case.success_count} | {case.attempt_count} | "
            f"{case.empirical_success_rate:.3f} | "
            f"{'yes' if case.resolved_at_least_once else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Aggregate metrics",
            "",
            f"- Baseline reproduction: {summary.baseline_reproduction_count}/"
            f"{summary.total_attempts} ({summary.baseline_reproduction_rate:.3f})",
            f"- Target PASS count: {summary.target_test_pass_count}",
            f"- Regression PASS count: {summary.regression_pass_count}",
            f"- Model turns, average/median: {summary.average_model_turns:.2f} / "
            f"{summary.median_model_turns:.2f}",
            f"- Tool calls, average/median: {summary.average_tool_calls:.2f} / "
            f"{summary.median_tool_calls:.2f}",
            f"- Patch attempts, average/median: {summary.average_patch_attempts:.2f} / "
            f"{summary.median_patch_attempts:.2f}",
            f"- Duration seconds, average/median: {summary.average_duration_seconds:.2f} / "
            f"{summary.median_duration_seconds:.2f}",
            f"- Reported input/output tokens: {summary.total_input_tokens} / "
            f"{summary.total_output_tokens}",
            f"- Reasoning tokens (when exposed): {summary.total_reasoning_tokens}",
            f"- Average final Patch size: {summary.average_patch_size_bytes:.2f} bytes",
            "",
            "## Failure analysis",
            "",
            "- Most common failure categories: "
            + _display_list(summary.failure_analysis.most_common_failure_categories),
            "- Target-pass/regression-fail runs: "
            + _display_list(summary.failure_analysis.target_pass_regression_fail_runs),
            "- Policy-rejected runs: "
            + _display_list(summary.failure_analysis.policy_rejected_runs),
            "- Budget-exhausted runs: "
            + _display_list(summary.failure_analysis.budget_exhausted_runs),
            "- Model-stopped-without-verification runs: "
            + _display_list(
                summary.failure_analysis.model_stopped_without_verification_runs
            ),
            "- Infrastructure-failure runs: "
            + _display_list(summary.failure_analysis.infrastructure_failure_runs),
            "",
            "## Reproducibility",
            "",
            f"- PatchPilot commit: `{summary.reproducibility.patchpilot_git_commit}` "
            f"(dirty: {str(summary.reproducibility.patchpilot_worktree_dirty).lower()})",
            f"- OS: {summary.reproducibility.operating_system}",
            f"- Python: {summary.reproducibility.python_version}",
            f"- Java: {summary.reproducibility.java_version}",
            f"- Maven: {summary.reproducibility.maven_version}",
            f"- UTC timestamp: {summary.reproducibility.run_timestamp_utc.isoformat()}",
            "",
            "Environment, provider availability, model behavior, dependency caches, and hardware "
            "can affect live reproducibility. Scripted/offline runs measure harness behavior only.",
            "",
        ]
    )
    return "\n".join(lines)


def validation_markdown(summary: ValidationSummary) -> str:
    lines = [
        f"# PatchPilot Benchmark Validation: {summary.suite_id}",
        "",
        f"- Benchmark fingerprint: `{summary.benchmark_fingerprint.value}`",
        f"- Valid cases: {summary.valid_cases}/{summary.total_cases}",
        "",
        "| Case | Valid | Baseline | Target | Regression | Production only | Integrity | Cleanup |",
        "|------|-------|----------|--------|------------|-----------------|-----------|---------|",
    ]
    for result in summary.results:
        lines.append(
            f"| {result.case_id} | {'yes' if result.valid else 'no'} | "
            f"{result.baseline_result.value} | {result.patched_target_result.value} | "
            f"{result.regression_result.value} | {'yes' if result.production_only else 'no'} | "
            f"{'yes' if result.original_repository_unchanged else 'no'} | "
            f"{'yes' if result.worktree_cleanup_verified else 'no'} |"
        )
    lines.extend(
        [
            "",
            "A case is valid only when the selected target genuinely fails at baseline, the "
            "nonempty hidden Patch changes production code only, the target and full regression "
            "suite pass, the source repository is unchanged, and the worktree is removed.",
            "",
        ]
    )
    return "\n".join(lines)


def write_benchmark_summary(summary: BenchmarkSummary, root: Path) -> None:
    _atomic_write(
        root / "benchmark-summary.json",
        summary.model_dump_json(indent=2) + "\n",
    )
    rows = [run.model_dump(mode="json") for run in summary.runs]
    _atomic_write(root / "benchmark-runs.csv", _csv_text(rows, BENCHMARK_CSV_FIELDS))
    _atomic_write(root / "benchmark-report.md", benchmark_markdown(summary))


def write_validation_summary(summary: ValidationSummary, root: Path) -> None:
    _atomic_write(
        root / "validation-summary.json",
        summary.model_dump_json(indent=2) + "\n",
    )
    rows = [result.model_dump(mode="json") for result in summary.results]
    _atomic_write(
        root / "validation-summary.csv",
        _csv_text(rows, VALIDATION_CSV_FIELDS),
    )
    _atomic_write(root / "validation-report.md", validation_markdown(summary))


def finite_nonnegative(value: float) -> float:
    """Normalize optional external timings before constructing strict records."""

    return value if math.isfinite(value) and value >= 0 else 0.0
