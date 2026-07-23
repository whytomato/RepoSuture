"""Temporary compatibility entry point for the former ``patchpilot`` command."""

from __future__ import annotations

import sys

from reposuture.cli import app


def legacy_main() -> None:
    """Forward to the sole CLI implementation without changing its exit status."""

    print(
        "warning: 'patchpilot' is deprecated; use 'reposuture' instead",
        file=sys.stderr,
    )
    app(prog_name="patchpilot")


if __name__ == "__main__":
    legacy_main()
