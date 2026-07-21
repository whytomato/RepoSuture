from __future__ import annotations

from pathlib import Path

import pytest

from patchpilot.patching import (
    PatchApplier,
    PatchErrorCode,
    PatchIngestionError,
    PatchNormalizationOperation,
    PatchValidationResult,
    normalize_model_patch,
)
from patchpilot.process import ProcessResult, ProcessRunner

SOURCE_PATH = "src/main/java/example/Example.java"


def _source_patch(*, old: str = "false", new: str = "true") -> str:
    return (
        f"diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}\n"
        f"--- a/{SOURCE_PATH}\n"
        f"+++ b/{SOURCE_PATH}\n"
        "@@ -1,3 +1,3 @@\n"
        " public class Example {\n"
        f"-    private boolean enabled = {old};\n"
        f"+    private boolean enabled = {new};\n"
        " }\n"
    )


def _worktree(tmp_path: Path) -> Path:
    worktree = tmp_path / "worktree"
    source = worktree / SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_text(
        "public class Example {\n    private boolean enabled = false;\n}\n",
        encoding="utf-8",
    )
    return worktree


def _repository(tmp_path: Path, runner: ProcessRunner | None = None) -> tuple[Path, ProcessRunner]:
    active_runner = runner or ProcessRunner()
    repository = _worktree(tmp_path)
    extra_files = {
        "src/test/java/example/ExampleTest.java": "class ExampleTest {}\n",
        "pom.xml": "<project/>\n",
        ".github/workflows/ci.yml": "name: ci\n",
    }
    for relative, content in extra_files.items():
        candidate = repository / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content, encoding="utf-8")
    for command in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.name", "PatchPilot Tests"],
        ["git", "config", "user.email", "patchpilot@example.invalid"],
        ["git", "add", "."],
        ["git", "commit", "--quiet", "-m", "base"],
    ):
        result = active_runner.run(command, cwd=repository, timeout_seconds=10)
        assert result.succeeded, result.stderr
    return repository, active_runner


def _replacement_patch(path: str, old: str, new: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def test_normalization_records_only_safe_text_transformations(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    raw = "\ufeff\r\n```diff\r\n" + _source_patch().replace("\n", "\r\n") + "```\r\n\r\n"

    normalized = normalize_model_patch(raw, worktree)

    assert normalized.document.content == _source_patch().encode()
    assert normalized.record.normalization_occurred is True
    assert normalized.record.normalization_operations == (
        PatchNormalizationOperation.NORMALIZED_NEWLINES,
        PatchNormalizationOperation.REMOVED_UTF8_BOM,
        PatchNormalizationOperation.REMOVED_OUTER_BLANK_LINES,
        PatchNormalizationOperation.REMOVED_MARKDOWN_FENCE,
    )
    assert normalized.record.original_sha256 != normalized.record.normalized_sha256


def test_missing_git_header_is_synthesized_only_from_matching_file_headers(
    tmp_path: Path,
) -> None:
    worktree = _worktree(tmp_path)
    raw = _source_patch().split("\n", maxsplit=1)[1]

    normalized = normalize_model_patch(raw, worktree)

    assert normalized.document.content == _source_patch().encode()
    assert normalized.record.normalization_operations == (
        PatchNormalizationOperation.SYNTHESIZED_SINGLE_FILE_GIT_HEADER,
    )


@pytest.mark.parametrize(
    ("patch", "error_code"),
    [
        ("@@ -1 +1 @@\n-old\n+new\n", PatchErrorCode.PATCH_FILE_HEADERS_MISSING),
        (
            f"--- a/{SOURCE_PATH}\n+++ b/src/main/java/example/Other.java\n"
            "@@ -1 +1 @@\n-old\n+new\n",
            PatchErrorCode.PATCH_PATH_MISMATCH,
        ),
        ("\x00", PatchErrorCode.PATCH_ENCODING_INVALID),
        ("", PatchErrorCode.PATCH_EMPTY),
    ],
)
def test_ambiguous_or_invalid_headerless_patches_are_rejected(
    tmp_path: Path,
    patch: str,
    error_code: PatchErrorCode,
) -> None:
    worktree = _worktree(tmp_path)

    with pytest.raises(PatchIngestionError) as caught:
        normalize_model_patch(patch, worktree)

    assert caught.value.code is error_code


def test_multiple_headerless_file_sections_are_rejected(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    raw = _source_patch().split("\n", maxsplit=1)[1] * 2

    with pytest.raises(PatchIngestionError) as caught:
        normalize_model_patch(raw, worktree)

    assert caught.value.code is PatchErrorCode.PATCH_GIT_HEADER_MISSING


def test_invalid_utf8_and_incomplete_fence_have_distinct_errors(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)

    with pytest.raises(PatchIngestionError) as encoding:
        normalize_model_patch(b"\xff", worktree)
    with pytest.raises(PatchIngestionError) as fence:
        normalize_model_patch("```diff\n" + _source_patch(), worktree)

    assert encoding.value.code is PatchErrorCode.PATCH_ENCODING_INVALID
    assert encoding.value.record is not None
    assert fence.value.code is PatchErrorCode.PATCH_FENCE_INVALID
    assert fence.value.record is not None


def test_complete_model_patch_applies_and_returns_canonical_evidence(tmp_path: Path) -> None:
    repository, runner = _repository(tmp_path)

    result = PatchApplier(runner).apply_model_patch(_source_patch(), repository)

    assert result.inspection.affected_files == (SOURCE_PATH,)
    assert result.record.validation_result is PatchValidationResult.APPLIED
    assert result.record.recount_used is False
    assert result.record.parsed_paths == (SOURCE_PATH,)
    assert result.record.operation_types == ("MODIFY",)
    assert result.final_patch.startswith(f"diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}")
    assert "enabled = true" in (repository / SOURCE_PATH).read_text(encoding="utf-8")


class RecordingRunner(ProcessRunner):
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
        self.commands.append(tuple(command))
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


def test_incorrect_hunk_counts_use_recount_only_after_strict_check(tmp_path: Path) -> None:
    runner = RecordingRunner()
    repository, _ = _repository(tmp_path, runner)
    inaccurate = _source_patch().replace("@@ -1,3 +1,3 @@", "@@ -1,30 +1,30 @@")
    runner.commands.clear()

    result = PatchApplier(runner).apply_model_patch(inaccurate, repository)

    apply_commands = [command for command in runner.commands if command[:2] == ("git", "apply")]
    assert apply_commands == [
        ("git", "apply", "--check", "-"),
        ("git", "apply", "--check", "--recount", "-"),
        ("git", "apply", "--recount", "-"),
    ]
    assert result.record.recount_used is True
    assert result.record.strict_git_diagnostic is not None


def test_invalid_hunk_prefix_remains_rejected_without_git_apply(tmp_path: Path) -> None:
    runner = RecordingRunner()
    repository, _ = _repository(tmp_path, runner)
    invalid = _source_patch().replace(" public class Example {", "xpublic class Example {")
    runner.commands.clear()

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(invalid, repository)

    assert caught.value.code is PatchErrorCode.PATCH_HUNK_INVALID
    assert not any(command[:2] == ("git", "apply") for command in runner.commands)
    assert (repository / SOURCE_PATH).read_text(encoding="utf-8").endswith(
        "enabled = false;\n}\n"
    )


def test_incorrect_context_is_rejected_after_strict_and_recount_checks(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    repository, _ = _repository(tmp_path, runner)
    invalid = _source_patch().replace(" public class Example {", " public class Missing {")
    runner.commands.clear()

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(invalid, repository)

    assert caught.value.code is PatchErrorCode.PATCH_GIT_RECOUNT_FAILED
    apply_commands = [command for command in runner.commands if command[:2] == ("git", "apply")]
    assert apply_commands == [
        ("git", "apply", "--check", "-"),
        ("git", "apply", "--check", "--recount", "-"),
    ]
    assert (repository / SOURCE_PATH).read_text(encoding="utf-8").endswith(
        "enabled = false;\n}\n"
    )


def test_unsafe_path_is_rejected_before_git_apply(tmp_path: Path) -> None:
    runner = RecordingRunner()
    repository, _ = _repository(tmp_path, runner)
    unsafe = _source_patch().replace(SOURCE_PATH, "../../outside.java")
    runner.commands.clear()

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(unsafe, repository)

    assert caught.value.code is PatchErrorCode.PATCH_PATH_UNSAFE
    assert not any(command[:2] == ("git", "apply") for command in runner.commands)


@pytest.mark.parametrize(
    ("path", "old", "new"),
    [
        ("src/test/java/example/ExampleTest.java", "class ExampleTest {}", "class Changed {}"),
        ("pom.xml", "<project/>", "<project><name>changed</name></project>"),
        (".github/workflows/ci.yml", "name: ci", "name: changed"),
    ],
)
def test_nonproduction_model_patch_is_policy_rejected_before_git_apply(
    tmp_path: Path,
    path: str,
    old: str,
    new: str,
) -> None:
    runner = RecordingRunner()
    repository, _ = _repository(tmp_path, runner)
    runner.commands.clear()

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(
            _replacement_patch(path, old, new), repository
        )

    assert caught.value.code is PatchErrorCode.PATCH_POLICY_REJECTED
    assert not any(command[:2] == ("git", "apply") for command in runner.commands)
    assert (repository / path).read_text(encoding="utf-8") == old + "\n"


@pytest.mark.parametrize(
    "operation_patch",
    [
        (
            f"diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}\n"
            "deleted file mode 100644\n"
            f"--- a/{SOURCE_PATH}\n"
            "+++ /dev/null\n"
            "@@ -1,3 +0,0 @@\n"
            "-public class Example {\n"
            "-    private boolean enabled = false;\n"
            "-}\n"
        ),
        (
            "diff --git a/src/main/java/example/New.java "
            "b/src/main/java/example/New.java\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/main/java/example/New.java\n"
            "@@ -0,0 +1 @@\n"
            "+class New {}\n"
        ),
    ],
)
def test_create_and_delete_operations_are_rejected_before_git_apply(
    tmp_path: Path,
    operation_patch: str,
) -> None:
    runner = RecordingRunner()
    repository, _ = _repository(tmp_path, runner)
    runner.commands.clear()

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(operation_patch, repository)

    assert caught.value.code is PatchErrorCode.PATCH_OPERATION_UNSUPPORTED
    assert not any(command[:2] == ("git", "apply") for command in runner.commands)


@pytest.mark.parametrize(
    ("operation_patch", "operation"),
    [
        (
            f"diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}\n"
            "GIT binary patch\n"
            "literal 0\n",
            "BINARY",
        ),
        (
            "diff --git a/src/main/java/example/Example.java "
            "b/src/main/java/example/Renamed.java\n"
            "similarity index 100%\n"
            "rename from src/main/java/example/Example.java\n"
            "rename to src/main/java/example/Renamed.java\n",
            "RENAME",
        ),
        (
            f"diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}\n"
            "old mode 100644\n"
            "new mode 100755\n",
            "MODE_CHANGE",
        ),
    ],
)
def test_binary_rename_and_mode_operations_are_never_repaired_or_applied(
    tmp_path: Path,
    operation_patch: str,
    operation: str,
) -> None:
    runner = RecordingRunner()
    repository, _ = _repository(tmp_path, runner)
    runner.commands.clear()

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(operation_patch, repository)

    assert caught.value.code is PatchErrorCode.PATCH_OPERATION_UNSUPPORTED
    assert caught.value.record is not None
    assert [item.value for item in caught.value.record.operation_types] == [operation]
    assert not any(command[:2] == ("git", "apply") for command in runner.commands)


class LongDiagnosticRunner(RecordingRunner):
    secret = "sk-or-v1-" + "diagnosticsecretvalue"

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        if tuple(command[:3]) == ("git", "apply", "--check"):
            self.commands.append(tuple(command))
            detail = ("cannot apply " + self.secret + " ") * 500
            return ProcessResult(
                command=tuple(command),
                cwd=cwd,
                exit_code=1,
                duration_seconds=0.01,
                stdout="",
                stderr=detail,
                timed_out=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stdout_bytes_seen=0,
                stderr_bytes_seen=len(detail),
            )
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


def test_git_rejection_diagnostics_are_bounded_and_secret_redacted(tmp_path: Path) -> None:
    runner = LongDiagnosticRunner()
    repository, _ = _repository(tmp_path, runner)

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(_source_patch(), repository)

    assert caught.value.code is PatchErrorCode.PATCH_GIT_RECOUNT_FAILED
    assert caught.value.git_diagnostic is not None
    assert len(caught.value.git_diagnostic) <= 2_000
    assert LongDiagnosticRunner.secret not in caught.value.git_diagnostic
    assert "<redacted>" in caught.value.git_diagnostic


class FailFinalDiffOnceRunner(RecordingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        if tuple(command) == ("git", "diff", "--binary", "--no-ext-diff", "--") and not self.failed:
            self.failed = True
            return ProcessResult(
                command=tuple(command),
                cwd=cwd,
                exit_code=1,
                duration_seconds=0.01,
                stdout="",
                stderr="injected final diff failure",
                timed_out=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stdout_bytes_seen=0,
                stderr_bytes_seen=27,
            )
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


class PartialModelApplyFailureRunner(RecordingRunner):
    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        if tuple(command) == ("git", "apply", "-"):
            self.commands.append(tuple(command))
            (cwd / SOURCE_PATH).write_text("partial\n", encoding="utf-8")
            return ProcessResult(
                command=tuple(command),
                cwd=cwd,
                exit_code=1,
                duration_seconds=0.01,
                stdout="",
                stderr="injected partial apply failure",
                timed_out=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stdout_bytes_seen=0,
                stderr_bytes_seen=30,
            )
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


def test_partial_model_apply_failure_is_transactionally_rolled_back(tmp_path: Path) -> None:
    runner = PartialModelApplyFailureRunner()
    repository, _ = _repository(tmp_path, runner)

    with pytest.raises(PatchIngestionError) as caught:
        PatchApplier(runner).apply_model_patch(_source_patch(), repository)

    assert caught.value.code is PatchErrorCode.PATCH_APPLICATION_FAILED
    assert "enabled = false" in (repository / SOURCE_PATH).read_text(encoding="utf-8")
    status = ProcessRunner().run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repository,
        timeout_seconds=10,
    )
    assert status.stdout == ""


def test_post_apply_failure_rolls_back_and_later_patch_can_apply(tmp_path: Path) -> None:
    runner = FailFinalDiffOnceRunner()
    repository, _ = _repository(tmp_path, runner)
    applier = PatchApplier(runner)

    with pytest.raises(PatchIngestionError) as caught:
        applier.apply_model_patch(_source_patch(), repository)

    assert caught.value.code is PatchErrorCode.PATCH_POST_APPLY_FAILED
    status = ProcessRunner().run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repository,
        timeout_seconds=10,
    )
    assert status.stdout == ""
    assert "enabled = false" in (repository / SOURCE_PATH).read_text(encoding="utf-8")

    recovered = applier.apply_model_patch(_source_patch(), repository)

    assert recovered.record.validation_result is PatchValidationResult.APPLIED
    assert "enabled = true" in (repository / SOURCE_PATH).read_text(encoding="utf-8")
