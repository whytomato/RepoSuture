"""Structured benchmark metrics, deterministic aggregation, and report rendering."""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
import uuid
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from reposuture.benchmark_spec import BenchmarkFingerprint
from reposuture.reporting import (
    AgentExecutionMode,
    FinalStatus,
    ObservedFailure,
    PrimaryFailure,
    RunReport,
    TestOutcome,
)

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


def _legacy_primary_failure(value: object) -> str | None:
    """Best-effort compatibility projection for pre-0.4 aggregate records."""

    if value in {None, FailureCategory.RESOLVED, FailureCategory.RESOLVED.value}:
        return None
    mapping = {
        FailureCategory.INVALID_CASE.value: PrimaryFailure.INVALID_CASE.value,
        FailureCategory.BASELINE_NOT_REPRODUCED.value: (
            PrimaryFailure.BASELINE_NOT_REPRODUCED.value
        ),
        FailureCategory.MODEL_CONFIGURATION.value: PrimaryFailure.PROVIDER_REJECTED.value,
        FailureCategory.MODEL_API.value: PrimaryFailure.PROVIDER_REJECTED.value,
        FailureCategory.MODEL_STOPPED.value: (
            PrimaryFailure.MODEL_STOPPED_WITHOUT_VERIFICATION.value
        ),
        FailureCategory.SEARCH_FAILURE.value: PrimaryFailure.TOOL_PROTOCOL_FAILURE.value,
        FailureCategory.PATCH_REJECTED.value: PrimaryFailure.NO_PATCH_ACCEPTED.value,
        FailureCategory.TARGET_TEST_FAILED.value: PrimaryFailure.TARGET_UNRESOLVED.value,
        FailureCategory.REGRESSION_FAILED.value: (
            PrimaryFailure.REGRESSION_UNRESOLVED.value
        ),
        FailureCategory.POLICY_REJECTED.value: PrimaryFailure.PATCH_POLICY_BLOCKED.value,
        FailureCategory.BUDGET_EXHAUSTED.value: (
            PrimaryFailure.BUDGET_EXHAUSTED_WITHOUT_PROGRESS.value
        ),
        FailureCategory.INFRASTRUCTURE.value: (
            PrimaryFailure.INFRASTRUCTURE_FAILURE.value
        ),
    }
    key = value.value if isinstance(value, FailureCategory) else str(value)
    return mapping.get(key)


class DescriptiveWilsonInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confidence: float = Field(default=0.95, ge=0.95, le=0.95)
    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)


def wilson_interval(
    successes: int,
    attempts: int,
) -> DescriptiveWilsonInterval | None:
    """Return a descriptive 95% Wilson interval, or N/A for no observations."""

    if successes < 0 or attempts < 0 or successes > attempts:
        raise ValueError("Wilson inputs require 0 <= successes <= attempts")
    if attempts == 0:
        return None
    z = 1.959963984540054
    proportion = successes / attempts
    denominator = 1 + z * z / attempts
    center = (proportion + z * z / (2 * attempts)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / attempts
            + z * z / (4 * attempts * attempts)
        )
        / denominator
    )
    return DescriptiveWilsonInterval(
        lower=max(0.0, center - margin),
        upper=min(1.0, center + margin),
    )


class ReproducibilityMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_git_commit: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=128)
    ] = Field(
        validation_alias=AliasChoices("project_git_commit", "patchpilot_git_commit")
    )
    project_worktree_dirty: bool = Field(
        validation_alias=AliasChoices(
            "project_worktree_dirty", "patchpilot_worktree_dirty"
        )
    )
    project_version: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=100)
    ] = "0.4.0"
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
    agent_execution_mode: AgentExecutionMode = AgentExecutionMode.FULL_AGENT
    provider: str
    model: str
    final_status: FinalStatus
    terminal_status: FinalStatus
    primary_failure: PrimaryFailure | None = None
    observed_failures: list[ObservedFailure] = Field(default_factory=list)
    failure_category: FailureCategory | None = Field(default=None, exclude=True)
    failure_reason: str | None
    baseline_reproduced: bool
    baseline_result: TestOutcome
    target_test_result: TestOutcome
    regression_result: TestOutcome
    total_model_turns: int = Field(ge=0)
    tool_calls_by_name: dict[str, int]
    total_tool_calls: int = Field(ge=0)
    generated_tool_calls: int = Field(ge=0)
    executed_tool_calls: int = Field(ge=0)
    discarded_extra_tool_calls: int = Field(ge=0)
    patch_attempts: int = Field(ge=0)
    rejected_patch_attempts: int = Field(ge=0)
    normalization_used: bool = False
    recount_used: bool = False
    target_test_executions: int = Field(ge=0)
    regression_executions: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    model_request_count: int = Field(ge=0)
    api_error_count: int = Field(ge=0)
    provider_accepted: bool = False
    provider_rejected: bool = False
    model_executed: bool = False
    model_tool_call_observed: bool = False
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

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_tool_protocol_counters(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        updated = dict(value)
        if "terminal_status" not in updated and "final_status" in updated:
            updated["terminal_status"] = updated["final_status"]
        if "final_status" not in updated and "terminal_status" in updated:
            updated["final_status"] = updated["terminal_status"]
        if (
            "failure_category" in updated
            and updated.get("terminal_status") != updated.get("final_status")
        ):
            updated["terminal_status"] = updated.get("final_status")
        updated.setdefault("agent_execution_mode", AgentExecutionMode.FULL_AGENT.value)
        legacy = updated.get("failure_category")
        if "primary_failure" not in updated or (
            updated.get("primary_failure") is None
            and legacy not in {None, FailureCategory.RESOLVED, FailureCategory.RESOLVED.value}
        ):
            updated["primary_failure"] = _legacy_primary_failure(legacy)
        updated.setdefault("observed_failures", [])
        inferred_tool_call = int(updated.get("total_tool_calls", 0)) > 0
        inferred_resolved = updated.get("final_status") == FinalStatus.RESOLVED.value
        inferred_executed = inferred_tool_call or inferred_resolved
        updated.setdefault("provider_accepted", inferred_executed)
        updated.setdefault(
            "provider_rejected",
            int(updated.get("model_request_count", 0)) > 0
            and int(updated.get("api_error_count", 0)) > 0
            and not inferred_executed,
        )
        updated.setdefault("model_executed", inferred_executed)
        updated.setdefault("model_tool_call_observed", inferred_tool_call)
        executed = updated.setdefault(
            "executed_tool_calls", updated.get("total_tool_calls", 0)
        )
        discarded = updated.setdefault("discarded_extra_tool_calls", 0)
        updated.setdefault("generated_tool_calls", int(executed) + int(discarded))
        return updated

    @model_validator(mode="after")
    def validate_counters(self) -> Self:
        if self.terminal_status is not self.final_status:
            raise ValueError("terminal and legacy final status must agree")
        if self.model_tool_call_observed and not self.model_executed:
            raise ValueError("model Tool Calls require model execution")
        if self.model_executed and not self.provider_accepted:
            raise ValueError("model execution requires Provider acceptance")
        if self.provider_rejected and (
            self.provider_accepted or self.model_executed
        ):
            raise ValueError("Provider rejection cannot contain model execution")
        if sum(self.tool_calls_by_name.values()) != self.total_tool_calls:
            raise ValueError("tool-call distribution does not equal total tool calls")
        if self.rejected_patch_attempts > self.patch_attempts:
            raise ValueError("rejected Patch attempts exceed total Patch attempts")
        if self.executed_tool_calls != self.total_tool_calls:
            raise ValueError("executed tool calls must equal runtime total tool calls")
        if self.generated_tool_calls != (
            self.executed_tool_calls + self.discarded_extra_tool_calls
        ):
            raise ValueError("generated tool calls must equal executed plus discarded")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        if self.failure_category is not None and (
            (self.failure_category is FailureCategory.RESOLVED)
            != (self.final_status is FinalStatus.RESOLVED)
        ):
            raise ValueError("RESOLVED category and deterministic final status disagree")
        if self.final_status is FinalStatus.RESOLVED and self.primary_failure is not None:
            raise ValueError("RESOLVED observations cannot have a primary failure")
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

    schema_version: int = 2
    suite_id: str
    benchmark_fingerprint: BenchmarkFingerprint
    execution_mode: BenchmarkExecutionMode
    provider: str
    model: str
    runs_per_case: int = Field(ge=1)
    requested_attempts: int = Field(ge=0)
    total_cases: int = Field(ge=0)
    total_attempts: int = Field(ge=0)
    assigned_attempts: int = Field(default=0, ge=0)
    provider_accepted_attempts: int = Field(default=0, ge=0)
    model_executed_attempts: int = Field(default=0, ge=0)
    model_tool_call_attempts: int = Field(default=0, ge=0)
    provider_rejected_attempts: int = Field(default=0, ge=0)
    infrastructure_failed_attempts: int = Field(default=0, ge=0)
    executable_attempts: int = Field(ge=0)
    resolved_attempts: int = Field(ge=0)
    unresolved_attempts: int = Field(ge=0)
    attempt_level_resolution_rate: float = Field(ge=0, le=1)
    system_end_to_end_resolution_rate: float = Field(default=0.0, ge=0, le=1)
    provider_acceptance_rate: float = Field(default=0.0, ge=0, le=1)
    capability_resolution_rate: float | None = Field(default=None, ge=0, le=1)
    system_descriptive_wilson_95: DescriptiveWilsonInterval | None = None
    capability_descriptive_wilson_95: DescriptiveWilsonInterval | None = None
    cases_resolved_at_least_once: int = Field(ge=0)
    baseline_reproduction_count: int = Field(ge=0)
    baseline_reproduction_rate: float = Field(ge=0, le=1)
    target_test_pass_count: int = Field(ge=0)
    regression_pass_count: int = Field(ge=0)
    failure_counts_by_category: dict[FailureCategory, int]
    terminal_status_distribution: dict[FinalStatus, int] = Field(default_factory=dict)
    primary_failure_distribution: dict[PrimaryFailure, int] = Field(
        default_factory=dict
    )
    observed_failure_occurrence_counts: dict[ObservedFailure, int] = Field(
        default_factory=dict
    )
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
        if self.schema_version >= 2:
            if self.assigned_attempts != self.total_attempts:
                raise ValueError("assigned attempts must equal serialized observations")
            if self.resolved_attempts > self.model_executed_attempts:
                raise ValueError("resolved attempts require model execution")
            if self.model_tool_call_attempts > self.model_executed_attempts:
                raise ValueError("model Tool Call attempts exceed model execution")
            if self.provider_accepted_attempts > self.assigned_attempts:
                raise ValueError("Provider acceptance exceeds assigned attempts")
            if self.capability_resolution_rate is None:
                if (
                    self.model_executed_attempts != 0
                    or self.capability_descriptive_wilson_95 is not None
                ):
                    raise ValueError("capability N/A requires zero model executions")
            elif self.model_executed_attempts == 0:
                raise ValueError("capability rate requires model execution")
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
    if report.final_status is FinalStatus.RESOLVED:
        return FailureCategory.RESOLVED
    primary_mapping = {
        PrimaryFailure.INVALID_CASE: FailureCategory.INVALID_CASE,
        PrimaryFailure.BASELINE_NOT_REPRODUCED: FailureCategory.BASELINE_NOT_REPRODUCED,
        PrimaryFailure.REPOSITORY_OR_ARTIFACT_INTEGRITY: (
            FailureCategory.INFRASTRUCTURE
        ),
        PrimaryFailure.INFRASTRUCTURE_FAILURE: FailureCategory.INFRASTRUCTURE,
        PrimaryFailure.PROVIDER_REJECTED: FailureCategory.MODEL_API,
        PrimaryFailure.NO_PATCH_ACCEPTED: FailureCategory.PATCH_REJECTED,
        PrimaryFailure.TARGET_UNRESOLVED: FailureCategory.TARGET_TEST_FAILED,
        PrimaryFailure.REGRESSION_UNRESOLVED: FailureCategory.REGRESSION_FAILED,
        PrimaryFailure.PATCH_POLICY_BLOCKED: FailureCategory.POLICY_REJECTED,
        PrimaryFailure.TOOL_PROTOCOL_FAILURE: FailureCategory.MODEL_API,
        PrimaryFailure.BUDGET_EXHAUSTED_WITHOUT_PROGRESS: (
            FailureCategory.BUDGET_EXHAUSTED
        ),
        PrimaryFailure.MODEL_STOPPED_WITHOUT_VERIFICATION: (
            FailureCategory.MODEL_STOPPED
        ),
    }
    if report.primary_failure is not None:
        return primary_mapping[report.primary_failure]
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
    }
    if search_failure_observed:
        return FailureCategory.SEARCH_FAILURE
    if report.final_status is FinalStatus.UNRESOLVED:
        if report.regression_result.outcome in {TestOutcome.FAIL, TestOutcome.TIMEOUT}:
            return FailureCategory.REGRESSION_FAILED
        return FailureCategory.TARGET_TEST_FAILED
    return mapping[report.final_status]


def _compatibility_failure_category(run: BenchmarkRunRecord) -> FailureCategory:
    """Retain the pre-0.4 aggregate view without using it as causal authority."""

    if run.failure_category is not None:
        return run.failure_category
    if run.terminal_status is FinalStatus.RESOLVED:
        return FailureCategory.RESOLVED
    primary_mapping = {
        PrimaryFailure.INVALID_CASE: FailureCategory.INVALID_CASE,
        PrimaryFailure.BASELINE_NOT_REPRODUCED: FailureCategory.BASELINE_NOT_REPRODUCED,
        PrimaryFailure.REPOSITORY_OR_ARTIFACT_INTEGRITY: (
            FailureCategory.INFRASTRUCTURE
        ),
        PrimaryFailure.INFRASTRUCTURE_FAILURE: FailureCategory.INFRASTRUCTURE,
        PrimaryFailure.PROVIDER_REJECTED: FailureCategory.MODEL_API,
        PrimaryFailure.NO_PATCH_ACCEPTED: FailureCategory.PATCH_REJECTED,
        PrimaryFailure.TARGET_UNRESOLVED: FailureCategory.TARGET_TEST_FAILED,
        PrimaryFailure.REGRESSION_UNRESOLVED: FailureCategory.REGRESSION_FAILED,
        PrimaryFailure.PATCH_POLICY_BLOCKED: FailureCategory.POLICY_REJECTED,
        PrimaryFailure.TOOL_PROTOCOL_FAILURE: FailureCategory.MODEL_API,
        PrimaryFailure.BUDGET_EXHAUSTED_WITHOUT_PROGRESS: (
            FailureCategory.BUDGET_EXHAUSTED
        ),
        PrimaryFailure.MODEL_STOPPED_WITHOUT_VERIFICATION: (
            FailureCategory.MODEL_STOPPED
        ),
    }
    if run.primary_failure is not None:
        return primary_mapping[run.primary_failure]
    return FailureCategory.MODEL_STOPPED


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
    case_run_counts: dict[str, int] | None = None,
    runs: list[BenchmarkRunRecord],
    reproducibility: ReproducibilityMetadata,
    artifacts: dict[str, str],
) -> BenchmarkSummary:
    if any(run.execution_mode is not execution_mode for run in runs):
        raise ValueError("scripted and live benchmark records must not be mixed")
    total_attempts = len(runs)
    resolved_attempts = sum(
        run.terminal_status is FinalStatus.RESOLVED for run in runs
    )
    baseline_count = sum(run.baseline_reproduced for run in runs)
    failure_counts = {category: 0 for category in FailureCategory}
    for run in runs:
        failure_counts[_compatibility_failure_category(run)] += 1
    terminal_counts = Counter(run.terminal_status for run in runs)
    primary_counts = Counter(
        run.primary_failure for run in runs if run.primary_failure is not None
    )
    observed_counts: Counter[ObservedFailure] = Counter()
    for run in runs:
        observed_counts.update(run.observed_failures)
    tool_usage: Counter[str] = Counter()
    for run in runs:
        tool_usage.update(run.tool_calls_by_name)
    per_case: list[PerCaseAggregate] = []
    for case_id in selected_case_ids:
        attempts = [run for run in runs if run.case_id == case_id]
        successes = sum(
            run.terminal_status is FinalStatus.RESOLVED for run in attempts
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
        run.primary_failure.value
        for run in runs
        if run.primary_failure is not None
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
    provider_accepted = sum(run.provider_accepted for run in runs)
    model_executed = sum(run.model_executed for run in runs)
    model_tool_calls = sum(run.model_tool_call_observed for run in runs)
    provider_rejected = sum(run.provider_rejected for run in runs)
    infrastructure_failed = sum(
        run.primary_failure
        in {
            PrimaryFailure.INFRASTRUCTURE_FAILURE,
            PrimaryFailure.REPOSITORY_OR_ARTIFACT_INTEGRITY,
        }
        for run in runs
    )
    return BenchmarkSummary(
        suite_id=suite_id,
        benchmark_fingerprint=fingerprint,
        execution_mode=execution_mode,
        provider=provider,
        model=model,
        runs_per_case=runs_per_case,
        requested_attempts=(
            sum(case_run_counts.values())
            if case_run_counts is not None
            else len(selected_case_ids) * runs_per_case
        ),
        total_cases=len(selected_case_ids),
        total_attempts=total_attempts,
        assigned_attempts=total_attempts,
        provider_accepted_attempts=provider_accepted,
        model_executed_attempts=model_executed,
        model_tool_call_attempts=model_tool_calls,
        provider_rejected_attempts=provider_rejected,
        infrastructure_failed_attempts=infrastructure_failed,
        executable_attempts=sum(
            run.baseline_result is not TestOutcome.NOT_RUN for run in runs
        ),
        resolved_attempts=resolved_attempts,
        unresolved_attempts=total_attempts - resolved_attempts,
        attempt_level_resolution_rate=(
            resolved_attempts / total_attempts if total_attempts else 0.0
        ),
        system_end_to_end_resolution_rate=(
            resolved_attempts / total_attempts if total_attempts else 0.0
        ),
        provider_acceptance_rate=(
            provider_accepted / total_attempts if total_attempts else 0.0
        ),
        capability_resolution_rate=(
            resolved_attempts / model_executed if model_executed else None
        ),
        system_descriptive_wilson_95=wilson_interval(
            resolved_attempts, total_attempts
        ),
        capability_descriptive_wilson_95=wilson_interval(
            resolved_attempts, model_executed
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
        terminal_status_distribution={
            status: terminal_counts.get(status, 0) for status in FinalStatus
        },
        primary_failure_distribution={
            failure: primary_counts.get(failure, 0) for failure in PrimaryFailure
        },
        observed_failure_occurrence_counts={
            failure: observed_counts.get(failure, 0) for failure in ObservedFailure
        },
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
    "agent_execution_mode",
    "provider",
    "model",
    "final_status",
    "terminal_status",
    "primary_failure",
    "observed_failures",
    "baseline_reproduced",
    "baseline_result",
    "target_test_result",
    "regression_result",
    "total_model_turns",
    "total_tool_calls",
    "generated_tool_calls",
    "executed_tool_calls",
    "discarded_extra_tool_calls",
    "patch_attempts",
    "rejected_patch_attempts",
    "normalization_used",
    "recount_used",
    "target_test_executions",
    "regression_executions",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "model_request_count",
    "api_error_count",
    "provider_accepted",
    "provider_rejected",
    "model_executed",
    "model_tool_call_observed",
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
    "aggregate_assigned_attempts",
    "aggregate_provider_accepted_attempts",
    "aggregate_model_executed_attempts",
    "aggregate_model_tool_call_attempts",
    "aggregate_resolved_attempts",
    "aggregate_system_end_to_end_resolution_rate",
    "aggregate_provider_acceptance_rate",
    "aggregate_capability_resolution_rate",
    "aggregate_system_wilson_95",
    "aggregate_capability_wilson_95",
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
    temporary = path.with_name(f".agg-{uuid.uuid4().hex[:12]}.tmp")
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


def aggregate_csv_metrics(
    *,
    assigned_attempts: int,
    provider_accepted_attempts: int,
    model_executed_attempts: int,
    model_tool_call_attempts: int,
    resolved_attempts: int,
) -> dict[str, object]:
    """Return consistent aggregate rate columns for JSON-adjacent CSV evidence."""

    system_interval = wilson_interval(resolved_attempts, assigned_attempts)
    capability_interval = wilson_interval(resolved_attempts, model_executed_attempts)

    def interval_text(value: DescriptiveWilsonInterval | None) -> str:
        return (
            f"[{value.lower:.6f},{value.upper:.6f}]"
            if value is not None
            else "N/A"
        )

    return {
        "aggregate_assigned_attempts": assigned_attempts,
        "aggregate_provider_accepted_attempts": provider_accepted_attempts,
        "aggregate_model_executed_attempts": model_executed_attempts,
        "aggregate_model_tool_call_attempts": model_tool_call_attempts,
        "aggregate_resolved_attempts": resolved_attempts,
        "aggregate_system_end_to_end_resolution_rate": (
            resolved_attempts / assigned_attempts if assigned_attempts else "N/A"
        ),
        "aggregate_provider_acceptance_rate": (
            provider_accepted_attempts / assigned_attempts
            if assigned_attempts
            else "N/A"
        ),
        "aggregate_capability_resolution_rate": (
            resolved_attempts / model_executed_attempts
            if model_executed_attempts
            else "N/A"
        ),
        "aggregate_system_wilson_95": interval_text(system_interval),
        "aggregate_capability_wilson_95": interval_text(capability_interval),
    }


def benchmark_markdown(summary: BenchmarkSummary) -> str:
    capability_rate = (
        f"{summary.capability_resolution_rate:.3f}"
        if summary.capability_resolution_rate is not None
        else "N/A"
    )
    capability_interval = (
        f"[{summary.capability_descriptive_wilson_95.lower:.3f}, "
        f"{summary.capability_descriptive_wilson_95.upper:.3f}]"
        if summary.capability_descriptive_wilson_95 is not None
        else "N/A"
    )
    lines = [
        f"# RepoSuture Benchmark Report: {summary.suite_id}",
        "",
        f"- Execution mode: `{summary.execution_mode.value}`",
        f"- Provider/model: `{summary.provider}` / `{summary.model}`",
        f"- Benchmark fingerprint: `{summary.benchmark_fingerprint.value}`",
        f"- Attempts: {summary.total_attempts} ({summary.resolved_attempts} resolved, "
        f"{summary.unresolved_attempts} unresolved)",
        f"- System end-to-end resolution: {summary.resolved_attempts}/"
        f"{summary.assigned_attempts} "
        f"({summary.system_end_to_end_resolution_rate:.3f})",
        f"- Provider acceptance: {summary.provider_accepted_attempts}/"
        f"{summary.assigned_attempts} ({summary.provider_acceptance_rate:.3f})",
        f"- Model capability observation: {summary.resolved_attempts}/"
        f"{summary.model_executed_attempts} ({capability_rate}); "
        f"descriptive Wilson 95%: {capability_interval}",
        "",
        "Capability is N/A when no model response entered the Agent loop. Provider rejection "
        "still counts as an end-to-end service failure. These empirical rates are not pass@k.",
        "",
        "## Runs",
        "",
        "| Case | Status | Turns | Tools | Patches | Target | Regression | Primary failure |",
        "|------|--------|------:|------:|--------:|--------|------------|---------|",
    ]
    for run in summary.runs:
        lines.append(
            f"| {run.case_id} | {run.final_status.value} | {run.total_model_turns} | "
            f"{run.total_tool_calls} | {run.patch_attempts} | "
            f"{run.target_test_result.value} | {run.regression_result.value} | "
            f"{run.primary_failure.value if run.primary_failure else 'none'} |"
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
            "- Terminal-status distribution: "
            + _display_list(
                [
                    f"{status.value}: {count}"
                    for status, count in summary.terminal_status_distribution.items()
                    if count
                ]
            ),
            "- Primary-failure distribution: "
            + _display_list(
                [
                    f"{failure.value}: {count}"
                    for failure, count in summary.primary_failure_distribution.items()
                    if count
                ]
            ),
            "- Observed-failure occurrences (non-exclusive): "
            + _display_list(
                [
                    f"{failure.value}: {count}"
                    for failure, count in summary.observed_failure_occurrence_counts.items()
                    if count
                ]
            ),
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
            f"- RepoSuture commit: `{summary.reproducibility.project_git_commit}` "
            f"(dirty: {str(summary.reproducibility.project_worktree_dirty).lower()})",
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
        f"# RepoSuture Benchmark Validation: {summary.suite_id}",
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
            "nonempty hidden Patch changes production code only, the target and configured "
            "regression "
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
    rows = []
    for run in summary.runs:
        row = run.model_dump(mode="json")
        row["tool_calls_by_name"] = json.dumps(
            row["tool_calls_by_name"], sort_keys=True, separators=(",", ":")
        )
        row["observed_failures"] = json.dumps(
            row["observed_failures"], separators=(",", ":")
        )
        row.update(
            aggregate_csv_metrics(
                assigned_attempts=summary.assigned_attempts,
                provider_accepted_attempts=summary.provider_accepted_attempts,
                model_executed_attempts=summary.model_executed_attempts,
                model_tool_call_attempts=summary.model_tool_call_attempts,
                resolved_attempts=summary.resolved_attempts,
            )
        )
        rows.append(row)
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
