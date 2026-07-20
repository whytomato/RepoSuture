"""Unified Diff inspection, classification, Git validation, and application."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from patchpilot.process import ProcessResult, ProcessRunner
from patchpilot.workspace import PathSecurityError, safe_worktree_path

MAX_PATCH_BYTES = 10 * 1024 * 1024
MAX_PATCH_FILES = 1_000
GIT_PATCH_TIMEOUT_SECONDS = 30.0


class PatchFormatError(ValueError):
    """Raised when input is not a supported Git-style Unified Diff."""


class PatchRejectedError(RuntimeError):
    """Raised when Git reports that an inspected patch cannot be applied."""


class PatchInfrastructureError(RuntimeError):
    """Raised when Git cannot be executed to validate or apply a patch."""


class FileClassification(StrEnum):
    PRODUCTION = "production"
    TEST = "test"
    BUILD = "build"
    CI = "CI"
    DOCUMENTATION = "documentation"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class PatchInspection:
    affected_files: tuple[str, ...]
    file_classifications: dict[str, FileClassification]
    patch_size: int
    modifies_tests: bool
    modifies_build: bool
    modifies_maven_wrapper: bool
    modifies_ci: bool
    patch_sha256: str


@dataclass(frozen=True, slots=True)
class PatchDocument:
    """An immutable in-memory snapshot of one configured patch file."""

    source_path: Path
    content: bytes
    sha256: str


def classify_file(file_path: str) -> FileClassification:
    """Classify a repository-relative path for change-risk reporting."""

    normalized = file_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    lowered = normalized.lower()
    name = PurePosixPath(normalized).name.lower()

    if name == "pom.xml" or lowered in {"mvnw", "mvnw.cmd"} or lowered.startswith(
        ".mvn/"
    ):
        return FileClassification.BUILD
    if (
        lowered.startswith(".github/workflows/")
        or lowered.startswith(".circleci/")
        or name in {".gitlab-ci.yml", "jenkinsfile", "azure-pipelines.yml"}
    ):
        return FileClassification.CI
    if lowered.startswith("src/test/"):
        return FileClassification.TEST
    if lowered.startswith("src/main/"):
        return FileClassification.PRODUCTION
    if (
        lowered.startswith("docs/")
        or name.startswith("readme")
        or name.endswith((".md", ".rst", ".adoc"))
    ):
        return FileClassification.DOCUMENTATION
    return FileClassification.OTHER


def _validate_patch_path(file_path: str, worktree: Path) -> str:
    if not file_path or "\\" in file_path or ":" in file_path:
        raise PathSecurityError(f"unsupported patch path: {file_path!r}")
    pure_path = PurePosixPath(file_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise PathSecurityError(f"patch path is not safely relative: {file_path!r}")
    if any(part.casefold() == ".git" for part in pure_path.parts):
        raise PathSecurityError(f"patch paths must not reference Git metadata: {file_path!r}")
    if any(character.isspace() or ord(character) < 32 for character in file_path):
        raise PathSecurityError(
            f"unsupported whitespace or control character in patch path: {file_path!r}"
        )
    normalized = pure_path.as_posix()
    safe_worktree_path(worktree, Path(*pure_path.parts))
    return normalized


def _parse_file_marker(line: str, marker: str, worktree: Path) -> str | None:
    value = line[len(marker) :]
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        raise PatchFormatError("quoted Git paths are not supported in Milestone 1")
    value = value.split("\t", maxsplit=1)[0]
    expected_prefix = "a/" if marker == "--- " else "b/"
    if not value.startswith(expected_prefix):
        raise PatchFormatError(f"file marker must start with {expected_prefix!r}: {line}")
    return _validate_patch_path(value[2:], worktree)


def load_patch_document(patch_file: Path) -> PatchDocument:
    """Read and bound a patch once so later checks and application use identical bytes."""
    try:
        resolved_patch = patch_file.expanduser().resolve(strict=True)
        if not resolved_patch.is_file():
            raise PatchFormatError(f"patch path is not a file: {resolved_patch}")
        patch_bytes = resolved_patch.read_bytes()
    except PatchFormatError:
        raise
    except OSError as exc:
        raise PatchFormatError(f"unable to read patch: {exc}") from exc

    return create_patch_document(patch_bytes, source_path=resolved_patch)


def create_patch_document(patch_bytes: bytes, *, source_path: Path) -> PatchDocument:
    """Freeze and validate patch bytes supplied by a trusted non-filesystem caller."""

    if not patch_bytes:
        raise PatchFormatError("patch is empty")
    if len(patch_bytes) > MAX_PATCH_BYTES:
        raise PatchFormatError(f"patch exceeds the {MAX_PATCH_BYTES}-byte limit")
    if b"\x00" in patch_bytes:
        raise PatchFormatError("NUL bytes are forbidden in a Unified Diff")
    try:
        patch_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchFormatError("patch must be UTF-8 text") from exc
    return PatchDocument(
        source_path=source_path,
        content=patch_bytes,
        sha256=hashlib.sha256(patch_bytes).hexdigest(),
    )


def inspect_patch_document(document: PatchDocument, worktree: Path) -> PatchInspection:
    """Parse frozen Git-style Unified Diff bytes and validate every referenced path."""

    text = document.content.decode("utf-8")

    lines = text.splitlines()
    section_starts = [
        index for index, line in enumerate(lines) if line.startswith("diff --git ")
    ]
    if not section_starts or section_starts[0] != 0:
        raise PatchFormatError("patch must begin with a 'diff --git' header")

    affected_files: list[str] = []
    for section_index, start in enumerate(section_starts):
        end = (
            section_starts[section_index + 1]
            if section_index + 1 < len(section_starts)
            else len(lines)
        )
        section = lines[start:end]
        match = re.fullmatch(r"diff --git a/(.+?) b/(.+)", section[0])
        if match is None or any(value.startswith('"') for value in match.groups()):
            raise PatchFormatError(f"malformed Git diff header: {section[0]}")
        old_path = _validate_patch_path(match.group(1), worktree)
        new_path = _validate_patch_path(match.group(2), worktree)
        if old_path != new_path:
            raise PatchFormatError("rename and copy operations are not supported in Milestone 1")
        if any(
            line.startswith(("rename from ", "rename to ", "copy from ", "copy to "))
            for line in section[1:]
        ):
            raise PatchFormatError("rename and copy metadata are not supported in Milestone 1")
        if any(
            line == "GIT binary patch"
            or line.startswith("Binary files ")
            or line.startswith("similarity index ")
            or re.fullmatch(r"(?:old|new|new file) mode (?:120000|160000)", line)
            or re.fullmatch(
                r"index [0-9a-fA-F]+\.\.[0-9a-fA-F]+ (?:120000|160000)",
                line,
            )
            for line in section[1:]
        ):
            raise PatchFormatError("binary, symlink, and submodule patches are not supported")
        for path in (old_path, new_path):
            if path not in affected_files:
                affected_files.append(path)
                if len(affected_files) > MAX_PATCH_FILES:
                    raise PatchFormatError(
                        f"patch exceeds the {MAX_PATCH_FILES}-file limit"
                    )

        old_markers = [line for line in section if line.startswith("--- ")]
        new_markers = [line for line in section if line.startswith("+++ ")]
        hunks = [line for line in section if line.startswith("@@ ")]
        if len(old_markers) != 1 or len(new_markers) != 1 or not hunks:
            raise PatchFormatError(
                "each diff section must contain one '---', one '+++', and at least one '@@' hunk"
            )
        old_marker_path = _parse_file_marker(old_markers[0], "--- ", worktree)
        new_marker_path = _parse_file_marker(new_markers[0], "+++ ", worktree)
        if old_marker_path is not None and old_marker_path != old_path:
            raise PatchFormatError("'---' path does not match the 'diff --git' header")
        if new_marker_path is not None and new_marker_path != new_path:
            raise PatchFormatError("'+++' path does not match the 'diff --git' header")

    classifications = {path: classify_file(path) for path in affected_files}
    values = set(classifications.values())
    return PatchInspection(
        affected_files=tuple(affected_files),
        file_classifications=classifications,
        patch_size=len(document.content),
        modifies_tests=FileClassification.TEST in values,
        modifies_build=FileClassification.BUILD in values,
        modifies_maven_wrapper=any(
                path.lower() in {"mvnw", "mvnw.cmd"}
                or path.lower().startswith(".mvn/wrapper/")
            for path in affected_files
        ),
        modifies_ci=FileClassification.CI in values,
        patch_sha256=document.sha256,
    )


def inspect_patch(patch_file: Path, worktree: Path) -> PatchInspection:
    """Load and inspect a bounded Git-style Unified Diff."""

    return inspect_patch_document(load_patch_document(patch_file), worktree)


class PatchApplier:
    """Use Git as the authority for patch applicability and application."""

    def __init__(self, runner: ProcessRunner) -> None:
        self.runner = runner

    def validate(self, patch_file: Path, worktree: Path) -> PatchInspection:
        return self.validate_document(load_patch_document(patch_file), worktree)

    def validate_document(
        self, document: PatchDocument, worktree: Path
    ) -> PatchInspection:
        inspection = inspect_patch_document(document, worktree)
        self._require_clean_worktree(worktree)
        self._reject_ignored_new_files(worktree, inspection)
        result = self._git_apply(["--check", "-"], worktree, document.content)
        self._require_apply_success(result, "check")
        return inspection

    def apply(self, patch_file: Path, worktree: Path) -> PatchInspection:
        return self.apply_document(load_patch_document(patch_file), worktree)

    def apply_document(self, document: PatchDocument, worktree: Path) -> PatchInspection:
        inspection = inspect_patch_document(document, worktree)
        self._require_clean_worktree(worktree)
        self._reject_ignored_new_files(worktree, inspection)
        check = self._git_apply(["--check", "-"], worktree, document.content)
        self._require_apply_success(check, "check")
        result = self._git_apply(
            ["--whitespace=nowarn", "-"], worktree, document.content
        )
        try:
            self._require_apply_success(result, "apply")
        except (PatchInfrastructureError, PatchRejectedError):
            self._restore_baseline(worktree, inspection)
            raise
        try:
            self._mark_new_files_for_diff(worktree, inspection)
            actual_files = self._actual_changed_files(worktree)
            if not actual_files:
                raise PatchRejectedError("applied patch produced no reviewable Git diff")
            if set(actual_files) != set(inspection.affected_files):
                raise PatchRejectedError(
                    "applied Git diff paths did not match the validated patch paths"
                )
        except (PatchInfrastructureError, PatchRejectedError):
            self._restore_baseline(worktree, inspection)
            raise
        return self._inspection_for_files(document, actual_files)

    def final_diff(self, worktree: Path, inspection: PatchInspection) -> str:
        self._mark_all_untracked_files_for_diff(worktree)
        self._mark_new_files_for_diff(worktree, inspection)

        result = self.runner.run(
            ["git", "diff", "--binary", "--no-ext-diff", "--"],
            cwd=worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
        )
        self._require_git_success(result, "collect final diff")
        if result.stdout_truncated:
            raise PatchInfrastructureError("final Git diff exceeded the retained output limit")
        if not result.stdout:
            raise PatchRejectedError("final Git diff is empty")
        return result.stdout

    def restore_baseline(self, worktree: Path, inspection: PatchInspection) -> None:
        """Restore only this validated candidate's paths to the detached baseline."""

        self._restore_baseline(worktree, inspection)

    def _mark_all_untracked_files_for_diff(self, worktree: Path) -> None:
        result = self.runner.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"],
            cwd=worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
        )
        self._require_git_success(result, "collect untracked final-diff files")
        if result.stdout_truncated or result.stderr_truncated:
            raise PatchInfrastructureError("untracked Git paths exceeded the output limit")
        untracked = [path for path in result.stdout.split("\x00") if path]
        if len(untracked) > MAX_PATCH_FILES:
            raise PatchInfrastructureError(
                f"final worktree exceeds the {MAX_PATCH_FILES}-untracked-file limit"
            )
        for path in untracked:
            _validate_patch_path(path, worktree)
        if untracked:
            intent = self.runner.run(
                ["git", "add", "--intent-to-add", "--", *untracked],
                cwd=worktree,
                timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
            )
            self._require_git_success(intent, "mark untracked files for final diff")

    def _require_clean_worktree(self, worktree: Path) -> None:
        result = self.runner.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
        )
        self._require_git_success(result, "verify clean pre-patch worktree")
        if result.stdout_truncated or result.stderr_truncated:
            raise PatchInfrastructureError("pre-patch Git status exceeded the output limit")
        if result.stdout:
            raise PatchInfrastructureError(
                "worktree contains non-ignored changes before patch application"
            )

    def _reject_ignored_new_files(
        self, worktree: Path, inspection: PatchInspection
    ) -> None:
        for file_path in inspection.affected_files:
            tracked = self.runner.run(
                ["git", "ls-files", "--error-unmatch", "--", file_path],
                cwd=worktree,
                timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
            )
            if tracked.infrastructure_error is not None:
                raise PatchInfrastructureError(
                    f"unable to inspect patch target {file_path}: {tracked.infrastructure_error}"
                )
            if tracked.timed_out:
                raise PatchInfrastructureError(
                    f"timed out while inspecting patch target {file_path}"
                )
            if tracked.exit_code == 0:
                continue

            ignored = self.runner.run(
                ["git", "check-ignore", "--quiet", "--no-index", "--", file_path],
                cwd=worktree,
                timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
            )
            if ignored.infrastructure_error is not None:
                raise PatchInfrastructureError(
                    f"unable to check ignore rules for {file_path}: "
                    f"{ignored.infrastructure_error}"
                )
            if ignored.timed_out:
                raise PatchInfrastructureError(
                    f"timed out while checking ignore rules for {file_path}"
                )
            if ignored.exit_code == 0:
                raise PatchRejectedError(
                    f"patch creates an ignored file that cannot appear in final.patch: {file_path}"
                )
            if ignored.exit_code != 1:
                detail = ignored.stderr.strip() or ignored.stdout.strip()
                raise PatchInfrastructureError(
                    f"unable to check ignore rules for {file_path}: {detail}"
                )

    def _mark_new_files_for_diff(
        self, worktree: Path, inspection: PatchInspection
    ) -> None:
        new_files: list[str] = []
        for file_path in inspection.affected_files:
            resolved = safe_worktree_path(worktree, file_path)
            tracked = self.runner.run(
                ["git", "ls-files", "--error-unmatch", "--", file_path],
                cwd=worktree,
                timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
            )
            if tracked.infrastructure_error is not None or tracked.timed_out:
                raise PatchInfrastructureError(
                    tracked.infrastructure_error or "timed out while checking tracked patch files"
                )
            if tracked.exit_code != 0 and resolved.exists():
                new_files.append(file_path)

        if new_files:
            intent = self.runner.run(
                ["git", "add", "--intent-to-add", "--", *new_files],
                cwd=worktree,
                timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
            )
            self._require_git_success(intent, "mark new files for final diff")

    def _actual_changed_files(self, worktree: Path) -> tuple[str, ...]:
        result = self.runner.run(
            [
                "git",
                "diff",
                "--name-only",
                "--no-renames",
                "--no-ext-diff",
                "-z",
                "--",
            ],
            cwd=worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
        )
        self._require_git_success(result, "collect actual patch paths")
        if result.stdout_truncated or result.stderr_truncated:
            raise PatchInfrastructureError("actual Git diff paths exceeded the output limit")
        paths = tuple(path for path in result.stdout.split("\x00") if path)
        for path in paths:
            _validate_patch_path(path, worktree)
        return paths

    def _restore_baseline(self, worktree: Path, inspection: PatchInspection) -> None:
        reset = self.runner.run(
            ["git", "reset", "--hard", "--quiet", "HEAD"],
            cwd=worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
        )
        self._require_git_success(reset, "restore worktree after rejected patch")
        clean = self.runner.run(
            ["git", "clean", "-fd", "--", *inspection.affected_files],
            cwd=worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
        )
        self._require_git_success(clean, "remove new files after rejected patch")

    @staticmethod
    def _inspection_for_files(
        document: PatchDocument, affected_files: tuple[str, ...]
    ) -> PatchInspection:
        classifications = {path: classify_file(path) for path in affected_files}
        values = set(classifications.values())
        return PatchInspection(
            affected_files=affected_files,
            file_classifications=classifications,
            patch_size=len(document.content),
            modifies_tests=FileClassification.TEST in values,
            modifies_build=FileClassification.BUILD in values,
            modifies_maven_wrapper=any(
                path.lower() in {"mvnw", "mvnw.cmd"}
                or path.lower().startswith(".mvn/wrapper/")
                for path in affected_files
            ),
            modifies_ci=FileClassification.CI in values,
            patch_sha256=document.sha256,
        )

    def _git_apply(
        self,
        arguments: list[str],
        worktree: Path,
        patch_content: bytes,
    ) -> ProcessResult:
        return self.runner.run(
            ["git", "apply", *arguments],
            cwd=worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
            input_bytes=patch_content,
        )

    @staticmethod
    def _require_apply_success(result: ProcessResult, action: str) -> None:
        if result.infrastructure_error is not None:
            raise PatchInfrastructureError(
                f"unable to {action} patch: {result.infrastructure_error}"
            )
        if result.timed_out:
            raise PatchInfrastructureError(f"timed out while attempting to {action} patch")
        if result.exit_code != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "Git returned no detail"
            raise PatchRejectedError(f"Git rejected patch during {action}: {detail}")

    @staticmethod
    def _require_git_success(result: ProcessResult, action: str) -> None:
        if result.infrastructure_error is not None:
            raise PatchInfrastructureError(f"unable to {action}: {result.infrastructure_error}")
        if result.timed_out:
            raise PatchInfrastructureError(f"timed out while attempting to {action}")
        if result.exit_code != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "Git returned no detail"
            raise PatchInfrastructureError(f"unable to {action}: {detail}")
