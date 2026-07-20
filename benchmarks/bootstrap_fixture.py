"""Recreate the benchmark's deterministic nested Git repository after checkout."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from patchpilot.process import ProcessRunner

EXPECTED_COMMIT = "5f31109dd8742b5515baae16c9f7eefb0ed3deba"
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


def bootstrap_fixture(repository: Path) -> str:
    """Initialize or validate a clean fixture repository at its fixed commit."""

    repository = repository.expanduser().resolve(strict=True)
    if not repository.is_dir():
        raise ValueError(f"fixture path is not a directory: {repository}")
    runner = ProcessRunner()
    git_metadata = repository / ".git"
    if git_metadata.exists():
        actual = _git(runner, repository, "rev-parse", "HEAD")
        status = _git(runner, repository, "status", "--porcelain=v1", "--untracked-files=all")
        if actual != EXPECTED_COMMIT or status:
            raise RuntimeError(
                "existing fixture Git repository is not clean at the expected commit"
            )
        return actual

    _git(runner, repository, "init", "--quiet", "--initial-branch=main")
    _git(runner, repository, "config", "core.autocrlf", "false")
    _git(runner, repository, "config", "user.name", "PatchPilot Fixture")
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
            "fixture: reproducible null-email bug",
        )
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    actual = _git(runner, repository, "rev-parse", "HEAD")
    if actual != EXPECTED_COMMIT:
        raise RuntimeError(
            f"fixture commit mismatch: expected {EXPECTED_COMMIT}, created {actual}"
        )
    return actual


def main() -> int:
    fixture = (
        Path(sys.argv[1])
        if len(sys.argv) == 2
        else Path(__file__).resolve().parent / "fixtures/null-email-repo"
    )
    if len(sys.argv) > 2:
        raise SystemExit("usage: python benchmarks/bootstrap_fixture.py [FIXTURE_PATH]")
    commit = bootstrap_fixture(fixture)
    print(f"Fixture ready at {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
