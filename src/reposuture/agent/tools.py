"""Bounded repository tools backed by the deterministic Milestone 1 runtime."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    model_validator,
)

from reposuture.agent.base import (
    ToolCall,
    ToolError,
    ToolErrorCode,
    ToolResult,
    ToolSpec,
)
from reposuture.case_spec import TargetTest
from reposuture.maven import MavenExecution, MavenRunner
from reposuture.patching import (
    GIT_PATCH_TIMEOUT_SECONDS,
    MAX_PATCH_BYTES,
    FileClassification,
    PatchApplier,
    PatchErrorCode,
    PatchIngestionError,
    PatchIngestionRecord,
    PatchInspection,
    PatchOperationType,
    PatchValidationResult,
    classify_file,
)
from reposuture.process import ProcessRunner
from reposuture.reporting import TestOutcome
from reposuture.workspace import PathSecurityError, safe_worktree_path

MAX_TOOL_PATH_CHARS = 1_024
MAX_LISTED_FILES = 500
MAX_SCANNED_PATHS = 10_000
MAX_SEARCH_FILES = 2_000
MAX_SEARCH_FILE_BYTES = 1 * 1024 * 1024
MAX_SEARCH_MATCHES = 100
MAX_SEARCH_LINE_CHARS = 500
MAX_READ_FILE_BYTES = 256 * 1024
MAX_READ_LINES = 400
MAX_TEST_OUTPUT_CHARS = 12_000
MAX_TOOL_ERROR_CHARS = 3_500
MAX_LIST_DEPTH = 12
MAX_GIT_DIFF_BYTES = 128 * 1024

PATCH_REQUIRED_FORMAT = (
    "diff --git a/<path> b/<path>",
    "--- a/<path>",
    "+++ b/<path>",
    "@@ -old_start,old_count +new_start,new_count @@",
)
PATCH_FEEDBACK_RULES = (
    "Every hunk content line must begin with space, +, -, or backslash.",
    "Return only the Patch in the patch tool argument; do not add explanatory prose.",
    "Do not use Markdown code fences.",
    "Include complete Git-style headers and unchanged context lines with a leading space.",
    "Ensure hunk counts match; Git recount can recover count mistakes only.",
    "Do not modify tests, build files, Maven Wrapper files, or CI.",
    "Reread the relevant source region after a rejected Patch when necessary.",
)
PATCH_TOOL_DESCRIPTION = """Validate and transactionally apply one UTF-8 Git-style Unified Diff.
Return only the Patch in the `patch` tool argument; do not use Markdown code fences. Include
complete Git-style headers, unchanged context lines with a leading space, and matching hunk
counts. Git recount may recover count mistakes only. Reread the relevant source after rejection.
Never modify tests, build files, Maven Wrapper files, or CI. Example:
diff --git a/src/main/java/example/Example.java b/src/main/java/example/Example.java
--- a/src/main/java/example/Example.java
+++ b/src/main/java/example/Example.java
@@ -1,3 +1,3 @@
 public class Example {
-    private boolean enabled = false;
+    private boolean enabled = true;
 }
"""

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".idea",
        ".vscode",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "__pycache__",
        "target",
    }
)
IGNORED_BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".class",
        ".dll",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".so",
        ".tar",
        ".war",
        ".zip",
    }
)

PathText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=MAX_TOOL_PATH_CHARS),
]


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ListFilesInput(_ToolInput):
    path: PathText
    max_depth: Annotated[StrictInt, Field(ge=0, le=MAX_LIST_DEPTH)] = 6


class SearchCodeInput(_ToolInput):
    query: Annotated[
        str,
        StringConstraints(
            strict=True,
            strip_whitespace=True,
            min_length=1,
            max_length=256,
        ),
    ]
    path: PathText = "."
    file_type: Literal["java", "all"] = "java"


class ReadFileInput(_ToolInput):
    path: PathText
    start_line: Annotated[StrictInt, Field(ge=1)] = 1
    end_line: Annotated[StrictInt, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def validate_line_window(self) -> Self:
        if self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError("end_line must not be before start_line")
            if self.end_line - self.start_line + 1 > MAX_READ_LINES:
                raise ValueError(f"read window exceeds the {MAX_READ_LINES}-line limit")
        return self


class ApplyPatchInput(_ToolInput):
    patch: Annotated[
        str,
        StringConstraints(strict=True, max_length=MAX_PATCH_BYTES),
    ]


class RunTargetTestInput(_ToolInput):
    pass


class GitDiffInput(_ToolInput):
    pass


class ToolPolicyError(ValueError):
    """Raised when a locally valid tool request violates repair policy."""


class StructuredToolFailure(RuntimeError):
    """A bounded handler rejection with model-visible structured details."""

    def __init__(
        self,
        code: ToolErrorCode | PatchErrorCode,
        message: str,
        output: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.output = output


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """Internal successful handler response before call metadata is attached."""

    output: dict[str, Any]
    verifier_passed: bool | None = None


ToolHandler = Callable[[BaseModel], ToolExecution]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One registered name, schema, description, and trusted handler."""

    name: str
    description: str
    input_model: type[BaseModel]
    execute: ToolHandler

    def as_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )


class ToolExecutor:
    """Validate and dispatch model-selected calls without exposing a shell."""

    def __init__(self, definitions: Sequence[ToolDefinition]) -> None:
        registry: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.name in registry:
                raise ValueError(f"duplicate tool registration: {definition.name}")
            registry[definition.name] = definition
        if not registry:
            raise ValueError("at least one tool must be registered")
        self._registry = registry

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(definition.as_spec() for definition in self._registry.values())

    def execute(self, call: ToolCall) -> ToolResult:
        definition = self._registry.get(call.name)
        if definition is None:
            return self._failure(
                call,
                ToolErrorCode.UNKNOWN_TOOL,
                f"tool is not registered: {call.name}",
            )
        if call.argument_error is not None:
            return self._failure(
                call,
                ToolErrorCode.INVALID_ARGUMENTS,
                call.argument_error,
            )
        try:
            arguments = definition.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors(include_url=False, include_input=False)
            )
            return self._failure(
                call,
                ToolErrorCode.INVALID_ARGUMENTS,
                details or "tool arguments did not match the input schema",
            )

        try:
            execution = definition.execute(arguments)
        except StructuredToolFailure as exc:
            return self._failure(
                call,
                exc.code,
                exc.message,
                output=exc.output,
            )
        except ToolPolicyError as exc:
            return self._failure(
                call,
                ToolErrorCode.POLICY_REJECTED,
                str(exc) or "tool request was rejected by policy",
            )
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            return self._failure(
                call,
                ToolErrorCode.EXECUTION_ERROR,
                f"{type(exc).__name__}: {detail}",
            )
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            success=True,
            output=execution.output,
            verifier_passed=execution.verifier_passed,
        )

    @staticmethod
    def _failure(
        call: ToolCall,
        code: ToolErrorCode | PatchErrorCode,
        message: str,
        *,
        output: dict[str, Any] | None = None,
    ) -> ToolResult:
        bounded = message[:MAX_TOOL_ERROR_CHARS]
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            success=False,
            output=output,
            error=ToolError(code=code, message=bounded),
        )


@dataclass(slots=True)
class RepoSutureToolEnvironment:
    """Trusted bindings for tools operating on one existing linked worktree."""

    worktree: Path
    target_test: TargetTest
    target_test_timeout_seconds: float
    process_runner: ProcessRunner
    production_java_only: bool = False
    max_patch_attempts: int = 2
    patch_inspection: PatchInspection | None = field(default=None, init=False)
    final_patch: str | None = field(default=None, init=False)
    latest_target_execution: MavenExecution | None = field(default=None, init=False)
    patch_attempts: list[PatchAttemptRecord] = field(default_factory=list, init=False)
    _seen_patch_hashes: set[str] = field(default_factory=set, init=False, repr=False)
    _patch_applier: PatchApplier = field(init=False, repr=False)
    _maven_runner: MavenRunner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        resolved = self.worktree.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"Agent tool worktree is not a directory: {resolved}")
        metadata = resolved / ".git"
        try:
            metadata_stat = metadata.lstat()
            if stat.S_ISLNK(metadata_stat.st_mode) or not stat.S_ISREG(metadata_stat.st_mode):
                raise ValueError("Agent tools require an isolated linked Git worktree")
            if metadata_stat.st_size > 4_096:
                raise ValueError("linked-worktree Git metadata marker is unexpectedly large")
            marker = metadata.read_text(encoding="utf-8").strip().replace("\\", "/")
        except OSError as exc:
            raise ValueError(f"unable to validate linked-worktree metadata: {exc}") from exc
        normalized_marker = marker.casefold()
        if not normalized_marker.startswith("gitdir:") or (
            "/.git/worktrees/" not in normalized_marker
        ):
            raise ValueError("Agent tools require an isolated linked Git worktree")
        if not 1 <= self.target_test_timeout_seconds <= 3_600:
            raise ValueError("target test timeout must be between 1 and 3600 seconds")
        if not 1 <= self.max_patch_attempts <= 10:
            raise ValueError("max_patch_attempts must be between 1 and 10")
        self.worktree = resolved
        self._patch_applier = PatchApplier(self.process_runner)
        self._maven_runner = MavenRunner(self.process_runner)

    def record_rejected_patch_call(
        self,
        arguments: dict[str, Any],
        *,
        failure_reason: str,
    ) -> PatchAttemptRecord:
        """Audit an apply_patch call rejected before its handler could execute."""

        raw_patch = arguments.get("patch")
        if isinstance(raw_patch, str):
            patch_bytes = raw_patch.encode("utf-8")
        else:
            marker = f"<invalid-patch-argument:{type(raw_patch).__name__}>"
            patch_bytes = marker.encode("utf-8")
        digest = hashlib.sha256(patch_bytes).hexdigest()
        equivalent = digest in self._seen_patch_hashes
        self._seen_patch_hashes.add(digest)
        record = PatchAttemptRecord(
            attempt_id=len(self.patch_attempts) + 1,
            patch_sha256=digest,
            patch_size=len(patch_bytes) if isinstance(raw_patch, str) else 0,
            affected_files=(),
            accepted=False,
            equivalent_to_previous=equivalent,
            failure_reason=(failure_reason or "invalid apply_patch call")[
                :MAX_TOOL_ERROR_CHARS
            ],
            original_patch_sha256=digest,
            normalized_patch_sha256=None,
            error_code=None,
        )
        self.patch_attempts.append(record)
        return record


@dataclass(frozen=True, slots=True)
class PatchAttemptRecord:
    """Content-safe audit record for every apply_patch invocation."""

    attempt_id: int
    patch_sha256: str
    patch_size: int
    affected_files: tuple[str, ...]
    accepted: bool
    equivalent_to_previous: bool
    failure_reason: str | None = None
    original_patch_sha256: str | None = None
    normalized_patch_sha256: str | None = None
    normalization_occurred: bool = False
    normalization_operations: tuple[str, ...] = ()
    parsed_paths: tuple[str, ...] = ()
    operation_types: tuple[PatchOperationType, ...] = ()
    validation_result: PatchValidationResult | None = None
    recount_used: bool = False
    error_code: PatchErrorCode | None = None
    git_diagnostic: str | None = None
    strict_git_diagnostic: str | None = None
    recount_git_diagnostic: str | None = None
    policy_diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class _RepositoryFiles:
    paths: tuple[str, ...]
    scanned_paths: int
    truncated: bool


class _RepoSutureToolHandlers:
    def __init__(self, environment: RepoSutureToolEnvironment) -> None:
        self.environment = environment

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition(
                name="list_files",
                description="List a bounded set of repository-relative files below a path.",
                input_model=ListFilesInput,
                execute=self.list_files,
            ),
            ToolDefinition(
                name="search_code",
                description=(
                    "Search bounded repository text for a literal query and return line matches."
                ),
                input_model=SearchCodeInput,
                execute=self.search_code,
            ),
            ToolDefinition(
                name="read_file",
                description="Read a bounded line range from one repository source file.",
                input_model=ReadFileInput,
                execute=self.read_file,
            ),
            ToolDefinition(
                name="apply_patch",
                description=PATCH_TOOL_DESCRIPTION,
                input_model=ApplyPatchInput,
                execute=self.apply_patch,
            ),
            ToolDefinition(
                name="run_target_test",
                description=(
                    "Run the configured Maven/JUnit target and return deterministic evidence."
                ),
                input_model=RunTargetTestInput,
                execute=self.run_target_test,
            ),
            ToolDefinition(
                name="git_diff",
                description=(
                    "Return a bounded Git diff summary for the current candidate repair."
                ),
                input_model=GitDiffInput,
                execute=self.git_diff,
            ),
        )

    def list_files(self, arguments: BaseModel) -> ToolExecution:
        if not isinstance(arguments, ListFilesInput):
            raise TypeError("list_files received the wrong validated input model")
        listing = self._repository_files(
            arguments.path,
            limit=MAX_LISTED_FILES,
            max_depth=arguments.max_depth,
        )
        return ToolExecution(
            {
                "path": arguments.path,
                "files": list(listing.paths),
                "count": len(listing.paths),
                "scanned_paths": listing.scanned_paths,
                "truncated": listing.truncated,
            }
        )

    def search_code(self, arguments: BaseModel) -> ToolExecution:
        if not isinstance(arguments, SearchCodeInput):
            raise TypeError("search_code received the wrong validated input model")
        listing = self._repository_files(
            arguments.path,
            limit=MAX_SEARCH_FILES,
            max_depth=MAX_LIST_DEPTH,
        )
        query = arguments.query.casefold()
        matches: list[dict[str, Any]] = []
        skipped_files = 0
        truncated = listing.truncated
        for relative in listing.paths:
            if arguments.file_type == "java" and not relative.casefold().endswith(".java"):
                continue
            candidate = _safe_repository_path(self.environment.worktree, relative)
            try:
                with candidate.open("rb") as stream:
                    content = stream.read(MAX_SEARCH_FILE_BYTES + 1)
            except OSError as exc:
                raise RuntimeError(f"unable to search {relative}: {exc}") from exc
            if len(content) > MAX_SEARCH_FILE_BYTES or b"\x00" in content:
                skipped_files += 1
                truncated = truncated or len(content) > MAX_SEARCH_FILE_BYTES
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                skipped_files += 1
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                column = line.casefold().find(query)
                if column < 0:
                    continue
                matches.append(
                    {
                        "path": relative,
                        "line": line_number,
                        "column": column + 1,
                        "text": line[:MAX_SEARCH_LINE_CHARS],
                    }
                )
                if len(matches) >= MAX_SEARCH_MATCHES:
                    truncated = True
                    break
            if len(matches) >= MAX_SEARCH_MATCHES:
                break
        return ToolExecution(
            {
                "query": arguments.query,
                "path": arguments.path,
                "file_type": arguments.file_type,
                "matches": matches,
                "match_count": len(matches),
                "files_considered": len(listing.paths),
                "skipped_files": skipped_files,
                "truncated": truncated,
            }
        )

    def read_file(self, arguments: BaseModel) -> ToolExecution:
        if not isinstance(arguments, ReadFileInput):
            raise TypeError("read_file received the wrong validated input model")
        candidate = _safe_repository_path(self.environment.worktree, arguments.path)
        if not candidate.exists():
            raise FileNotFoundError(f"repository file does not exist: {arguments.path}")
        if not candidate.is_file():
            raise ValueError(f"repository path is not a file: {arguments.path}")
        try:
            with candidate.open("rb") as stream:
                content = stream.read(MAX_READ_FILE_BYTES + 1)
        except OSError as exc:
            raise RuntimeError(f"unable to read {arguments.path}: {exc}") from exc
        file_truncated = len(content) > MAX_READ_FILE_BYTES
        retained = content[:MAX_READ_FILE_BYTES]
        if b"\x00" in retained:
            raise ValueError(f"repository file is binary: {arguments.path}")
        try:
            text = retained.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"repository file is not UTF-8 text: {arguments.path}") from exc
        lines = text.splitlines()
        start_index = arguments.start_line - 1
        if start_index >= len(lines) and file_truncated:
            raise ValueError("requested line starts beyond the bounded readable prefix")
        requested_end = arguments.end_line or arguments.start_line + MAX_READ_LINES - 1
        end_index = min(requested_end, len(lines))
        selected = lines[start_index:end_index]
        truncated = file_truncated or end_index < len(lines)
        return ToolExecution(
            {
                "path": arguments.path,
                "start_line": arguments.start_line,
                "end_line": end_index,
                "content": "\n".join(selected),
                "retained_line_count": len(lines),
                "total_lines_exact": not file_truncated,
                "truncated": truncated,
            }
        )

    def apply_patch(self, arguments: BaseModel) -> ToolExecution:
        if not isinstance(arguments, ApplyPatchInput):
            raise TypeError("apply_patch received the wrong validated input model")
        patch_bytes = arguments.patch.encode("utf-8")
        patch_sha256 = hashlib.sha256(patch_bytes).hexdigest()
        attempt_id = len(self.environment.patch_attempts) + 1
        equivalent = patch_sha256 in self.environment._seen_patch_hashes
        self.environment._seen_patch_hashes.add(patch_sha256)
        if equivalent:
            self._record_patch_attempt(
                attempt_id=attempt_id,
                patch_sha256=patch_sha256,
                patch_size=len(patch_bytes),
                affected_files=(),
                accepted=False,
                equivalent=True,
                failure_reason="equivalent patch content was already attempted",
                ingestion=None,
                error_code=PatchErrorCode.PATCH_POLICY_REJECTED,
            )
            raise StructuredToolFailure(
                ToolErrorCode.POLICY_REJECTED,
                "Equivalent patch content was already attempted.",
                self._patch_rejection_output(
                    code=PatchErrorCode.PATCH_POLICY_REJECTED,
                    message="Equivalent patch content was already attempted.",
                    ingestion=None,
                ),
            )

        try:
            application = self.environment._patch_applier.apply_model_patch(
                arguments.patch,
                self.environment.worktree,
                production_java_only=self.environment.production_java_only,
            )
        except PatchIngestionError as exc:
            self.environment.patch_inspection = None
            self.environment.final_patch = None
            ingestion = exc.record
            affected_files = ingestion.parsed_paths if ingestion is not None else ()
            failure_detail = " ".join(
                value
                for value in (exc.message, exc.policy_diagnostic, exc.git_diagnostic)
                if value
            )[:MAX_TOOL_ERROR_CHARS]
            self._record_patch_attempt(
                attempt_id=attempt_id,
                patch_sha256=patch_sha256,
                patch_size=len(patch_bytes),
                affected_files=affected_files,
                accepted=False,
                equivalent=False,
                failure_reason=failure_detail,
                ingestion=ingestion,
                error_code=exc.code,
            )
            raise StructuredToolFailure(
                _tool_error_code_for_patch(exc.code),
                exc.message,
                self._patch_rejection_output(
                    code=exc.code,
                    message=exc.message,
                    ingestion=ingestion,
                    git_diagnostic=exc.git_diagnostic,
                    policy_diagnostic=exc.policy_diagnostic,
                    terminal=exc.terminal,
                ),
            ) from exc

        inspection = application.inspection
        final_patch = application.final_patch
        self._record_patch_attempt(
            attempt_id=attempt_id,
            patch_sha256=patch_sha256,
            patch_size=len(patch_bytes),
            affected_files=inspection.affected_files,
            accepted=True,
            equivalent=False,
            failure_reason=None,
            ingestion=application.record,
            error_code=None,
        )
        self.environment.patch_inspection = inspection
        self.environment.final_patch = final_patch
        return ToolExecution(
            {
                "affected_files": list(inspection.affected_files),
                "file_classifications": {
                    path: classification.value
                    for path, classification in inspection.file_classifications.items()
                },
                "patch_size": inspection.patch_size,
                "patch_sha256": inspection.patch_sha256,
                "original_patch_sha256": application.record.original_sha256,
                "normalized_patch_sha256": application.record.normalized_sha256,
                "normalization_occurred": application.record.normalization_occurred,
                "normalization_operations": [
                    operation.value
                    for operation in application.record.normalization_operations
                ],
                "parsed_paths": list(application.record.parsed_paths),
                "patch_operation_types": [
                    operation.value for operation in application.record.operation_types
                ],
                "validation_result": application.record.validation_result.value,
                "recount_used": application.record.recount_used,
                "strict_git_diagnostic": application.record.strict_git_diagnostic,
                "recount_git_diagnostic": application.record.recount_git_diagnostic,
                "final_patch_size": len(final_patch.encode("utf-8")),
                "final_patch_sha256": hashlib.sha256(final_patch.encode("utf-8")).hexdigest(),
                "modifies_tests": inspection.modifies_tests,
                "modifies_build": inspection.modifies_build,
                "modifies_maven_wrapper": inspection.modifies_maven_wrapper,
                "modifies_ci": inspection.modifies_ci,
            }
        )

    def _record_patch_attempt(
        self,
        *,
        attempt_id: int,
        patch_sha256: str,
        patch_size: int,
        affected_files: tuple[str, ...],
        accepted: bool,
        equivalent: bool,
        failure_reason: str | None,
        ingestion: PatchIngestionRecord | None,
        error_code: PatchErrorCode | None,
    ) -> None:
        self.environment.patch_attempts.append(
            PatchAttemptRecord(
                attempt_id=attempt_id,
                patch_sha256=patch_sha256,
                patch_size=patch_size,
                affected_files=affected_files,
                accepted=accepted,
                equivalent_to_previous=equivalent,
                failure_reason=failure_reason,
                original_patch_sha256=(
                    ingestion.original_sha256 if ingestion is not None else patch_sha256
                ),
                normalized_patch_sha256=(
                    ingestion.normalized_sha256 if ingestion is not None else None
                ),
                normalization_occurred=(
                    ingestion.normalization_occurred if ingestion is not None else False
                ),
                normalization_operations=(
                    tuple(
                        operation.value
                        for operation in ingestion.normalization_operations
                    )
                    if ingestion is not None
                    else ()
                ),
                parsed_paths=(ingestion.parsed_paths if ingestion is not None else ()),
                operation_types=(
                    ingestion.operation_types if ingestion is not None else ()
                ),
                validation_result=(
                    ingestion.validation_result if ingestion is not None else None
                ),
                recount_used=(ingestion.recount_used if ingestion is not None else False),
                error_code=error_code,
                git_diagnostic=(
                    ingestion.git_diagnostic if ingestion is not None else None
                ),
                strict_git_diagnostic=(
                    ingestion.strict_git_diagnostic if ingestion is not None else None
                ),
                recount_git_diagnostic=(
                    ingestion.recount_git_diagnostic if ingestion is not None else None
                ),
                policy_diagnostic=(
                    ingestion.policy_diagnostic if ingestion is not None else None
                ),
            )
        )

    def _patch_rejection_output(
        self,
        *,
        code: PatchErrorCode,
        message: str,
        ingestion: PatchIngestionRecord | None,
        git_diagnostic: str | None = None,
        policy_diagnostic: str | None = None,
        terminal: bool = False,
    ) -> dict[str, Any]:
        remaining = max(
            0,
            self.environment.max_patch_attempts - len(self.environment.patch_attempts),
        )
        return {
            "status": "rejected",
            "error_code": code.value,
            "message": message[:MAX_TOOL_ERROR_CHARS],
            "git_diagnostic": git_diagnostic,
            "strict_git_diagnostic": (
                ingestion.strict_git_diagnostic if ingestion is not None else None
            ),
            "recount_git_diagnostic": (
                ingestion.recount_git_diagnostic if ingestion is not None else None
            ),
            "policy_diagnostic": policy_diagnostic,
            "required_format": list(PATCH_REQUIRED_FORMAT),
            "rules": list(PATCH_FEEDBACK_RULES),
            "worktree_modified": False,
            "patch_attempts_remaining": remaining,
            "terminal": terminal,
            "original_patch_sha256": (
                ingestion.original_sha256 if ingestion is not None else None
            ),
            "normalized_patch_sha256": (
                ingestion.normalized_sha256 if ingestion is not None else None
            ),
            "normalization_occurred": (
                ingestion.normalization_occurred if ingestion is not None else False
            ),
            "normalization_operations": (
                [operation.value for operation in ingestion.normalization_operations]
                if ingestion is not None
                else []
            ),
            "parsed_paths": list(ingestion.parsed_paths) if ingestion is not None else [],
            "patch_operation_types": (
                [operation.value for operation in ingestion.operation_types]
                if ingestion is not None
                else []
            ),
            "validation_result": (
                ingestion.validation_result.value if ingestion is not None else "REJECTED"
            ),
            "recount_used": ingestion.recount_used if ingestion is not None else False,
        }

    def run_target_test(self, arguments: BaseModel) -> ToolExecution:
        if not isinstance(arguments, RunTargetTestInput):
            raise TypeError("run_target_test received the wrong validated input model")
        execution = self.environment._maven_runner.run_target(
            self.environment.worktree,
            self.environment.target_test,
            timeout_seconds=self.environment.target_test_timeout_seconds,
            candidate_patch_applied=self.environment.patch_inspection is not None,
        )
        self.environment.latest_target_execution = execution
        process = execution.process
        verifier_passed = (
            execution.outcome is TestOutcome.PASS
            and execution.test_observed
            and execution.target_found
        )
        stdout, stdout_tool_truncated = _bounded_tail(process.stdout)
        stderr, stderr_tool_truncated = _bounded_tail(process.stderr)
        return ToolExecution(
            {
                "outcome": execution.outcome.value,
                "test_observed": execution.test_observed,
                "target_found": execution.target_found,
                "tests_executed": execution.tests_executed,
                "test_failures": execution.test_failures,
                "tests_skipped": execution.tests_skipped,
                "surefire_report_files": execution.surefire_report_files,
                "exit_code": process.exit_code,
                "duration_seconds": process.duration_seconds,
                "timed_out": process.timed_out,
                "compilation_failed": execution.compilation_failed,
                "infrastructure_error": execution.infrastructure_error,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": process.stdout_truncated or stdout_tool_truncated,
                "stderr_truncated": process.stderr_truncated or stderr_tool_truncated,
            },
            verifier_passed=verifier_passed,
        )

    def git_diff(self, arguments: BaseModel) -> ToolExecution:
        if not isinstance(arguments, GitDiffInput):
            raise TypeError("git_diff received the wrong validated input model")
        names = self._git(
            ["diff", "--name-only", "--no-renames", "--no-ext-diff", "-z", "--"],
            operation="collect modified file names",
        )
        modified_files = [path for path in names.stdout.split("\x00") if path]
        for path in modified_files:
            _safe_repository_path(self.environment.worktree, path)
        classifications = {path: classify_file(path) for path in modified_files}

        numstat = self._git(
            ["diff", "--numstat", "--no-renames", "--no-ext-diff", "-z", "--"],
            operation="collect diff statistics",
        )
        insertions = 0
        deletions = 0
        for entry in (value for value in numstat.stdout.split("\x00") if value):
            parts = entry.split("\t", maxsplit=2)
            if len(parts) != 3:
                raise RuntimeError("Git returned malformed diff statistics")
            if parts[0].isdigit():
                insertions += int(parts[0])
            if parts[1].isdigit():
                deletions += int(parts[1])

        diff_result = self._git(
            ["diff", "--binary", "--no-ext-diff", "--"],
            operation="collect bounded candidate diff",
        )
        bounded_diff, tool_truncated = _bounded_utf8(
            diff_result.stdout, MAX_GIT_DIFF_BYTES
        )
        sensitive = any(not _is_production_java(path) for path in modified_files)
        return ToolExecution(
            {
                "modified_files": modified_files,
                "file_classifications": {
                    path: classification.value
                    for path, classification in classifications.items()
                },
                "insertions": insertions,
                "deletions": deletions,
                "diff": bounded_diff,
                "truncated": diff_result.stdout_truncated or tool_truncated,
                "policy_sensitive_files_changed": sensitive,
            }
        )

    def _git(self, arguments: list[str], *, operation: str) -> Any:
        result = self.environment.process_runner.run(
            ["git", *arguments],
            cwd=self.environment.worktree,
            timeout_seconds=GIT_PATCH_TIMEOUT_SECONDS,
        )
        if result.infrastructure_error is not None:
            raise RuntimeError(f"unable to {operation}: {result.infrastructure_error}")
        if result.timed_out:
            raise RuntimeError(f"timed out while attempting to {operation}")
        if result.exit_code != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "Git failed"
            raise RuntimeError(f"unable to {operation}: {detail[:MAX_TOOL_ERROR_CHARS]}")
        if result.stderr_truncated:
            raise RuntimeError(f"Git stderr exceeded its bound while attempting to {operation}")
        return result

    def _repository_files(
        self, path: str, *, limit: int, max_depth: int
    ) -> _RepositoryFiles:
        base = _safe_repository_path(self.environment.worktree, path, allow_root=True)
        if not base.exists():
            raise FileNotFoundError(f"repository path does not exist: {path}")
        if not base.is_dir():
            raise ValueError(f"repository path is not a directory: {path}")

        paths: list[str] = []
        scanned = 0
        truncated = False
        for current, directory_names, file_names in os.walk(
            base,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            relative_current = current_path.relative_to(base)
            current_depth = 0 if relative_current == Path(".") else len(relative_current.parts)
            if current_depth >= max_depth:
                if directory_names:
                    truncated = True
                directory_names[:] = []
            safe_directories: list[str] = []
            for directory_name in sorted(directory_names):
                scanned += 1
                if scanned > MAX_SCANNED_PATHS:
                    truncated = True
                    break
                directory = current_path / directory_name
                lowered_directory = directory_name.casefold()
                if (
                    lowered_directory in IGNORED_DIRECTORY_NAMES
                    or lowered_directory.startswith(".artifacts")
                    or _is_link_or_reparse(directory)
                ):
                    continue
                try:
                    _safe_existing_repository_path(self.environment.worktree, directory)
                except PathSecurityError:
                    continue
                safe_directories.append(directory_name)
            directory_names[:] = safe_directories
            if truncated:
                break

            for file_name in sorted(file_names):
                scanned += 1
                if scanned > MAX_SCANNED_PATHS:
                    truncated = True
                    break
                candidate = current_path / file_name
                if Path(file_name).suffix.casefold() in IGNORED_BINARY_SUFFIXES:
                    continue
                try:
                    safe_candidate = _safe_existing_repository_path(
                        self.environment.worktree,
                        candidate,
                    )
                except PathSecurityError:
                    continue
                try:
                    candidate_stat = safe_candidate.stat()
                except OSError:
                    continue
                if not stat.S_ISREG(candidate_stat.st_mode):
                    continue
                relative = candidate.relative_to(self.environment.worktree).as_posix()
                if any(part.casefold() == ".git" for part in PurePosixPath(relative).parts):
                    continue
                paths.append(relative)
                if len(paths) >= limit:
                    truncated = True
                    break
            if truncated:
                break
        paths.sort()
        return _RepositoryFiles(tuple(paths), scanned, truncated)


def _safe_repository_path(
    worktree: Path,
    raw_path: str,
    *,
    allow_root: bool = False,
) -> Path:
    if "\\" in raw_path or "\x00" in raw_path:
        raise PathSecurityError("repository tool paths must use NUL-free forward slashes")
    if allow_root and raw_path == ".":
        return worktree
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise PathSecurityError(f"repository tool path is not safely relative: {raw_path!r}")
    if any(part.casefold() == ".git" for part in pure.parts):
        raise PathSecurityError("repository tools cannot access Git metadata")
    return safe_worktree_path(worktree, Path(*pure.parts))


def _safe_existing_repository_path(worktree: Path, candidate: Path) -> Path:
    relative = candidate.relative_to(worktree)
    if any(part.casefold() == ".git" for part in relative.parts):
        raise PathSecurityError("repository tools cannot access Git metadata")
    return safe_worktree_path(worktree, relative)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return True
    is_reparse = bool(
        getattr(path_stat, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    return stat.S_ISLNK(path_stat.st_mode) or is_reparse


def _bounded_tail(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_TEST_OUTPUT_CHARS:
        return text, False
    return text[-MAX_TEST_OUTPUT_CHARS:], True


def _bounded_utf8(text: str, maximum_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return text, False
    retained = encoded[:maximum_bytes]
    while retained:
        try:
            return retained.decode("utf-8"), True
        except UnicodeDecodeError:
            retained = retained[:-1]
    return "", True


def _is_production_java(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        classify_file(normalized) is FileClassification.PRODUCTION
        and normalized.casefold().startswith("src/main/java/")
        and normalized.casefold().endswith(".java")
    )


def _tool_error_code_for_patch(
    code: PatchErrorCode,
) -> ToolErrorCode | PatchErrorCode:
    if code in {
        PatchErrorCode.PATCH_PATH_UNSAFE,
        PatchErrorCode.PATCH_OPERATION_UNSUPPORTED,
        PatchErrorCode.PATCH_POLICY_REJECTED,
    }:
        return ToolErrorCode.POLICY_REJECTED
    return code


def create_reposuture_tool_executor(
    environment: RepoSutureToolEnvironment,
) -> ToolExecutor:
    """Register the six approved tools for one isolated worktree."""

    return ToolExecutor(_RepoSutureToolHandlers(environment).definitions())


# Temporary source-level aliases for callers migrating from the former public name.
PatchPilotToolEnvironment = RepoSutureToolEnvironment
create_patchpilot_tool_executor = create_reposuture_tool_executor
