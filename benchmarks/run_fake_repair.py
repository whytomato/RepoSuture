"""Run the user-facing repair orchestration with a deterministic injected model."""

from __future__ import annotations

import argparse
from pathlib import Path

from patchpilot.agent import AgentResponse, FakeLLM, ToolCall
from patchpilot.repair import repair_case
from patchpilot.reporting import FinalStatus

SOURCE_PATH = "src/main/java/dev/patchpilot/fixture/UserRegistrationService.java"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline validation helper: inject a scripted FakeLLM into the real repair "
            "orchestration, Git worktree, Maven, and JUnit runtime."
        )
    )
    parser.add_argument("case_file", type=Path)
    parser.add_argument("--patch-file", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--keep-worktree", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    patch = arguments.patch_file.resolve(strict=True).read_text(encoding="utf-8")
    fake = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(
                    call_id="offline-search-1",
                    name="search_code",
                    arguments={
                        "query": "email",
                        "path": "src",
                        "file_type": "java",
                    },
                )
            ),
            AgentResponse.request_tool(
                ToolCall(
                    call_id="offline-read-2",
                    name="read_file",
                    arguments={
                        "path": SOURCE_PATH,
                        "start_line": 1,
                        "end_line": 80,
                    },
                )
            ),
            AgentResponse.request_tool(
                ToolCall(
                    call_id="offline-patch-3",
                    name="apply_patch",
                    arguments={"patch": patch},
                )
            ),
        ]
    )
    report = repair_case(
        arguments.case_file,
        arguments.artifacts_dir,
        keep_worktree=arguments.keep_worktree,
        llm_client=fake,
        progress=print,
    )
    print(f"Case ID: {report.task_id}")
    print(f"Baseline target test: {report.baseline_test_result.outcome.value}")
    print(f"Patched target test: {report.patched_target_test_result.outcome.value}")
    print(f"Regression: {report.regression_result.outcome.value}")
    print(f"Final status: {report.final_status.value}")
    print(f"Report: {report.artifacts['report']}")
    return 0 if report.final_status is FinalStatus.RESOLVED else 1


if __name__ == "__main__":
    raise SystemExit(main())
