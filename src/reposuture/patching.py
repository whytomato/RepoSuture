"""Unified Diff inspection, classification, Git validation, and application."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath

from reposuture.process import ProcessResult, ProcessRunner
from reposuture.workspace import PathSecurityError, safe_worktree_path

MAX_PATCH_BYTES = 10 * 1024 * 1024
MAX_PATCH_FILES = 1_000
GIT_PATCH_TIMEOUT_SECONDS = 30.0


class PatchFormatError(ValueError):
    """Raised when input is not a supported Git-style Unified Diff."""


class PatchRejectedError(RuntimeError):
    """Raised when Git reports that an inspected patch cannot be applied."""


class PatchInfrastructureError(RuntimeError):
    """Raised when Git cannot be executed to validate or apply a patch."""


class PatchErrorCode(StrEnum):
    """Stable model-patch ingestion failure categories."""

    PATCH_EMPTY = "PATCH_EMPTY"
    PATCH_ENCODING_INVALID = "PATCH_ENCODING_INVALID"
    PATCH_FENCE_INVALID = "PATCH_FENCE_INVALID"
    PATCH_GIT_HEADER_MISSING = "PATCH_GIT_HEADER_MISSING"
    PATCH_FILE_HEADERS_MISSING = "PATCH_FILE_HEADERS_MISSING"
    PATCH_PATH_MISMATCH = "PATCH_PATH_MISMATCH"
    PATCH_PATH_UNSAFE = "PATCH_PATH_UNSAFE"
    PATCH_OPERATION_UNSUPPORTED = "PATCH_OPERATION_UNSUPPORTED"
    PATCH_POLICY_REJECTED = "PATCH_POLICY_REJECTED"
    PATCH_HUNK_INVALID = "PATCH_HUNK_INVALID"
    PATCH_GIT_CHECK_FAILED = "PATCH_GIT_CHECK_FAILED"
    PATCH_GIT_RECOUNT_FAILED = "PATCH_GIT_RECOUNT_FAILED"
    PATCH_APPLICATION_FAILED = "PATCH_APPLICATION_FAILED"
    PATCH_POST_APPLY_FAILED = "PATCH_POST_APPLY_FAILED"
    PATCH_ROLLBACK_FAILED = "PATCH_ROLLBACK_FAILED"


class PatchNormalizationOperation(StrEnum):
    """Audited semantics-preserving transformations of model Patch text."""

    NORMALIZED_NEWLINES = "NORMALIZED_NEWLINES"
    REMOVED_UTF8_BOM = "REMOVED_UTF8_BOM"
    REMOVED_MARKDOWN_FENCE = "REMOVED_MARKDOWN_FENCE"
    REMOVED_OUTER_BLANK_LINES = "REMOVED_OUTER_BLANK_LINES"
    ENSURED_FINAL_NEWLINE = "ENSURED_FINAL_NEWLINE"
    SYNTHESIZED_SINGLE_FILE_GIT_HEADER = "SYNTHESIZED_SINGLE_FILE_GIT_HEADER"


class PatchOperationType(StrEnum):
    """Repository operations represented by one parsed Patch."""

    MODIFY = "MODIFY"
    CREATE = "CREATE"
    DELETE = "DELETE"
    RENAME = "RENAME"
    COPY = "COPY"
    BINARY = "BINARY"
    MODE_CHANGE = "MODE_CHANGE"


class PatchValidationResult(StrEnum):
    """Furthest deterministic stage reached by model Patch ingestion."""

    NORMALIZED = "NORMALIZED"
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    POLICY_VALID = "POLICY_VALID"
    GIT_VALID = "GIT_VALID"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


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


@dataclass(frozen=True, slots=True)
class PatchIngestionRecord:
    """Content-safe evidence retained for every model Patch ingestion stage."""

    original_sha256: str
    normalized_sha256: str
    normalization_occurred: bool
    normalization_operations: tuple[PatchNormalizationOperation, ...]
    parsed_paths: tuple[str, ...]
    operation_types: tuple[PatchOperationType, ...]
    validation_result: PatchValidationResult
    recount_used: bool = False
    git_diagnostic: str | None = None
    strict_git_diagnostic: str | None = None
    recount_git_diagnostic: str | None = None
    policy_diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedModelPatch:
    """Normalized immutable Patch bytes plus their transformation audit record."""

    document: PatchDocument
    record: PatchIngestionRecord


@dataclass(frozen=True, slots=True)
class ModelPatchApplication:
    """Applied model Patch evidence, including the canonical final Git diff."""

    inspection: PatchInspection
    record: PatchIngestionRecord
    final_patch: str


class PatchIngestionError(RuntimeError):
    """Structured, bounded model Patch failure safe for tool feedback."""

    def __init__(
        self,
        code: PatchErrorCode,
        message: str,
        *,
        record: PatchIngestionRecord | None = None,
        git_diagnostic: str | None = None,
        policy_diagnostic: str | None = None,
        terminal: bool = False,
    ) -> None:
        bounded_message = message[:4_000]
        super().__init__(bounded_message)
        self.code = code
        self.message = bounded_message
        self.record = record
        self.git_diagnostic = _bounded_patch_diagnostic(git_diagnostic)
        self.policy_diagnostic = _bounded_patch_diagnostic(policy_diagnostic)
        self.terminal = terminal


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


def normalize_model_patch(
    raw_patch: str | bytes,
    worktree: Path,
) -> NormalizedModelPatch:
    """Apply only audited, semantics-preserving normalization to model Patch text."""

    original = raw_patch.encode("utf-8") if isinstance(raw_patch, str) else raw_patch
    original_sha256 = hashlib.sha256(original).hexdigest()
    if not original:
        record = _normalization_record(original_sha256, original, ())
        raise PatchIngestionError(
            PatchErrorCode.PATCH_EMPTY,
            "The submitted patch is empty.",
            record=record,
        )
    if len(original) > MAX_PATCH_BYTES:
        record = _normalization_record(original_sha256, original, ())
        raise PatchIngestionError(
            PatchErrorCode.PATCH_ENCODING_INVALID,
            f"The submitted patch exceeds the {MAX_PATCH_BYTES}-byte limit.",
            record=record,
        )
    if b"\x00" in original:
        record = _normalization_record(original_sha256, original, ())
        raise PatchIngestionError(
            PatchErrorCode.PATCH_ENCODING_INVALID,
            "The submitted patch contains a forbidden NUL byte.",
            record=record,
        )
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        record = _normalization_record(original_sha256, original, ())
        raise PatchIngestionError(
            PatchErrorCode.PATCH_ENCODING_INVALID,
            "The submitted patch must be valid UTF-8 text.",
            record=record,
        ) from exc

    operations: list[PatchNormalizationOperation] = []
    normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized_newlines != text:
        operations.append(PatchNormalizationOperation.NORMALIZED_NEWLINES)
        text = normalized_newlines
    if text.startswith("\ufeff"):
        text = text.removeprefix("\ufeff")
        operations.append(PatchNormalizationOperation.REMOVED_UTF8_BOM)

    text, outer_blanks_removed = _remove_outer_blank_lines(text)
    if outer_blanks_removed:
        operations.append(PatchNormalizationOperation.REMOVED_OUTER_BLANK_LINES)
    try:
        text, fence_removed = _unwrap_complete_patch_fence(text)
    except PatchIngestionError as exc:
        if exc.record is None:
            exc.record = _normalization_record(
                original_sha256,
                text.encode("utf-8"),
                tuple(operations),
            )
        raise
    if fence_removed:
        operations.append(PatchNormalizationOperation.REMOVED_MARKDOWN_FENCE)
        text, inner_blanks_removed = _remove_outer_blank_lines(text)
        if inner_blanks_removed and (
            PatchNormalizationOperation.REMOVED_OUTER_BLANK_LINES not in operations
        ):
            operations.append(PatchNormalizationOperation.REMOVED_OUTER_BLANK_LINES)

    if not text.strip():
        current = text.encode("utf-8")
        record = _normalization_record(original_sha256, current, tuple(operations))
        raise PatchIngestionError(
            PatchErrorCode.PATCH_EMPTY,
            "The submitted patch is empty.",
            record=record,
        )
    exactly_one_final_newline = text.rstrip("\n") + "\n"
    if exactly_one_final_newline != text:
        text = exactly_one_final_newline
        operations.append(PatchNormalizationOperation.ENSURED_FINAL_NEWLINE)

    parsed_paths: tuple[str, ...] = ()
    lines = text.splitlines()
    if not lines or not lines[0].startswith("diff --git "):
        try:
            text, synthesized_path = _synthesize_single_file_header(text, worktree)
        except PatchIngestionError as exc:
            if exc.record is None:
                exc.record = _normalization_record(
                    original_sha256,
                    text.encode("utf-8"),
                    tuple(operations),
                    policy_diagnostic=exc.policy_diagnostic,
                )
            raise
        parsed_paths = (synthesized_path,)
        operations.append(
            PatchNormalizationOperation.SYNTHESIZED_SINGLE_FILE_GIT_HEADER
        )

    normalized_bytes = text.encode("utf-8")
    document = create_patch_document(
        normalized_bytes,
        source_path=Path("agent-input.patch"),
    )
    record = PatchIngestionRecord(
        original_sha256=original_sha256,
        normalized_sha256=document.sha256,
        normalization_occurred=bool(operations),
        normalization_operations=tuple(operations),
        parsed_paths=parsed_paths,
        operation_types=(),
        validation_result=PatchValidationResult.NORMALIZED,
    )
    return NormalizedModelPatch(document=document, record=record)


def _normalization_record(
    original_sha256: str,
    normalized: bytes,
    operations: tuple[PatchNormalizationOperation, ...],
    *,
    policy_diagnostic: str | None = None,
) -> PatchIngestionRecord:
    return PatchIngestionRecord(
        original_sha256=original_sha256,
        normalized_sha256=hashlib.sha256(normalized).hexdigest(),
        normalization_occurred=bool(operations),
        normalization_operations=operations,
        parsed_paths=(),
        operation_types=(),
        validation_result=PatchValidationResult.REJECTED,
        policy_diagnostic=_bounded_patch_diagnostic(policy_diagnostic),
    )


def _remove_outer_blank_lines(text: str) -> tuple[str, bool]:
    """Remove blank lines outside content while preserving one existing final newline."""

    had_final_newline = text.endswith("\n")
    lines = text.split("\n")
    if had_final_newline:
        lines.pop()
    removed = False
    while lines and not lines[0].strip():
        lines.pop(0)
        removed = True
    while lines and not lines[-1].strip():
        lines.pop()
        removed = True
    result = "\n".join(lines)
    if had_final_newline and lines:
        result += "\n"
    return result, removed


def _unwrap_complete_patch_fence(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    fence_lines = [line for line in lines if line.strip().startswith("```")]
    if not fence_lines:
        return text, False
    opening_valid = bool(lines) and re.fullmatch(
        r"```(?:diff|patch)?[ \t]*", lines[0], flags=re.IGNORECASE
    )
    closing_valid = bool(lines) and re.fullmatch(r"```[ \t]*", lines[-1])
    if not opening_valid or not closing_valid or len(fence_lines) != 2:
        raise PatchIngestionError(
            PatchErrorCode.PATCH_FENCE_INVALID,
            "Markdown fences are allowed only when the entire argument is one fenced Patch block.",
        )
    inner = "\n".join(lines[1:-1])
    return inner + "\n", True


def _synthesize_single_file_header(text: str, worktree: Path) -> tuple[str, str]:
    """Handle only the unambiguous existing-file header omission allowed for models."""

    lines = text.splitlines()
    if any(line.startswith("diff --git ") for line in lines):
        raise PatchIngestionError(
            PatchErrorCode.PATCH_GIT_HEADER_MISSING,
            "The patch must begin with a complete 'diff --git' header.",
        )
    old_markers = [line for line in lines if line.startswith("--- ")]
    new_markers = [line for line in lines if line.startswith("+++ ")]
    if not old_markers and not new_markers:
        raise PatchIngestionError(
            PatchErrorCode.PATCH_FILE_HEADERS_MISSING,
            "The patch is missing the required '--- a/<path>' and '+++ b/<path>' headers.",
        )
    if len(old_markers) != 1 or len(new_markers) != 1:
        raise PatchIngestionError(
            PatchErrorCode.PATCH_GIT_HEADER_MISSING,
            "A missing Git header can be synthesized only for exactly one file section.",
        )
    if len(lines) < 2 or lines[0] != old_markers[0] or lines[1] != new_markers[0]:
        raise PatchIngestionError(
            PatchErrorCode.PATCH_GIT_HEADER_MISSING,
            "A headerless Patch must start with one matching '---' and '+++' file-header pair.",
        )
    old_value = old_markers[0][4:].split("\t", maxsplit=1)[0]
    new_value = new_markers[0][4:].split("\t", maxsplit=1)[0]
    if old_value == "/dev/null" or new_value == "/dev/null":
        raise PatchIngestionError(
            PatchErrorCode.PATCH_OPERATION_UNSUPPORTED,
            "A missing Git header cannot be synthesized for file creation or deletion.",
        )
    if not old_value.startswith("a/") or not new_value.startswith("b/"):
        raise PatchIngestionError(
            PatchErrorCode.PATCH_FILE_HEADERS_MISSING,
            "File headers must use '--- a/<path>' and '+++ b/<path>'.",
        )
    old_path = old_value[2:]
    new_path = new_value[2:]
    if old_path != new_path:
        raise PatchIngestionError(
            PatchErrorCode.PATCH_PATH_MISMATCH,
            "The '---' and '+++' file-header paths do not match.",
        )
    try:
        normalized_path = _validate_patch_path(old_path, worktree)
        resolved_path = safe_worktree_path(worktree, normalized_path)
    except PathSecurityError as exc:
        raise PatchIngestionError(
            PatchErrorCode.PATCH_PATH_UNSAFE,
            "The file-header path is not a safe repository-relative path.",
            policy_diagnostic=str(exc),
        ) from exc
    if (
        classify_file(normalized_path) is not FileClassification.PRODUCTION
        or not normalized_path.casefold().startswith("src/main/java/")
        or not normalized_path.casefold().endswith(".java")
    ):
        raise PatchIngestionError(
            PatchErrorCode.PATCH_POLICY_REJECTED,
            "Agent patches may modify only src/main/java production Java files.",
            policy_diagnostic=normalized_path,
        )
    if not resolved_path.is_file():
        raise PatchIngestionError(
            PatchErrorCode.PATCH_OPERATION_UNSUPPORTED,
            "A missing Git header can be synthesized only for an existing file.",
        )
    unsupported_prefixes = (
        "new file mode ",
        "deleted file mode ",
        "old mode ",
        "new mode ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
        "Binary files ",
    )
    if any(
        line == "GIT binary patch" or line.startswith(unsupported_prefixes)
        for line in lines
    ):
        raise PatchIngestionError(
            PatchErrorCode.PATCH_OPERATION_UNSUPPORTED,
            "A missing Git header cannot be synthesized for this Patch operation.",
        )
    header = f"diff --git a/{normalized_path} b/{normalized_path}\n"
    return header + text, normalized_path


def _inspect_model_patch(
    normalized: NormalizedModelPatch,
    worktree: Path,
) -> tuple[PatchInspection, tuple[PatchOperationType, ...]]:
    """Perform structural parsing before any Git apply command can run."""

    lines = normalized.document.content.decode("utf-8").splitlines()
    record = normalized.record
    section_starts = [
        index for index, line in enumerate(lines) if line.startswith("diff --git ")
    ]
    if not section_starts or section_starts[0] != 0:
        raise _patch_error(
            record,
            PatchErrorCode.PATCH_GIT_HEADER_MISSING,
            "The patch must begin with a complete 'diff --git' header.",
        )

    operation_types: list[PatchOperationType] = []
    for section_index, start in enumerate(section_starts):
        end = (
            section_starts[section_index + 1]
            if section_index + 1 < len(section_starts)
            else len(lines)
        )
        section = lines[start:end]
        match = re.fullmatch(r"diff --git a/(.+?) b/(.+)", section[0])
        if match is None:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_GIT_HEADER_MISSING,
                "The Git diff header is malformed or incomplete.",
            )
        try:
            old_path = _validate_patch_path(match.group(1), worktree)
            new_path = _validate_patch_path(match.group(2), worktree)
        except PathSecurityError as exc:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_PATH_UNSAFE,
                "A Patch path is not a safe repository-relative path.",
                policy_diagnostic=str(exc),
            ) from exc

        parsed_paths = list(record.parsed_paths)
        for path in (old_path, new_path):
            if path not in parsed_paths:
                parsed_paths.append(path)
        record = replace(record, parsed_paths=tuple(parsed_paths))

        metadata_operation: PatchOperationType | None = None
        if any(line.startswith(("copy from ", "copy to ")) for line in section[1:]):
            metadata_operation = PatchOperationType.COPY
        elif any(
            line.startswith(("rename from ", "rename to ")) for line in section[1:]
        ):
            metadata_operation = PatchOperationType.RENAME
        elif any(
            line == "GIT binary patch" or line.startswith("Binary files ")
            for line in section[1:]
        ):
            metadata_operation = PatchOperationType.BINARY
        elif any(
            line.startswith(("old mode ", "new mode "))
            for line in section[1:]
        ):
            metadata_operation = PatchOperationType.MODE_CHANGE
        if metadata_operation is not None:
            operation_types.append(metadata_operation)
            record = replace(record, operation_types=tuple(operation_types))
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_OPERATION_UNSUPPORTED,
                f"The {metadata_operation.value} Patch operation is not supported.",
                policy_diagnostic=metadata_operation.value,
            )

        old_markers = [line for line in section if line.startswith("--- ")]
        new_markers = [line for line in section if line.startswith("+++ ")]
        if len(old_markers) != 1 or len(new_markers) != 1:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_FILE_HEADERS_MISSING,
                "Each file section requires exactly one '---' and one '+++' header.",
            )
        try:
            old_marker_path = _parse_file_marker(old_markers[0], "--- ", worktree)
            new_marker_path = _parse_file_marker(new_markers[0], "+++ ", worktree)
        except PathSecurityError as exc:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_PATH_UNSAFE,
                "A file-header path is not a safe repository-relative path.",
                policy_diagnostic=str(exc),
            ) from exc
        except PatchFormatError as exc:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_FILE_HEADERS_MISSING,
                "File headers must use '--- a/<path>' and '+++ b/<path>'.",
            ) from exc

        if old_marker_path is None:
            operation = PatchOperationType.CREATE
        elif new_marker_path is None:
            operation = PatchOperationType.DELETE
        else:
            operation = PatchOperationType.MODIFY
        operation_types.append(operation)
        record = replace(record, operation_types=tuple(operation_types))

        if old_path != new_path:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_PATH_MISMATCH,
                "The old and new Git-header paths do not match.",
            )
        if old_marker_path is not None and old_marker_path != old_path:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_PATH_MISMATCH,
                "The '---' path does not match the Git diff header.",
            )
        if new_marker_path is not None and new_marker_path != new_path:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_PATH_MISMATCH,
                "The '+++' path does not match the Git diff header.",
            )

        hunk_starts = [
            index for index, line in enumerate(section) if line.startswith("@@")
        ]
        if not hunk_starts:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_HUNK_INVALID,
                "Each file section requires at least one Unified Diff hunk.",
            )
        for hunk_index, hunk_start in enumerate(hunk_starts):
            hunk_header = section[hunk_start]
            if re.fullmatch(
                r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?",
                hunk_header,
            ) is None:
                raise _patch_error(
                    record,
                    PatchErrorCode.PATCH_HUNK_INVALID,
                    "A Unified Diff hunk header is malformed.",
                )
            hunk_end = (
                hunk_starts[hunk_index + 1]
                if hunk_index + 1 < len(hunk_starts)
                else len(section)
            )
            for content_line in section[hunk_start + 1 : hunk_end]:
                if not content_line or content_line[0] not in {" ", "+", "-", "\\"}:
                    raise _patch_error(
                        record,
                        PatchErrorCode.PATCH_HUNK_INVALID,
                        "Every hunk content line must begin with space, '+', '-', or backslash.",
                    )

    try:
        inspection = inspect_patch_document(normalized.document, worktree)
    except PathSecurityError as exc:
        raise _patch_error(
            record,
            PatchErrorCode.PATCH_PATH_UNSAFE,
            "A Patch path is not a safe repository-relative path.",
            policy_diagnostic=str(exc),
        ) from exc
    except PatchFormatError as exc:
        raise _patch_error(
            record,
            PatchErrorCode.PATCH_HUNK_INVALID,
            "The submitted patch is not a structurally valid Git-style Unified Diff.",
        ) from exc
    return inspection, tuple(operation_types)


def _patch_error(
    record: PatchIngestionRecord,
    code: PatchErrorCode,
    message: str,
    *,
    git_diagnostic: str | None = None,
    strict_git_diagnostic: str | None = None,
    recount_git_diagnostic: str | None = None,
    policy_diagnostic: str | None = None,
    terminal: bool = False,
) -> PatchIngestionError:
    safe_git = _bounded_patch_diagnostic(git_diagnostic)
    safe_policy = _bounded_patch_diagnostic(policy_diagnostic)
    rejected_record = replace(
        record,
        validation_result=PatchValidationResult.REJECTED,
        git_diagnostic=safe_git,
        strict_git_diagnostic=_bounded_patch_diagnostic(strict_git_diagnostic),
        recount_git_diagnostic=_bounded_patch_diagnostic(recount_git_diagnostic),
        policy_diagnostic=safe_policy,
    )
    return PatchIngestionError(
        code,
        message,
        record=rejected_record,
        git_diagnostic=safe_git,
        policy_diagnostic=safe_policy,
        terminal=terminal,
    )


def _bounded_patch_diagnostic(value: str | None) -> str | None:
    if not value:
        return None
    redacted = re.sub(
        r"(?i)\b(?:sk|sk-or-v1)-[A-Za-z0-9._~-]{8,}\b",
        "<redacted>",
        value,
    )
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+",
        r"\1<redacted>",
        redacted,
    )
    return redacted[:2_000]


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

    def apply_model_patch(
        self,
        raw_patch: str | bytes,
        worktree: Path,
        *,
        production_java_only: bool = True,
    ) -> ModelPatchApplication:
        """Normalize, validate, and transactionally apply one model-generated Patch."""

        normalized = normalize_model_patch(raw_patch, worktree)
        inspection, operation_types = _inspect_model_patch(normalized, worktree)
        record = replace(
            normalized.record,
            parsed_paths=inspection.affected_files,
            operation_types=operation_types,
            validation_result=PatchValidationResult.STRUCTURALLY_VALID,
        )
        unsupported = [
            operation
            for operation in operation_types
            if operation is not PatchOperationType.MODIFY
        ]
        if unsupported:
            names = ", ".join(dict.fromkeys(operation.value for operation in unsupported))
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_OPERATION_UNSUPPORTED,
                f"Model patches may modify existing files only; unsupported operation: {names}.",
                policy_diagnostic=names,
            )
        for path in inspection.affected_files:
            try:
                candidate = safe_worktree_path(worktree, path)
            except PathSecurityError as exc:
                raise _patch_error(
                    record,
                    PatchErrorCode.PATCH_PATH_UNSAFE,
                    "A Patch target is not contained in the isolated worktree.",
                    policy_diagnostic=str(exc),
                ) from exc
            if not candidate.is_file():
                raise _patch_error(
                    record,
                    PatchErrorCode.PATCH_OPERATION_UNSUPPORTED,
                    "Model patches may modify existing regular files only.",
                    policy_diagnostic=path,
                )
        if production_java_only:
            disallowed = [
                path
                for path in inspection.affected_files
                if classify_file(path) is not FileClassification.PRODUCTION
                or not path.casefold().startswith("src/main/java/")
                or not path.casefold().endswith(".java")
            ]
            if disallowed:
                diagnostic = ", ".join(disallowed)
                raise _patch_error(
                    record,
                    PatchErrorCode.PATCH_POLICY_REJECTED,
                    "Agent patches may modify only src/main/java production Java files.",
                    policy_diagnostic=diagnostic,
                )
        record = replace(record, validation_result=PatchValidationResult.POLICY_VALID)

        try:
            self._require_clean_worktree(worktree)
            self._reject_ignored_new_files(worktree, inspection)
        except (PatchInfrastructureError, PatchRejectedError) as exc:
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_GIT_CHECK_FAILED,
                "The isolated worktree could not be prepared for Patch validation.",
                git_diagnostic=str(exc),
                terminal=isinstance(exc, PatchInfrastructureError),
            ) from exc

        strict = self._git_apply(["--check", "-"], worktree, normalized.document.content)
        self._raise_model_git_infrastructure(
            strict,
            record,
            PatchErrorCode.PATCH_GIT_CHECK_FAILED,
            "strict Patch validation",
        )
        strict_diagnostic = self._apply_diagnostic(strict) if strict.exit_code != 0 else None
        recount_used = False
        recount_diagnostic: str | None = None
        if strict.exit_code != 0:
            recount = self._git_apply(
                ["--check", "--recount", "-"],
                worktree,
                normalized.document.content,
            )
            self._raise_model_git_infrastructure(
                recount,
                record,
                PatchErrorCode.PATCH_GIT_RECOUNT_FAILED,
                "Patch recount validation",
                strict_git_diagnostic=strict_diagnostic,
            )
            recount_diagnostic = (
                self._apply_diagnostic(recount) if recount.exit_code != 0 else None
            )
            if recount.exit_code != 0:
                combined = "\n".join(
                    value for value in (strict_diagnostic, recount_diagnostic) if value
                )
                parse_failure = "corrupt patch" in combined.casefold()
                code = (
                    PatchErrorCode.PATCH_HUNK_INVALID
                    if parse_failure
                    else PatchErrorCode.PATCH_GIT_RECOUNT_FAILED
                )
                message = (
                    "Git could not parse the submitted patch."
                    if parse_failure
                    else "The patch did not apply to the current source context."
                )
                raise _patch_error(
                    record,
                    code,
                    message,
                    git_diagnostic=recount_diagnostic or strict_diagnostic,
                    strict_git_diagnostic=strict_diagnostic,
                    recount_git_diagnostic=recount_diagnostic,
                )
            recount_used = True

        record = replace(
            record,
            validation_result=PatchValidationResult.GIT_VALID,
            recount_used=recount_used,
            strict_git_diagnostic=strict_diagnostic,
            recount_git_diagnostic=recount_diagnostic,
        )
        apply_arguments = ["--recount", "-"] if recount_used else ["-"]
        applied = self._git_apply(
            apply_arguments,
            worktree,
            normalized.document.content,
        )
        if (
            applied.infrastructure_error is not None
            or applied.timed_out
            or applied.exit_code != 0
        ):
            diagnostic = self._apply_diagnostic(applied)
            self._rollback_model_patch(worktree, inspection, record)
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_APPLICATION_FAILED,
                "Git failed while applying the already validated patch.",
                git_diagnostic=diagnostic,
                strict_git_diagnostic=strict_diagnostic,
                recount_git_diagnostic=recount_diagnostic,
                terminal=applied.infrastructure_error is not None or applied.timed_out,
            )

        try:
            self._mark_new_files_for_diff(worktree, inspection)
            actual_files = self._actual_changed_files(worktree)
            if not actual_files:
                raise PatchRejectedError("applied patch produced no reviewable Git diff")
            if set(actual_files) != set(inspection.affected_files):
                raise PatchRejectedError(
                    "applied Git diff paths did not match the validated patch paths"
                )
            final_inspection = self._inspection_for_files(
                normalized.document,
                actual_files,
            )
            final_patch = self.final_diff(worktree, final_inspection)
        except Exception as exc:
            diagnostic = str(exc).strip() or type(exc).__name__
            self._rollback_model_patch(worktree, inspection, record)
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_POST_APPLY_FAILED,
                "Patch application was rolled back because post-apply verification failed.",
                git_diagnostic=diagnostic,
                strict_git_diagnostic=strict_diagnostic,
                recount_git_diagnostic=recount_diagnostic,
                terminal=isinstance(exc, PatchInfrastructureError),
            ) from exc

        applied_record = replace(
            record,
            validation_result=PatchValidationResult.APPLIED,
        )
        return ModelPatchApplication(
            inspection=final_inspection,
            record=applied_record,
            final_patch=final_patch,
        )

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

    def _rollback_model_patch(
        self,
        worktree: Path,
        inspection: PatchInspection,
        record: PatchIngestionRecord,
    ) -> None:
        try:
            self._restore_baseline(worktree, inspection)
            self._require_clean_worktree(worktree)
        except Exception as exc:
            diagnostic = str(exc).strip() or type(exc).__name__
            raise _patch_error(
                record,
                PatchErrorCode.PATCH_ROLLBACK_FAILED,
                "Patch rollback failed; Agent execution must stop on unknown repository state.",
                git_diagnostic=diagnostic,
                terminal=True,
            ) from exc

    def _raise_model_git_infrastructure(
        self,
        result: ProcessResult,
        record: PatchIngestionRecord,
        code: PatchErrorCode,
        action: str,
        *,
        strict_git_diagnostic: str | None = None,
    ) -> None:
        if result.infrastructure_error is None and not result.timed_out:
            return
        diagnostic = self._apply_diagnostic(result)
        raise _patch_error(
            record,
            code,
            f"Git infrastructure failed during {action}.",
            git_diagnostic=diagnostic,
            strict_git_diagnostic=strict_git_diagnostic,
            terminal=True,
        )

    @staticmethod
    def _apply_diagnostic(result: ProcessResult) -> str:
        if result.infrastructure_error is not None:
            return result.infrastructure_error
        if result.timed_out:
            return "Git Patch command timed out"
        return result.stderr.strip() or result.stdout.strip() or "Git returned no detail"

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
