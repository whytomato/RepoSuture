"""Structured run reports, status invariants, artifacts, and bounded JSONL traces."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from reposuture.process import EMPTY_SHA256


class FinalStatus(StrEnum):
    INVALID_CASE = "INVALID_CASE"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    BASELINE_NOT_REPRODUCED = "BASELINE_NOT_REPRODUCED"
    PATCH_REJECTED = "PATCH_REJECTED"
    TARGET_TEST_FAILED = "TARGET_TEST_FAILED"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    MODEL_CONFIGURATION_ERROR = "MODEL_CONFIGURATION_ERROR"
    MODEL_API_ERROR = "MODEL_API_ERROR"
    MODEL_STOPPED = "MODEL_STOPPED"
    AGENT_BUDGET_EXHAUSTED = "AGENT_BUDGET_EXHAUSTED"
    POLICY_REJECTED = "POLICY_REJECTED"
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"


class TestOutcome(StrEnum):
    __test__: ClassVar[bool] = False

    NOT_RUN = "NOT_RUN"
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"


class SanitizedTraceEvent(BaseModel):
    """One bounded, content-safe event shared by trace storage and presentation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    timestamp: datetime
    event_type: Annotated[
        str,
        StringConstraints(
            strict=True,
            min_length=1,
            max_length=100,
            pattern=r"^[a-z][a-z0-9_]*$",
        ),
    ]
    status: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)]
    duration: float | None = Field(default=None, ge=0)
    run_id: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=160)
    ] | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        if self.timestamp.utcoffset() != UTC.utcoffset(self.timestamp):
            raise ValueError("trace timestamps must use timezone-aware UTC")
        if self.duration is not None and not math.isfinite(self.duration):
            raise ValueError("trace duration must be finite")
        return self


class TestResultReport(BaseModel):
    __test__: ClassVar[bool] = False

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: TestOutcome
    command: list[str] = Field(default_factory=list)
    exit_code: int | None = None
    duration: float = Field(default=0.0, ge=0)
    timed_out: bool = False
    test_observed: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_bytes_seen: int = Field(default=0, ge=0)
    stderr_bytes_seen: int = Field(default=0, ge=0)
    stdout_sha256: str = EMPTY_SHA256
    stderr_sha256: str = EMPTY_SHA256
    tests_executed: int = Field(default=0, ge=0)
    test_failures: int = Field(default=0, ge=0)
    tests_skipped: int = Field(default=0, ge=0)
    surefire_report_files: int = Field(default=0, ge=0)
    target_found: bool = False
    infrastructure_error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is TestOutcome.PASS and (
            self.exit_code != 0
            or self.timed_out
            or not self.test_observed
            or self.tests_executed < 1
            or self.test_failures != 0
            or self.infrastructure_error is not None
        ):
            raise ValueError("PASS requires an observed test run with exit code 0")
        if self.outcome is TestOutcome.FAIL and (
            self.exit_code in {None, 0}
            or self.timed_out
            or not self.test_observed
            or self.tests_executed < 1
            or self.test_failures < 1
            or self.infrastructure_error is not None
        ):
            raise ValueError("FAIL requires an observed test failure and non-zero exit code")
        if self.outcome is TestOutcome.TIMEOUT and not self.timed_out:
            raise ValueError("TIMEOUT requires timed_out=true")
        if self.outcome is TestOutcome.INFRASTRUCTURE_ERROR and not self.infrastructure_error:
            raise ValueError("INFRASTRUCTURE_ERROR requires infrastructure_error detail")
        if self.outcome is TestOutcome.NOT_RUN and (
            self.command
            or self.exit_code is not None
            or self.timed_out
            or self.test_observed
            or self.infrastructure_error is not None
        ):
            raise ValueError("NOT_RUN must not contain process or test evidence")
        for name, value in (
            ("stdout_sha256", self.stdout_sha256),
            ("stderr_sha256", self.stderr_sha256),
        ):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        return self

    @classmethod
    def not_run(cls) -> TestResultReport:
        return cls(outcome=TestOutcome.NOT_RUN)

    @classmethod
    def failed_observed(cls) -> TestResultReport:
        return cls(
            outcome=TestOutcome.FAIL,
            command=["test"],
            exit_code=1,
            test_observed=True,
            tests_executed=1,
            test_failures=1,
            target_found=True,
        )

    @classmethod
    def passed_observed(cls) -> TestResultReport:
        return cls(
            outcome=TestOutcome.PASS,
            command=["test"],
            exit_code=0,
            test_observed=True,
            tests_executed=1,
            target_found=True,
        )


Classification = Literal["production", "test", "build", "CI", "documentation", "other"]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
REQUIRED_ARTIFACT_KEYS = frozenset(
    {
        "report",
        "trace",
        "final_patch",
        "baseline_target_test_log",
        "patched_target_test_log",
        "regression_test_log",
    }
)
REQUIRED_ARTIFACT_METADATA_KEYS = REQUIRED_ARTIFACT_KEYS - {"report"}


class RepositoryStateReport(BaseModel):
    """Auditable, content-safe fingerprint of the original checkout state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    head_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]
    index_sha256: Sha256
    index_bytes: int = Field(ge=0)
    git_status_sha256: Sha256
    git_status_bytes: int = Field(ge=0)
    content_sha256: Sha256


class ArtifactMetadata(BaseModel):
    """On-disk evidence metadata recorded before the final report is committed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    size_bytes: int = Field(ge=0)
    sha256: Sha256
    output_truncated: bool = False


class PatchAttemptReport(BaseModel):
    """Content-safe record of one accepted or rejected Agent Patch attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: int = Field(ge=1)
    patch_sha256: Sha256
    patch_size: int = Field(ge=0)
    affected_files: list[str] = Field(default_factory=list)
    file_classifications: dict[str, Classification] = Field(default_factory=dict)
    accepted: bool
    equivalent_to_previous: bool = False
    original_patch_sha256: Sha256 | None = None
    normalized_patch_sha256: Sha256 | None = None
    normalization_occurred: bool = False
    normalization_operations: list[str] = Field(default_factory=list)
    parsed_paths: list[str] = Field(default_factory=list)
    operation_types: list[str] = Field(default_factory=list)
    validation_result: str | None = None
    recount_used: bool = False
    error_code: str | None = None
    git_diagnostic: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=2_000)
    ] | None = None
    strict_git_diagnostic: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=2_000)
    ] | None = None
    recount_git_diagnostic: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=2_000)
    ] | None = None
    policy_diagnostic: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=2_000)
    ] | None = None
    failure_reason: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=4_000)
    ] | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if set(self.affected_files) != set(self.file_classifications):
            raise ValueError("Patch attempt classifications must match affected files")
        if self.accepted and self.failure_reason is not None:
            raise ValueError("accepted Patch attempts cannot have a failure reason")
        if not self.accepted and self.failure_reason is None:
            raise ValueError("rejected Patch attempts require a failure reason")
        return self


class RunReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    task_id: str
    schema_version: int | None
    base_commit: str | None
    start_time: datetime
    end_time: datetime
    total_duration: float = Field(ge=0)
    original_repository: Path | None
    worktree_path: Path | None
    baseline_test_result: TestResultReport
    patched_target_test_result: TestResultReport
    regression_result: TestResultReport
    affected_files: list[str]
    file_classifications: dict[str, Classification]
    patch_size: int = Field(ge=0)
    patch_sha256: Sha256 | None = None
    patch_applied: bool
    modifies_tests: bool
    modifies_build: bool
    modifies_maven_wrapper: bool
    modifies_ci: bool
    original_repository_unchanged: bool
    original_repository_before: RepositoryStateReport | None = None
    original_repository_after: RepositoryStateReport | None = None
    keep_worktree_requested: bool = False
    worktree_retained: bool = False
    worktree_exists_at_report: bool = False
    final_status: FinalStatus
    failure_reason: str | None
    artifacts: dict[str, str]
    artifact_metadata: dict[str, ArtifactMetadata] = Field(default_factory=dict)
    workflow: Literal["deterministic_verify", "agent_repair"] = "deterministic_verify"
    provider: Annotated[str, StringConstraints(strict=True, max_length=64)] | None = None
    model: Annotated[str, StringConstraints(strict=True, max_length=256)] | None = None
    issue_title: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=300)
    ] | None = None
    issue_description: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=20_000)
    ] | None = None
    total_model_turns: int = Field(default=0, ge=0)
    total_tool_calls: int = Field(default=0, ge=0)
    tool_calls_by_name: dict[str, int] = Field(default_factory=dict)
    total_patch_attempts: int = Field(default=0, ge=0)
    patch_attempts: list[PatchAttemptReport] = Field(default_factory=list)
    target_test_execution_count: int = Field(default=0, ge=0)
    regression_execution_count: int = Field(default=0, ge=0)
    input_token_usage: int = Field(default=0, ge=0)
    output_token_usage: int = Field(default=0, ge=0)
    reasoning_token_usage: int = Field(default=0, ge=0)
    model_request_count: int = Field(default=0, ge=0)
    api_error_count: int = Field(default=0, ge=0)
    api_request_ids: list[
        Annotated[str, StringConstraints(strict=True, max_length=512)]
    ] = Field(default_factory=list, max_length=200)
    model_latency_seconds: float = Field(default=0.0, ge=0)
    test_execution_duration_seconds: float = Field(default=0.0, ge=0)
    final_visible_model_message: Annotated[
        str, StringConstraints(strict=True, max_length=65_536)
    ] | None = None
    presentation_warning: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=500)
    ] | None = None
    final_deterministic_status: FinalStatus | None = None

    @model_validator(mode="after")
    def validate_final_status(self) -> Self:
        if self.end_time < self.start_time:
            raise ValueError("end_time must not precede start_time")
        if self.start_time.utcoffset() != UTC.utcoffset(self.start_time) or (
            self.end_time.utcoffset() != UTC.utcoffset(self.end_time)
        ):
            raise ValueError("report timestamps must use timezone-aware UTC")

        if set(self.file_classifications) != set(self.affected_files):
            raise ValueError("file classifications must exactly match affected files")
        if any(count < 0 for count in self.tool_calls_by_name.values()) or sum(
            self.tool_calls_by_name.values()
        ) != self.total_tool_calls:
            raise ValueError("tool call counters are internally inconsistent")
        if len(self.patch_attempts) != self.total_patch_attempts or [
            attempt.attempt_id for attempt in self.patch_attempts
        ] != list(range(1, self.total_patch_attempts + 1)):
            raise ValueError("Patch attempt records are internally inconsistent")
        classification_values = set(self.file_classifications.values())
        expected_wrapper_change = any(
            path.casefold() in {"mvnw", "mvnw.cmd"}
            or path.replace("\\", "/").lower().startswith(".mvn/wrapper/")
            for path in self.affected_files
        )
        if self.modifies_tests != ("test" in classification_values):
            raise ValueError("modifies_tests disagrees with file classifications")
        if self.modifies_build != ("build" in classification_values):
            raise ValueError("modifies_build disagrees with file classifications")
        if self.modifies_ci != ("CI" in classification_values):
            raise ValueError("modifies_ci disagrees with file classifications")
        if self.modifies_maven_wrapper != expected_wrapper_change:
            raise ValueError("modifies_maven_wrapper disagrees with affected files")
        if self.patch_applied and (
            self.patch_size == 0
            or self.patch_sha256 is None
            or not self.affected_files
        ):
            raise ValueError("an applied patch requires non-empty content and affected files")

        for name, metadata in self.artifact_metadata.items():
            configured_path = self.artifacts.get(name)
            if configured_path is None or Path(configured_path).resolve(
                strict=False
            ) != metadata.path.resolve(strict=False):
                raise ValueError(f"artifact metadata path disagrees with artifacts[{name!r}]")
        if ("trajectory" in self.artifacts) != (
            "trajectory" in self.artifact_metadata
        ):
            raise ValueError(
                "trajectory must be present in both artifacts and artifact metadata"
            )
        expected_log_truncation = {
            "baseline_target_test_log": (
                self.baseline_test_result.stdout_truncated
                or self.baseline_test_result.stderr_truncated
            ),
            "patched_target_test_log": (
                self.patched_target_test_result.stdout_truncated
                or self.patched_target_test_result.stderr_truncated
            ),
            "regression_test_log": (
                self.regression_result.stdout_truncated
                or self.regression_result.stderr_truncated
            ),
        }
        for name, expected in expected_log_truncation.items():
            log_metadata = self.artifact_metadata.get(name)
            if log_metadata is not None and log_metadata.output_truncated != expected:
                raise ValueError(f"artifact truncation flag disagrees for {name}")

        status_shape_is_valid = {
            FinalStatus.INVALID_CASE: (
                self.baseline_test_result.outcome is TestOutcome.NOT_RUN
                and self.patched_target_test_result.outcome is TestOutcome.NOT_RUN
                and self.regression_result.outcome is TestOutcome.NOT_RUN
                and not self.patch_applied
            ),
            FinalStatus.BASELINE_NOT_REPRODUCED: (
                self.baseline_test_result.outcome
                in {TestOutcome.PASS, TestOutcome.TIMEOUT}
                and self.patched_target_test_result.outcome is TestOutcome.NOT_RUN
                and self.regression_result.outcome is TestOutcome.NOT_RUN
                and not self.patch_applied
            ),
            FinalStatus.PATCH_REJECTED: (
                self.baseline_test_result.outcome is TestOutcome.FAIL
                and self.patched_target_test_result.outcome is TestOutcome.NOT_RUN
                and self.regression_result.outcome is TestOutcome.NOT_RUN
                and not self.patch_applied
            ),
            FinalStatus.TARGET_TEST_FAILED: (
                self.baseline_test_result.outcome is TestOutcome.FAIL
                and self.patch_applied
                and self.patched_target_test_result.outcome
                in {TestOutcome.FAIL, TestOutcome.TIMEOUT}
                and self.regression_result.outcome is TestOutcome.NOT_RUN
            ),
            FinalStatus.REGRESSION_FAILED: (
                self.baseline_test_result.outcome is TestOutcome.FAIL
                and self.patch_applied
                and self.patched_target_test_result.outcome is TestOutcome.PASS
                and self.regression_result.outcome
                in {TestOutcome.FAIL, TestOutcome.TIMEOUT}
            ),
        }
        if self.final_status in status_shape_is_valid and not status_shape_is_valid[
            self.final_status
        ]:
            raise ValueError(f"test phase evidence is inconsistent with {self.final_status}")

        if self.final_status is FinalStatus.RESOLVED:
            artifact_keys_valid = REQUIRED_ARTIFACT_KEYS.issubset(self.artifacts)
            metadata_keys_valid = REQUIRED_ARTIFACT_METADATA_KEYS.issubset(
                self.artifact_metadata
            )
            final_patch_metadata = self.artifact_metadata.get("final_patch")
            cleanup_valid = (
                self.worktree_retained and self.worktree_exists_at_report
                if self.keep_worktree_requested
                else not self.worktree_retained and not self.worktree_exists_at_report
            )
            agent_telemetry_valid = self.schema_version == 1 or (
                self.schema_version == 2
                and self.workflow == "agent_repair"
                and bool(self.provider)
                and bool(self.model)
                and self.total_model_turns > 0
                and self.total_tool_calls > 0
                and self.total_patch_attempts > 0
                and self.target_test_execution_count >= 2
                and self.regression_execution_count >= 1
                and self.final_deterministic_status is FinalStatus.RESOLVED
                and not self.modifies_tests
                and not self.modifies_build
                and not self.modifies_maven_wrapper
                and not self.modifies_ci
                and set(self.file_classifications.values()) == {"production"}
            )
            valid = (
                self.baseline_test_result.outcome is TestOutcome.FAIL
                and self.baseline_test_result.test_observed
                and self.baseline_test_result.target_found
                and self.patch_applied
                and self.patched_target_test_result.outcome is TestOutcome.PASS
                and self.patched_target_test_result.target_found
                and self.regression_result.outcome is TestOutcome.PASS
                and self.original_repository_unchanged
                and self.original_repository is not None
                and self.worktree_path is not None
                and self.schema_version in {1, 2}
                and self.base_commit is not None
                and self.failure_reason is None
                and self.patch_size > 0
                and self.patch_sha256 is not None
                and bool(self.affected_files)
                and set(self.file_classifications) == set(self.affected_files)
                and artifact_keys_valid
                and metadata_keys_valid
                and final_patch_metadata is not None
                and final_patch_metadata.size_bytes > 0
                and cleanup_valid
                and self.original_repository_before is not None
                and self.original_repository_after == self.original_repository_before
                and agent_telemetry_valid
            )
            if not valid:
                raise ValueError(
                    "RESOLVED requires observed baseline failure, applied patch, passing target "
                    "and regression tests, and an unchanged original repository"
                )
        elif not self.failure_reason:
            raise ValueError("non-RESOLVED reports require a failure_reason")
        return self


def write_report(report: RunReport, report_path: Path) -> None:
    """Atomically persist a UTF-8 JSON report."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    portable_report = _portable_report(report, report_path)
    temporary_path = report_path.with_name(f".rpt-{uuid.uuid4().hex[:12]}.tmp")
    try:
        temporary_path.write_text(
            portable_report.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(report_path)
    finally:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)


def _portable_report(report: RunReport, report_path: Path) -> RunReport:
    """Serialize artifact references relative to the report's immutable run directory."""

    try:
        run_directory = report_path.parent.resolve(strict=True)
        resolved_report_path = report_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise OSError(f"unable to resolve report artifact directory: {exc}") from exc
    if not run_directory.is_dir():
        raise OSError(f"report artifact directory is not a directory: {run_directory}")

    payload = report.model_dump(mode="python")
    portable_artifacts: dict[str, str] = {}
    for name, configured in report.artifacts.items():
        portable_artifacts[name] = _portable_artifact_reference(
            run_directory,
            Path(configured),
            label=f"artifacts[{name!r}]",
        )
    if portable_artifacts.get("report") != resolved_report_path.relative_to(
        run_directory
    ).as_posix():
        raise OSError("report artifact reference does not identify the output report")
    payload["artifacts"] = portable_artifacts

    portable_metadata: dict[str, dict[str, object]] = {}
    for name, metadata in report.artifact_metadata.items():
        metadata_payload = metadata.model_dump(mode="python")
        metadata_payload["path"] = _portable_artifact_reference(
            run_directory,
            metadata.path,
            label=f"artifact_metadata[{name!r}]",
        )
        portable_metadata[name] = metadata_payload
    payload["artifact_metadata"] = portable_metadata
    return RunReport.model_validate(payload)


def _portable_artifact_reference(
    run_directory: Path,
    configured: Path,
    *,
    label: str,
) -> str:
    candidate = configured if configured.is_absolute() else run_directory / configured
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise OSError(f"{label} cannot be safely resolved: {exc}") from exc
    if resolved == run_directory or not resolved.is_relative_to(run_directory):
        raise OSError(f"{label} escapes the run directory")
    return resolved.relative_to(run_directory).as_posix()


class TraceWriter:
    """Append a small, deterministic sequence of bounded trace events."""

    def __init__(
        self,
        path: Path,
        *,
        max_metadata_value_chars: int = 2_000,
        run_id: str | None = None,
        observer: Callable[[SanitizedTraceEvent], None] | None = None,
    ) -> None:
        if max_metadata_value_chars < 1:
            raise ValueError("max_metadata_value_chars must be positive")
        self.path = path
        self.max_metadata_value_chars = max_metadata_value_chars
        self.run_id = run_id
        self.sequence = 0
        self.observer = observer
        self.observer_warning: str | None = None
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def emit(
        self,
        event_type: str,
        *,
        status: str,
        duration: float | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if duration is not None and (duration < 0 or not math.isfinite(duration)):
            raise ValueError("trace duration must be a finite non-negative number")
        with self._lock:
            self.sequence += 1
            event = SanitizedTraceEvent(
                sequence=self.sequence,
                timestamp=datetime.now(UTC),
                event_type=event_type,
                duration=duration,
                status=status,
                metadata=self._limit_metadata(metadata or {}),
                run_id=self.run_id,
            )
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    json.dumps(
                        event.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
            observer = self.observer
        if observer is not None:
            try:
                observer(event)
            except Exception as exc:
                with self._lock:
                    if self.observer is observer:
                        self.observer = None
                        detail = self._redact_sensitive_text(
                            str(exc).strip() or type(exc).__name__
                        )
                        self.observer_warning = (
                            f"trace presentation observer disabled after "
                            f"{type(exc).__name__}: {detail}"
                        )[:500]

    def _limit_metadata(self, metadata: dict[str, object]) -> dict[str, object]:
        limited: dict[str, object] = {}
        for key, value in list(metadata.items())[:50]:
            safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key))[:100]
            if self._is_sensitive_key(safe_key):
                limited[safe_key] = "<redacted>"
            else:
                limited[safe_key] = self._limit_value(value, depth=0)
        return limited

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        lowered_key = key.casefold()
        return lowered_key == "env" or any(
            marker in lowered_key
            for marker in (
                "token",
                "password",
                "secret",
                "credential",
                "authorization",
                "cookie",
                "environment",
            )
        )

    def _limit_value(self, value: object, *, depth: int) -> object:
        if depth >= 3:
            return "<depth-limit>"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            redacted = self._redact_sensitive_text(value)
            if len(redacted) <= self.max_metadata_value_chars:
                return redacted
            return redacted[: self.max_metadata_value_chars] + "…"
        if isinstance(value, (list, tuple)):
            return [self._limit_value(item, depth=depth + 1) for item in value[:50]]
        if isinstance(value, dict):
            limited: dict[str, object] = {}
            for key, item in list(value.items())[:50]:
                safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key))[:100]
                limited[safe_key] = (
                    "<redacted>"
                    if self._is_sensitive_key(safe_key)
                    else self._limit_value(item, depth=depth + 1)
                )
            return limited
        return self._limit_value(str(value), depth=depth + 1)

    @staticmethod
    def _redact_sensitive_text(value: str) -> str:
        redacted = re.sub(
            r"(?i)authorization\s*:\s*bearer\s+[^\s,;]+",
            "<redacted>",
            value,
        )
        redacted = re.sub(
            r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}",
            "<redacted>",
            redacted,
        )
        redacted = re.sub(
            r"(?i)\bsk(?:-or)?-[A-Za-z0-9_-]{8,}",
            "<redacted>",
            redacted,
        )
        return re.sub(
            r"(?i)\b(?:OPENAI_API_KEY|OPENROUTER_API_KEY)\s*=\s*[^\s,;]+",
            "<redacted>",
            redacted,
        )


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    run_id: str
    directory: Path
    report: Path
    trace: Path
    final_patch: Path
    baseline_log: Path
    patched_target_log: Path
    regression_log: Path
    trajectory: Path

    def as_report_mapping(self, *, include_trajectory: bool = False) -> dict[str, str]:
        mapping = {
            "report": str(self.report),
            "trace": str(self.trace),
            "final_patch": str(self.final_patch),
            "baseline_target_test_log": str(self.baseline_log),
            "patched_target_test_log": str(self.patched_target_log),
            "regression_test_log": str(self.regression_log),
        }
        if include_trajectory:
            mapping["trajectory"] = str(self.trajectory)
        return mapping

    def metadata_files(self, *, include_trajectory: bool = False) -> dict[str, Path]:
        files = {
            "trace": self.trace,
            "final_patch": self.final_patch,
            "baseline_target_test_log": self.baseline_log,
            "patched_target_test_log": self.patched_target_log,
            "regression_test_log": self.regression_log,
        }
        if include_trajectory:
            files["trajectory"] = self.trajectory
        return files


def create_artifact_paths(
    artifacts_root: Path,
    task_hint: str,
    *,
    run_id: str | None = None,
) -> ArtifactPaths:
    """Create a unique run directory strictly below the caller-selected root."""

    artifacts_root.mkdir(parents=True, exist_ok=True)
    resolved_root = artifacts_root.expanduser().resolve(strict=True)
    if run_id is None:
        safe_task = re.sub(r"[^a-zA-Z0-9._-]", "-", task_hint).strip("-.")[:48] or "case"
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        effective_run_id = f"{safe_task}-{timestamp}-{uuid.uuid4().hex[:12]}"
    else:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", run_id) is None:
            raise ValueError("explicit run_id must be a safe 1-160 character identifier")
        effective_run_id = run_id
    directory = (resolved_root / effective_run_id).resolve(strict=False)
    if directory.parent != resolved_root:
        raise ValueError("generated artifact path escaped the artifact root")
    directory.mkdir()
    directory = directory.resolve(strict=True)
    if directory.parent != resolved_root:
        raise ValueError("created artifact directory escaped the artifact root")
    paths = ArtifactPaths(
        run_id=effective_run_id,
        directory=directory,
        report=directory / "report.json",
        trace=directory / "trace.jsonl",
        final_patch=directory / "final.patch",
        baseline_log=directory / "baseline-target-test.log",
        patched_target_log=directory / "patched-target-test.log",
        regression_log=directory / "regression-test.log",
        trajectory=directory / "trajectory.md",
    )
    for path in (
        paths.final_patch,
        paths.baseline_log,
        paths.patched_target_log,
        paths.regression_log,
    ):
        path.write_text("", encoding="utf-8")
    return paths


def collect_artifact_metadata(
    paths: ArtifactPaths,
    *,
    output_truncation: dict[str, bool] | None = None,
    include_trajectory: bool = False,
) -> dict[str, ArtifactMetadata]:
    """Hash every completed non-report artifact without following escapes."""

    truncation = output_truncation or {}
    resolved_directory = paths.directory.resolve(strict=True)
    records: dict[str, ArtifactMetadata] = {}
    for name, path in paths.metadata_files(
        include_trajectory=include_trajectory
    ).items():
        resolved = path.resolve(strict=True)
        if resolved.parent != resolved_directory or not resolved.is_file():
            raise OSError(f"artifact is not a regular file in the run directory: {path}")
        digest = hashlib.sha256()
        size = 0
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        records[name] = ArtifactMetadata(
            path=resolved,
            size_bytes=size,
            sha256=digest.hexdigest(),
            output_truncated=truncation.get(name, False),
        )
    return records
