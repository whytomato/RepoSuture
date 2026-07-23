from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from reposuture.process import ProcessResult, ProcessRunner
from reposuture.reporting import FinalStatus, TestOutcome
from reposuture.runner import verify_case
from reposuture.workspace import ArtifactContainmentError


def run_git(runner: ProcessRunner, repository: Path, *arguments: str) -> str:
    result = runner.run(["git", *arguments], cwd=repository, timeout_seconds=10)
    assert result.infrastructure_error is None, result.infrastructure_error
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def create_case(tmp_path: Path) -> tuple[Path, Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = ProcessRunner()
    run_git(runner, repository, "init", "--quiet")
    run_git(runner, repository, "config", "user.name", "RepoSuture Tests")
    run_git(runner, repository, "config", "user.email", "reposuture@example.invalid")
    source = repository / "src/main/java/App.java"
    source.parent.mkdir(parents=True)
    source.write_text("old\n", encoding="utf-8")
    run_git(runner, repository, "add", "--all")
    run_git(runner, repository, "commit", "--quiet", "-m", "base")
    commit = run_git(runner, repository, "rev-parse", "HEAD")
    patch = tmp_path / "golden.patch"
    patch.write_text(
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )
    case_file = tmp_path / "case.yaml"
    case_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "unexpected-process-error",
                "repository": str(repository),
                "base_commit": commit,
                "issue_title": "Unexpected process error",
                "issue_description": "Exercise cleanup when process execution raises.",
                "target_test": {
                    "class_name": "example.AppTest",
                    "method_name": "fails",
                },
                "target_test_timeout_seconds": 30,
                "regression_timeout_seconds": 30,
                "golden_patch": str(patch),
                "expected_baseline_failure": "test_failure",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return case_file, repository, commit


class RaiseOnMavenRunner(ProcessRunner):
    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        if command[0] == "mvn" or Path(command[0]).name.lower() in {"mvnw", "mvnw.cmd"}:
            raise RuntimeError("deliberate process boundary failure")
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


def test_unexpected_workflow_exception_cleans_real_worktree_and_reports_failure(
    tmp_path: Path,
) -> None:
    case_file, repository, commit = create_case(tmp_path)
    status_before = run_git(ProcessRunner(), repository, "status", "--porcelain=v1")

    report = verify_case(
        case_file,
        tmp_path / "artifacts",
        process_runner=RaiseOnMavenRunner(),
    )

    assert report.final_status is FinalStatus.INFRASTRUCTURE_ERROR
    assert report.baseline_test_result.outcome is TestOutcome.NOT_RUN
    assert "deliberate process boundary failure" in (report.failure_reason or "")
    assert report.worktree_path is not None
    assert not report.worktree_path.exists()
    assert report.worktree_exists_at_report is False
    assert report.worktree_retained is False
    assert report.original_repository_unchanged is True
    assert report.original_repository_before == report.original_repository_after
    assert report.original_repository_before is not None
    assert report.original_repository_before.head_commit == commit
    assert run_git(ProcessRunner(), repository, "status", "--porcelain=v1") == status_before
    payload = json.loads(Path(report.artifacts["report"]).read_text(encoding="utf-8"))
    assert payload["final_status"] == "INFRASTRUCTURE_ERROR"


def test_artifacts_inside_original_repository_are_rejected_without_writing_there(
    tmp_path: Path,
) -> None:
    case_file, repository, _ = create_case(tmp_path)
    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    payload["repository"] = str(repository / "src/main")
    case_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    requested = repository / "artifacts"
    status_before = run_git(ProcessRunner(), repository, "status", "--porcelain=v1")
    files_before = {
        path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()
    }

    with pytest.raises(
        ArtifactContainmentError,
        match="outside the canonical Git repository root",
    ):
        verify_case(case_file, requested)

    assert not requested.exists()
    assert {
        path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()
    } == files_before
    assert run_git(ProcessRunner(), repository, "status", "--porcelain=v1") == status_before


def test_case_repository_subdirectory_uses_git_root_and_allows_external_artifacts(
    tmp_path: Path,
) -> None:
    case_file, repository, _ = create_case(tmp_path)
    payload = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    payload["repository"] = str(repository / "src/main")
    case_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = verify_case(
        case_file,
        tmp_path / "external-artifacts",
        process_runner=RaiseOnMavenRunner(),
    )

    assert report.final_status is FinalStatus.INFRASTRUCTURE_ERROR
    assert report.original_repository == repository.resolve()
    assert Path(report.artifacts["report"]).is_file()
    assert run_git(ProcessRunner(), repository, "status", "--porcelain=v1") == ""
