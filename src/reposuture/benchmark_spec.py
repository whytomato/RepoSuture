"""Strict benchmark suite loading, public/hidden separation, and fingerprints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from reposuture.case_spec import (
    AgentBudgets,
    AgentBugCase,
    BugCase,
    CaseId,
    CaseValidationError,
    load_agent_case,
    load_case,
)
from reposuture.process import ProcessRunner
from reposuture.workspace import WorkspaceError, canonical_git_root

MAX_SUITE_BYTES = 1_048_576
MAX_SCRIPT_BYTES = 1_048_576
MAX_FINGERPRINT_GIT_OUTPUT_BYTES = 10 * 1024 * 1024

BenchmarkTag = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
RelativeFile = Annotated[
    Path,
    Field(description="A suite-relative file that is resolved inside benchmarks/"),
]


class BenchmarkSuiteError(ValueError):
    """Raised when a suite cannot be loaded, linked, or fingerprinted safely."""


class BenchmarkCaseReference(BaseModel):
    """Paths that join one public Agent Case to private harness-only metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: CaseId
    agent_case: RelativeFile
    validation_case: RelativeFile
    scripted_case: RelativeFile | None = None
    tags: list[BenchmarkTag] = Field(min_length=1, max_length=20)

    @field_validator("agent_case", "validation_case", "scripted_case", mode="before")
    @classmethod
    def validate_file_path(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, (str, Path)):
            raise ValueError("benchmark file path must be a string")
        raw = str(value)
        if not raw.strip() or "\x00" in raw:
            raise ValueError("benchmark file path must be nonempty and contain no NUL")
        if Path(raw).is_absolute() or re.match(r"^[A-Za-z]:", raw) or raw.startswith("\\\\"):
            raise ValueError("benchmark file paths must be relative")
        return value

    @model_validator(mode="after")
    def validate_tags(self) -> Self:
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("case tags must be unique")
        return self


class BenchmarkSuiteManifest(BaseModel):
    """Versioned top-level benchmark suite manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    suite_id: CaseId
    description: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    default_runs_per_case: Annotated[StrictInt, Field(ge=1, le=20)]
    default_agent_budgets: AgentBudgets
    tags: list[BenchmarkTag] = Field(min_length=1, max_length=20)
    notes: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, max_length=4_000)
    ] | None = None
    cases: list[BenchmarkCaseReference] = Field(min_length=1, max_length=100)

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def validate_unique_values(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case ids must be unique")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("suite tags must be unique")
        return self


class ScriptedBenchmarkCase(BaseModel):
    """Harness-only deterministic model actions, never an Agent prompt payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    case_id: CaseId
    search_query: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)
    ]
    read_files: list[
        Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1_024)]
    ] = Field(min_length=1, max_length=10)
    patch_files: list[RelativeFile] = Field(min_length=1, max_length=4)

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1")
        return value

    @field_validator("patch_files", mode="before")
    @classmethod
    def validate_patch_paths(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        for candidate in value:
            if not isinstance(candidate, (str, Path)):
                raise ValueError("scripted patch path must be a string")
            raw = str(candidate)
            if not raw.strip() or "\x00" in raw or Path(raw).is_absolute():
                raise ValueError("scripted patch paths must be nonempty relative paths")
        return value

    @model_validator(mode="after")
    def validate_read_paths(self) -> Self:
        for path in self.read_files:
            normalized = path.replace("\\", "/")
            if (
                normalized.startswith("/")
                or normalized.startswith("../")
                or "/../" in normalized
                or normalized.casefold().startswith(".git/")
            ):
                raise ValueError("scripted read paths must remain inside the worktree")
        return self


class BenchmarkFingerprint(BaseModel):
    """Auditable SHA-256 components for one fully linked benchmark suite."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    suite_manifest_sha256: Annotated[
        str, StringConstraints(pattern=r"^[0-9a-f]{64}$")
    ]
    case_files_sha256: dict[str, Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]]
    support_files_sha256: dict[
        str, Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    ]
    base_commits: dict[str, Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]]
    fixture_content_sha256: dict[
        str, Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    ]


@dataclass(frozen=True, slots=True)
class LoadedBenchmarkCase:
    reference: BenchmarkCaseReference
    agent_case_path: Path
    validation_case_path: Path
    scripted_case_path: Path | None
    agent_case: AgentBugCase
    validation_case: BugCase
    scripted_case: ScriptedBenchmarkCase | None
    scripted_patch_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class LoadedBenchmarkSuite:
    path: Path
    benchmark_root: Path
    manifest: BenchmarkSuiteManifest
    cases: tuple[LoadedBenchmarkCase, ...]
    fingerprint: BenchmarkFingerprint


def _read_yaml_mapping(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise BenchmarkSuiteError(f"benchmark path is not a file: {resolved}")
        if resolved.stat().st_size > maximum_bytes:
            raise BenchmarkSuiteError(f"benchmark file exceeds {maximum_bytes} bytes: {resolved}")
        value = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except BenchmarkSuiteError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise BenchmarkSuiteError(f"unable to read benchmark file: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkSuiteError("benchmark YAML root must be a mapping")
    return value


def _resolve_suite_file(configured: Path, *, suite_dir: Path, benchmark_root: Path) -> Path:
    candidate = (suite_dir / configured).resolve(strict=True)
    if not candidate.is_relative_to(benchmark_root) or not candidate.is_file():
        raise BenchmarkSuiteError(
            f"benchmark file must resolve inside {benchmark_root}: {configured.as_posix()}"
        )
    return candidate


def _canonical_yaml_sha256(path: Path) -> str:
    value = _read_yaml_mapping(path, maximum_bytes=MAX_SUITE_BYTES)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _public_case_values(case: AgentBugCase | BugCase) -> tuple[object, ...]:
    return (
        case.id,
        case.repository,
        case.base_commit,
        case.issue_title,
        case.issue_description,
        case.target_test,
        case.target_test_timeout_seconds,
        case.regression_timeout_seconds,
        case.expected_baseline_failure,
    )


def _validate_repository_and_tree(
    repository: Path,
    base_commit: str,
    *,
    benchmark_root: Path,
    runner: ProcessRunner,
) -> str:
    try:
        resolved_repository = repository.resolve(strict=True)
    except OSError as exc:
        raise BenchmarkSuiteError(f"benchmark repository is unavailable: {repository}") from exc
    if not resolved_repository.is_dir() or not resolved_repository.is_relative_to(benchmark_root):
        raise BenchmarkSuiteError("benchmark repository must be a directory inside benchmarks/")
    try:
        actual_top_level = canonical_git_root(resolved_repository, runner)
    except WorkspaceError as exc:
        raise BenchmarkSuiteError(f"invalid benchmark repository: {exc}") from exc
    if not actual_top_level.is_relative_to(benchmark_root):
        raise BenchmarkSuiteError("benchmark Git roots must remain inside benchmarks/")
    safe_repository = str(actual_top_level).replace("\\", "/")
    prefix = ["git", "-c", f"safe.directory={safe_repository}"]
    commit = runner.run(
        [*prefix, "cat-file", "-e", f"{base_commit}^{{commit}}"],
        cwd=actual_top_level,
        timeout_seconds=30,
    )
    if not commit.succeeded:
        raise BenchmarkSuiteError(f"invalid base commit for benchmark repository: {base_commit}")
    tree = runner.run(
        [*prefix, "ls-tree", "-r", "--full-tree", "-z", base_commit],
        cwd=actual_top_level,
        timeout_seconds=30,
    )
    if not tree.succeeded or tree.stdout_truncated or tree.stderr_truncated:
        detail = tree.infrastructure_error or tree.stderr or "fixture tree output was truncated"
        raise BenchmarkSuiteError(f"unable to fingerprint fixture tree: {detail.strip()}")
    if tree.stdout_bytes_seen > MAX_FINGERPRINT_GIT_OUTPUT_BYTES or not tree.stdout:
        raise BenchmarkSuiteError("fixture tree is empty or exceeds the fingerprint limit")
    return tree.stdout_sha256


def _build_fingerprint(
    suite_path: Path,
    cases: tuple[LoadedBenchmarkCase, ...],
    *,
    benchmark_root: Path,
    runner: ProcessRunner,
) -> BenchmarkFingerprint:
    case_files: dict[str, str] = {}
    support_files: dict[str, str] = {}
    commits: dict[str, str] = {}
    fixture_trees: dict[str, str] = {}
    for loaded in cases:
        case_id = loaded.reference.id
        case_files[f"{case_id}:agent"] = _canonical_yaml_sha256(loaded.agent_case_path)
        case_files[f"{case_id}:validation"] = _canonical_yaml_sha256(
            loaded.validation_case_path
        )
        if loaded.scripted_case_path is not None:
            case_files[f"{case_id}:scripted"] = _canonical_yaml_sha256(
                loaded.scripted_case_path
            )
        support_files[f"{case_id}:golden"] = _file_sha256(
            loaded.validation_case.golden_patch
        )
        for index, path in enumerate(loaded.scripted_patch_paths, start=1):
            support_files[f"{case_id}:scripted-patch-{index}"] = _file_sha256(path)
        commits[case_id] = loaded.agent_case.base_commit
        fixture_trees[case_id] = _validate_repository_and_tree(
            loaded.agent_case.repository,
            loaded.agent_case.base_commit,
            benchmark_root=benchmark_root,
            runner=runner,
        )
    suite_manifest_sha256 = _canonical_yaml_sha256(suite_path)
    components: dict[str, object] = {
        "suite_manifest_sha256": suite_manifest_sha256,
        "case_files_sha256": case_files,
        "support_files_sha256": support_files,
        "base_commits": commits,
        "fixture_content_sha256": fixture_trees,
    }
    encoded = json.dumps(components, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return BenchmarkFingerprint(
        value=hashlib.sha256(encoded).hexdigest(),
        suite_manifest_sha256=suite_manifest_sha256,
        case_files_sha256=case_files,
        support_files_sha256=support_files,
        base_commits=commits,
        fixture_content_sha256=fixture_trees,
    )


def load_benchmark_suite(
    suite_file: Path,
    *,
    process_runner: ProcessRunner | None = None,
) -> LoadedBenchmarkSuite:
    """Load, cross-check, and fingerprint a complete benchmark suite."""

    try:
        suite_path = suite_file.expanduser().resolve(strict=True)
    except OSError as exc:
        raise BenchmarkSuiteError(f"suite manifest is unavailable: {suite_file}") from exc
    raw = _read_yaml_mapping(suite_path, maximum_bytes=MAX_SUITE_BYTES)
    try:
        manifest = BenchmarkSuiteManifest.model_validate(raw)
    except ValidationError as exc:
        raise BenchmarkSuiteError(f"invalid benchmark suite: {exc}") from exc
    suite_dir = suite_path.parent
    benchmark_root = suite_dir.parent.resolve(strict=True)
    runner = process_runner or ProcessRunner(max_output_bytes=MAX_FINGERPRINT_GIT_OUTPUT_BYTES)
    loaded_cases: list[LoadedBenchmarkCase] = []
    for reference in manifest.cases:
        try:
            agent_path = _resolve_suite_file(
                reference.agent_case,
                suite_dir=suite_dir,
                benchmark_root=benchmark_root,
            )
            validation_path = _resolve_suite_file(
                reference.validation_case,
                suite_dir=suite_dir,
                benchmark_root=benchmark_root,
            )
            scripted_path = (
                _resolve_suite_file(
                    reference.scripted_case,
                    suite_dir=suite_dir,
                    benchmark_root=benchmark_root,
                )
                if reference.scripted_case is not None
                else None
            )
        except OSError as exc:
            raise BenchmarkSuiteError(
                f"missing benchmark case file for {reference.id}: {exc}"
            ) from exc
        try:
            agent_case = load_agent_case(agent_path)
            validation_case = load_case(validation_path)
        except CaseValidationError as exc:
            raise BenchmarkSuiteError(f"invalid linked Case for {reference.id}: {exc}") from exc
        if (
            reference.id != agent_case.id
            or reference.id != validation_case.id
            or _public_case_values(agent_case) != _public_case_values(validation_case)
        ):
            raise BenchmarkSuiteError(
                f"public Agent and hidden validation metadata disagree for {reference.id}"
            )
        if agent_case.agent_budgets != manifest.default_agent_budgets:
            raise BenchmarkSuiteError(
                f"Agent budgets for {reference.id} disagree with suite defaults"
            )
        try:
            configured_repository = agent_case.repository.resolve(strict=True)
            golden_patch = validation_case.golden_patch.resolve(strict=True)
        except OSError as exc:
            raise BenchmarkSuiteError(f"linked benchmark path is unavailable: {exc}") from exc
        if not configured_repository.is_relative_to(benchmark_root):
            raise BenchmarkSuiteError("benchmark repositories must remain inside benchmarks/")
        try:
            repository = canonical_git_root(configured_repository, runner)
        except WorkspaceError as exc:
            raise BenchmarkSuiteError(f"invalid benchmark repository: {exc}") from exc
        if not repository.is_relative_to(benchmark_root):
            raise BenchmarkSuiteError("benchmark Git roots must remain inside benchmarks/")
        agent_case = agent_case.model_copy(update={"repository": repository})
        validation_case = validation_case.model_copy(update={"repository": repository})
        if golden_patch.is_relative_to(repository):
            raise BenchmarkSuiteError("golden patches must not be inside the Agent repository")
        scripted_case: ScriptedBenchmarkCase | None = None
        patch_paths: list[Path] = []
        if scripted_path is not None:
            scripted_raw = _read_yaml_mapping(
                scripted_path, maximum_bytes=MAX_SCRIPT_BYTES
            )
            try:
                scripted_case = ScriptedBenchmarkCase.model_validate(scripted_raw)
            except ValidationError as exc:
                raise BenchmarkSuiteError(
                    f"invalid scripted Case for {reference.id}: {exc}"
                ) from exc
            if scripted_case.case_id != reference.id:
                raise BenchmarkSuiteError(f"scripted Case id disagrees for {reference.id}")
            for configured_patch in scripted_case.patch_files:
                try:
                    patch_path = (
                        scripted_path.parent / configured_patch
                    ).resolve(strict=True)
                except OSError as exc:
                    raise BenchmarkSuiteError(
                        f"scripted patch is unavailable for {reference.id}: "
                        f"{configured_patch}"
                    ) from exc
                if not patch_path.is_file() or not patch_path.is_relative_to(
                    benchmark_root
                ):
                    raise BenchmarkSuiteError(
                        "scripted patches must be files inside benchmarks/"
                    )
                if patch_path.is_relative_to(repository):
                    raise BenchmarkSuiteError(
                        "scripted patches must not be inside the Agent repository"
                    )
                patch_paths.append(patch_path)
        loaded_cases.append(
            LoadedBenchmarkCase(
                reference=reference,
                agent_case_path=agent_path,
                validation_case_path=validation_path,
                scripted_case_path=scripted_path,
                agent_case=agent_case,
                validation_case=validation_case,
                scripted_case=scripted_case,
                scripted_patch_paths=tuple(patch_paths),
            )
        )
    loaded_tuple = tuple(loaded_cases)
    fingerprint = _build_fingerprint(
        suite_path,
        loaded_tuple,
        benchmark_root=benchmark_root,
        runner=runner,
    )
    return LoadedBenchmarkSuite(
        path=suite_path,
        benchmark_root=benchmark_root,
        manifest=manifest,
        cases=loaded_tuple,
        fingerprint=fingerprint,
    )
