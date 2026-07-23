"""Isolated Git worktree management and filesystem containment checks."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal

from reposuture.process import ProcessResult, ProcessRunner

GIT_TIMEOUT_SECONDS = 30.0


class PathSecurityError(ValueError):
    """Raised when a configured path can escape its allowed root."""


class WorkspaceError(RuntimeError):
    """Raised when a Git workspace cannot be safely created or removed."""


class OriginalRepositoryChangedError(WorkspaceError):
    """Raised when the original repository differs after worktree execution."""


class ArtifactContainmentError(PathSecurityError):
    """Raised before output creation when artifacts overlap a source Git repository."""


def canonical_git_root(repository: Path, runner: ProcessRunner) -> Path:
    """Resolve a configured repository directory to Git's canonical worktree root."""

    try:
        configured = repository.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceError(f"repository is unavailable: {repository}: {exc}") from exc
    if not configured.is_dir():
        raise WorkspaceError(f"repository is not a directory: {configured}")

    safe_repository = str(configured).replace("\\", "/")
    result = runner.run(
        [
            "git",
            "-c",
            f"safe.directory={safe_repository}",
            "rev-parse",
            "--show-toplevel",
        ],
        cwd=configured,
        timeout_seconds=GIT_TIMEOUT_SECONDS,
    )
    if result.infrastructure_error is not None:
        raise WorkspaceError(
            f"unable to resolve canonical Git root: {result.infrastructure_error}"
        )
    if result.timed_out:
        raise WorkspaceError("timed out while resolving canonical Git root")
    if result.exit_code != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Git returned no detail"
        raise WorkspaceError(f"unable to resolve canonical Git root: {detail}")
    if result.stdout_truncated or result.stderr_truncated:
        raise WorkspaceError("canonical Git root output exceeded the configured limit")

    raw_root = result.stdout.strip()
    if not raw_root or "\x00" in raw_root:
        raise WorkspaceError("Git returned an invalid canonical repository root")
    try:
        root = Path(raw_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceError(f"unable to resolve canonical Git root: {exc}") from exc
    if not root.is_dir() or (
        configured != root and not configured.is_relative_to(root)
    ):
        raise WorkspaceError("configured repository is outside Git's reported top level")
    return root


def validate_artifacts_outside_git_root(
    repository: Path,
    artifacts_dir: Path,
    runner: ProcessRunner,
) -> Path:
    """Return the canonical Git root after proving artifacts cannot be created beneath it."""

    root = canonical_git_root(repository, runner)
    try:
        lexical = Path(os.path.abspath(artifacts_dir.expanduser()))
        requested = artifacts_dir.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ArtifactContainmentError(
            f"artifacts directory cannot be safely resolved: {artifacts_dir}: {exc}"
        ) from exc
    if (
        lexical == root
        or lexical.is_relative_to(root)
        or requested == root
        or requested.is_relative_to(root)
    ):
        raise ArtifactContainmentError(
            "artifacts directory must be outside the canonical Git repository root"
        )
    return root


def safe_worktree_path(worktree: Path, relative_path: str | Path) -> Path:
    """Resolve a relative worktree path and reject lexical or symlink escapes."""

    raw = str(relative_path)
    if not raw or "\x00" in raw:
        raise PathSecurityError("worktree path must be a non-empty, NUL-free relative path")

    candidate_path = Path(relative_path)
    windows_candidate = PureWindowsPath(raw)
    if candidate_path.is_absolute() or windows_candidate.drive or windows_candidate.root:
        raise PathSecurityError(f"absolute paths are forbidden in a worktree: {relative_path}")
    if ".." in candidate_path.parts or ".." in windows_candidate.parts:
        raise PathSecurityError(f"parent traversal is forbidden in a worktree: {relative_path}")

    try:
        resolved_root = worktree.resolve(strict=True)
    except OSError as exc:
        raise PathSecurityError(f"worktree root is unavailable: {worktree}: {exc}") from exc
    if not resolved_root.is_dir():
        raise PathSecurityError(f"worktree root is not a directory: {resolved_root}")

    try:
        resolved_candidate = (resolved_root / candidate_path).resolve(strict=False)
    except OSError as exc:
        raise PathSecurityError(
            f"worktree path cannot be resolved: {relative_path}: {exc}"
        ) from exc
    if not resolved_candidate.is_relative_to(resolved_root):
        raise PathSecurityError(f"path escapes the worktree: {relative_path}")
    return resolved_candidate


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    head_commit: str
    index_sha256: str
    index_bytes: int
    git_status_sha256: str
    git_status_bytes: int
    content_sha256: str


def _tree_digest(repository: Path) -> str:
    """Hash working-tree paths and bytes without following links or reading .git."""

    digest = hashlib.sha256()
    try:
        for current, directory_names, file_names in os.walk(
            repository, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            directory_names.sort()
            file_names.sort()
            if current_path == repository and ".git" in directory_names:
                directory_names.remove(".git")
            if current_path == repository and ".git" in file_names:
                file_names.remove(".git")

            for directory_name in list(directory_names):
                path = current_path / directory_name
                relative = path.relative_to(repository).as_posix().encode("utf-8")
                path_stat = path.lstat()
                is_reparse = bool(
                    getattr(path_stat, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                )
                if stat.S_ISLNK(path_stat.st_mode) or is_reparse:
                    digest.update(b"L\0" + relative + b"\0")
                    try:
                        target = os.readlink(path)
                    except OSError:
                        target = str(path.resolve(strict=False))
                    digest.update(target.encode("utf-8", errors="surrogateescape"))
                    directory_names.remove(directory_name)
                else:
                    digest.update(b"D\0" + relative + b"\0")
                    digest.update(str(stat.S_IMODE(path_stat.st_mode)).encode("ascii"))

            for file_name in file_names:
                path = current_path / file_name
                relative = path.relative_to(repository).as_posix().encode("utf-8")
                path_stat = path.lstat()
                is_reparse = bool(
                    getattr(path_stat, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                )
                if stat.S_ISLNK(path_stat.st_mode) or is_reparse:
                    digest.update(b"L\0" + relative + b"\0")
                    try:
                        target = os.readlink(path)
                    except OSError:
                        target = str(path.resolve(strict=False))
                    digest.update(target.encode("utf-8", errors="surrogateescape"))
                    continue
                digest.update(b"F\0" + relative + b"\0")
                digest.update(str(stat.S_IMODE(path_stat.st_mode)).encode("ascii"))
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
    except OSError as exc:
        raise WorkspaceError(f"unable to fingerprint original repository: {exc}") from exc
    return digest.hexdigest()


class GitWorktree:
    """Context-managed detached worktree that treats the source repository as immutable."""

    def __init__(
        self,
        *,
        repository: Path,
        base_commit: str,
        runner: ProcessRunner,
        worktrees_root: Path,
        keep: bool = False,
    ) -> None:
        if re.fullmatch(r"[0-9a-fA-F]{40}", base_commit) is None:
            raise ValueError("base_commit must be a full 40-character Git commit hash")
        self.repository = repository.expanduser().resolve(strict=False)
        self.base_commit = base_commit
        self.runner = runner
        self.worktrees_root = worktrees_root.expanduser().resolve(strict=False)
        self.keep = keep
        self.path: Path | None = None
        self.original_snapshot: RepositorySnapshot | None = None
        self.final_snapshot: RepositorySnapshot | None = None
        self.original_unchanged: bool | None = None
        self.cleanup_error: str | None = None
        self.created = False

    def __enter__(self) -> Path:
        self.repository = self._validate_repository()
        if self.worktrees_root == self.repository or self.worktrees_root.is_relative_to(
            self.repository
        ):
            raise WorkspaceError("worktrees_root must be outside the original repository")

        self.original_snapshot = self._snapshot()
        try:
            self.worktrees_root.mkdir(parents=True, exist_ok=True)
            resolved_root = self.worktrees_root.resolve(strict=True)
            candidate = resolved_root / f"reposuture-{uuid.uuid4().hex}"
            if candidate.is_relative_to(self.repository):
                raise WorkspaceError("generated worktree path is inside the original repository")
            self.path = candidate
            result = self._git(
                ["worktree", "add", "--detach", str(candidate), self.base_commit],
                timeout_seconds=GIT_TIMEOUT_SECONDS,
            )
            self._require_success(result, "create detached worktree")
            resolved_candidate = candidate.resolve(strict=True)
            if resolved_candidate.parent != resolved_root or (
                resolved_candidate == self.repository
                or resolved_candidate.is_relative_to(self.repository)
                or self.repository.is_relative_to(resolved_candidate)
            ):
                raise WorkspaceError(
                    "created worktree path escaped its root or overlapped the repository"
                )
            self.path = resolved_candidate
            self.created = True
            return self.path
        except BaseException as exc:
            if self.path is not None:
                try:
                    self._cleanup()
                except WorkspaceError as cleanup_exc:
                    self.cleanup_error = str(cleanup_exc)
                    exc.add_note(str(cleanup_exc))
            try:
                self._check_original_unchanged()
            except WorkspaceError as repository_exc:
                exc.add_note(str(repository_exc))
            raise

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> Literal[False]:
        del exception_type, traceback
        cleanup_exception: WorkspaceError | None = None
        try:
            self._cleanup()
        except WorkspaceError as exc:
            cleanup_exception = exc
            self.cleanup_error = str(exc)

        repository_exception: WorkspaceError | None = None
        try:
            self._check_original_unchanged()
        except WorkspaceError as exc:
            repository_exception = exc

        errors = [error for error in (cleanup_exception, repository_exception) if error]
        if exception is not None:
            for error in errors:
                exception.add_note(str(error))
            return False
        if errors:
            raise errors[0]
        return False

    def _validate_repository(self) -> Path:
        top_level = canonical_git_root(self.repository, self.runner)
        self.repository = top_level
        commit_result = self._git(
            ["cat-file", "-e", f"{self.base_commit}^{{commit}}"],
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        )
        self._require_success(commit_result, "validate base commit")
        return top_level

    def _snapshot(self) -> RepositorySnapshot:
        head = self._git(
            ["rev-parse", "--verify", "HEAD^{commit}"],
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        )
        self._require_success(head, "read original repository HEAD")
        if head.stdout_truncated or head.stderr_truncated:
            raise WorkspaceError("original repository HEAD exceeded the output limit")

        index = self._git(
            ["ls-files", "--stage", "--full-name", "-z"],
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        )
        self._require_success(index, "fingerprint original repository index")
        index_flags = self._git(
            ["ls-files", "-v", "-z", "--full-name"],
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        )
        self._require_success(index_flags, "fingerprint original repository index flags")
        index_digest = hashlib.sha256()
        index_digest.update(bytes.fromhex(index.stdout_sha256))
        index_digest.update(bytes.fromhex(index_flags.stdout_sha256))

        status = self._git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        )
        self._require_success(status, "read original repository status")
        return RepositorySnapshot(
            head_commit=head.stdout.strip(),
            index_sha256=index_digest.hexdigest(),
            index_bytes=index.stdout_bytes_seen + index_flags.stdout_bytes_seen,
            git_status_sha256=status.stdout_sha256,
            git_status_bytes=status.stdout_bytes_seen,
            content_sha256=_tree_digest(self.repository),
        )

    def _check_original_unchanged(self) -> None:
        if self.original_snapshot is None:
            return
        current = self._snapshot()
        self.final_snapshot = current
        self.original_unchanged = current == self.original_snapshot
        if not self.original_unchanged:
            raise OriginalRepositoryChangedError(
                "original repository content or Git status changed during verification"
            )

    def _cleanup(self) -> None:
        if (self.keep and self.created) or self.path is None:
            return

        worktree_path = self.path
        remove_result = self._git(
            ["worktree", "remove", "--force", str(worktree_path)],
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        )
        self._require_success(remove_result, "remove temporary worktree")
        if worktree_path.exists():
            raise WorkspaceError(f"temporary worktree was not removed: {worktree_path}")
        self.created = False

    def _git(self, arguments: list[str], *, timeout_seconds: float) -> ProcessResult:
        return self.runner.run(
            ["git", "-c", f"safe.directory={self.repository}", *arguments],
            cwd=self.repository,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _require_success(result: ProcessResult, action: str) -> None:
        if result.infrastructure_error is not None:
            raise WorkspaceError(f"unable to {action}: {result.infrastructure_error}")
        if result.timed_out:
            raise WorkspaceError(f"timed out while attempting to {action}")
        if result.exit_code != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "Git returned no detail"
            raise WorkspaceError(f"unable to {action}: {detail}")
