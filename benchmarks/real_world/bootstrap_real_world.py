"""Command-line bootstrap for the locked real-world benchmark cache."""

from __future__ import annotations

import argparse
from pathlib import Path

from reposuture.real_world import bootstrap_real_world

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-lock",
        action="store_true",
        help="Create/update source-lock.json after verifying fixed upstream evidence.",
    )
    arguments = parser.parse_args()
    lock = bootstrap_real_world(ROOT, write_lock=arguments.write_lock)
    print(f"Real-world fixtures ready: {len(lock.entries)} locked Cases")
    for entry in lock.entries:
        print(f"  {entry.case_id}: {entry.benchmark_base_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
