"""Versioned, strictly validated RepoSuture Bug Case specifications."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    field_validator,
)

MAX_CASE_BYTES = 1_048_576

CaseId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
CommitHash = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-fA-F]{40}$"),
]
JavaClassName = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=512,
        pattern=r"^(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*[A-Za-z_$][A-Za-z0-9_$]*$",
    ),
]
JavaMethodName = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z_$][A-Za-z0-9_$]*$",
    ),
]


class CaseValidationError(ValueError):
    """Raised when a case file cannot be safely loaded or validated."""


class TargetTest(BaseModel):
    """A JUnit target represented as data rather than an executable command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    class_name: JavaClassName
    method_name: JavaMethodName

    @property
    def maven_selector(self) -> str:
        return f"{self.class_name}#{self.method_name}"


class AgentBudgets(BaseModel):
    """Hard execution limits for a single model-driven repair run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_model_turns: Annotated[StrictInt, Field(ge=1, le=50)]
    max_tool_calls: Annotated[StrictInt, Field(ge=1, le=200)]
    max_patch_attempts: Annotated[StrictInt, Field(ge=1, le=10)]
    max_target_test_executions: Annotated[StrictInt, Field(ge=1, le=25)]
    max_regression_executions: Annotated[StrictInt, Field(ge=1, le=10)]
    max_wall_clock_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)]
    api_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=600)]
    api_max_retries: Annotated[StrictInt, Field(ge=0, le=5)]
    max_output_tokens: Annotated[StrictInt, Field(ge=128, le=32_768)]
    max_retained_model_output_bytes: Annotated[
        StrictInt, Field(ge=1_024, le=1_048_576)
    ]
    max_retained_tool_output_bytes: Annotated[
        StrictInt, Field(ge=1_024, le=1_048_576)
    ]


class AllowedFilePolicy(BaseModel):
    """The only file policy supported by the first autonomous-repair milestone."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    production_java_only: Literal[True]


class BugCase(BaseModel):
    """The supported schema version for a deterministic bug verification case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    id: CaseId
    repository: Path
    base_commit: CommitHash
    issue_title: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)
    ]
    issue_description: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=20_000),
    ]
    target_test: TargetTest
    target_test_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=3_600)]
    regression_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)]
    golden_patch: Path
    expected_baseline_failure: Literal["test_failure"]

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: object) -> object:
        if type(value) is not int:  # bool is an int subclass but is not a schema version
            raise ValueError("schema_version must be the integer 1")
        return value

    @field_validator("repository", "golden_patch", mode="before")
    @classmethod
    def validate_input_path(cls, value: object) -> object:
        if not isinstance(value, (str, Path)):
            raise ValueError("path must be a string")
        raw = str(value)
        if not raw.strip():
            raise ValueError("path must not be empty")
        if "\x00" in raw:
            raise ValueError("path must not contain NUL")
        return value


class AgentBugCase(BaseModel):
    """A model-driven repair Case that deliberately contains no candidate Patch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2]
    workflow: Literal["agent_repair"]
    id: CaseId
    repository: Path
    base_commit: CommitHash
    issue_title: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)
    ]
    issue_description: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=20_000),
    ]
    target_test: TargetTest
    target_test_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=3_600)]
    regression_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)]
    expected_baseline_failure: Literal["test_failure"]
    agent_budgets: AgentBudgets
    allowed_file_policy: AllowedFilePolicy

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 2")
        return value

    @field_validator("repository", mode="before")
    @classmethod
    def validate_input_path(cls, value: object) -> object:
        if not isinstance(value, (str, Path)):
            raise ValueError("path must be a string")
        raw = str(value)
        if not raw.strip():
            raise ValueError("path must not be empty")
        if "\x00" in raw:
            raise ValueError("path must not contain NUL")
        return value


def _resolve_from_case(case_file: Path, configured_path: Path) -> Path:
    if configured_path.is_absolute():
        return configured_path.resolve(strict=False)
    return (case_file.parent / configured_path).resolve(strict=False)


def _load_case_mapping(case_file: Path) -> tuple[Path, dict[str, object]]:
    try:
        resolved_case = case_file.expanduser().resolve(strict=True)
        if not resolved_case.is_file():
            raise CaseValidationError(f"case path is not a file: {resolved_case}")
        size = resolved_case.stat().st_size
        if size > MAX_CASE_BYTES:
            raise CaseValidationError(
                f"case file exceeds the {MAX_CASE_BYTES}-byte limit: {resolved_case}"
            )
        raw = yaml.safe_load(resolved_case.read_text(encoding="utf-8"))
    except CaseValidationError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CaseValidationError(f"unable to read case file: {exc}") from exc

    if not isinstance(raw, dict):
        raise CaseValidationError("case YAML root must be a mapping")

    return resolved_case, raw


def load_case(case_file: Path) -> BugCase:
    """Load the deterministic schema-v1 Case and resolve its input paths."""

    resolved_case, raw = _load_case_mapping(case_file)

    try:
        case = BugCase.model_validate(raw)
    except ValidationError as exc:
        raise CaseValidationError(f"invalid case: {exc}") from exc

    return case.model_copy(
        update={
            "repository": _resolve_from_case(resolved_case, case.repository),
            "golden_patch": _resolve_from_case(resolved_case, case.golden_patch),
        }
    )


def load_agent_case(case_file: Path) -> AgentBugCase:
    """Load the separate schema-v2 Agent Case without accepting a golden Patch."""

    resolved_case, raw = _load_case_mapping(case_file)
    try:
        case = AgentBugCase.model_validate(raw)
    except ValidationError as exc:
        raise CaseValidationError(f"invalid agent case: {exc}") from exc

    return case.model_copy(
        update={"repository": _resolve_from_case(resolved_case, case.repository)}
    )
