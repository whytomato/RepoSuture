from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from reposuture.process import ProcessResult, ProcessRunner
from reposuture.reporting import FinalStatus, TestOutcome
from reposuture.runner import verify_case

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SOURCE = PROJECT_ROOT / "benchmarks/fixtures/null-email-repo"
GOLDEN_PATCH = PROJECT_ROOT / "benchmarks/fixtures/null-email-golden.patch"


def git(runner: ProcessRunner, repository: Path, *arguments: str) -> str:
    result = runner.run(
        ["git", *arguments],
        cwd=repository,
        timeout_seconds=30,
    )
    assert result.infrastructure_error is None, result.infrastructure_error
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def initialize_fixture_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "java-repository"
    shutil.copytree(
        FIXTURE_SOURCE,
        repository,
        ignore=shutil.ignore_patterns(".git", "target"),
    )
    runner = ProcessRunner()
    git(runner, repository, "init", "--quiet", "--initial-branch=main")
    git(runner, repository, "config", "core.autocrlf", "false")
    git(runner, repository, "config", "user.name", "RepoSuture Tests")
    git(runner, repository, "config", "user.email", "reposuture@example.invalid")
    git(runner, repository, "add", "--all")
    git(runner, repository, "update-index", "--chmod=+x", "mvnw")
    git(runner, repository, "commit", "--quiet", "-m", "fixture base")
    return repository, git(runner, repository, "rev-parse", "HEAD")


def repository_files(repository: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repository).as_posix(): path.read_bytes()
        for path in sorted(repository.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(repository).parts
    }


def write_case(
    case_path: Path,
    *,
    repository: Path,
    commit: str,
    golden_patch: Path = GOLDEN_PATCH,
    case_id: str = "null-email-integration",
) -> None:
    case_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": case_id,
                "repository": str(repository),
                "base_commit": commit,
                "issue_title": "Reject a null email",
                "issue_description": "Reject null email with a domain validation error.",
                "target_test": {
                    "class_name": "dev.patchpilot.fixture.UserRegistrationServiceTest",
                    "method_name": "shouldRejectNullEmail",
                },
                "target_test_timeout_seconds": 300,
                "regression_timeout_seconds": 300,
                "golden_patch": str(golden_patch),
                "expected_baseline_failure": "test_failure",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.integration
def test_real_java_case_is_resolved_without_modifying_original_repository(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    java = runner.run(["java", "-version"], cwd=tmp_path, timeout_seconds=10)
    if java.infrastructure_error is not None:
        pytest.skip(f"Java is unavailable: {java.infrastructure_error}")

    repository, commit = initialize_fixture_repository(tmp_path)
    original_files = repository_files(repository)
    original_status = git(runner, repository, "status", "--porcelain=v1")
    case_path = tmp_path / "null-email.yaml"
    write_case(case_path, repository=repository, commit=commit)

    report = verify_case(case_path, tmp_path / "artifacts")

    assert report.final_status is FinalStatus.RESOLVED, report.failure_reason
    assert report.baseline_test_result.outcome is TestOutcome.FAIL
    assert report.patched_target_test_result.outcome is TestOutcome.PASS
    assert report.regression_result.outcome is TestOutcome.PASS
    assert report.affected_files == [
        "src/main/java/dev/patchpilot/fixture/UserRegistrationService.java"
    ]
    assert report.modifies_tests is False
    assert report.modifies_build is False
    assert report.original_repository_before == report.original_repository_after
    assert report.original_repository_before is not None
    assert report.original_repository_before.head_commit == commit
    assert report.worktree_retained is False
    assert report.worktree_exists_at_report is False
    assert report.worktree_path is not None
    assert not report.worktree_path.exists()
    for artifact in report.artifacts.values():
        assert Path(artifact).is_file()
    assert Path(report.artifacts["final_patch"]).read_text(encoding="utf-8").startswith(
        "diff --git"
    )
    for name, metadata in report.artifact_metadata.items():
        artifact = Path(report.artifacts[name])
        content = artifact.read_bytes()
        assert metadata.path == artifact.resolve()
        assert metadata.size_bytes == len(content)
        assert metadata.sha256 == hashlib.sha256(content).hexdigest()
    report_payload = json.loads(Path(report.artifacts["report"]).read_text(encoding="utf-8"))
    assert report_payload["run_id"] == report.run_id
    assert report_payload["final_status"] == "RESOLVED"
    events = [
        json.loads(line)
        for line in Path(report.artifacts["trace"]).read_text(encoding="utf-8").splitlines()
    ]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert all(
        datetime.fromisoformat(event["timestamp"]).utcoffset() == UTC.utcoffset(None)
        for event in events
    )
    assert all(event["duration"] is None or event["duration"] >= 0 for event in events)
    assert json.loads(
        Path(report.artifacts["baseline_target_test_log"])
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )["outcome"] == "FAIL"
    assert json.loads(
        Path(report.artifacts["patched_target_test_log"])
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )["outcome"] == "PASS"
    assert json.loads(
        Path(report.artifacts["regression_test_log"])
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )["outcome"] == "PASS"
    assert repository_files(repository) == original_files
    assert git(runner, repository, "status", "--porcelain=v1") == original_status


@pytest.mark.integration
def test_real_regression_failure_unrelated_to_target_is_not_resolved(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    java = runner.run(["java", "-version"], cwd=tmp_path, timeout_seconds=10)
    if java.infrastructure_error is not None:
        pytest.skip(f"Java is unavailable: {java.infrastructure_error}")

    repository, _ = initialize_fixture_repository(tmp_path)
    unrelated_test = (
        repository
        / "src/test/java/dev/patchpilot/fixture/UnrelatedRegressionTest.java"
    )
    unrelated_test.write_text(
        """package dev.patchpilot.fixture;

import static org.junit.jupiter.api.Assertions.fail;
import org.junit.jupiter.api.Test;

class UnrelatedRegressionTest {
    @Test
    void unrelatedRegression() {
        fail("deliberate unrelated regression");
    }
}
""",
        encoding="utf-8",
    )
    git(runner, repository, "add", "--all")
    git(runner, repository, "commit", "--quiet", "-m", "add unrelated regression")
    commit = git(runner, repository, "rev-parse", "HEAD")
    original_files = repository_files(repository)
    original_status = git(runner, repository, "status", "--porcelain=v1")
    case_path = tmp_path / "regression-failure.yaml"
    write_case(
        case_path,
        repository=repository,
        commit=commit,
        case_id="unrelated-regression",
    )

    report = verify_case(case_path, tmp_path / "artifacts")

    assert report.final_status is FinalStatus.REGRESSION_FAILED
    assert report.baseline_test_result.outcome is TestOutcome.FAIL
    assert report.patched_target_test_result.outcome is TestOutcome.PASS
    assert report.regression_result.outcome is TestOutcome.FAIL
    assert report.failure_reason == "full Maven regression suite failed"
    assert repository_files(repository) == original_files
    assert git(runner, repository, "status", "--porcelain=v1") == original_status


class MutateGoldenPatchAfterBaselineRunner(ProcessRunner):
    def __init__(self, golden_patch: Path) -> None:
        super().__init__()
        self.golden_patch = golden_patch
        self.mutated = False

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        result = super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )
        if (
            not self.mutated
            and any(argument.startswith("-Dtest=") for argument in command)
        ):
            self.golden_patch.write_text("", encoding="utf-8")
            self.mutated = True
        return result


@pytest.mark.integration
def test_golden_patch_is_frozen_before_real_baseline_execution(tmp_path: Path) -> None:
    setup_runner = ProcessRunner()
    java = setup_runner.run(["java", "-version"], cwd=tmp_path, timeout_seconds=10)
    if java.infrastructure_error is not None:
        pytest.skip(f"Java is unavailable: {java.infrastructure_error}")

    repository, commit = initialize_fixture_repository(tmp_path)
    frozen_source = tmp_path / "golden.patch"
    frozen_source.write_bytes(GOLDEN_PATCH.read_bytes())
    case_path = tmp_path / "frozen.yaml"
    write_case(
        case_path,
        repository=repository,
        commit=commit,
        golden_patch=frozen_source,
        case_id="frozen-golden",
    )
    runner = MutateGoldenPatchAfterBaselineRunner(frozen_source)

    report = verify_case(
        case_path,
        tmp_path / "artifacts",
        process_runner=runner,
    )

    assert runner.mutated is True
    assert frozen_source.read_bytes() == b""
    assert report.final_status is FinalStatus.RESOLVED, report.failure_reason
    assert report.patch_sha256 == hashlib.sha256(GOLDEN_PATCH.read_bytes()).hexdigest()


@pytest.mark.integration
def test_keep_worktree_report_points_to_real_retained_worktree(tmp_path: Path) -> None:
    runner = ProcessRunner()
    java = runner.run(["java", "-version"], cwd=tmp_path, timeout_seconds=10)
    if java.infrastructure_error is not None:
        pytest.skip(f"Java is unavailable: {java.infrastructure_error}")

    repository, commit = initialize_fixture_repository(tmp_path)
    case_path = tmp_path / "keep.yaml"
    write_case(
        case_path,
        repository=repository,
        commit=commit,
        case_id="keep-worktree",
    )

    report = verify_case(case_path, tmp_path / "artifacts", keep_worktree=True)

    assert report.final_status is FinalStatus.RESOLVED, report.failure_reason
    assert report.keep_worktree_requested is True
    assert report.worktree_retained is True
    assert report.worktree_exists_at_report is True
    assert report.worktree_path is not None
    assert report.worktree_path.is_dir()
    git(
        runner,
        repository,
        "worktree",
        "remove",
        "--force",
        str(report.worktree_path),
    )
    assert not report.worktree_path.exists()
