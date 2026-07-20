from __future__ import annotations

from pathlib import Path

import pytest

from patchpilot.patching import (
    FileClassification,
    PatchApplier,
    PatchFormatError,
    PatchRejectedError,
    PathSecurityError,
    classify_file,
    inspect_patch,
)
from patchpilot.process import ProcessResult, ProcessRunner


def initialize_repository(repository: Path, runner: ProcessRunner) -> None:
    repository.mkdir()

    def git(*arguments: str) -> None:
        result = runner.run(
            ["git", *arguments], cwd=repository, timeout_seconds=10
        )
        assert result.exit_code == 0, result.stderr

    git("init", "--quiet")
    git("config", "user.name", "PatchPilot Tests")
    git("config", "user.email", "patchpilot@example.invalid")
    source = repository / "src/main/java/App.java"
    source.parent.mkdir(parents=True)
    source.write_text("old\n", encoding="utf-8")
    git("add", ".")
    git("commit", "--quiet", "-m", "base")


def replacement_patch(replacement: str) -> str:
    return (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        f"+{replacement}\n"
    )


def test_inspect_patch_rejects_malformed_unified_diff(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / "broken.patch"
    patch.write_text("--- a/file.txt\n+++ b/file.txt\nthis is not a hunk\n", encoding="utf-8")

    with pytest.raises(PatchFormatError):
        inspect_patch(patch, worktree)


def test_inspect_patch_rejects_empty_patch(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / "empty.patch"
    patch.write_bytes(b"")

    with pytest.raises(PatchFormatError, match="empty"):
        inspect_patch(patch, worktree)


def test_inspect_patch_rejects_path_escape(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / "escape.patch"
    patch.write_text(
        "diff --git a/../../escaped.txt b/../../escaped.txt\n"
        "--- a/../../escaped.txt\n"
        "+++ b/../../escaped.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )

    with pytest.raises(PathSecurityError):
        inspect_patch(patch, worktree)


def test_inspect_patch_rejects_git_metadata_path(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    (worktree / ".git").mkdir(parents=True)
    patch = tmp_path / "git-metadata.patch"
    patch.write_text(
        "diff --git a/.git/config b/.git/config\n"
        "--- a/.git/config\n"
        "+++ b/.git/config\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )

    with pytest.raises(PathSecurityError, match="Git metadata"):
        inspect_patch(patch, worktree)


def test_inspect_patch_rejects_case_variant_git_metadata_path(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / "git-metadata-case.patch"
    patch.write_text(
        "diff --git a/.GIT/config b/.GIT/config\n"
        "--- a/.GIT/config\n"
        "+++ b/.GIT/config\n"
        "@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )

    with pytest.raises(PathSecurityError, match="Git metadata"):
        inspect_patch(patch, worktree)


@pytest.mark.parametrize("operation", ["rename", "copy"])
def test_inspect_patch_rejects_rename_and_copy_metadata(
    tmp_path: Path, operation: str
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / f"{operation}.patch"
    patch.write_text(
        "diff --git a/src/main/Old.java b/src/main/New.java\n"
        f"{operation} from src/main/Old.java\n"
        f"{operation} to src/main/New.java\n"
        "--- a/src/main/Old.java\n"
        "+++ b/src/main/New.java\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )

    with pytest.raises(PatchFormatError, match=operation):
        inspect_patch(patch, worktree)


@pytest.mark.parametrize(
    "metadata",
    [
        "new file mode 120000",
        "new file mode 160000",
        "index 0123456..abcdef0 160000",
        "GIT binary patch",
    ],
)
def test_inspect_patch_rejects_symlink_submodule_and_binary_diffs(
    tmp_path: Path, metadata: str
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / "unsupported.patch"
    patch.write_text(
        "diff --git a/src/main/link b/src/main/link\n"
        f"{metadata}\n"
        "--- /dev/null\n"
        "+++ b/src/main/link\n"
        "@@ -0,0 +1 @@\n"
        "+../../outside\n",
        encoding="utf-8",
    )

    with pytest.raises(PatchFormatError, match="binary, symlink, and submodule"):
        inspect_patch(patch, worktree)


def test_inspect_patch_rejects_mismatched_file_markers(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / "mismatch.patch"
    patch.write_text(
        "diff --git a/src/main/App.java b/src/main/App.java\n"
        "--- a/src/test/AppTest.java\n"
        "+++ b/src/test/AppTest.java\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n",
        encoding="utf-8",
    )

    with pytest.raises(PatchFormatError):
        inspect_patch(patch, worktree)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/main/java/com/example/App.java", FileClassification.PRODUCTION),
        ("src/test/java/com/example/AppTest.java", FileClassification.TEST),
        ("pom.xml", FileClassification.BUILD),
        ("MVNW.CMD", FileClassification.BUILD),
        (".mvn/wrapper/maven-wrapper.properties", FileClassification.BUILD),
        (".github/workflows/ci.yml", FileClassification.CI),
        ("docs/design.md", FileClassification.DOCUMENTATION),
        ("config/settings.ini", FileClassification.OTHER),
    ],
)
def test_classify_file(path: str, expected: FileClassification) -> None:
    assert classify_file(path) is expected


def test_patch_applier_checks_applies_and_collects_final_diff(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository = tmp_path / "repository"
    initialize_repository(repository, runner)
    source = repository / "src/main/java/App.java"

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

    applier = PatchApplier(runner)
    inspection = applier.apply(patch, repository)
    final_diff = applier.final_diff(repository, inspection)

    assert source.read_text(encoding="utf-8") == "new\n"
    assert inspection.affected_files == ("src/main/java/App.java",)
    assert inspection.modifies_tests is False
    assert inspection.modifies_build is False
    assert "git diff" not in final_diff
    assert "+new" in final_diff


class SwapOriginalPatchAfterCheckRunner(ProcessRunner):
    def __init__(self, patch_path: Path) -> None:
        super().__init__()
        self.patch_path = patch_path

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
        if tuple(command[:3]) == ("git", "apply", "--check"):
            self.patch_path.write_text(replacement_patch("attacker"), encoding="utf-8")
        return result


def test_patch_applier_freezes_content_before_check_and_apply(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    setup_runner = ProcessRunner()
    initialize_repository(repository, setup_runner)
    patch = tmp_path / "golden.patch"
    patch.write_text(replacement_patch("intended"), encoding="utf-8")
    runner = SwapOriginalPatchAfterCheckRunner(patch)

    PatchApplier(runner).apply(patch, repository)

    assert (repository / "src/main/java/App.java").read_text(encoding="utf-8") == (
        "intended\n"
    )


def test_patch_applier_rejects_new_file_hidden_by_gitignore(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    runner = ProcessRunner()
    initialize_repository(repository, runner)
    (repository / ".gitignore").write_text("target/\n", encoding="utf-8")
    git_add = runner.run(
        ["git", "add", ".gitignore"], cwd=repository, timeout_seconds=10
    )
    assert git_add.exit_code == 0, git_add.stderr
    git_commit = runner.run(
        ["git", "commit", "--quiet", "-m", "ignore build output"],
        cwd=repository,
        timeout_seconds=10,
    )
    assert git_commit.exit_code == 0, git_commit.stderr
    patch = tmp_path / "ignored.patch"
    patch.write_text(
        "diff --git a/target/generated.txt b/target/generated.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/target/generated.txt\n"
        "@@ -0,0 +1 @@\n"
        "+not-reviewable\n",
        encoding="utf-8",
    )

    with pytest.raises(PatchRejectedError, match="ignored"):
        PatchApplier(runner).apply(patch, repository)

    assert not (repository / "target/generated.txt").exists()


def test_patch_applier_supports_deleting_a_tracked_file(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    runner = ProcessRunner()
    initialize_repository(repository, runner)
    patch = tmp_path / "delete.patch"
    patch.write_text(
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "deleted file mode 100644\n"
        "--- a/src/main/java/App.java\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-old\n",
        encoding="utf-8",
    )

    inspection = PatchApplier(runner).apply(patch, repository)

    assert inspection.affected_files == ("src/main/java/App.java",)
    assert not (repository / "src/main/java/App.java").exists()


def test_rejected_patch_leaves_worktree_at_baseline(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    runner = ProcessRunner()
    initialize_repository(repository, runner)
    patch = tmp_path / "bad-context.patch"
    patch.write_text(replacement_patch("intended").replace("-old", "-missing"), encoding="utf-8")

    with pytest.raises(PatchRejectedError):
        PatchApplier(runner).apply(patch, repository)

    source = repository / "src/main/java/App.java"
    assert source.read_text(encoding="utf-8") == "old\n"
    status = runner.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repository,
        timeout_seconds=10,
    )
    assert status.exit_code == 0
    assert status.stdout == ""


class PartialApplyFailureRunner(ProcessRunner):
    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        if tuple(command[:3]) == ("git", "apply", "--whitespace=nowarn"):
            (cwd / "src/main/java/App.java").write_text("partial\n", encoding="utf-8")
            return ProcessResult(
                command=tuple(command),
                cwd=cwd,
                exit_code=1,
                duration_seconds=0.01,
                stdout="",
                stderr="simulated apply failure",
                timed_out=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stdout_bytes_seen=0,
                stderr_bytes_seen=len("simulated apply failure"),
            )
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


def test_apply_failure_rolls_back_even_if_git_left_a_partial_change(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    setup_runner = ProcessRunner()
    initialize_repository(repository, setup_runner)
    patch = tmp_path / "golden.patch"
    patch.write_text(replacement_patch("intended"), encoding="utf-8")

    with pytest.raises(PatchRejectedError, match="simulated apply failure"):
        PatchApplier(PartialApplyFailureRunner()).apply(patch, repository)

    assert (repository / "src/main/java/App.java").read_text(encoding="utf-8") == "old\n"
    status = setup_runner.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repository,
        timeout_seconds=10,
    )
    assert status.stdout == ""


def test_final_diff_includes_unexpected_nonignored_files_for_conservative_check(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    runner = ProcessRunner()
    initialize_repository(repository, runner)
    patch = tmp_path / "golden.patch"
    patch.write_text(replacement_patch("intended"), encoding="utf-8")
    applier = PatchApplier(runner)
    inspection = applier.apply(patch, repository)
    unexpected = repository / "generated.txt"
    unexpected.write_text("unexpected\n", encoding="utf-8")

    final_diff = applier.final_diff(repository, inspection)

    assert "diff --git a/generated.txt b/generated.txt" in final_diff
    assert "diff --git a/src/main/java/App.java b/src/main/java/App.java" in final_diff


def test_inspection_reports_test_and_build_file_modifications(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    patch = tmp_path / "sensitive.patch"
    patch.write_text(
        "diff --git a/src/test/java/AppTest.java b/src/test/java/AppTest.java\n"
        "--- a/src/test/java/AppTest.java\n"
        "+++ b/src/test/java/AppTest.java\n"
        "@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/pom.xml b/pom.xml\n"
        "--- a/pom.xml\n"
        "+++ b/pom.xml\n"
        "@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )

    inspection = inspect_patch(patch, worktree)

    assert inspection.modifies_tests is True
    assert inspection.modifies_build is True
    assert inspection.file_classifications["src/test/java/AppTest.java"] is (
        FileClassification.TEST
    )
    assert inspection.file_classifications["pom.xml"] is FileClassification.BUILD
