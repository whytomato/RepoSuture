import os
from pathlib import Path

import pytest

from patchpilot.process import ProcessRunner
from patchpilot.workspace import PathSecurityError, safe_worktree_path


def test_safe_worktree_path_accepts_contained_relative_path(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)

    result = safe_worktree_path(worktree, "src/Main.java")

    assert result == (worktree / "src/Main.java").resolve()


@pytest.mark.parametrize("candidate", ["../outside.txt", "src/../../outside.txt"])
def test_safe_worktree_path_rejects_parent_escape(
    tmp_path: Path, candidate: str
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(PathSecurityError):
        safe_worktree_path(worktree, candidate)


@pytest.mark.parametrize(
    "candidate",
    [
        r"C:\outside.txt",
        r"C:drive-relative.txt",
        r"\\server\share\outside.txt",
        r"\\?\C:\outside.txt",
        r"src\..\..\outside.txt",
    ],
)
def test_safe_worktree_path_rejects_windows_escape_forms_on_every_platform(
    tmp_path: Path, candidate: str
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(PathSecurityError):
        safe_worktree_path(worktree, candidate)


def test_safe_worktree_path_rejects_absolute_path(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(PathSecurityError):
        safe_worktree_path(worktree, tmp_path / "outside.txt")


def test_safe_worktree_path_rejects_symlink_escape(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    outside = tmp_path / "outside"
    worktree.mkdir()
    outside.mkdir()
    link = worktree / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"symlinks are unavailable on this host: {exc}")
        junction = ProcessRunner().run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            cwd=tmp_path,
            timeout_seconds=10,
        )
        if not junction.succeeded:
            pytest.skip(
                "neither symlink nor Windows junction creation is available: "
                f"{junction.stderr or junction.stdout}"
            )

    with pytest.raises(PathSecurityError):
        safe_worktree_path(worktree, "linked/escaped.txt")


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case-insensitive")
def test_safe_worktree_path_handles_root_case_without_prefix_comparison(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "WorkTree"
    (worktree / "src").mkdir(parents=True)
    differently_cased_root = Path(str(worktree).swapcase())

    result = safe_worktree_path(differently_cased_root, "src/Main.java")

    assert result.is_relative_to(worktree.resolve())
