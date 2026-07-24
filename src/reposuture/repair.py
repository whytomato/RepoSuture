"""Model-driven repair orchestration with deterministic verification authority."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from reposuture.agent.base import (
    AgentMessage,
    LLMClient,
    ProviderContinuation,
    ToolCall,
    ToolErrorCode,
    ToolResult,
)
from reposuture.agent.fake_llm import FakeLLM
from reposuture.agent.tools import (
    RepoSutureToolEnvironment,
    create_reposuture_tool_executor,
)
from reposuture.case_spec import AgentBugCase, CaseValidationError, load_agent_case
from reposuture.maven import MavenExecution, MavenInfrastructureError, MavenRunner
from reposuture.models import (
    ModelAPIError,
    ModelConfigurationError,
    ModelProtocolError,
    OpenAIResponsesClient,
    load_openai_model_config,
)
from reposuture.patching import (
    PatchApplier,
    PatchErrorCode,
    PatchInspection,
    classify_file,
)
from reposuture.process import ProcessRunner
from reposuture.reporting import (
    AgentExecutionMode,
    ArtifactPaths,
    Classification,
    FinalStatus,
    PatchAttemptReport,
    RepositoryStateReport,
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
from reposuture.trajectory import (
    load_trace_events,
    render_trajectory_markdown,
    write_trajectory_markdown,
)
from reposuture.workspace import (
    GitWorktree,
    RepositorySnapshot,
    WorkspaceError,
    validate_artifacts_outside_git_root,
)

RUNNER_MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_SAFE_MODEL_MESSAGE_CHARS = 65_536
MAX_BASELINE_DIAGNOSTIC_CHARS = 8_000

REPAIR_MODEL_INSTRUCTIONS = """You repair one small Java Maven defect using only the supplied tools.
Inspect relevant code before editing and use the reproduced baseline failure as evidence.
Make the smallest reasonable production-code change; avoid broad refactoring.
Never modify tests, pom.xml, Maven Wrapper files, .mvn, CI, or Git metadata.
Return only the Patch in the apply_patch `patch` argument; do not use Markdown code fences or prose.
Include complete Git-style headers and unchanged context lines with a leading space. Ensure hunk
counts match; Git recount can safely recover count mistakes only. A fictional valid example is:
diff --git a/src/main/java/example/Example.java b/src/main/java/example/Example.java
--- a/src/main/java/example/Example.java
+++ b/src/main/java/example/Example.java
@@ -1,3 +1,3 @@
 public class Example {
-    private boolean enabled = false;
+    private boolean enabled = true;
 }
If a Patch is rejected, use its structured diagnostic and reread the relevant source region when
necessary. Test results are the source of truth.
Do not claim success from inspection or fabricate evidence. Do not repeat equivalent patches.
Stop when no evidence-based next step remains.
"""

ProgressCallback = Callable[[str], None]
TraceObserver = Callable[[SanitizedTraceEvent], None]


def repair_case(
    case_file: Path,
    artifacts_dir: Path,
    *,
    model_override: str | None = None,
    max_turns: int | None = None,
    max_tool_calls: int | None = None,
    max_patch_attempts: int | None = None,
    max_target_test_executions: int | None = None,
    max_regression_executions: int | None = None,
    max_wall_clock_seconds: int | None = None,
    keep_worktree: bool = False,
    llm_client: LLMClient | None = None,
    injected_provider: str | None = None,
    injected_model: str | None = None,
    process_runner: ProcessRunner | None = None,
    progress: ProgressCallback | None = None,
    trace_observer: TraceObserver | None = None,
    run_id: str | None = None,
    execution_mode: AgentExecutionMode = AgentExecutionMode.FULL_AGENT,
) -> RunReport:
    """Run one bounded repair and persist deterministic evidence for every outcome."""

    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    emit_progress = progress or (lambda _message: None)
    case: AgentBugCase | None = None
    case_error: str | None = None
    try:
        case = load_agent_case(case_file)
    except CaseValidationError as exc:
        case_error = str(exc)

    task_hint = case.id if case is not None else case_file.stem
    runner = process_runner or ProcessRunner(max_output_bytes=RUNNER_MAX_OUTPUT_BYTES)
    if case is not None:
        repository_root = validate_artifacts_outside_git_root(
            case.repository,
            artifacts_dir,
            runner,
        )
        case = case.model_copy(update={"repository": repository_root})

    artifacts = create_artifact_paths(artifacts_dir, task_hint, run_id=run_id)
    trace = TraceWriter(
        artifacts.trace,
        run_id=artifacts.run_id,
        observer=trace_observer,
    )
    trace.emit(
        "run_started",
        status="STARTED",
        metadata={
            "case_file_name": case_file.name,
            "keep_worktree": keep_worktree,
            "execution_mode": execution_mode.value,
        },
    )

    baseline = TestResultReport.not_run()
    patched_target = TestResultReport.not_run()
    regression = TestResultReport.not_run()
    affected_files: list[str] = []
    classifications: dict[str, Classification] = {}
    patch_size = 0
    patch_sha256: str | None = None
    patch_applied = False
    inspection: PatchInspection | None = None
    modifies_tests = False
    modifies_build = False
    modifies_maven_wrapper = False
    modifies_ci = False
    worktree_path: Path | None = None
    worktree_retained = False
    worktree_exists_at_report = False
    original_unchanged = False
    original_before: RepositoryStateReport | None = None
    original_after: RepositoryStateReport | None = None
    final_status = FinalStatus.INFRASTRUCTURE_ERROR
    failure_reason: str | None = "repair did not start"

    provider: str | None = None
    model_name: str | None = None
    model_turns = 0
    model_responses = 0
    tool_calls = 0
    tool_counts: Counter[str] = Counter()
    target_executions = 0
    regression_executions = 0
    input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    api_request_ids: list[str] = []
    model_latency = 0.0
    test_execution_duration = 0.0
    final_visible_message: str | None = None
    environment: RepoSutureToolEnvironment | None = None
    manager: GitWorktree | None = None

    turn_limit = 1
    tool_limit = 1
    patch_limit = 1
    wall_limit = 1
    target_limit = 1
    regression_limit = 1

    active_llm = llm_client
    if case_error is not None:
        final_status = FinalStatus.INVALID_CASE
        failure_reason = case_error
        trace.emit("case_loaded", status="INVALID", metadata={"error": case_error})
    else:
        if case is None:
            raise AssertionError("validated Agent Case is unexpectedly unavailable")
        budget_error = _validate_budget_overrides(
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_patch_attempts=max_patch_attempts,
            max_target_test_executions=max_target_test_executions,
            max_regression_executions=max_regression_executions,
            max_wall_clock_seconds=max_wall_clock_seconds,
        )
        if budget_error is not None:
            final_status = FinalStatus.INVALID_CASE
            failure_reason = budget_error
        else:
            turn_limit = max_turns or case.agent_budgets.max_model_turns
            tool_limit = max_tool_calls or case.agent_budgets.max_tool_calls
            patch_limit = max_patch_attempts or case.agent_budgets.max_patch_attempts
            if execution_mode is AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK:
                patch_limit = 1
            wall_limit = max_wall_clock_seconds or case.agent_budgets.max_wall_clock_seconds
            target_limit = (
                max_target_test_executions
                or case.agent_budgets.max_target_test_executions
            )
            regression_limit = (
                max_regression_executions
                or case.agent_budgets.max_regression_executions
            )
            if active_llm is None:
                try:
                    config = load_openai_model_config(
                        model_override=model_override,
                        api_timeout_seconds=case.agent_budgets.api_timeout_seconds,
                        max_retries=case.agent_budgets.api_max_retries,
                        max_output_tokens=case.agent_budgets.max_output_tokens,
                        max_retained_model_output_bytes=(
                            case.agent_budgets.max_retained_model_output_bytes
                        ),
                        max_retained_tool_output_bytes=(
                            case.agent_budgets.max_retained_tool_output_bytes
                        ),
                    )
                    active_llm = OpenAIResponsesClient(
                        config=config,
                        instructions=REPAIR_MODEL_INSTRUCTIONS,
                    )
                    provider = config.provider_name
                    model_name = config.model
                except (ValidationError, ModelConfigurationError) as exc:
                    del exc
                    final_status = FinalStatus.MODEL_CONFIGURATION_ERROR
                    failure_reason = (
                        "OpenAI repair requires non-empty OPENAI_API_KEY and "
                        "REPOSUTURE_MODEL values (or --model); configuration was invalid"
                    )
                except Exception as exc:
                    del exc
                    final_status = FinalStatus.MODEL_CONFIGURATION_ERROR
                    failure_reason = (
                        "OpenAI client initialization failed before worktree creation; "
                        "verify the installed SDK and model configuration"
                    )
            else:
                provider = injected_provider or (
                    "fake" if isinstance(active_llm, FakeLLM) else "injected"
                )
                model_name = injected_model or type(active_llm).__name__

    if (
        case is not None
        and active_llm is not None
        and final_status is FinalStatus.INFRASTRUCTURE_ERROR
        and failure_reason == "repair did not start"
    ):
        maven = MavenRunner(runner)
        patcher = PatchApplier(runner)
        manager = GitWorktree(
            repository=case.repository,
            base_commit=case.base_commit,
            runner=runner,
            worktrees_root=Path(tempfile.gettempdir()) / "reposuture-worktrees",
            keep=keep_worktree,
        )
        try:
            with manager as worktree:
                worktree_path = worktree
                trace.emit(
                    "worktree_created",
                    status="OK",
                    metadata={"worktree_name": worktree.name, "base_commit": case.base_commit},
                )
                emit_progress("Baseline target test started")
                baseline_execution = _run_target(
                    maven,
                    worktree,
                    case,
                    artifacts.baseline_log,
                    append=False,
                    attempt_label="baseline",
                )
                target_executions += 1
                test_execution_duration += baseline_execution.process.duration_seconds
                baseline = baseline_execution.as_report()
                trace.emit(
                    "target_test_completed",
                    status=baseline.outcome.value,
                    duration=baseline.duration,
                    metadata={
                        "phase": "baseline",
                        "test_observed": baseline.test_observed,
                        "target_found": baseline.target_found,
                        "timed_out": baseline.timed_out,
                    },
                )
                if baseline.outcome is TestOutcome.INFRASTRUCTURE_ERROR:
                    final_status = FinalStatus.INFRASTRUCTURE_ERROR
                    failure_reason = (
                        baseline.infrastructure_error
                        or "baseline target test infrastructure failed"
                    )
                elif baseline.outcome is not TestOutcome.FAIL:
                    final_status = FinalStatus.BASELINE_NOT_REPRODUCED
                    failure_reason = (
                        "baseline target test timed out"
                        if baseline.outcome is TestOutcome.TIMEOUT
                        else "baseline target JUnit failure was not reproduced"
                    )
                elif not baseline.test_observed or not baseline.target_found:
                    final_status = FinalStatus.BASELINE_NOT_REPRODUCED
                    failure_reason = "baseline did not prove the configured target test failed"
                else:
                    emit_progress("Baseline failure reproduced")
                    trace.emit(
                        "agent_execution_started",
                        status="STARTED",
                        metadata={
                            "max_model_turns": turn_limit,
                            "max_tool_calls": tool_limit,
                            "max_patch_attempts": patch_limit,
                            "max_target_test_executions": target_limit,
                            "max_regression_executions": regression_limit,
                            "max_wall_clock_seconds": wall_limit,
                            "execution_mode": execution_mode.value,
                        },
                    )
                    environment = RepoSutureToolEnvironment(
                        worktree=worktree,
                        target_test=case.target_test,
                        target_test_timeout_seconds=case.target_test_timeout_seconds,
                        process_runner=runner,
                        production_java_only=True,
                        max_patch_attempts=patch_limit,
                    )
                    executor = create_reposuture_tool_executor(environment)
                    messages = [
                        AgentMessage(
                            role="user",
                            content=_repair_task_message(
                                case,
                                baseline_execution,
                                execution_mode=execution_mode,
                            ),
                        )
                    ]
                    continuation: ProviderContinuation | None = None
                    last_tool_error: ToolErrorCode | PatchErrorCode | None = None
                    pending_replan: dict[str, object] | None = None

                    while True:
                        elapsed = time.monotonic() - started_monotonic
                        if elapsed >= wall_limit:
                            final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                            failure_reason = "maximum repair wall-clock duration reached"
                            trace.emit("budget_exhausted", status="WALL_CLOCK")
                            break
                        if model_turns >= turn_limit:
                            final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                            failure_reason = "maximum model turns reached"
                            trace.emit("budget_exhausted", status="MODEL_TURNS")
                            break

                        if (
                            pending_replan is not None
                            and execution_mode is AgentExecutionMode.FULL_AGENT
                        ):
                            trace.emit(
                                "agent_replan_requested",
                                status="FEEDBACK_RETURNED",
                                metadata={
                                    **pending_replan,
                                    "next_model_turn": model_turns + 1,
                                },
                            )
                            pending_replan = None

                        model_turns += 1
                        emit_progress(f"Model turn {model_turns}")
                        trace.emit(
                            "model_request_started",
                            status="STARTED",
                            metadata={
                                "model_turn": model_turns,
                                "model": model_name,
                                "max_model_turns": turn_limit,
                                "tool_calls": tool_calls,
                                "max_tool_calls": tool_limit,
                                "patch_attempts": len(environment.patch_attempts),
                                "max_patch_attempts": patch_limit,
                            },
                        )
                        request_started = time.monotonic()
                        try:
                            response = active_llm.chat(
                                tuple(messages),
                                executor.specs,
                                continuation=continuation,
                            )
                        except ModelConfigurationError as exc:
                            final_status = FinalStatus.MODEL_CONFIGURATION_ERROR
                            failure_reason = str(exc)
                            trace.emit(
                                "model_request_failed",
                                status=final_status.value,
                                metadata=_provider_failure_metadata(exc),
                            )
                            break
                        except (ModelAPIError, ModelProtocolError) as exc:
                            final_status = FinalStatus.MODEL_API_ERROR
                            failure_reason = str(exc)
                            trace.emit(
                                "model_request_failed",
                                status=final_status.value,
                                metadata=_provider_failure_metadata(exc),
                            )
                            break
                        except Exception as exc:
                            final_status = FinalStatus.MODEL_API_ERROR
                            detail = str(exc).strip() or type(exc).__name__
                            failure_reason = (
                                f"model client failed: {type(exc).__name__}: {detail}"
                            )[:4_000]
                            trace.emit(
                                "model_request_failed",
                                status=final_status.value,
                                metadata=_provider_failure_metadata(exc),
                            )
                            break
                        request_duration = max(0.0, time.monotonic() - request_started)
                        model_responses += 1
                        model_latency += response.latency_seconds or request_duration
                        continuation = response.continuation
                        model_name = response.model or model_name
                        input_tokens += response.usage.input_tokens
                        output_tokens += response.usage.output_tokens
                        reasoning_tokens += response.usage.reasoning_tokens
                        if response.request_id:
                            api_request_ids.append(response.request_id)
                        if response.message:
                            final_visible_message = response.message[
                                :MAX_SAFE_MODEL_MESSAGE_CHARS
                            ]
                        if response.discarded_tool_call_count:
                            trace.emit(
                                "provider_tool_calls_sequentialized",
                                status="COMPATIBILITY",
                                metadata={
                                    "model_turn": model_turns,
                                    "discarded_tool_calls": (
                                        response.discarded_tool_call_count
                                    ),
                                    "retained_tool_calls": 1,
                                },
                            )
                        trace.emit(
                            "model_response_received",
                            status=("INCOMPLETE" if response.incomplete_reason else "OK"),
                            duration=request_duration,
                            metadata={
                                "model_turn": model_turns,
                                "model": model_name,
                                "request_id": response.request_id,
                                "response_id": response.response_id,
                                "incomplete_reason": response.incomplete_reason,
                                "output_truncated": response.output_truncated,
                                "input_tokens": response.usage.input_tokens,
                                "output_tokens": response.usage.output_tokens,
                                "reasoning_tokens": response.usage.reasoning_tokens,
                            },
                        )
                        messages.append(
                            AgentMessage(
                                role="assistant",
                                content=response.message,
                                tool_call=response.tool_call,
                            )
                        )
                        if response.finish_requested:
                            final_status = (
                                FinalStatus.POLICY_REJECTED
                                if last_tool_error
                                in {
                                    ToolErrorCode.POLICY_REJECTED,
                                    PatchErrorCode.PATCH_POLICY_REJECTED,
                                }
                                else FinalStatus.MODEL_STOPPED
                            )
                            suffix = (
                                f" ({response.incomplete_reason})"
                                if response.incomplete_reason
                                else ""
                            )
                            failure_reason = (
                                "model stopped without deterministic success" + suffix
                            )
                            trace.emit(
                                "model_stopped",
                                status=final_status.value,
                                metadata={"model_turn": model_turns},
                            )
                            break

                        call = response.tool_call
                        if call is None:
                            final_status = FinalStatus.MODEL_API_ERROR
                            failure_reason = "model returned no executable action"
                            break
                        if tool_calls >= tool_limit:
                            final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                            failure_reason = "maximum total tool calls reached"
                            trace.emit("budget_exhausted", status="TOOL_CALLS")
                            break
                        if (
                            call.name == "apply_patch"
                            and len(environment.patch_attempts) >= patch_limit
                        ):
                            final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                            failure_reason = "maximum patch attempts reached"
                            trace.emit("budget_exhausted", status="PATCH_ATTEMPTS")
                            break
                        if call.name == "run_target_test" and target_executions >= target_limit:
                            final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                            failure_reason = "maximum target-test executions reached"
                            trace.emit("budget_exhausted", status="TARGET_TESTS")
                            break

                        tool_calls += 1
                        tool_counts[call.name] += 1
                        emit_progress(f"Tool: {call.name}")
                        trace.emit(
                            "tool_call_requested",
                            status="REQUESTED",
                            metadata={
                                "model_turn": model_turns,
                                "tool_name": call.name,
                                "arguments": _safe_tool_arguments(call),
                                "tool_call_number": tool_calls,
                                "max_tool_calls": tool_limit,
                                "patch_attempts_remaining": max(
                                    0,
                                    patch_limit - len(environment.patch_attempts),
                                ),
                            },
                        )
                        patch_attempts_before = len(environment.patch_attempts)
                        tool_started_monotonic = time.monotonic()
                        result = executor.execute(call)
                        if (
                            call.name == "apply_patch"
                            and len(environment.patch_attempts) == patch_attempts_before
                        ):
                            environment.record_rejected_patch_call(
                                call.arguments,
                                failure_reason=(
                                    result.error.message
                                    if result.error is not None
                                    else "apply_patch did not execute"
                                ),
                            )
                        last_tool_error = result.error.code if result.error else None
                        validation_rejected = result.error is not None
                        trace.emit(
                            "tool_call_rejected" if validation_rejected else "tool_call_validated",
                            status=(result.error.code.value if result.error else "OK"),
                            metadata={
                                "tool_name": call.name,
                                "error_code": (
                                    result.error.code.value if result.error else None
                                ),
                                "error_message": (
                                    result.error.message if result.error else None
                                ),
                            },
                        )

                        if call.name == "apply_patch" and environment.patch_attempts:
                            attempt = environment.patch_attempts[-1]
                            emit_progress(f"Patch attempt {attempt.attempt_id}")
                            trace.emit(
                                "patch_attempted",
                                status="ACCEPTED" if attempt.accepted else "REJECTED",
                                metadata={
                                    "patch_attempt_id": attempt.attempt_id,
                                    "model_turn": model_turns,
                                    "patch_attempts_remaining": max(
                                        0, patch_limit - attempt.attempt_id
                                    ),
                                    "patch_sha256": attempt.patch_sha256,
                                    "patch_size": attempt.patch_size,
                                    "affected_files": list(attempt.affected_files),
                                    "equivalent": attempt.equivalent_to_previous,
                                    "original_patch_sha256": attempt.original_patch_sha256,
                                    "normalized_patch_sha256": attempt.normalized_patch_sha256,
                                    "normalization_occurred": attempt.normalization_occurred,
                                    "normalization_operations": list(
                                        attempt.normalization_operations
                                    ),
                                    "parsed_paths": list(attempt.parsed_paths),
                                    "patch_operation_types": [
                                        operation.value for operation in attempt.operation_types
                                    ],
                                    "validation_result": (
                                        attempt.validation_result.value
                                        if attempt.validation_result is not None
                                        else None
                                    ),
                                    "recount_used": attempt.recount_used,
                                    "error_code": (
                                        attempt.error_code.value
                                        if attempt.error_code is not None
                                        else None
                                    ),
                                    "git_diagnostic": attempt.git_diagnostic,
                                    "strict_git_diagnostic": (
                                        attempt.strict_git_diagnostic
                                    ),
                                    "recount_git_diagnostic": (
                                        attempt.recount_git_diagnostic
                                    ),
                                    "policy_diagnostic": attempt.policy_diagnostic,
                                },
                            )
                            if not attempt.accepted:
                                pending_replan = {
                                    "reasons": ["PATCH_REJECTED"],
                                    "patch_attempt_id": attempt.attempt_id,
                                    "error_code": (
                                        attempt.error_code.value
                                        if attempt.error_code is not None
                                        else None
                                    ),
                                }
                                if (
                                    execution_mode
                                    is AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK
                                ):
                                    trace.emit(
                                        "tool_execution_completed",
                                        status="FAILED",
                                        duration=max(
                                            0.0,
                                            time.monotonic() - tool_started_monotonic,
                                        ),
                                        metadata={
                                            "tool_name": call.name,
                                            "model_turn": model_turns,
                                            "truncated": _result_truncated(result),
                                            "observation": _safe_tool_observation(result),
                                        },
                                    )
                                    final_status = (
                                        FinalStatus.POLICY_REJECTED
                                        if attempt.error_code
                                        is PatchErrorCode.PATCH_POLICY_REJECTED
                                        else FinalStatus.PATCH_REJECTED
                                    )
                                    failure_reason = (
                                        attempt.failure_reason
                                        or "the single candidate Patch was rejected"
                                    )
                                    pending_replan = None
                                    break

                            if result.output and result.output.get("terminal") is True:
                                messages.append(
                                    AgentMessage(role="tool", tool_result=result)
                                )
                                trace.emit(
                                    "tool_execution_completed",
                                    status="FAILED",
                                    duration=max(
                                        0.0,
                                        time.monotonic() - tool_started_monotonic,
                                    ),
                                    metadata={
                                        "tool_name": call.name,
                                        "model_turn": model_turns,
                                        "truncated": _result_truncated(result),
                                        "observation": _safe_tool_observation(result),
                                    },
                                )
                                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                                failure_reason = (
                                    result.error.message
                                    if result.error is not None
                                    else "terminal Patch transaction failure"
                                )
                                break

                        if call.name == "run_target_test" and result.success:
                            target_executions += 1
                            if environment.latest_target_execution is not None:
                                test_execution_duration += (
                                    environment.latest_target_execution.process.duration_seconds
                                )
                                patched_target = environment.latest_target_execution.as_report()
                                _append_execution_log(
                                    artifacts.patched_target_log,
                                    environment.latest_target_execution,
                                    f"model-requested-{target_executions}",
                                )

                        if call.name == "apply_patch" and result.success:
                            verification_terminal = False
                            inspection = environment.patch_inspection
                            if inspection is None or environment.final_patch is None:
                                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                                failure_reason = (
                                    "accepted Patch did not produce deterministic diff evidence"
                                )
                                break
                            affected_files = list(inspection.affected_files)
                            classifications = {
                                path: value.value
                                for path, value in inspection.file_classifications.items()
                            }
                            patch_size = inspection.patch_size
                            patch_sha256 = inspection.patch_sha256
                            modifies_tests = inspection.modifies_tests
                            modifies_build = inspection.modifies_build
                            modifies_maven_wrapper = inspection.modifies_maven_wrapper
                            modifies_ci = inspection.modifies_ci
                            patch_applied = True
                            candidate_before_tests = environment.final_patch

                            if target_executions >= target_limit:
                                final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                                failure_reason = "maximum target-test executions reached"
                                _rollback_candidate(environment, patcher, inspection)
                                trace.emit(
                                    "candidate_reverted",
                                    status="REVERTED",
                                    metadata={
                                        "reason": "TARGET_TEST_BUDGET",
                                        "patch_attempt_id": len(environment.patch_attempts),
                                    },
                                )
                                patch_applied = False
                                verification_terminal = True
                                messages.append(
                                    AgentMessage(role="tool", tool_result=result)
                                )
                                trace.emit(
                                    "tool_execution_completed",
                                    status="OK",
                                    duration=max(
                                        0.0,
                                        time.monotonic() - tool_started_monotonic,
                                    ),
                                    metadata={
                                        "tool_name": call.name,
                                        "model_turn": model_turns,
                                        "truncated": _result_truncated(result),
                                        "observation": _safe_tool_observation(result),
                                    },
                                )
                                break
                                break
                            target_execution = _run_target(
                                maven,
                                worktree,
                                case,
                                artifacts.patched_target_log,
                                append=True,
                                attempt_label=f"patch-{len(environment.patch_attempts)}",
                            )
                            target_executions += 1
                            test_execution_duration += (
                                target_execution.process.duration_seconds
                            )
                            patched_target = target_execution.as_report()
                            emit_progress(
                                f"Target test: {patched_target.outcome.value}"
                            )
                            trace.emit(
                                "target_test_completed",
                                status=patched_target.outcome.value,
                                duration=patched_target.duration,
                                metadata={
                                    "phase": "patched",
                                    "patch_attempt_id": len(environment.patch_attempts),
                                    "test_observed": patched_target.test_observed,
                                    "target_found": patched_target.target_found,
                                    "timed_out": patched_target.timed_out,
                                },
                            )
                            result = _with_verification_observation(
                                result,
                                target=patched_target,
                                regression=None,
                                candidate_reverted=False,
                            )
                            if patched_target.outcome is TestOutcome.INFRASTRUCTURE_ERROR:
                                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                                failure_reason = (
                                    patched_target.infrastructure_error
                                    or "patched target test infrastructure failed"
                                )
                                verification_terminal = True
                            elif patched_target.outcome is TestOutcome.TIMEOUT:
                                final_status = FinalStatus.UNRESOLVED
                                failure_reason = "patched target test timed out"
                                verification_terminal = True
                            elif patched_target.outcome is TestOutcome.FAIL:
                                _rollback_candidate(environment, patcher, inspection)
                                trace.emit(
                                    "candidate_reverted",
                                    status="REVERTED",
                                    metadata={
                                        "reason": "TARGET_TEST_FAILED",
                                        "patch_attempt_id": len(environment.patch_attempts),
                                    },
                                )
                                patch_applied = False
                                if (
                                    execution_mode
                                    is AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK
                                ):
                                    final_status = FinalStatus.TARGET_TEST_FAILED
                                    failure_reason = (
                                        "the single accepted candidate did not pass "
                                        "the target test"
                                    )
                                    verification_terminal = True
                                else:
                                    pending_replan = {
                                        "reasons": [
                                            "TARGET_TEST_FAILED",
                                            "CANDIDATE_REVERTED",
                                        ],
                                        "patch_attempt_id": len(
                                            environment.patch_attempts
                                        ),
                                    }
                                result = _with_verification_observation(
                                    result,
                                    target=patched_target,
                                    regression=None,
                                    candidate_reverted=True,
                                )
                            elif (
                                not patched_target.test_observed
                                or not patched_target.target_found
                            ):
                                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                                failure_reason = (
                                    "patched target test lacked matching JUnit evidence"
                                )
                                verification_terminal = True
                            else:
                                if regression_executions >= regression_limit:
                                    final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                                    failure_reason = "maximum regression executions reached"
                                    verification_terminal = True
                                else:
                                    regression_execution = _run_regression(
                                        maven,
                                        worktree,
                                        case,
                                        artifacts.regression_log,
                                        attempt_label=f"patch-{len(environment.patch_attempts)}",
                                    )
                                    regression_executions += 1
                                    test_execution_duration += (
                                        regression_execution.process.duration_seconds
                                    )
                                    regression = regression_execution.as_report()
                                    emit_progress(
                                        f"Regression: {regression.outcome.value}"
                                    )
                                    trace.emit(
                                        "regression_test_completed",
                                        status=regression.outcome.value,
                                        duration=regression.duration,
                                        metadata={
                                            "patch_attempt_id": len(environment.patch_attempts),
                                            "test_observed": regression.test_observed,
                                            "timed_out": regression.timed_out,
                                        },
                                    )
                                    result = _with_verification_observation(
                                        result,
                                        target=patched_target,
                                        regression=regression,
                                        candidate_reverted=False,
                                    )
                                    if regression.outcome is TestOutcome.PASS:
                                        final_after_tests = patcher.final_diff(
                                            worktree, inspection
                                        )
                                        if final_after_tests != candidate_before_tests:
                                            final_status = FinalStatus.INFRASTRUCTURE_ERROR
                                            failure_reason = (
                                                "worktree diff changed outside the verified Patch "
                                                "during tests"
                                            )
                                            verification_terminal = True
                                        else:
                                            artifacts.final_patch.write_text(
                                                final_after_tests, encoding="utf-8"
                                            )
                                            final_status = FinalStatus.RESOLVED
                                            failure_reason = None
                                            verification_terminal = True
                                    elif regression.outcome is TestOutcome.INFRASTRUCTURE_ERROR:
                                        final_status = FinalStatus.INFRASTRUCTURE_ERROR
                                        failure_reason = (
                                            regression.infrastructure_error
                                            or "regression test infrastructure failed"
                                        )
                                        verification_terminal = True
                                    elif regression.outcome is TestOutcome.TIMEOUT:
                                        final_status = FinalStatus.UNRESOLVED
                                        failure_reason = "regression test timed out"
                                        verification_terminal = True
                                    else:
                                        _rollback_candidate(
                                            environment, patcher, inspection
                                        )
                                        trace.emit(
                                            "candidate_reverted",
                                            status="REVERTED",
                                            metadata={
                                                "reason": "REGRESSION_FAILED",
                                                "patch_attempt_id": len(
                                                    environment.patch_attempts
                                                ),
                                            },
                                        )
                                        patch_applied = False
                                        if (
                                            execution_mode
                                            is AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK
                                        ):
                                            final_status = FinalStatus.REGRESSION_FAILED
                                            failure_reason = (
                                                "the single accepted candidate passed "
                                                "the target but failed regression"
                                            )
                                            verification_terminal = True
                                        else:
                                            pending_replan = {
                                                "reasons": [
                                                    "REGRESSION_FAILED",
                                                    "CANDIDATE_REVERTED",
                                                ],
                                                "patch_attempt_id": len(
                                                    environment.patch_attempts
                                                ),
                                            }
                                        result = _with_verification_observation(
                                            result,
                                            target=patched_target,
                                            regression=regression,
                                            candidate_reverted=True,
                                        )

                            if verification_terminal:
                                if execution_mode is AgentExecutionMode.FULL_AGENT:
                                    messages.append(
                                        AgentMessage(role="tool", tool_result=result)
                                    )
                                trace.emit(
                                    "tool_execution_completed",
                                    status="OK" if result.success else "FAILED",
                                    duration=max(
                                        0.0,
                                        time.monotonic() - tool_started_monotonic,
                                    ),
                                    metadata={
                                        "tool_name": call.name,
                                        "model_turn": model_turns,
                                        "truncated": _result_truncated(result),
                                        "observation": _safe_tool_observation(result),
                                    },
                                )
                                break

                        messages.append(AgentMessage(role="tool", tool_result=result))
                        trace.emit(
                            "tool_execution_completed",
                            status="OK" if result.success else "FAILED",
                            duration=max(
                                0.0,
                                time.monotonic() - tool_started_monotonic,
                            ),
                            metadata={
                                "tool_name": call.name,
                                "model_turn": model_turns,
                                "truncated": _result_truncated(result),
                                "observation": _safe_tool_observation(result),
                            },
                        )
                        emit_progress(
                            f"Tool outcome: {'OK' if result.success else result.error.code.value}"
                            if result.error
                            else "Tool outcome: OK"
                        )
                        if (
                            call.name == "apply_patch"
                            and len(environment.patch_attempts) >= patch_limit
                            and not patch_applied
                        ):
                            final_status = FinalStatus.AGENT_BUDGET_EXHAUSTED
                            failure_reason = "maximum patch attempts reached"
                            trace.emit("budget_exhausted", status="PATCH_ATTEMPTS")
                            break

                if final_status is FinalStatus.RESOLVED:
                    if environment is None:
                        raise AssertionError(
                            "resolved repair is missing its tool environment"
                        )
                    trace.emit(
                        "repair_resolved",
                        status="RESOLVED",
                        metadata={"patch_attempts": len(environment.patch_attempts)},
                    )
        except MavenInfrastructureError as exc:
            final_status = FinalStatus.INFRASTRUCTURE_ERROR
            failure_reason = str(exc)
        except WorkspaceError as exc:
            final_status = FinalStatus.INFRASTRUCTURE_ERROR
            failure_reason = str(exc)
        except Exception as exc:
            final_status = FinalStatus.INFRASTRUCTURE_ERROR
            detail = str(exc).strip() or type(exc).__name__
            failure_reason = f"unexpected {type(exc).__name__}: {detail}"[:4_000]

        original_unchanged = manager.original_unchanged is True
        original_before = _repository_state(manager.original_snapshot)
        original_after = _repository_state(manager.final_snapshot)
        worktree_exists_at_report = bool(worktree_path and worktree_path.is_dir())
        worktree_retained = bool(keep_worktree and worktree_exists_at_report)
        if final_status is FinalStatus.RESOLVED:
            cleanup_valid = (
                worktree_retained
                if keep_worktree
                else not worktree_exists_at_report and not manager.cleanup_error
            )
            if not cleanup_valid:
                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                failure_reason = "worktree cleanup state did not match requested policy"
            elif not original_unchanged:
                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                failure_reason = "original repository unchanged check did not pass"

    _write_not_run_logs(artifacts)
    if final_status is not FinalStatus.RESOLVED:
        if failure_reason is None:
            failure_reason = "repair ended without deterministic success"
        trace.emit(
            "repair_failed",
            status=final_status.value,
            metadata={"failure_reason": failure_reason},
        )
    total_duration = max(0.0, time.monotonic() - started_monotonic)
    trace.emit(
        "agent_finished",
        status=final_status.value,
        duration=total_duration,
        metadata={
            "model_turns": model_turns,
            "tool_calls": tool_calls,
            "patch_attempts": len(environment.patch_attempts) if environment else 0,
            "target_test_executions": target_executions,
            "regression_executions": regression_executions,
            "duration_seconds": total_duration,
            "failure_reason": failure_reason,
            "execution_mode": execution_mode.value,
        },
    )
    trace.emit(
        "run_finished",
        status=final_status.value,
        duration=total_duration,
        metadata={"failure_reason": failure_reason},
    )
    ended_at = datetime.now(UTC)
    artifact_metadata = collect_artifact_metadata(
        artifacts,
        output_truncation={
            "baseline_target_test_log": (
                baseline.stdout_truncated or baseline.stderr_truncated
            ),
            "patched_target_test_log": (
                patched_target.stdout_truncated or patched_target.stderr_truncated
            ),
            "regression_test_log": (
                regression.stdout_truncated or regression.stderr_truncated
            ),
        },
    )
    total_patch_attempts = len(environment.patch_attempts) if environment else 0
    patch_attempt_reports = [
        PatchAttemptReport(
            attempt_id=attempt.attempt_id,
            patch_sha256=attempt.patch_sha256,
            patch_size=attempt.patch_size,
            affected_files=list(attempt.affected_files),
            file_classifications={
                path: classify_file(path).value for path in attempt.affected_files
            },
            accepted=attempt.accepted,
            equivalent_to_previous=attempt.equivalent_to_previous,
            failure_reason=attempt.failure_reason,
            original_patch_sha256=attempt.original_patch_sha256,
            normalized_patch_sha256=attempt.normalized_patch_sha256,
            normalization_occurred=attempt.normalization_occurred,
            normalization_operations=list(attempt.normalization_operations),
            parsed_paths=list(attempt.parsed_paths),
            operation_types=[operation.value for operation in attempt.operation_types],
            validation_result=(
                attempt.validation_result.value
                if attempt.validation_result is not None
                else None
            ),
            recount_used=attempt.recount_used,
            error_code=(
                attempt.error_code.value if attempt.error_code is not None else None
            ),
            git_diagnostic=attempt.git_diagnostic,
            strict_git_diagnostic=attempt.strict_git_diagnostic,
            recount_git_diagnostic=attempt.recount_git_diagnostic,
            policy_diagnostic=attempt.policy_diagnostic,
        )
        for attempt in (environment.patch_attempts if environment else [])
    ]
    model_request_count = _client_counter(
        active_llm,
        "model_request_count",
        fallback=model_turns,
    )
    api_error_count = _client_counter(active_llm, "api_error_count", fallback=0)
    provider_accepted_count = _client_counter(
        active_llm,
        "provider_accepted_count",
        fallback=model_responses,
    )
    provider_rejected_count = _client_counter(
        active_llm,
        "provider_rejected_count",
        fallback=0,
    )
    model_executed_count = _client_counter(
        active_llm,
        "model_executed_count",
        fallback=model_responses,
    )
    provider_accepted = provider_accepted_count > 0
    model_executed = model_executed_count > 0
    provider_rejected = (
        provider_rejected_count > 0
        and not provider_accepted
        and not model_executed
    )
    report = RunReport(
        run_id=artifacts.run_id,
        task_id=case.id if case is not None else task_hint,
        schema_version=case.schema_version if case is not None else None,
        base_commit=case.base_commit if case is not None else None,
        start_time=started_at,
        end_time=ended_at,
        total_duration=total_duration,
        original_repository=case.repository if case is not None else None,
        worktree_path=worktree_path,
        baseline_test_result=baseline,
        patched_target_test_result=patched_target,
        regression_result=regression,
        affected_files=affected_files,
        file_classifications=classifications,
        patch_size=patch_size,
        patch_sha256=patch_sha256,
        patch_applied=patch_applied,
        modifies_tests=modifies_tests,
        modifies_build=modifies_build,
        modifies_maven_wrapper=modifies_maven_wrapper,
        modifies_ci=modifies_ci,
        original_repository_unchanged=original_unchanged,
        original_repository_before=original_before,
        original_repository_after=original_after,
        keep_worktree_requested=keep_worktree,
        worktree_retained=worktree_retained,
        worktree_exists_at_report=worktree_exists_at_report,
        final_status=final_status,
        terminal_status=final_status,
        failure_reason=failure_reason,
        artifacts=artifacts.as_report_mapping(),
        artifact_metadata=artifact_metadata,
        workflow="agent_repair",
        execution_mode=execution_mode,
        provider=provider,
        model=model_name,
        issue_title=case.issue_title if case is not None else None,
        issue_description=case.issue_description if case is not None else None,
        total_model_turns=model_turns,
        total_tool_calls=tool_calls,
        tool_calls_by_name=dict(sorted(tool_counts.items())),
        total_patch_attempts=total_patch_attempts,
        patch_attempts=patch_attempt_reports,
        target_test_execution_count=target_executions,
        regression_execution_count=regression_executions,
        input_token_usage=input_tokens,
        output_token_usage=output_tokens,
        reasoning_token_usage=reasoning_tokens,
        model_request_count=model_request_count,
        api_error_count=api_error_count,
        provider_accepted=provider_accepted,
        provider_rejected=provider_rejected,
        model_executed=model_executed,
        model_tool_call_observed=tool_calls > 0,
        api_request_ids=api_request_ids,
        model_latency_seconds=model_latency,
        test_execution_duration_seconds=test_execution_duration,
        final_visible_model_message=final_visible_message,
        presentation_warning=trace.observer_warning,
        final_deterministic_status=final_status,
    )
    trace_events = load_trace_events(artifacts.trace)
    classification = classify_run_failures(report, trace_events)
    report = report.model_copy(
        update={
            "terminal_status": classification.terminal_status,
            "primary_failure": classification.primary_failure,
            "observed_failures": classification.observed_failures,
        }
    )
    trajectory = render_trajectory_markdown(report, trace_events)
    write_trajectory_markdown(artifacts.trajectory, trajectory)
    report = RunReport.model_validate(
        {
            **report.model_dump(mode="python"),
            "artifacts": artifacts.as_report_mapping(include_trajectory=True),
            "artifact_metadata": collect_artifact_metadata(
                artifacts,
                output_truncation={
                    "baseline_target_test_log": (
                        baseline.stdout_truncated or baseline.stderr_truncated
                    ),
                    "patched_target_test_log": (
                        patched_target.stdout_truncated or patched_target.stderr_truncated
                    ),
                    "regression_test_log": (
                        regression.stdout_truncated or regression.stderr_truncated
                    ),
                },
                include_trajectory=True,
            ),
        }
    )
    write_report(report, artifacts.report)
    return report


def _run_target(
    maven: MavenRunner,
    worktree: Path,
    case: AgentBugCase,
    log_path: Path,
    *,
    append: bool,
    attempt_label: str,
) -> MavenExecution:
    execution = maven.run_target(
        worktree,
        case.target_test,
        timeout_seconds=case.target_test_timeout_seconds,
    )
    if append:
        _append_execution_log(log_path, execution, attempt_label)
    else:
        log_path.write_text(MavenRunner.format_log(execution), encoding="utf-8")
    return execution


def _run_regression(
    maven: MavenRunner,
    worktree: Path,
    case: AgentBugCase,
    log_path: Path,
    *,
    attempt_label: str,
) -> MavenExecution:
    execution = maven.run_regression(
        worktree,
        case.regression_tests,
        timeout_seconds=case.regression_timeout_seconds,
    )
    _append_execution_log(log_path, execution, attempt_label)
    return execution


def _append_execution_log(path: Path, execution: MavenExecution, label: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"\n===== {label} =====\n")
        stream.write(MavenRunner.format_log(execution))


def _write_not_run_logs(artifacts: ArtifactPaths) -> None:
    for path in (
        artifacts.baseline_log,
        artifacts.patched_target_log,
        artifacts.regression_log,
    ):
        if path.stat().st_size == 0:
            path.write_text('{"outcome":"NOT_RUN"}\n', encoding="utf-8")


def _rollback_candidate(
    environment: RepoSutureToolEnvironment,
    patcher: PatchApplier,
    inspection: PatchInspection,
) -> None:
    patcher.restore_baseline(environment.worktree, inspection)
    environment.patch_inspection = None
    environment.final_patch = None


def _with_verification_observation(
    result: ToolResult,
    *,
    target: TestResultReport,
    regression: TestResultReport | None,
    candidate_reverted: bool,
) -> ToolResult:
    output = dict(result.output or {})
    output["automatic_target_test"] = _compact_test_result(target)
    if regression is not None:
        output["automatic_regression"] = _compact_test_result(regression)
    output["candidate_reverted_to_baseline"] = candidate_reverted
    verified = (
        target.outcome is TestOutcome.PASS
        and regression is not None
        and regression.outcome is TestOutcome.PASS
    )
    return result.model_copy(update={"output": output, "verifier_passed": verified})


def _compact_test_result(result: TestResultReport) -> dict[str, object]:
    return {
        "outcome": result.outcome.value,
        "test_observed": result.test_observed,
        "target_found": result.target_found,
        "tests_executed": result.tests_executed,
        "test_failures": result.test_failures,
        "tests_skipped": result.tests_skipped,
        "timed_out": result.timed_out,
        "infrastructure_error": result.infrastructure_error,
    }


def _repair_task_message(
    case: AgentBugCase,
    baseline: MavenExecution,
    *,
    execution_mode: AgentExecutionMode,
) -> str:
    process = baseline.process
    diagnostic = {
        "outcome": baseline.outcome.value,
        "test_observed": baseline.test_observed,
        "target_found": baseline.target_found,
        "tests_executed": baseline.tests_executed,
        "test_failures": baseline.test_failures,
        "stdout_tail": process.stdout[-MAX_BASELINE_DIAGNOSTIC_CHARS // 2 :],
        "stderr_tail": process.stderr[-MAX_BASELINE_DIAGNOSTIC_CHARS // 2 :],
        "stdout_truncated": process.stdout_truncated,
        "stderr_truncated": process.stderr_truncated,
    }
    mode_instruction = (
        "\nThis controlled baseline permits exactly one candidate Patch. "
        "After that Patch is submitted, verification ends the attempt and no "
        "test feedback or replanning turn will be provided."
        if execution_mode is AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK
        else ""
    )
    return (
        f"Task ID: {case.id}\n"
        f"Issue: {case.issue_title}\n"
        f"Description: {case.issue_description}\n"
        f"Target test: {case.target_test.maven_selector}\n"
        "The isolated baseline target test was deterministically reproduced as failing.\n"
        f"Baseline diagnostic: {json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)}"
        f"{mode_instruction}"
    )


def _provider_failure_metadata(exc: Exception) -> dict[str, object]:
    """Return bounded categorical provider diagnostics without response bodies."""

    if isinstance(exc, ModelProtocolError):
        failure_kind = "PROTOCOL"
    elif "timeout" in (type(exc).__name__ + " " + str(exc)).casefold():
        failure_kind = "TIMEOUT"
    elif isinstance(exc, ModelConfigurationError):
        failure_kind = "CONFIGURATION"
    else:
        failure_kind = "API"
    match = re.search(r"(?<!\d)([45]\d{2})(?!\d)", str(exc))
    return {
        "failure_kind": failure_kind,
        "http_status": int(match.group(1)) if match else None,
        "exception_type": type(exc).__name__[:100],
    }


def _safe_tool_arguments(call: ToolCall) -> dict[str, object]:
    if call.name == "apply_patch":
        raw_patch = call.arguments.get("patch")
        if isinstance(raw_patch, str):
            encoded = raw_patch.encode("utf-8")
            return {
                "patch_size": len(encoded),
                "patch_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        return {"patch_present": raw_patch is not None}
    safe: dict[str, object] = {}
    for key, value in list(call.arguments.items())[:20]:
        if isinstance(value, str):
            safe[key] = value[:500]
        elif value is None or isinstance(value, (bool, int, float)):
            safe[key] = value
        else:
            safe[key] = type(value).__name__
    return safe


def _result_truncated(result: ToolResult) -> bool:
    output = result.output or {}
    return any(
        value is True
        for key, value in output.items()
        if key.endswith("truncated") or key == "truncated"
    )


def _safe_tool_observation(result: ToolResult) -> dict[str, object]:
    """Project a tool result into bounded counts without source, Patch, or log bodies."""

    output = result.output or {}
    observation: dict[str, object] = {"truncated": _result_truncated(result)}
    if result.error is not None:
        observation["error_code"] = result.error.code.value
    allowed_by_tool = {
        "list_files": ("count", "scanned_paths"),
        "search_code": ("match_count", "files_considered", "skipped_files"),
        "read_file": ("start_line", "end_line", "retained_line_count"),
        "apply_patch": ("patch_size", "normalization_occurred", "recount_used"),
        "run_target_test": (
            "outcome",
            "test_observed",
            "target_found",
            "tests_executed",
            "test_failures",
            "tests_skipped",
            "duration_seconds",
            "timed_out",
        ),
        "git_diff": ("insertions", "deletions"),
    }
    for key in allowed_by_tool.get(result.tool_name, ()):
        value = output.get(key)
        if value is None or isinstance(value, (bool, int, float, str)):
            observation[key] = value
    if result.tool_name == "read_file":
        start = output.get("start_line")
        end = output.get("end_line")
        if isinstance(start, int) and isinstance(end, int) and end >= start:
            observation["lines_returned"] = end - start + 1
        content = output.get("content")
        if isinstance(content, str):
            observation["bytes_returned"] = len(content.encode("utf-8"))
    if result.tool_name == "apply_patch":
        affected = output.get("affected_files")
        if isinstance(affected, list):
            observation["affected_file_count"] = len(affected)
    if result.tool_name == "git_diff":
        modified = output.get("modified_files")
        if isinstance(modified, list):
            observation["modified_file_count"] = len(modified)
    return observation


def _repository_state(snapshot: RepositorySnapshot | None) -> RepositoryStateReport | None:
    if snapshot is None:
        return None
    return RepositoryStateReport(
        head_commit=snapshot.head_commit,
        index_sha256=snapshot.index_sha256,
        index_bytes=snapshot.index_bytes,
        git_status_sha256=snapshot.git_status_sha256,
        git_status_bytes=snapshot.git_status_bytes,
        content_sha256=snapshot.content_sha256,
    )


def _validate_budget_overrides(
    *,
    max_turns: int | None,
    max_tool_calls: int | None,
    max_patch_attempts: int | None,
    max_target_test_executions: int | None,
    max_regression_executions: int | None,
    max_wall_clock_seconds: int | None,
) -> str | None:
    for name, value, upper in (
        ("max_turns", max_turns, 50),
        ("max_tool_calls", max_tool_calls, 200),
        ("max_patch_attempts", max_patch_attempts, 10),
        ("max_target_test_executions", max_target_test_executions, 25),
        ("max_regression_executions", max_regression_executions, 10),
        ("max_wall_clock_seconds", max_wall_clock_seconds, 86_400),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper
        ):
            return f"{name} must be an integer between 1 and {upper}"
    return None


def _client_counter(
    client: LLMClient | None,
    attribute: str,
    *,
    fallback: int,
) -> int:
    if client is None:
        return fallback
    value = getattr(client, attribute, fallback)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return fallback
