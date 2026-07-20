"""Helper process that creates a descendant for ProcessRunner timeout tests."""

from __future__ import annotations

import signal
import sys
import time
from multiprocessing import Process
from pathlib import Path


def descendant(marker: str) -> None:
    signal.signal(signal.SIGTERM, lambda *_: None)
    time.sleep(2)
    Path(marker).write_text("survived", encoding="utf-8")


def main() -> int:
    child = Process(target=descendant, args=(sys.argv[1],))
    child.start()
    print("descendant-started", flush=True)
    child.join(timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
