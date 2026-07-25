"""Maven/JUnit execution with Surefire evidence as the test-result authority."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from reposuture.case_spec import TargetTest
from reposuture.process import ProcessResult, ProcessRunner
from reposuture.reporting import TestOutcome, TestResultReport
from reposuture.workspace import PathSecurityError, safe_worktree_path

MAX_SUREFIRE_REPORT_BYTES = 16 * 1024 * 1024
# Large established projects can emit hundreds of bounded reports with repeated JVM
# properties. Keep each report and the aggregate strictly bounded while admitting the
# observed Apache Commons suites (over 40,000 real JUnit executions). The measured
# Commons Lang evidence is 313 files / 14.97 MiB total / 5.94 MiB maximum.
MAX_SUREFIRE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SUREFIRE_REPORT_FILES = 1_000
WINDOWS = os.name == "nt"


class MavenInfrastructureError(RuntimeError):
    """Raised when Maven or its test evidence cannot be used safely."""


@dataclass(frozen=True, slots=True)
class MavenExecution:
    process: ProcessResult
    outcome: TestOutcome
    test_observed: bool
    infrastructure_error: str | None = None
    tests_executed: int = 0
    test_failures: int = 0
    tests_skipped: int = 0
    surefire_report_files: int = 0
    target_found: bool = False
    compilation_failed: bool = False

    def as_report(self) -> TestResultReport:
        return TestResultReport(
            outcome=self.outcome,
            command=list(self.process.command),
            exit_code=self.process.exit_code,
            duration=self.process.duration_seconds,
            timed_out=self.process.timed_out,
            test_observed=self.test_observed,
            stdout_truncated=self.process.stdout_truncated,
            stderr_truncated=self.process.stderr_truncated,
            stdout_bytes_seen=self.process.stdout_bytes_seen,
            stderr_bytes_seen=self.process.stderr_bytes_seen,
            stdout_sha256=self.process.stdout_sha256,
            stderr_sha256=self.process.stderr_sha256,
            tests_executed=self.tests_executed,
            test_failures=self.test_failures,
            tests_skipped=self.tests_skipped,
            surefire_report_files=self.surefire_report_files,
            target_found=self.target_found,
            compilation_failed=self.compilation_failed,
            infrastructure_error=self.infrastructure_error,
        )


@dataclass(frozen=True, slots=True)
class _SurefireEvidence:
    executed: int
    failures: int
    target_found: bool
    target_executed: bool
    target_failed: bool
    error: str | None = None
    skipped: int = 0
    report_files: int = 0
    missing_required_targets: tuple[str, ...] = ()


class MavenRunner:
    """Run structured Maven goals and interpret JUnit results from Surefire XML."""

    def __init__(self, runner: ProcessRunner) -> None:
        self.runner = runner

    def target_command(self, worktree: Path, target: TargetTest) -> list[str]:
        return [
            self._maven_executable(worktree),
            "-q",
            f"-Dtest={target.maven_selector}",
            "test",
        ]

    def regression_command(
        self,
        worktree: Path,
        regression_tests: tuple[TargetTest, ...] | None = None,
    ) -> list[str]:
        command = [self._maven_executable(worktree), "-q"]
        if regression_tests is not None:
            selectors = ",".join(test.maven_selector for test in regression_tests)
            command.append(f"-Dtest={selectors}")
        return [*command, "test"]

    def run_target(
        self,
        worktree: Path,
        target: TargetTest,
        *,
        timeout_seconds: float,
        candidate_patch_applied: bool = False,
    ) -> MavenExecution:
        self._clear_surefire_reports(worktree)
        with self._execution_command(
            worktree,
            ["-q", f"-Dtest={target.maven_selector}", "test"],
        ) as command:
            process = self.runner.run(
                command,
                cwd=worktree,
                timeout_seconds=timeout_seconds,
            )
        return self.interpret_target_process(
            process,
            worktree,
            target,
            candidate_patch_applied=candidate_patch_applied,
        )

    def run_regression(
        self,
        worktree: Path,
        regression_tests: tuple[TargetTest, ...] | None = None,
        *,
        timeout_seconds: float,
        candidate_patch_applied: bool = False,
    ) -> MavenExecution:
        self._clear_surefire_reports(worktree)
        arguments = ["-q"]
        if regression_tests is not None:
            selectors = ",".join(test.maven_selector for test in regression_tests)
            arguments.append(f"-Dtest={selectors}")
        arguments.append("test")
        with self._execution_command(worktree, arguments) as command:
            process = self.runner.run(
                command,
                cwd=worktree,
                timeout_seconds=timeout_seconds,
            )
        return self.interpret_regression_process(
            process,
            worktree,
            regression_tests,
            candidate_patch_applied=candidate_patch_applied,
        )

    def interpret_target_process(
        self,
        process: ProcessResult,
        worktree: Path,
        target: TargetTest,
        *,
        candidate_patch_applied: bool = False,
    ) -> MavenExecution:
        terminal = self._terminal_process_outcome(process)
        if terminal is not None:
            return terminal

        evidence = self._read_surefire_evidence(worktree, target)
        if evidence.error is not None:
            return self._infrastructure(process, evidence.error, evidence)
        if process.exit_code == 0 and evidence.target_executed and not evidence.target_failed:
            return self._with_evidence(process, TestOutcome.PASS, evidence)
        if process.exit_code != 0 and evidence.target_executed and evidence.target_failed:
            return self._with_evidence(process, TestOutcome.FAIL, evidence)
        if (
            candidate_patch_applied
            and process.exit_code != 0
            and self._is_compilation_failure(process)
        ):
            return self._candidate_compilation_failure(process)

        if evidence.target_found and not evidence.target_executed:
            detail = "target JUnit test was skipped rather than executed"
        elif not evidence.target_found:
            detail = "matching target JUnit result was not found in Surefire reports"
        else:
            detail = "Maven exit code and target JUnit result were inconsistent"
        return self._infrastructure(process, detail, evidence)

    def interpret_regression_process(
        self,
        process: ProcessResult,
        worktree: Path,
        regression_tests: tuple[TargetTest, ...] | None = None,
        *,
        candidate_patch_applied: bool = False,
    ) -> MavenExecution:
        terminal = self._terminal_process_outcome(process)
        if terminal is not None:
            return terminal

        evidence = self._read_surefire_evidence(
            worktree,
            target=None,
            required_targets=regression_tests or (),
        )
        if evidence.error is not None:
            return self._infrastructure(process, evidence.error, evidence)
        if evidence.missing_required_targets:
            return self._infrastructure(
                process,
                "selected regression JUnit tests were not executed: "
                + ", ".join(evidence.missing_required_targets),
                evidence,
            )
        if process.exit_code == 0 and evidence.executed > 0 and evidence.failures == 0:
            return self._with_evidence(process, TestOutcome.PASS, evidence)
        if process.exit_code != 0 and evidence.executed > 0 and evidence.failures > 0:
            return self._with_evidence(process, TestOutcome.FAIL, evidence)
        if (
            candidate_patch_applied
            and process.exit_code != 0
            and self._is_compilation_failure(process)
        ):
            return self._candidate_compilation_failure(process)
        if evidence.executed == 0:
            detail = "no executed JUnit tests were found in Surefire reports"
        else:
            detail = "Maven exit code and regression JUnit results were inconsistent"
        return self._infrastructure(process, detail, evidence)

    @staticmethod
    def format_log(execution: MavenExecution) -> str:
        process = execution.process
        header = {
            "command": list(process.command),
            "cwd": str(process.cwd),
            "exit_code": process.exit_code,
            "duration": process.duration_seconds,
            "timed_out": process.timed_out,
            "outcome": execution.outcome.value,
            "test_observed": execution.test_observed,
            "stdout_truncated": process.stdout_truncated,
            "stderr_truncated": process.stderr_truncated,
            "infrastructure_error": execution.infrastructure_error,
            "tests_executed": execution.tests_executed,
            "test_failures": execution.test_failures,
            "tests_skipped": execution.tests_skipped,
            "surefire_report_files": execution.surefire_report_files,
            "target_found": execution.target_found,
            "compilation_failed": execution.compilation_failed,
        }
        return (
            json.dumps(header, ensure_ascii=False, sort_keys=True)
            + "\n\n[stdout]\n"
            + process.stdout
            + "\n\n[stderr]\n"
            + process.stderr
            + "\n"
        )

    def _maven_executable(self, worktree: Path) -> str:
        wrapper_name = "mvnw.cmd" if WINDOWS else "mvnw"
        wrapper_candidate = worktree / wrapper_name
        if wrapper_candidate.exists() or wrapper_candidate.is_symlink():
            try:
                wrapper = safe_worktree_path(worktree, wrapper_name)
            except PathSecurityError as exc:
                raise MavenInfrastructureError(f"unsafe Maven Wrapper path: {exc}") from exc
            if not wrapper.is_file():
                raise MavenInfrastructureError(f"Maven Wrapper is not a file: {wrapper}")
            return str(wrapper)
        return "mvn"

    @contextmanager
    def _execution_command(
        self,
        worktree: Path,
        arguments: Sequence[str],
    ) -> Iterator[list[str]]:
        executable = self._maven_executable(worktree)
        if WINDOWS or executable == "mvn":
            yield [executable, *arguments]
            return

        wrapper = Path(executable)
        try:
            raw_wrapper = wrapper.read_bytes()
        except OSError as exc:
            raise MavenInfrastructureError(
                f"unable to read Maven Wrapper: {wrapper}: {exc}"
            ) from exc
        normalized_wrapper = raw_wrapper.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if normalized_wrapper == raw_wrapper:
            yield [executable, *arguments]
            return
        if b"\x00" in raw_wrapper:
            raise MavenInfrastructureError("Maven Wrapper contains a NUL byte")

        launcher_root: Path | None = None
        launcher: Path | None = None
        try:
            launcher_root = Path(
                tempfile.mkdtemp(
                    prefix=".reposuture-maven-wrapper-",
                    dir=worktree,
                )
            )
            safe_root = safe_worktree_path(worktree, launcher_root.name)
            if launcher_root.resolve(strict=True) != safe_root:
                raise MavenInfrastructureError(
                    "temporary Maven Wrapper directory escaped the worktree"
                )
            source_maven_config = safe_worktree_path(worktree, ".mvn")
            if not source_maven_config.is_dir():
                raise MavenInfrastructureError(
                    "Maven Wrapper configuration directory is unavailable"
                )
            linked_maven_config = launcher_root / ".mvn"
            linked_maven_config.symlink_to(
                source_maven_config,
                target_is_directory=True,
            )
            safe_link = safe_worktree_path(
                worktree,
                Path(launcher_root.name) / ".mvn",
            )
            if safe_link != source_maven_config:
                raise MavenInfrastructureError(
                    "temporary Maven Wrapper configuration link is unsafe"
                )
            launcher = launcher_root / "mvnw"
            launcher.write_bytes(normalized_wrapper)
            safe_launcher = safe_worktree_path(
                worktree,
                Path(launcher_root.name) / "mvnw",
            )
            if launcher.resolve(strict=True) != safe_launcher:
                raise MavenInfrastructureError(
                    "temporary Maven Wrapper launcher escaped the worktree"
                )
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
            yield [str(launcher), *arguments]
        except OSError as exc:
            raise MavenInfrastructureError(
                f"unable to prepare compatible Maven Wrapper launcher: {exc}"
            ) from exc
        finally:
            if launcher_root is not None:
                try:
                    safe_root = safe_worktree_path(worktree, launcher_root.name)
                    if launcher_root.resolve(strict=True) != safe_root:
                        raise MavenInfrastructureError(
                            "temporary Maven Wrapper cleanup path is unsafe"
                        )
                    shutil.rmtree(launcher_root)
                except OSError as exc:
                    raise MavenInfrastructureError(
                        f"unable to remove temporary Maven Wrapper directory: {exc}"
                    ) from exc

    @staticmethod
    def _terminal_process_outcome(process: ProcessResult) -> MavenExecution | None:
        if process.infrastructure_error is not None:
            return MavenExecution(
                process,
                TestOutcome.INFRASTRUCTURE_ERROR,
                test_observed=False,
                infrastructure_error=process.infrastructure_error,
            )
        if process.timed_out:
            return MavenExecution(
                process,
                TestOutcome.TIMEOUT,
                test_observed=False,
            )
        return None

    @staticmethod
    def _infrastructure(
        process: ProcessResult,
        detail: str,
        evidence: _SurefireEvidence | None = None,
    ) -> MavenExecution:
        if evidence is None:
            return MavenExecution(
                process,
                TestOutcome.INFRASTRUCTURE_ERROR,
                test_observed=False,
                infrastructure_error=detail,
            )
        return MavenExecution(
            process,
            TestOutcome.INFRASTRUCTURE_ERROR,
            test_observed=False,
            infrastructure_error=detail,
            tests_executed=evidence.executed,
            test_failures=evidence.failures,
            tests_skipped=evidence.skipped,
            surefire_report_files=evidence.report_files,
            target_found=evidence.target_found,
        )

    @staticmethod
    def _with_evidence(
        process: ProcessResult,
        outcome: TestOutcome,
        evidence: _SurefireEvidence,
    ) -> MavenExecution:
        return MavenExecution(
            process,
            outcome,
            test_observed=True,
            tests_executed=evidence.executed,
            test_failures=evidence.failures,
            tests_skipped=evidence.skipped,
            surefire_report_files=evidence.report_files,
            target_found=evidence.target_found,
        )

    @staticmethod
    def _candidate_compilation_failure(process: ProcessResult) -> MavenExecution:
        return MavenExecution(
            process,
            TestOutcome.COMPILATION_FAILED,
            test_observed=False,
            compilation_failed=True,
        )

    @staticmethod
    def _is_compilation_failure(process: ProcessResult) -> bool:
        diagnostic = f"{process.stdout}\n{process.stderr}".casefold()
        return any(
            marker in diagnostic
            for marker in (
                "compilation error",
                "compilation failure",
                "compilation failed",
            )
        )

    def _clear_surefire_reports(self, worktree: Path) -> None:
        try:
            reports = safe_worktree_path(worktree, "target/surefire-reports")
            if reports.is_symlink():
                raise MavenInfrastructureError(
                    f"refusing to remove symlinked Surefire report directory: {reports}"
                )
            if reports.exists():
                shutil.rmtree(reports)
        except (OSError, PathSecurityError) as exc:
            raise MavenInfrastructureError(f"unable to clear Surefire reports: {exc}") from exc

    def _read_surefire_evidence(
        self,
        worktree: Path,
        target: TargetTest | None,
        required_targets: tuple[TargetTest, ...] = (),
    ) -> _SurefireEvidence:
        try:
            reports = safe_worktree_path(worktree, "target/surefire-reports")
        except PathSecurityError as exc:
            return _SurefireEvidence(0, 0, False, False, False, str(exc))
        if not reports.is_dir():
            return _SurefireEvidence(0, 0, False, False, False)

        executed = 0
        failures = 0
        target_found = False
        target_executed = False
        target_failed = False
        skipped_count = 0
        required_executed = {
            required.maven_selector: False for required in required_targets
        }
        total_size = 0
        report_files: list[Path] = []
        try:
            for report_file in reports.glob("TEST-*.xml"):
                report_files.append(report_file)
                if len(report_files) > MAX_SUREFIRE_REPORT_FILES:
                    return _SurefireEvidence(
                        executed,
                        failures,
                        target_found,
                        target_executed,
                        target_failed,
                        "Surefire XML report count exceeded the configured limit",
                        skipped_count,
                        len(report_files),
                    )
            report_files.sort()
            for report_file in report_files:
                safe_report = safe_worktree_path(
                    worktree, report_file.relative_to(worktree)
                )
                size = safe_report.stat().st_size
                total_size += size
                if size > MAX_SUREFIRE_REPORT_BYTES:
                    return _SurefireEvidence(
                        executed,
                        failures,
                        target_found,
                        target_executed,
                        target_failed,
                        "an individual Surefire XML report exceeded the configured "
                        "size limit",
                        skipped_count,
                        len(report_files),
                    )
                if total_size > MAX_SUREFIRE_TOTAL_BYTES:
                    return _SurefireEvidence(
                        executed,
                        failures,
                        target_found,
                        target_executed,
                        target_failed,
                        "aggregate Surefire XML reports exceeded the configured "
                        "size limit",
                        skipped_count,
                        len(report_files),
                    )
                root = ElementTree.parse(safe_report).getroot()
                for testcase in root.iter():
                    if testcase.tag.rsplit("}", maxsplit=1)[-1] != "testcase":
                        continue
                    skipped = any(
                        child.tag.rsplit("}", maxsplit=1)[-1] == "skipped"
                        for child in testcase
                    )
                    failed = any(
                        child.tag.rsplit("}", maxsplit=1)[-1] in {"failure", "error"}
                        for child in testcase
                    )
                    if not skipped:
                        executed += 1
                    else:
                        skipped_count += 1
                    if failed:
                        failures += 1
                    if target is not None and self._matches_target(testcase.attrib, target):
                        target_found = True
                        target_executed = not skipped
                        target_failed = failed
                    for required in required_targets:
                        if self._matches_target(testcase.attrib, required) and not skipped:
                            required_executed[required.maven_selector] = True
        except (OSError, ElementTree.ParseError, PathSecurityError) as exc:
            return _SurefireEvidence(
                executed,
                failures,
                target_found,
                target_executed,
                target_failed,
                f"unable to read Surefire XML evidence: {type(exc).__name__}: {exc}",
                skipped_count,
                len(report_files),
            )
        return _SurefireEvidence(
            executed,
            failures,
            target_found,
            target_executed,
            target_failed,
            skipped=skipped_count,
            report_files=len(report_files),
            missing_required_targets=tuple(
                selector
                for selector, executed_target in required_executed.items()
                if not executed_target
            ),
        )

    @staticmethod
    def _matches_target(attributes: dict[str, str], target: TargetTest) -> bool:
        class_name = attributes.get("classname", "")
        method_name = attributes.get("name", "")
        expected_class = target.class_name
        class_matches = (
            class_name == expected_class
            if "." in expected_class
            else class_name.rsplit(".", maxsplit=1)[-1] == expected_class
        )
        return class_matches and method_name == target.method_name
