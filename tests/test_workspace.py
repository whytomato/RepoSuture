from __future__ import annotations

import os
from pathlib import Path

import pytest

from reposuture.process import ProcessResult, ProcessRunner
from reposuture.workspace import (
    ArtifactContainmentError,
    GitWorktree,
    OriginalRepositoryChangedError,
    WorkspaceError,
    canonical_git_root,
    validate_artifacts_outside_git_root,
)


def run_git(runner: ProcessRunner, repo: Path, *arguments: str) -> str:
    result = runner.run(
        ["git", *arguments],
        cwd=repo,
        timeout_seconds=10,
    )
    assert result.infrastructure_error is None, result.infrastructure_error
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def create_repository(tmp_path: Path, runner: ProcessRunner) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    run_git(runner, repository, "init", "--quiet")
    run_git(runner, repository, "config", "user.name", "RepoSuture Tests")
    run_git(runner, repository, "config", "user.email", "reposuture@example.invalid")
    (repository / "source.txt").write_text("original\n", encoding="utf-8")
    run_git(runner, repository, "add", "source.txt")
    run_git(runner, repository, "commit", "--quiet", "-m", "base")
    commit = run_git(runner, repository, "rev-parse", "HEAD")
    return repository, commit


def create_directory_link(
    link: Path,
    target: Path,
    *,
    runner: ProcessRunner,
    cwd: Path,
) -> None:
    if os.name == "nt":
        result = runner.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            cwd=cwd,
            timeout_seconds=10,
        )
        assert result.succeeded, result.infrastructure_error or result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


def test_canonical_git_root_accepts_configured_repository_subdirectory(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    repository, _ = create_repository(tmp_path, runner)
    subdirectory = repository / "backend"
    subdirectory.mkdir()

    assert canonical_git_root(subdirectory, runner) == repository.resolve()
    assert (
        validate_artifacts_outside_git_root(
            subdirectory,
            tmp_path / "external-artifacts",
            runner,
        )
        == repository.resolve()
    )


@pytest.mark.parametrize("relative", [Path("."), Path("artifacts"), Path("nested/output")])
def test_artifacts_at_or_beneath_canonical_git_root_are_rejected(
    tmp_path: Path,
    relative: Path,
) -> None:
    runner = ProcessRunner()
    repository, _ = create_repository(tmp_path, runner)

    with pytest.raises(ArtifactContainmentError, match="canonical Git repository root"):
        validate_artifacts_outside_git_root(
            repository / ".",
            repository / relative,
            runner,
        )


def test_artifact_containment_normalizes_parent_segments_and_windows_case(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    repository, _ = create_repository(tmp_path, runner)
    if os.name == "nt":
        requested = Path(str(repository).swapcase()) / "nested" / "artifacts"
    else:
        requested = repository / "nested" / ".." / "artifacts"

    with pytest.raises(ArtifactContainmentError):
        validate_artifacts_outside_git_root(repository, requested, runner)


def test_artifact_containment_rejects_lexical_and_resolved_link_escapes(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    repository, _ = create_repository(tmp_path, runner)
    outside = tmp_path / "outside"
    outside.mkdir()
    link_to_repository = outside / "repository-link"
    link_from_repository = repository / "outside-link"
    create_directory_link(
        link_to_repository,
        repository,
        runner=runner,
        cwd=tmp_path,
    )
    create_directory_link(
        link_from_repository,
        outside,
        runner=runner,
        cwd=tmp_path,
    )

    with pytest.raises(ArtifactContainmentError):
        validate_artifacts_outside_git_root(
            repository,
            link_to_repository / "artifacts",
            runner,
        )
    with pytest.raises(ArtifactContainmentError):
        validate_artifacts_outside_git_root(
            repository,
            link_from_repository / "artifacts",
            runner,
        )


def test_git_worktree_is_created_and_cleaned(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    original_status = run_git(runner, repository, "status", "--porcelain=v1")
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with manager as worktree:
        created_path = worktree
        assert created_path.is_dir()
        assert (created_path / "source.txt").read_text(encoding="utf-8") == "original\n"
        (created_path / "source.txt").write_text("changed only in worktree\n", encoding="utf-8")

    assert not created_path.exists()
    assert manager.original_unchanged is True
    assert (repository / "source.txt").read_text(encoding="utf-8") == "original\n"
    assert run_git(runner, repository, "status", "--porcelain=v1") == original_status


def test_git_worktree_is_cleaned_when_body_raises(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with pytest.raises(RuntimeError, match="deliberate failure"), manager as worktree:
        created_path = worktree
        raise RuntimeError("deliberate failure")

    assert not created_path.exists()
    assert manager.original_unchanged is True


def test_git_worktree_preserves_preexisting_dirty_original(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    (repository / "source.txt").write_text("user's dirty change\n", encoding="utf-8")
    dirty_status = run_git(runner, repository, "status", "--porcelain=v1")
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with manager as worktree:
        assert (worktree / "source.txt").read_text(encoding="utf-8") == "original\n"

    assert (repository / "source.txt").read_text(encoding="utf-8") == (
        "user's dirty change\n"
    )
    assert run_git(runner, repository, "status", "--porcelain=v1") == dirty_status
    assert manager.original_unchanged is True


def test_git_worktree_preserves_preexisting_staged_original(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    (repository / "source.txt").write_text("user's staged change\n", encoding="utf-8")
    run_git(runner, repository, "add", "source.txt")
    staged_before = run_git(runner, repository, "diff", "--cached", "--binary")
    status_before = run_git(runner, repository, "status", "--porcelain=v1")
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with manager as worktree:
        assert (worktree / "source.txt").read_text(encoding="utf-8") == "original\n"

    assert run_git(runner, repository, "diff", "--cached", "--binary") == staged_before
    assert run_git(runner, repository, "status", "--porcelain=v1") == status_before
    assert manager.original_unchanged is True


def test_git_worktree_preserves_preexisting_untracked_original(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    untracked = repository / "user-notes.txt"
    untracked.write_text("do not remove\n", encoding="utf-8")
    status_before = run_git(runner, repository, "status", "--porcelain=v1")
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with manager:
        pass

    assert untracked.read_text(encoding="utf-8") == "do not remove\n"
    assert run_git(runner, repository, "status", "--porcelain=v1") == status_before
    assert manager.original_unchanged is True


def test_original_head_change_with_identical_tree_is_detected(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, base_commit = create_repository(tmp_path, runner)
    run_git(runner, repository, "commit", "--allow-empty", "--quiet", "-m", "same tree")
    other_commit = run_git(runner, repository, "rev-parse", "HEAD")
    run_git(runner, repository, "reset", "--hard", "--quiet", base_commit)
    manager = GitWorktree(
        repository=repository,
        base_commit=base_commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with pytest.raises(OriginalRepositoryChangedError), manager:
        run_git(runner, repository, "reset", "--hard", "--quiet", other_commit)

    assert manager.original_unchanged is False


def test_original_index_flag_change_is_detected_even_when_status_is_clean(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with pytest.raises(OriginalRepositoryChangedError), manager:
        run_git(runner, repository, "update-index", "--assume-unchanged", "source.txt")
        assert run_git(runner, repository, "status", "--porcelain=v1") == ""

    assert manager.original_unchanged is False


def test_two_worktrees_for_same_case_are_unique_and_independent(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    first = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )
    second = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with first as first_path:
        with second as second_path:
            assert first_path != second_path
            assert first_path.is_dir()
            assert second_path.is_dir()
            (first_path / "source.txt").write_text("first only\n", encoding="utf-8")
            assert (second_path / "source.txt").read_text(encoding="utf-8") == "original\n"
        assert first_path.is_dir(), "cleaning one worktree removed another live worktree"

    assert not first_path.exists()
    assert not second_path.exists()


class FailWorktreeRemoveRunner(ProcessRunner):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        command_tuple = tuple(command)
        self.commands.append(command_tuple)
        if "worktree" in command_tuple and "remove" in command_tuple:
            return ProcessResult(
                command=command_tuple,
                cwd=cwd.resolve(),
                exit_code=None,
                duration_seconds=0.0,
                stdout="",
                stderr="",
                timed_out=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stdout_bytes_seen=0,
                stderr_bytes_seen=0,
                infrastructure_error="simulated worktree remove failure",
            )
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


def test_cleanup_failure_is_reported_without_global_prune(tmp_path: Path) -> None:
    setup_runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, setup_runner)
    runner = FailWorktreeRemoveRunner()
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with pytest.raises(WorkspaceError, match="remove temporary worktree"), manager as path:
        assert path.is_dir()

    assert path.exists()
    assert manager.cleanup_error is not None
    assert not any("prune" in command for command in runner.commands)
    run_git(setup_runner, repository, "worktree", "remove", "--force", str(path))


def test_base_commit_must_belong_to_the_configured_repository(tmp_path: Path) -> None:
    runner = ProcessRunner()
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    repository, _ = create_repository(first_root, runner)
    unrelated_repository, _ = create_repository(second_root, runner)
    (unrelated_repository / "other.txt").write_text("other\n", encoding="utf-8")
    run_git(runner, unrelated_repository, "add", "other.txt")
    run_git(runner, unrelated_repository, "commit", "--quiet", "-m", "unrelated")
    unrelated_commit = run_git(runner, unrelated_repository, "rev-parse", "HEAD")
    manager = GitWorktree(
        repository=repository,
        base_commit=unrelated_commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
    )

    with pytest.raises(WorkspaceError, match="validate base commit"), manager:
        pass


def test_worktrees_root_inside_original_repository_is_rejected(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=repository / ".reposuture-worktrees",
    )

    with pytest.raises(WorkspaceError, match="outside the original repository"), manager:
        pass

    assert not (repository / ".reposuture-worktrees").exists()


def test_git_worktree_can_be_kept_for_debugging(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = create_repository(tmp_path, runner)
    manager = GitWorktree(
        repository=repository,
        base_commit=commit,
        runner=runner,
        worktrees_root=tmp_path / "worktrees",
        keep=True,
    )

    with manager as worktree:
        kept_path = worktree

    assert kept_path.is_dir()
    assert manager.original_unchanged is True
    run_git(runner, repository, "worktree", "remove", "--force", str(kept_path))
    assert not kept_path.exists()
