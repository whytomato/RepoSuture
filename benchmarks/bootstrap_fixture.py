"""Recreate the benchmark's deterministic nested Git repository after checkout."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from reposuture.process import ProcessRunner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SOURCES = PROJECT_ROOT / "benchmarks" / "fixture-sources"
DEFAULT_REPOSITORY = PROJECT_ROOT / "benchmarks" / "fixtures" / "null-email-repo"

CASE_IDS = (
    "null-input-validation",
    "pagination-boundary",
    "status-filtering",
    "shipping-eligibility",
    "country-code-normalization",
    "quota-regression-trap",
)
EXPECTED_COMMITS = {
    "null-input-validation": "edd183a37038d966afca53e94e8d8819fc508bb8",
    "pagination-boundary": "08a837f962356daf1a3751d3216441fe366f4a76",
    "status-filtering": "8c9b6162b3e4136c4fca15968aa6fb32acd02b0e",
    "shipping-eligibility": "3a876deb99c25b6b4af85214c06d73550bef353a",
    "country-code-normalization": "5f5882db3d5aaf86609401587853a01146c07b19",
    "quota-regression-trap": "d54d13bf5ef68037bcb392e934b8915195505888",
}
EXPECTED_COMMIT = EXPECTED_COMMITS["null-input-validation"]
FIXED_GIT_ENVIRONMENT = {
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
}


def _git(runner: ProcessRunner, repository: Path, *arguments: str) -> str:
    safe_repository = str(repository).replace("\\", "/")
    result = runner.run(
        ["git", "-c", f"safe.directory={safe_repository}", *arguments],
        cwd=repository,
        timeout_seconds=30,
    )
    if not result.succeeded:
        detail = result.infrastructure_error or result.stderr or result.stdout
        raise RuntimeError(f"Git command failed ({' '.join(arguments)}): {detail.strip()}")
    return result.stdout.strip()


def _commit_fixture(runner: ProcessRunner, repository: Path, case_id: str) -> str:
    _git(runner, repository, "init", "--quiet", "--initial-branch=main")
    _git(runner, repository, "config", "core.autocrlf", "false")
    _git(runner, repository, "config", "user.name", "PatchPilot Fixture")
    # Preserve the published MVP commit identities and fingerprint from before the rename.
    _git(runner, repository, "config", "user.email", "fixture@patchpilot.invalid")
    _git(runner, repository, "add", "--force", "--all")
    _git(runner, repository, "update-index", "--chmod=+x", "mvnw")

    previous = {name: os.environ.get(name) for name in FIXED_GIT_ENVIRONMENT}
    try:
        os.environ.update(FIXED_GIT_ENVIRONMENT)
        _git(
            runner,
            repository,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--no-verify",
            "-m",
            f"fixture: reproducible {case_id} bug",
        )
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return _git(runner, repository, "rev-parse", "HEAD")


def _copy_common_files(repository: Path, destination: Path) -> None:
    for source in sorted(repository.iterdir(), key=lambda path: path.name):
        if source.name in {".git", "src", "target"}:
            continue
        target = destination / source.name
        if source.is_symlink():
            raise RuntimeError(f"fixture common path must not be a symlink: {source}")
        if source.is_dir():
            shutil.copytree(source, target)
        elif source.is_file():
            shutil.copy2(source, target)


def _import_case_commit(
    runner: ProcessRunner,
    repository: Path,
    case_id: str,
) -> str:
    source = (FIXTURE_SOURCES / case_id).resolve(strict=True)
    if source.parent != FIXTURE_SOURCES.resolve(strict=True) or not source.is_dir():
        raise RuntimeError(f"invalid fixture source directory: {source}")
    temporary_parent = Path(tempfile.gettempdir()).expanduser().resolve(strict=True)
    temporary_root = temporary_parent / f"reposuture-{case_id}-{uuid.uuid4().hex}"
    temporary_root.mkdir()
    temporary_root = temporary_root.resolve(strict=True)
    if temporary_root.parent != temporary_parent:
        raise RuntimeError("generated fixture-build directory escaped its temporary root")
    try:
        candidate = temporary_root / "repository"
        candidate.mkdir()
        _copy_common_files(repository, candidate)
        shutil.copytree(source / "src", candidate / "src")
        actual = _commit_fixture(runner, candidate, case_id)
        source_objects = (candidate / ".git" / "objects").resolve(strict=True)
        target_objects = (repository / ".git" / "objects").resolve(strict=True)
        if source_objects.name != "objects" or target_objects.name != "objects":
            raise RuntimeError("invalid Git object directory while importing fixture")
        for object_file in sorted(source_objects.rglob("*")):
            if not object_file.is_file():
                continue
            relative = object_file.relative_to(source_objects)
            destination = target_objects / relative
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(object_file, destination)
        _git(runner, repository, "cat-file", "-e", f"{actual}^{{commit}}")
        _git(
            runner,
            repository,
            "update-ref",
            f"refs/reposuture-benchmarks/{case_id}",
            actual,
        )
        return actual
    finally:
        resolved = temporary_root.resolve(strict=True)
        if resolved.parent != temporary_parent or not resolved.name.startswith(
            f"reposuture-{case_id}-"
        ):
            raise RuntimeError("refusing to clean an unexpected fixture-build directory")
        for current, directory_names, file_names in os.walk(resolved, topdown=False):
            current_path = Path(current)
            for name in file_names:
                os.chmod(current_path / name, 0o600)
            for name in directory_names:
                os.chmod(current_path / name, 0o700)
        os.chmod(resolved, 0o700)
        shutil.rmtree(resolved)


def bootstrap_fixture(repository: Path) -> str:
    """Initialize or validate all benchmark commits without changing the checked-out tree."""

    repository = repository.expanduser().resolve(strict=True)
    if not repository.is_dir():
        raise ValueError(f"fixture path is not a directory: {repository}")
    runner = ProcessRunner()
    git_metadata = repository / ".git"
    actual_commits: dict[str, str] = {}

    if git_metadata.exists():
        actual = _git(runner, repository, "rev-parse", "HEAD")
        status = _git(runner, repository, "status", "--porcelain=v1", "--untracked-files=all")
        if status:
            raise RuntimeError("existing fixture Git repository is not clean")
        actual_commits["null-input-validation"] = actual
    else:
        actual = _commit_fixture(runner, repository, "null-input-validation")
        actual_commits["null-input-validation"] = actual

    _git(
        runner,
        repository,
        "update-ref",
        "refs/reposuture-benchmarks/null-input-validation",
        actual,
    )
    for case_id in CASE_IDS[1:]:
        actual_commits[case_id] = _import_case_commit(runner, repository, case_id)

    status = _git(runner, repository, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RuntimeError("fixture repository changed while importing benchmark commits")

    mismatches = [
        f"{case_id}: expected {EXPECTED_COMMITS[case_id]}, created {actual_commits[case_id]}"
        for case_id in CASE_IDS
        if actual_commits[case_id] != EXPECTED_COMMITS[case_id]
    ]
    if mismatches:
        raise RuntimeError("fixture commit mismatch:\n" + "\n".join(mismatches))
    return actual


def main() -> int:
    fixture = Path(sys.argv[1]) if len(sys.argv) == 2 else DEFAULT_REPOSITORY
    if len(sys.argv) > 2:
        raise SystemExit("usage: python benchmarks/bootstrap_fixture.py [FIXTURE_PATH]")
    commit = bootstrap_fixture(fixture)
    print(f"Fixture ready at {commit} with {len(CASE_IDS)} benchmark commits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
