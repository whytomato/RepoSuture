from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

import reposuture.maven as maven_module
from reposuture.case_spec import TargetTest
from reposuture.maven import MavenRunner
from reposuture.process import ProcessResult, ProcessRunner
from reposuture.reporting import TestOutcome


def process_result(tmp_path: Path, *, exit_code: int) -> ProcessResult:
    return ProcessResult(
        command=("mvnw", "test"),
        cwd=tmp_path,
        exit_code=exit_code,
        duration_seconds=0.5,
        stdout="",
        stderr="",
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_bytes_seen=0,
        stderr_bytes_seen=0,
    )


def test_target_command_is_structured_and_prefers_wrapper(tmp_path: Path) -> None:
    wrapper_name = "mvnw.cmd" if os.name == "nt" else "mvnw"
    wrapper = tmp_path / wrapper_name
    wrapper.write_text("", encoding="utf-8")
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")
    maven = MavenRunner(ProcessRunner())

    command = maven.target_command(tmp_path, target)

    assert command == [
        str(wrapper.resolve()),
        "-q",
        "-Dtest=com.example.ExampleTest#rejectsNull",
        "test",
    ]


def test_target_failure_requires_matching_surefire_failure(tmp_path: Path) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-com.example.ExampleTest.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite tests="1" failures="1" errors="0" skipped="0">
  <testcase name="rejectsNull" classname="com.example.ExampleTest">
    <failure message="expected domain exception"/>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")
    maven = MavenRunner(ProcessRunner())

    execution = maven.interpret_target_process(
        process_result(tmp_path, exit_code=1), tmp_path, target
    )

    assert execution.outcome is TestOutcome.FAIL
    assert execution.test_observed is True
    assert execution.infrastructure_error is None
    assert execution.tests_executed == 1
    assert execution.test_failures == 1
    assert execution.tests_skipped == 0
    assert execution.surefire_report_files == 1
    assert execution.target_found is True


def test_nonzero_maven_without_target_result_is_infrastructure_error(
    tmp_path: Path,
) -> None:
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")
    maven = MavenRunner(ProcessRunner())

    execution = maven.interpret_target_process(
        process_result(tmp_path, exit_code=1), tmp_path, target
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.test_observed is False
    assert execution.infrastructure_error is not None


def test_target_selector_does_not_match_same_simple_class_in_other_package(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-other.ExampleTest.xml").write_text(
        """<testsuite tests="1" failures="0" errors="0" skipped="0">
  <testcase name="rejectsNull" classname="other.ExampleTest"/>
</testsuite>
""",
        encoding="utf-8",
    )
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")
    maven = MavenRunner(ProcessRunner())

    execution = maven.interpret_target_process(
        process_result(tmp_path, exit_code=0), tmp_path, target
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.test_observed is False


def test_disabled_target_is_not_counted_as_executed(tmp_path: Path) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-com.example.ExampleTest.xml").write_text(
        """<testsuite tests="1" failures="0" errors="0" skipped="1">
  <testcase name="rejectsNull" classname="com.example.ExampleTest">
    <skipped message="disabled"/>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")

    execution = MavenRunner(ProcessRunner()).interpret_target_process(
        process_result(tmp_path, exit_code=0), tmp_path, target
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.test_observed is False
    assert execution.infrastructure_error is not None
    assert "skipped" in execution.infrastructure_error
    assert execution.tests_executed == 0
    assert execution.tests_skipped == 1
    assert execution.target_found is True


def test_compile_failure_is_infrastructure_not_baseline_failure(tmp_path: Path) -> None:
    process = process_result(tmp_path, exit_code=1)
    process = replace(
        process,
        stderr="[ERROR] COMPILATION ERROR",
        stderr_bytes_seen=len("[ERROR] COMPILATION ERROR"),
    )
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")

    execution = MavenRunner(ProcessRunner()).interpret_target_process(
        process, tmp_path, target
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.test_observed is False


def test_target_timeout_is_not_a_normal_failure(tmp_path: Path) -> None:
    process = ProcessResult(
        command=("mvn", "test"),
        cwd=tmp_path,
        exit_code=1,
        duration_seconds=1.0,
        stdout="",
        stderr="",
        timed_out=True,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_bytes_seen=0,
        stderr_bytes_seen=0,
    )
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")

    execution = MavenRunner(ProcessRunner()).interpret_target_process(
        process, tmp_path, target
    )

    assert execution.outcome is TestOutcome.TIMEOUT
    assert execution.test_observed is False


def test_regression_pass_requires_at_least_one_observed_test(tmp_path: Path) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-com.example.ExampleTest.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite tests="2" failures="0" errors="0" skipped="0">
  <testcase name="one" classname="com.example.ExampleTest"/>
  <testcase name="two" classname="com.example.ExampleTest"/>
</testsuite>
""",
        encoding="utf-8",
    )
    maven = MavenRunner(ProcessRunner())

    execution = maven.interpret_regression_process(
        process_result(tmp_path, exit_code=0), tmp_path
    )

    assert execution.outcome is TestOutcome.PASS
    assert execution.test_observed is True


def test_regression_maven_success_with_zero_tests_is_infrastructure_error(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-empty.xml").write_text(
        '<testsuite tests="0" failures="0" errors="0" skipped="0"/>\n',
        encoding="utf-8",
    )

    execution = MavenRunner(ProcessRunner()).interpret_regression_process(
        process_result(tmp_path, exit_code=0), tmp_path
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.test_observed is False


def test_regression_detects_failure_unrelated_to_target(tmp_path: Path) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-com.example.UnrelatedTest.xml").write_text(
        """<testsuite tests="1" failures="1" errors="0" skipped="0">
  <testcase name="unrelated" classname="com.example.UnrelatedTest">
    <failure message="regression"/>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    execution = MavenRunner(ProcessRunner()).interpret_regression_process(
        process_result(tmp_path, exit_code=1), tmp_path
    )

    assert execution.outcome is TestOutcome.FAIL
    assert execution.test_observed is True


def test_surefire_evidence_remains_bounded_by_total_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-bounded.xml").write_text(
        '<testsuite><testcase name="one" classname="example.Bounded"/></testsuite>',
        encoding="utf-8",
    )
    monkeypatch.setattr(maven_module, "MAX_SUREFIRE_TOTAL_BYTES", 16)

    execution = MavenRunner(ProcessRunner()).interpret_regression_process(
        process_result(tmp_path, exit_code=0), tmp_path
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.infrastructure_error == (
        "aggregate Surefire XML reports exceeded the configured size limit"
    )


def test_surefire_evidence_remains_bounded_per_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-bounded.xml").write_text(
        '<testsuite><testcase name="one" classname="example.Bounded"/></testsuite>',
        encoding="utf-8",
    )
    monkeypatch.setattr(maven_module, "MAX_SUREFIRE_REPORT_BYTES", 16)

    execution = MavenRunner(ProcessRunner()).interpret_regression_process(
        process_result(tmp_path, exit_code=0), tmp_path
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.infrastructure_error == (
        "an individual Surefire XML report exceeded the configured size limit"
    )


def test_default_surefire_total_limit_supports_large_bounded_suites() -> None:
    assert maven_module.MAX_SUREFIRE_REPORT_BYTES == 16 * 1024 * 1024
    assert maven_module.MAX_SUREFIRE_TOTAL_BYTES == 64 * 1024 * 1024
    assert maven_module.MAX_SUREFIRE_REPORT_FILES == 1_000


class AssertStaleReportsRemovedRunner(ProcessRunner):
    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        del timeout_seconds, input_bytes
        assert not (cwd / "target/surefire-reports").exists()
        return ProcessResult(
            command=tuple(command),
            cwd=cwd,
            exit_code=0,
            duration_seconds=0.01,
            stdout="",
            stderr="",
            timed_out=False,
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_bytes_seen=0,
            stderr_bytes_seen=0,
        )


def test_run_target_removes_stale_surefire_xml_before_process(tmp_path: Path) -> None:
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-com.example.ExampleTest.xml").write_text(
        """<testsuite tests="1" failures="0">
  <testcase name="rejectsNull" classname="com.example.ExampleTest"/>
</testsuite>
""",
        encoding="utf-8",
    )
    target = TargetTest(class_name="com.example.ExampleTest", method_name="rejectsNull")

    execution = MavenRunner(AssertStaleReportsRemovedRunner()).run_target(
        tmp_path, target, timeout_seconds=5
    )

    assert execution.outcome is TestOutcome.INFRASTRUCTURE_ERROR
    assert execution.test_observed is False
