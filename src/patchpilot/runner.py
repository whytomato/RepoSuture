"""Deterministic PatchPilot verification workflow orchestration."""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from patchpilot.case_spec import BugCase, CaseValidationError, load_case
from patchpilot.maven import MavenExecution, MavenInfrastructureError, MavenRunner
from patchpilot.patching import (
    PatchApplier,
    PatchDocument,
    PatchFormatError,
    PatchInfrastructureError,
    PatchInspection,
    PatchRejectedError,
    inspect_patch_document,
    load_patch_document,
)
from patchpilot.process import ProcessRunner
from patchpilot.reporting import (
    ArtifactPaths,
    Classification,
    FinalStatus,
    RepositoryStateReport,
    RunReport,
    TestOutcome,
    TestResultReport,
    TraceWriter,
    collect_artifact_metadata,
    create_artifact_paths,
    write_report,
)
from patchpilot.workspace import (
    GitWorktree,
    PathSecurityError,
    RepositorySnapshot,
    WorkspaceError,
    validate_artifacts_outside_git_root,
)

RUNNER_MAX_OUTPUT_BYTES = 10 * 1024 * 1024


def _infrastructure_test_result(detail: str) -> TestResultReport:
    return TestResultReport(
        outcome=TestOutcome.INFRASTRUCTURE_ERROR,
        infrastructure_error=detail,
    )


def _write_execution_log(path: Path, execution: MavenExecution) -> None:
    path.write_text(MavenRunner.format_log(execution), encoding="utf-8")


def _write_not_run_logs(artifacts: ArtifactPaths) -> None:
    for path in (
        artifacts.baseline_log,
        artifacts.patched_target_log,
        artifacts.regression_log,
    ):
        if path.stat().st_size == 0:
            path.write_text('{"outcome":"NOT_RUN"}\n', encoding="utf-8")


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


def verify_case(
    case_file: Path,
    artifacts_dir: Path,
    *,
    keep_worktree: bool = False,
    process_runner: ProcessRunner | None = None,
    run_id: str | None = None,
) -> RunReport:
    """Verify one Bug Case and persist a report for every classified outcome."""

    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    case: BugCase | None = None
    case_error: str | None = None
    try:
        case = load_case(case_file)
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
    trace = TraceWriter(artifacts.trace)
    trace.emit(
        "run_started",
        status="STARTED",
        metadata={
            "run_id": artifacts.run_id,
            "case_file_name": case_file.name,
            "keep_worktree": keep_worktree,
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
    initial_final_diff: str | None = None
    modifies_tests = False
    modifies_build = False
    modifies_maven_wrapper = False
    modifies_ci = False
    original_unchanged = False
    original_before: RepositoryStateReport | None = None
    original_after: RepositoryStateReport | None = None
    worktree_path: Path | None = None
    worktree_retained = False
    worktree_exists_at_report = False
    final_status = FinalStatus.INFRASTRUCTURE_ERROR
    failure_reason: str | None = "verification did not start"

    if case_error is not None:
        final_status = FinalStatus.INVALID_CASE
        failure_reason = case_error
        trace.emit("case_loaded", status="INVALID", metadata={"error": case_error})
    else:
        if case is None:
            raise RuntimeError("case loading reached an impossible state")
        trace.emit(
            "case_loaded",
            status="OK",
            metadata={"task_id": case.id, "schema_version": case.schema_version},
        )
        maven = MavenRunner(runner)
        patcher = PatchApplier(runner)
        patch_document: PatchDocument | None = None
        patch_document_error: str | None = None
        try:
            patch_document = load_patch_document(case.golden_patch)
            patch_size = len(patch_document.content)
            patch_sha256 = patch_document.sha256
            trace.emit(
                "patch_content_frozen",
                status="OK",
                metadata={
                    "patch_size": patch_size,
                    "patch_sha256": patch_sha256,
                },
            )
        except PatchFormatError as exc:
            patch_document_error = str(exc)
            trace.emit(
                "patch_content_frozen",
                status="REJECTED",
                metadata={"error": patch_document_error},
            )
        manager = GitWorktree(
            repository=case.repository,
            base_commit=case.base_commit,
            runner=runner,
            worktrees_root=Path(tempfile.gettempdir()) / "patchpilot-worktrees",
            keep=keep_worktree,
        )

        try:
            with manager as worktree:
                worktree_path = worktree
                trace.emit(
                    "worktree_created",
                    status="OK",
                    metadata={
                        "worktree_name": worktree.name,
                        "base_commit": case.base_commit,
                    },
                )

                try:
                    baseline_execution = maven.run_target(
                        worktree,
                        case.target_test,
                        timeout_seconds=case.target_test_timeout_seconds,
                    )
                    baseline = baseline_execution.as_report()
                    _write_execution_log(artifacts.baseline_log, baseline_execution)
                    trace.emit(
                        "baseline_target_test",
                        status=baseline.outcome.value,
                        duration=baseline.duration,
                        metadata={
                            "exit_code": baseline.exit_code,
                            "test_observed": baseline.test_observed,
                            "timed_out": baseline.timed_out,
                            "stdout_truncated": baseline.stdout_truncated,
                            "stderr_truncated": baseline.stderr_truncated,
                        },
                    )
                except MavenInfrastructureError as exc:
                    baseline = _infrastructure_test_result(str(exc))
                    artifacts.baseline_log.write_text(
                        f"infrastructure_error: {exc}\n", encoding="utf-8"
                    )
                    trace.emit(
                        "baseline_target_test",
                        status="INFRASTRUCTURE_ERROR",
                        metadata={"error": str(exc)},
                    )

                if baseline.outcome is TestOutcome.INFRASTRUCTURE_ERROR:
                    final_status = FinalStatus.INFRASTRUCTURE_ERROR
                    failure_reason = baseline.infrastructure_error or "baseline Maven failed"
                elif baseline.outcome is not TestOutcome.FAIL or not baseline.test_observed:
                    final_status = FinalStatus.BASELINE_NOT_REPRODUCED
                    failure_reason = (
                        "baseline target test timed out"
                        if baseline.outcome is TestOutcome.TIMEOUT
                        else "baseline target JUnit failure was not reproduced"
                    )
                else:
                    inspection: PatchInspection | None = None
                    try:
                        if patch_document_error is not None:
                            raise PatchFormatError(patch_document_error)
                        if patch_document is None:
                            raise PatchInfrastructureError(
                                "frozen patch content is unexpectedly unavailable"
                            )
                        inspection = inspect_patch_document(patch_document, worktree)
                        affected_files = list(inspection.affected_files)
                        classifications = {
                            path: classification.value
                            for path, classification in inspection.file_classifications.items()
                        }
                        patch_size = inspection.patch_size
                        patch_sha256 = inspection.patch_sha256
                        modifies_tests = inspection.modifies_tests
                        modifies_build = inspection.modifies_build
                        modifies_maven_wrapper = inspection.modifies_maven_wrapper
                        modifies_ci = inspection.modifies_ci
                        inspection = patcher.apply_document(patch_document, worktree)
                        affected_files = list(inspection.affected_files)
                        classifications = {
                            path: classification.value
                            for path, classification in inspection.file_classifications.items()
                        }
                        initial_final_diff = patcher.final_diff(worktree, inspection)
                        artifacts.final_patch.write_text(initial_final_diff, encoding="utf-8")
                        patch_applied = True
                        trace.emit(
                            "patch_applied",
                            status="OK",
                            metadata={
                                "affected_files": affected_files,
                                "patch_size": patch_size,
                                "patch_sha256": patch_sha256,
                                "modifies_tests": modifies_tests,
                                "modifies_build": modifies_build,
                                "modifies_maven_wrapper": modifies_maven_wrapper,
                                "modifies_ci": modifies_ci,
                            },
                        )
                    except (PatchFormatError, PatchRejectedError, PathSecurityError) as exc:
                        final_status = FinalStatus.PATCH_REJECTED
                        failure_reason = str(exc)
                        trace.emit(
                            "patch_applied",
                            status="REJECTED",
                            metadata={"error": str(exc)},
                        )
                    except PatchInfrastructureError as exc:
                        final_status = FinalStatus.INFRASTRUCTURE_ERROR
                        failure_reason = str(exc)
                        trace.emit(
                            "patch_applied",
                            status="INFRASTRUCTURE_ERROR",
                            metadata={"error": str(exc)},
                        )

                    if patch_applied:
                        try:
                            patched_execution = maven.run_target(
                                worktree,
                                case.target_test,
                                timeout_seconds=case.target_test_timeout_seconds,
                            )
                            patched_target = patched_execution.as_report()
                            _write_execution_log(
                                artifacts.patched_target_log, patched_execution
                            )
                            trace.emit(
                                "patched_target_test",
                                status=patched_target.outcome.value,
                                duration=patched_target.duration,
                                metadata={
                                    "exit_code": patched_target.exit_code,
                                    "test_observed": patched_target.test_observed,
                                    "timed_out": patched_target.timed_out,
                                    "stdout_truncated": patched_target.stdout_truncated,
                                    "stderr_truncated": patched_target.stderr_truncated,
                                },
                            )
                        except MavenInfrastructureError as exc:
                            patched_target = _infrastructure_test_result(str(exc))
                            artifacts.patched_target_log.write_text(
                                f"infrastructure_error: {exc}\n", encoding="utf-8"
                            )
                            trace.emit(
                                "patched_target_test",
                                status="INFRASTRUCTURE_ERROR",
                                metadata={"error": str(exc)},
                            )

                        if patched_target.outcome is TestOutcome.INFRASTRUCTURE_ERROR:
                            final_status = FinalStatus.INFRASTRUCTURE_ERROR
                            failure_reason = (
                                patched_target.infrastructure_error
                                or "patched target Maven failed"
                            )
                        elif patched_target.outcome is not TestOutcome.PASS:
                            final_status = FinalStatus.TARGET_TEST_FAILED
                            failure_reason = (
                                "patched target test timed out"
                                if patched_target.outcome is TestOutcome.TIMEOUT
                                else "target JUnit test still failed after applying the patch"
                            )
                        else:
                            try:
                                regression_execution = maven.run_regression(
                                    worktree,
                                    timeout_seconds=case.regression_timeout_seconds,
                                )
                                regression = regression_execution.as_report()
                                _write_execution_log(
                                    artifacts.regression_log, regression_execution
                                )
                                trace.emit(
                                    "regression_test",
                                    status=regression.outcome.value,
                                    duration=regression.duration,
                                    metadata={
                                        "exit_code": regression.exit_code,
                                        "test_observed": regression.test_observed,
                                        "timed_out": regression.timed_out,
                                        "stdout_truncated": regression.stdout_truncated,
                                        "stderr_truncated": regression.stderr_truncated,
                                    },
                                )
                            except MavenInfrastructureError as exc:
                                regression = _infrastructure_test_result(str(exc))
                                artifacts.regression_log.write_text(
                                    f"infrastructure_error: {exc}\n", encoding="utf-8"
                                )
                                trace.emit(
                                    "regression_test",
                                    status="INFRASTRUCTURE_ERROR",
                                    metadata={"error": str(exc)},
                                )

                            if regression.outcome is TestOutcome.INFRASTRUCTURE_ERROR:
                                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                                failure_reason = (
                                    regression.infrastructure_error
                                    or "regression Maven execution failed"
                                )
                            elif regression.outcome is not TestOutcome.PASS:
                                final_status = FinalStatus.REGRESSION_FAILED
                                failure_reason = (
                                    "regression test suite timed out"
                                    if regression.outcome is TestOutcome.TIMEOUT
                                    else "full Maven regression suite failed"
                                )
                            else:
                                final_status = FinalStatus.RESOLVED
                                failure_reason = None

                if patch_applied and inspection is not None:
                    try:
                        final_diff_after_tests = patcher.final_diff(worktree, inspection)
                        artifacts.final_patch.write_text(
                            final_diff_after_tests, encoding="utf-8"
                        )
                        if (
                            initial_final_diff is None
                            or final_diff_after_tests != initial_final_diff
                        ):
                            final_status = FinalStatus.INFRASTRUCTURE_ERROR
                            failure_reason = (
                                "worktree diff changed outside the verified patch during tests"
                            )
                            trace.emit(
                                "final_patch_verified",
                                status="CHANGED",
                                metadata={"error": failure_reason},
                            )
                        else:
                            trace.emit(
                                "final_patch_verified",
                                status="OK",
                                metadata={
                                    "patch_bytes": len(
                                        final_diff_after_tests.encode("utf-8")
                                    )
                                },
                            )
                    except (
                        PatchFormatError,
                        PatchRejectedError,
                        PatchInfrastructureError,
                        PathSecurityError,
                    ) as exc:
                        final_status = FinalStatus.INFRASTRUCTURE_ERROR
                        failure_reason = f"unable to verify final patch: {exc}"
                        trace.emit(
                            "final_patch_verified",
                            status="INFRASTRUCTURE_ERROR",
                            metadata={"error": str(exc)},
                        )

            original_unchanged = manager.original_unchanged is True
        except WorkspaceError as exc:
            original_unchanged = manager.original_unchanged is True
            final_status = FinalStatus.INFRASTRUCTURE_ERROR
            failure_reason = str(exc)
        except Exception as exc:
            original_unchanged = manager.original_unchanged is True
            final_status = FinalStatus.INFRASTRUCTURE_ERROR
            failure_reason = f"unexpected {type(exc).__name__}: {exc}"
            if manager.cleanup_error:
                failure_reason += f"; cleanup error: {manager.cleanup_error}"
            trace.emit(
                "workflow_failed",
                status="INFRASTRUCTURE_ERROR",
                metadata={"error_type": type(exc).__name__, "error": str(exc)},
            )

        original_before = _repository_state(manager.original_snapshot)
        original_after = _repository_state(manager.final_snapshot)
        worktree_exists_at_report = bool(
            worktree_path is not None and worktree_path.is_dir()
        )
        worktree_retained = bool(keep_worktree and worktree_exists_at_report)
        if final_status is FinalStatus.RESOLVED:
            cleanup_matches_request = (
                worktree_retained
                if keep_worktree
                else not worktree_exists_at_report and not manager.cleanup_error
            )
            if not cleanup_matches_request:
                final_status = FinalStatus.INFRASTRUCTURE_ERROR
                failure_reason = "worktree cleanup state did not match the requested policy"

        trace.emit(
            "worktree_finished",
            status=(
                "INFRASTRUCTURE_ERROR"
                if manager.cleanup_error
                else "KEPT"
                if worktree_retained
                else "CLEANED"
                if worktree_path is not None and not worktree_exists_at_report
                else "NOT_CREATED"
            ),
            metadata={
                "original_repository_unchanged": original_unchanged,
                "worktree_retained": worktree_retained,
                "worktree_exists": worktree_exists_at_report,
                "cleanup_error": manager.cleanup_error,
            },
        )

        if final_status is FinalStatus.RESOLVED and not original_unchanged:
            final_status = FinalStatus.INFRASTRUCTURE_ERROR
            failure_reason = "original repository unchanged check did not pass"

    _write_not_run_logs(artifacts)
    ended_at = datetime.now(UTC)
    total_duration = time.monotonic() - started_monotonic
    trace.emit(
        "run_finished",
        status=final_status.value,
        duration=total_duration,
        metadata={"failure_reason": failure_reason},
    )
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
        failure_reason=failure_reason,
        artifacts=artifacts.as_report_mapping(),
        artifact_metadata=artifact_metadata,
        target_test_execution_count=sum(
            result.outcome is not TestOutcome.NOT_RUN for result in (baseline, patched_target)
        ),
        regression_execution_count=int(regression.outcome is not TestOutcome.NOT_RUN),
        test_execution_duration_seconds=(
            baseline.duration + patched_target.duration + regression.duration
        ),
    )
    write_report(report, artifacts.report)
    return report
