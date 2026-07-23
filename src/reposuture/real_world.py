"""Locked construction of ignored real-world Java/Maven benchmark fixtures."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from reposuture.process import ProcessResult, ProcessRunner

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
SafeId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$", min_length=1, max_length=100),
]
MAX_MANIFEST_BYTES = 1024 * 1024
FIXED_IDENTITY = ("RepoSuture Benchmark", "benchmark@reposuture.invalid")


class RealWorldBenchmarkError(ValueError):
    """Raised when locked upstream evidence or fixture construction is invalid."""


class RealWorldSourceCase(BaseModel):
    """Hidden upstream provenance; this model is never serialized into an Agent Case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: SafeId
    source_slug: SafeId
    upstream_project: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    repository_url: Annotated[str, StringConstraints(pattern=r"^https://github\.com/.+\.git$")]
    license_identifier: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    license_file: str
    license_source_url: Annotated[str, StringConstraints(pattern=r"^https://github\.com/.+")]
    issue_url: Annotated[str, StringConstraints(pattern=r"^https://github\.com/.+")]
    fix_pr_url: Annotated[str, StringConstraints(pattern=r"^https://github\.com/.+")]
    buggy_commit: CommitSha
    fix_commit: CommitSha
    build_system: Literal["maven"]
    module_path: str
    target_test_selector: Annotated[str, StringConstraints(min_length=3, max_length=1000)]
    production_paths: list[str] = Field(min_length=1, max_length=20)
    test_paths: list[str] = Field(min_length=1, max_length=20)
    production_patch_sha256: Sha256
    test_overlay_sha256: Sha256
    license_sha256: Sha256
    deterministic_timestamp: datetime

    @field_validator("license_file", "module_path", mode="before")
    @classmethod
    def validate_relative_path(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("real-world paths must be strings")
        _validate_relative_path(value)
        return value

    @field_validator("production_paths", "test_paths", mode="before")
    @classmethod
    def validate_path_lists(cls, value: object) -> object:
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, str):
                    raise ValueError("real-world source paths must be strings")
                _validate_relative_path(item)
        return value

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if self.deterministic_timestamp.utcoffset() != UTC.utcoffset(
            self.deterministic_timestamp
        ):
            raise ValueError("deterministic timestamp must be timezone-aware UTC")
        if len(self.production_paths) != len(set(self.production_paths)) or len(
            self.test_paths
        ) != len(set(self.test_paths)):
            raise ValueError("real-world path lists must not contain duplicates")
        if set(self.production_paths) & set(self.test_paths):
            raise ValueError("production and test paths must be disjoint")
        if any(not path.startswith("src/main/java/") for path in self.production_paths):
            raise ValueError("production fixes must be under src/main/java")
        if any(not path.startswith("src/test/java/") for path in self.test_paths):
            raise ValueError("test overlays must be under src/test/java")
        if self.buggy_commit == self.fix_commit:
            raise ValueError("buggy and fix commits must differ")
        return self


class RealWorldSourcesManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    retrieval_date: date
    cases: list[RealWorldSourceCase] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> Self:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("real-world Case ids must be unique")
        return self


class RealWorldLockEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: SafeId
    buggy_commit: CommitSha
    fix_commit: CommitSha
    production_patch_sha256: Sha256
    test_overlay_sha256: Sha256
    license_sha256: Sha256
    benchmark_base_commit: CommitSha


class RealWorldSourceLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    sources_manifest_sha256: Sha256
    generated_by: Literal["reposuture-0.3"] = "reposuture-0.3"
    entries: list[RealWorldLockEntry] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> Self:
        ids = [entry.case_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("source-lock Case ids must be unique")
        return self


def _validate_relative_path(value: str) -> None:
    normalized = value.replace("\\", "/")
    if (
        not normalized
        or "\x00" in normalized
        or Path(value).is_absolute()
        or re.match(r"^[A-Za-z]:", normalized)
        or normalized.startswith("../")
        or "/../" in normalized
        or normalized == ".."
    ):
        raise ValueError("real-world paths must be safe relative paths")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_real_world_sources(path: Path) -> tuple[RealWorldSourcesManifest, str]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > MAX_MANIFEST_BYTES:
            raise RealWorldBenchmarkError("real-world source manifest is missing or oversized")
        content = resolved.read_bytes()
        raw = yaml.safe_load(content.decode("utf-8"))
    except RealWorldBenchmarkError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RealWorldBenchmarkError(f"unable to read real-world source manifest: {exc}") from exc
    try:
        return RealWorldSourcesManifest.model_validate(raw), _sha256_bytes(content)
    except ValidationError as exc:
        raise RealWorldBenchmarkError(f"invalid real-world source manifest: {exc}") from exc


def load_real_world_lock(path: Path) -> RealWorldSourceLock:
    try:
        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > MAX_MANIFEST_BYTES:
            raise RealWorldBenchmarkError("real-world source lock is missing or oversized")
        return RealWorldSourceLock.model_validate_json(resolved.read_text(encoding="utf-8"))
    except RealWorldBenchmarkError:
        raise
    except Exception as exc:
        raise RealWorldBenchmarkError(f"invalid real-world source lock: {exc}") from exc


def validate_source_lock(
    manifest: RealWorldSourcesManifest,
    manifest_sha256: str,
    lock: RealWorldSourceLock,
) -> None:
    if lock.sources_manifest_sha256 != manifest_sha256:
        raise RealWorldBenchmarkError("source-lock manifest hash does not match sources.yaml")
    entries = {entry.case_id: entry for entry in lock.entries}
    if set(entries) != {case.case_id for case in manifest.cases}:
        raise RealWorldBenchmarkError("source-lock Case ids do not match sources.yaml")
    for case in manifest.cases:
        entry = entries[case.case_id]
        expected = (
            case.buggy_commit,
            case.fix_commit,
            case.production_patch_sha256,
            case.test_overlay_sha256,
            case.license_sha256,
        )
        actual = (
            entry.buggy_commit,
            entry.fix_commit,
            entry.production_patch_sha256,
            entry.test_overlay_sha256,
            entry.license_sha256,
        )
        if actual != expected:
            raise RealWorldBenchmarkError(
                f"source-lock upstream identity mismatch for {case.case_id}"
            )


def _contained_child(root: Path, name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", name):
        raise RealWorldBenchmarkError("unsafe real-world cache identifier")
    resolved_root = root.expanduser().resolve(strict=True)
    candidate = (resolved_root / name).resolve(strict=False)
    if candidate.parent != resolved_root:
        raise RealWorldBenchmarkError("real-world cache path escapes its configured root")
    if candidate.exists():
        resolved = candidate.resolve(strict=True)
        if resolved.parent != resolved_root or resolved.is_symlink():
            raise RealWorldBenchmarkError("real-world cache path is a symlink or junction escape")
    return candidate


def _run_required(result: ProcessResult, description: str) -> str:
    if not result.succeeded or result.stdout_truncated or result.stderr_truncated:
        detail = result.infrastructure_error or result.stderr or result.stdout
        raise RealWorldBenchmarkError(f"{description} failed: {detail.strip()[:2000]}")
    return result.stdout


def _git(
    runner: ProcessRunner,
    repository: Path,
    *arguments: str,
    timeout_seconds: int = 300,
    input_bytes: bytes | None = None,
) -> str:
    safe = str(repository.resolve(strict=True)).replace("\\", "/")
    return _run_required(
        runner.run(
            ["git", "-c", f"safe.directory={safe}", *arguments],
            cwd=repository,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        ),
        f"git {' '.join(arguments)}",
    )


def _ensure_source_clone(
    runner: ProcessRunner,
    cache_root: Path,
    case: RealWorldSourceCase,
) -> Path:
    source = _contained_child(cache_root, case.source_slug)
    if not source.exists():
        _run_required(
            runner.run(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    case.repository_url,
                    str(source),
                ],
                cwd=cache_root,
                timeout_seconds=900,
            ),
            f"clone {case.repository_url}",
        )
    if not source.is_dir():
        raise RealWorldBenchmarkError("real-world source cache is not a directory")
    configured_remote = _git(runner, source, "remote", "get-url", "origin").strip()
    if configured_remote != case.repository_url:
        raise RealWorldBenchmarkError(
            f"cached upstream URL mismatch for {case.source_slug}"
        )
    for commit in (case.buggy_commit, case.fix_commit):
        check = runner.run(
            [
                "git",
                "-c",
                f"safe.directory={str(source).replace(chr(92), '/')}",
                "cat-file",
                "-e",
                f"{commit}^{{commit}}",
            ],
            cwd=source,
            timeout_seconds=30,
        )
        if not check.succeeded:
            _git(
                runner,
                source,
                "fetch",
                "--no-tags",
                "origin",
                commit,
                timeout_seconds=900,
            )
        _git(runner, source, "cat-file", "-e", f"{commit}^{{commit}}")
    return source.resolve(strict=True)


def _upstream_diff(
    runner: ProcessRunner,
    source: Path,
    case: RealWorldSourceCase,
    paths: list[str],
) -> bytes:
    text = _git(
        runner,
        source,
        "diff",
        "--binary",
        case.buggy_commit,
        case.fix_commit,
        "--",
        *paths,
        timeout_seconds=300,
    )
    content = text.encode("utf-8")
    if not content:
        raise RealWorldBenchmarkError(f"upstream diff is empty for {case.case_id}")
    return content


def _verify_hidden_patch(
    real_world_root: Path,
    case: RealWorldSourceCase,
    production_patch: bytes,
) -> None:
    path = real_world_root / "validation" / "patches" / f"{case.case_id}.patch"
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RealWorldBenchmarkError(
            f"hidden upstream production Patch is missing for {case.case_id}"
        ) from exc
    if not resolved.is_relative_to(real_world_root) or not resolved.is_file():
        raise RealWorldBenchmarkError("hidden production Patch escaped benchmark metadata")
    if _sha256_file(resolved) != case.production_patch_sha256:
        raise RealWorldBenchmarkError(
            f"committed production Patch hash mismatch for {case.case_id}"
        )
    if _sha256_bytes(production_patch) != case.production_patch_sha256:
        raise RealWorldBenchmarkError(
            f"upstream production Patch changed for {case.case_id}"
        )


def _remove_generated_fixture(path: Path, fixtures_root: Path) -> None:
    resolved_root = fixtures_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved.parent != resolved_root or not resolved.name:
        raise RealWorldBenchmarkError("refusing to remove an unexpected fixture path")
    _make_tree_writable(resolved)
    shutil.rmtree(resolved)


def _make_tree_writable(root: Path) -> None:
    for current, directory_names, file_names in os.walk(root, topdown=False):
        current_path = Path(current)
        for name in file_names:
            os.chmod(current_path / name, 0o600)
        for name in directory_names:
            os.chmod(current_path / name, 0o700)
    os.chmod(root, 0o700)


def _rename_generated_fixture(source: Path, destination: Path) -> None:
    last_error: OSError | None = None
    for _attempt in range(5):
        try:
            source.rename(destination)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
    raise RealWorldBenchmarkError(
        f"unable to finalize generated fixture: {last_error}"
    ) from last_error


def _apply_executable_modes(
    runner: ProcessRunner,
    source: Path,
    fixture: Path,
    buggy_commit: str,
) -> None:
    tree = _git(runner, source, "ls-tree", "-r", buggy_commit)
    for line in tree.splitlines():
        metadata, separator, path = line.partition("\t")
        if not separator:
            raise RealWorldBenchmarkError("malformed upstream tree listing")
        mode = metadata.split(" ", 1)[0]
        if mode == "120000":
            raise RealWorldBenchmarkError(
                "upstream symlinks are unsupported in real-world fixtures"
            )
        if mode == "100755":
            _git(runner, fixture, "update-index", "--chmod=+x", "--", path)


def _install_pinned_maven_wrapper(real_world_root: Path, fixture: Path) -> None:
    """Add the project-owned launcher without changing an upstream build definition."""

    wrapper_root = real_world_root.parent / "fixtures" / "null-email-repo"
    sources = (
        (wrapper_root / "mvnw", fixture / "mvnw"),
        (wrapper_root / "mvnw.cmd", fixture / "mvnw.cmd"),
        (
            wrapper_root / ".mvn" / "wrapper" / "maven-wrapper.properties",
            fixture / ".mvn" / "wrapper" / "maven-wrapper.properties",
        ),
    )
    for source, destination in sources:
        resolved_source = source.resolve(strict=True)
        if not resolved_source.is_file() or resolved_source.is_symlink():
            raise RealWorldBenchmarkError("pinned Maven Wrapper source is unsafe")
        if destination.exists() or destination.is_symlink():
            raise RealWorldBenchmarkError(
                "upstream repository already contains a Maven Wrapper path"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resolved_source, destination)


def _build_fixture(
    runner: ProcessRunner,
    real_world_root: Path,
    source_cache: Path,
    fixtures_root: Path,
    case: RealWorldSourceCase,
) -> str:
    source = _ensure_source_clone(runner, source_cache, case)
    source_head_before = _git(runner, source, "rev-parse", "HEAD").strip()
    source_status_before = _git(
        runner, source, "status", "--porcelain=v1", "--untracked-files=all"
    )
    # A deliberately no-checkout partial clone reports tracked files as deleted. The
    # exact bounded status digest is treated as immutable and compared after construction.
    production_patch = _upstream_diff(
        runner, source, case, case.production_paths
    )
    test_overlay = _upstream_diff(runner, source, case, case.test_paths)
    if _sha256_bytes(test_overlay) != case.test_overlay_sha256:
        raise RealWorldBenchmarkError(f"upstream test overlay changed for {case.case_id}")
    license_text = _git(runner, source, "show", f"{case.buggy_commit}:{case.license_file}")
    if _sha256_bytes(license_text.encode("utf-8")) != case.license_sha256:
        raise RealWorldBenchmarkError(f"upstream license hash changed for {case.case_id}")
    _verify_hidden_patch(real_world_root, case, production_patch)

    fixture = _contained_child(fixtures_root, case.case_id)
    if fixture.exists():
        _remove_generated_fixture(fixture, fixtures_root)
    temporary = _contained_child(fixtures_root, f"build-{case.case_id}-{uuid.uuid4().hex[:12]}")
    try:
        _run_required(
            runner.run(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    "--reference-if-able",
                    str(source),
                    case.repository_url,
                    str(temporary),
                ],
                cwd=fixtures_root,
                timeout_seconds=900,
            ),
            f"clone cached source for {case.case_id}",
        )
        # The source cache intentionally has no checkout. Pin line-ending behavior before
        # the first checkout so the benchmark commit retains the exact upstream blobs even
        # when the host's global Git configuration enables core.autocrlf.
        _git(runner, temporary, "config", "core.autocrlf", "false")
        _git(runner, temporary, "checkout", "--detach", case.buggy_commit, timeout_seconds=900)
        _git(runner, temporary, "apply", "--check", "-", input_bytes=test_overlay)
        _git(runner, temporary, "apply", "-", input_bytes=test_overlay)
        changed = {
            line.strip()
            for line in _git(
                runner, temporary, "diff", "--name-only", case.buggy_commit
            ).splitlines()
            if line.strip()
        }
        if changed != set(case.test_paths):
            raise RealWorldBenchmarkError(
                f"test-only overlay changed unexpected paths for {case.case_id}: "
                + ", ".join(sorted(changed)[:20])
            )
        production_check = runner.run(
            [
                "git",
                "-c",
                f"safe.directory={str(temporary).replace(chr(92), '/')}",
                "diff",
                "--exit-code",
                case.buggy_commit,
                "--",
                *case.production_paths,
            ],
            cwd=temporary,
            timeout_seconds=120,
        )
        if not production_check.succeeded:
            raise RealWorldBenchmarkError(
                f"test overlay included a production fix for {case.case_id}"
            )
        _install_pinned_maven_wrapper(real_world_root, temporary)
        metadata = temporary / ".git"
        if not metadata.is_dir() or metadata.is_symlink():
            raise RealWorldBenchmarkError("temporary upstream checkout has unsafe Git metadata")
        _make_tree_writable(metadata)
        shutil.rmtree(metadata)
        _git(runner, temporary, "init", "--quiet", "--initial-branch=main")
        _git(runner, temporary, "config", "core.autocrlf", "false")
        _git(runner, temporary, "config", "user.name", FIXED_IDENTITY[0])
        _git(runner, temporary, "config", "user.email", FIXED_IDENTITY[1])
        _git(runner, temporary, "add", "--all")
        _git(
            runner,
            temporary,
            "add",
            "--force",
            "--",
            ".mvn/wrapper/maven-wrapper.properties",
            "mvnw",
            "mvnw.cmd",
        )
        _apply_executable_modes(runner, source, temporary, case.buggy_commit)
        _git(runner, temporary, "update-index", "--chmod=+x", "--", "mvnw")
        prior_author = os.environ.get("GIT_AUTHOR_DATE")
        prior_committer = os.environ.get("GIT_COMMITTER_DATE")
        try:
            timestamp = case.deterministic_timestamp.isoformat()
            os.environ["GIT_AUTHOR_DATE"] = timestamp
            os.environ["GIT_COMMITTER_DATE"] = timestamp
            _git(
                runner,
                temporary,
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "--no-verify",
                "-m",
                f"benchmark: reproducible {case.case_id} bug",
            )
        finally:
            if prior_author is None:
                os.environ.pop("GIT_AUTHOR_DATE", None)
            else:
                os.environ["GIT_AUTHOR_DATE"] = prior_author
            if prior_committer is None:
                os.environ.pop("GIT_COMMITTER_DATE", None)
            else:
                os.environ["GIT_COMMITTER_DATE"] = prior_committer
        commit = _git(runner, temporary, "rev-parse", "HEAD").strip()
        upstream_production_tree = _git(
            runner,
            source,
            "rev-parse",
            f"{case.buggy_commit}:src/main/java",
        ).strip()
        benchmark_production_tree = _git(
            runner,
            temporary,
            "rev-parse",
            "HEAD:src/main/java",
        ).strip()
        if benchmark_production_tree != upstream_production_tree:
            raise RealWorldBenchmarkError(
                f"benchmark production tree differs from buggy upstream commit for "
                f"{case.case_id}"
            )
        for test_path in case.test_paths:
            expected_test_blob = _git(
                runner,
                source,
                "rev-parse",
                f"{case.fix_commit}:{test_path}",
            ).strip()
            benchmark_test_blob = _git(
                runner,
                temporary,
                "rev-parse",
                f"HEAD:{test_path}",
            ).strip()
            if benchmark_test_blob != expected_test_blob:
                raise RealWorldBenchmarkError(
                    f"benchmark test overlay differs from fixed upstream blob for "
                    f"{case.case_id}: {test_path}"
                )
        if _git(
            runner, temporary, "status", "--porcelain=v1", "--untracked-files=all"
        ):
            raise RealWorldBenchmarkError("generated real-world fixture is dirty")
        _rename_generated_fixture(temporary, fixture)
    finally:
        if temporary.exists():
            _remove_generated_fixture(temporary, fixtures_root)
    source_head_after = _git(runner, source, "rev-parse", "HEAD").strip()
    source_status_after = _git(
        runner, source, "status", "--porcelain=v1", "--untracked-files=all"
    )
    if source_head_after != source_head_before or source_status_after != source_status_before:
        raise RealWorldBenchmarkError(f"upstream cache integrity changed for {case.source_slug}")
    return commit


def _existing_fixture_commit(
    runner: ProcessRunner,
    fixtures_root: Path,
    case_id: str,
    expected_commit: str,
) -> str | None:
    fixture = _contained_child(fixtures_root, case_id)
    if not fixture.exists():
        return None
    head = _git(runner, fixture, "rev-parse", "HEAD").strip()
    status = _git(runner, fixture, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RealWorldBenchmarkError(f"existing fixture is dirty for {case_id}")
    if head != expected_commit:
        raise RealWorldBenchmarkError(f"existing fixture commit mismatch for {case_id}")
    return head


def bootstrap_real_world(
    real_world_root: Path,
    *,
    write_lock: bool = False,
    process_runner: ProcessRunner | None = None,
) -> RealWorldSourceLock:
    """Fetch fixed objects and construct parentless deterministic benchmark repositories."""

    root = real_world_root.expanduser().resolve(strict=True)
    manifest, manifest_sha = load_real_world_sources(root / "sources.yaml")
    cache_root = root / ".cache"
    cache_root.mkdir(exist_ok=True)
    cache_root = cache_root.resolve(strict=True)
    source_cache = cache_root / "candidates"
    fixtures_root = cache_root / "fixtures"
    source_cache.mkdir(exist_ok=True)
    fixtures_root.mkdir(exist_ok=True)
    source_cache = source_cache.resolve(strict=True)
    fixtures_root = fixtures_root.resolve(strict=True)
    if source_cache.parent != cache_root or fixtures_root.parent != cache_root:
        raise RealWorldBenchmarkError("real-world cache directories escaped .cache")
    for stale in fixtures_root.iterdir():
        if stale.is_dir() and stale.name.startswith("build-"):
            _remove_generated_fixture(stale, fixtures_root)
    lock_path = root / "source-lock.json"
    existing_lock: RealWorldSourceLock | None = None
    if lock_path.exists():
        existing_lock = load_real_world_lock(lock_path)
        validate_source_lock(manifest, manifest_sha, existing_lock)
    elif not write_lock:
        raise RealWorldBenchmarkError("source-lock.json is required; bootstrap is locked")
    existing_entries = (
        {entry.case_id: entry for entry in existing_lock.entries}
        if existing_lock is not None
        else {}
    )
    runner = process_runner or ProcessRunner(max_output_bytes=20 * 1024 * 1024)
    entries: list[RealWorldLockEntry] = []
    for case in manifest.cases:
        expected = existing_entries.get(case.case_id)
        commit = (
            _existing_fixture_commit(
                runner, fixtures_root, case.case_id, expected.benchmark_base_commit
            )
            if expected is not None and not write_lock
            else None
        )
        if commit is None:
            commit = _build_fixture(
                runner,
                root,
                source_cache,
                fixtures_root,
                case,
            )
        entries.append(
            RealWorldLockEntry(
                case_id=case.case_id,
                buggy_commit=case.buggy_commit,
                fix_commit=case.fix_commit,
                production_patch_sha256=case.production_patch_sha256,
                test_overlay_sha256=case.test_overlay_sha256,
                license_sha256=case.license_sha256,
                benchmark_base_commit=commit,
            )
        )
    generated = RealWorldSourceLock(
        sources_manifest_sha256=manifest_sha,
        entries=entries,
    )
    if existing_lock is not None and not write_lock and generated != existing_lock:
        raise RealWorldBenchmarkError("generated fixture commits disagree with source-lock.json")
    if write_lock:
        lock_path.write_text(generated.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return generated
