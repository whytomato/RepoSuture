from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from patchpilot.agent import AgentResponse, FakeLLM, ToolCall
from patchpilot.process import ProcessResult, ProcessRunner
from patchpilot.repair import repair_case
from patchpilot.reporting import FinalStatus, TestOutcome

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_CASE = PROJECT_ROOT / "benchmarks/cases/null-email-agent.yaml"
FIXTURE_REPOSITORY = PROJECT_ROOT / "benchmarks/fixtures/null-email-repo"
GOLDEN_PATCH = PROJECT_ROOT / "benchmarks/fixtures/null-email-golden.patch"
SOURCE_PATH = "src/main/java/dev/patchpilot/fixture/UserRegistrationService.java"
TEST_PATH = "src/test/java/dev/patchpilot/fixture/UserRegistrationServiceTest.java"

INEFFECTIVE_PATCH = f"""diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}
--- a/{SOURCE_PATH}
+++ b/{SOURCE_PATH}
@@ -7,5 +7,5 @@ public final class UserRegistrationService {{
         if (email.isBlank()) {{
             throw new InvalidEmailException("email must not be blank");
         }}
-        return new RegisteredUser(username.trim(), email.trim().toLowerCase(Locale.ROOT));
+        return new RegisteredUser(username.strip(), email.trim().toLowerCase(Locale.ROOT));
     }}
"""

REGRESSION_BREAKING_PATCH = f"""diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}
--- a/{SOURCE_PATH}
+++ b/{SOURCE_PATH}
@@ -4,9 +4,9 @@ import java.util.Locale;
 
 public final class UserRegistrationService {{
     public RegisteredUser register(String username, String email) {{
-        if (email.isBlank()) {{
+        if (email == null || email.isBlank()) {{
             throw new InvalidEmailException("email must not be blank");
         }}
-        return new RegisteredUser(username.trim(), email.trim().toLowerCase(Locale.ROOT));
+        return new RegisteredUser(username.trim(), email.trim());
     }}
 }}
"""

TEST_MODIFYING_PATCH = f"""diff --git a/{TEST_PATH} b/{TEST_PATH}
--- a/{TEST_PATH}
+++ b/{TEST_PATH}
@@ -6,7 +6,7 @@ import org.junit.jupiter.api.Test;
 
-class UserRegistrationServiceTest {{
+class UserRegistrationServiceTest {{ // forbidden weakening
     private final UserRegistrationService service = new UserRegistrationService();
 
     @Test
"""

TRAVERSAL_PATCH = """diff --git a/../../outside.txt b/../../outside.txt
new file mode 100644
--- /dev/null
+++ b/../../outside.txt
@@ -0,0 +1 @@
+escaped
"""


def _git(repository: Path, *arguments: str) -> str:
    result = ProcessRunner().run(
        ["git", *arguments],
        cwd=repository,
        timeout_seconds=30,
    )
    assert result.infrastructure_error is None, result.infrastructure_error
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def _initialize_case(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repair-repository"
    shutil.copytree(
        FIXTURE_REPOSITORY,
        repository,
        ignore=shutil.ignore_patterns(".git", "target"),
    )
    _git(repository, "init", "--quiet", "--initial-branch=main")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "config", "user.name", "PatchPilot Repair Tests")
    _git(repository, "config", "user.email", "repair@example.invalid")
    _git(repository, "add", "--all")
    _git(repository, "update-index", "--chmod=+x", "mvnw")
    _git(repository, "commit", "--quiet", "-m", "repair fixture base")
    commit = _git(repository, "rev-parse", "HEAD")

    raw_case = yaml.safe_load(AGENT_CASE.read_text(encoding="utf-8"))
    assert isinstance(raw_case, dict)
    raw_case["repository"] = str(repository)
    raw_case["base_commit"] = commit
    case_path = tmp_path / "agent-case.yaml"
    case_path.write_text(yaml.safe_dump(raw_case, sort_keys=False), encoding="utf-8")
    return repository, case_path


def _git_status(repository: Path) -> tuple[str, str]:
    result = ProcessRunner().run(
        ["git", "status", "--porcelain=v1"],
        cwd=repository,
        timeout_seconds=30,
    )
    assert result.infrastructure_error is None
    assert result.exit_code == 0
    head = ProcessRunner().run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        timeout_seconds=30,
    )
    assert head.exit_code == 0
    return head.stdout.strip(), result.stdout


def _successful_fake() -> FakeLLM:
    return FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(
                    call_id="repair-search-1",
                    name="search_code",
                    arguments={"query": "email", "path": "src", "file_type": "java"},
                )
            ),
            AgentResponse.request_tool(
                ToolCall(
                    call_id="repair-read-2",
                    name="read_file",
                    arguments={"path": SOURCE_PATH, "start_line": 1, "end_line": 80},
                )
            ),
            AgentResponse.request_tool(
                ToolCall(
                    call_id="repair-patch-3",
                    name="apply_patch",
                    arguments={"patch": GOLDEN_PATCH.read_text(encoding="utf-8")},
                )
            ),
            AgentResponse.finish("This must not be needed after deterministic success."),
        ]
    )


def _patch_call(call_id: str, patch: str) -> AgentResponse:
    return AgentResponse.request_tool(
        ToolCall(
            call_id=call_id,
            name="apply_patch",
            arguments={"patch": patch},
        )
    )


@pytest.mark.integration
def test_fake_repair_automatically_runs_real_target_and_regression(
    tmp_path: Path,
) -> None:
    repository, case_path = _initialize_case(tmp_path)
    original = _git_status(repository)
    fake = _successful_fake()

    report = repair_case(
        case_path,
        tmp_path / "artifacts",
        llm_client=fake,
    )

    assert report.final_status is FinalStatus.RESOLVED
    assert report.final_deterministic_status is FinalStatus.RESOLVED
    assert report.workflow == "agent_repair"
    assert report.provider == "fake"
    assert report.model == "FakeLLM"
    assert report.baseline_test_result.outcome is TestOutcome.FAIL
    assert report.patched_target_test_result.outcome is TestOutcome.PASS
    assert report.regression_result.outcome is TestOutcome.PASS
    assert report.total_model_turns == 3
    assert report.total_tool_calls == 3
    assert report.tool_calls_by_name == {
        "apply_patch": 1,
        "read_file": 1,
        "search_code": 1,
    }
    assert report.total_patch_attempts == 1
    assert len(report.patch_attempts) == 1
    assert report.patch_attempts[0].accepted is True
    assert report.patch_attempts[0].file_classifications == {
        SOURCE_PATH: "production"
    }
    assert report.target_test_execution_count == 2
    assert report.regression_execution_count == 1
    assert report.original_repository_unchanged is True
    assert fake.chat_count == 3
    assert _git_status(repository) == original

    report_path = Path(report.artifacts["report"])
    final_patch = Path(report.artifacts["final_patch"])
    trace_path = Path(report.artifacts["trace"])
    assert report_path.is_file()
    assert final_patch.read_text(encoding="utf-8").startswith("diff --git")
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["final_status"] == "RESOLVED"
    events = [
        json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    event_types = {event["event_type"] for event in events}
    assert {
        "model_request_started",
        "model_response_received",
        "tool_call_requested",
        "tool_call_validated",
        "tool_execution_completed",
        "patch_attempted",
        "target_test_completed",
        "regression_test_completed",
        "repair_resolved",
    }.issubset(event_types)
    assert all(event.get("run_id") == report.run_id for event in events)
    assert "sk-test" not in trace_path.read_text(encoding="utf-8")


@pytest.mark.integration
def test_model_claiming_success_without_patch_is_not_resolved(tmp_path: Path) -> None:
    repository, case_path = _initialize_case(tmp_path)
    original = _git_status(repository)

    report = repair_case(
        case_path,
        tmp_path / "artifacts",
        llm_client=FakeLLM([AgentResponse.finish("Fixed. Everything passes.")]),
    )

    assert report.final_status is FinalStatus.MODEL_STOPPED
    assert report.patch_applied is False
    assert report.patched_target_test_result.outcome is TestOutcome.NOT_RUN
    assert report.regression_result.outcome is TestOutcome.NOT_RUN
    assert report.failure_reason is not None
    assert "without deterministic success" in report.failure_reason
    assert _git_status(repository) == original


@pytest.mark.integration
def test_failed_target_diagnostic_allows_revised_patch_to_resolve(tmp_path: Path) -> None:
    repository, case_path = _initialize_case(tmp_path)
    fake = FakeLLM(
        [
            _patch_call("ineffective-1", INEFFECTIVE_PATCH),
            _patch_call("fixed-2", GOLDEN_PATCH.read_text(encoding="utf-8")),
        ]
    )

    report = repair_case(case_path, tmp_path / "artifacts", llm_client=fake)

    assert report.final_status is FinalStatus.RESOLVED
    assert report.total_patch_attempts == 2
    assert report.target_test_execution_count == 3
    assert report.regression_execution_count == 1
    assert report.patched_target_test_result.outcome is TestOutcome.PASS
    patched_log = Path(report.artifacts["patched_target_test_log"]).read_text(
        encoding="utf-8"
    )
    assert '"outcome": "FAIL"' in patched_log
    assert '"outcome": "PASS"' in patched_log
    assert _git_status(repository)[1] == ""


@pytest.mark.integration
def test_regression_failure_allows_second_complete_patch_to_resolve(
    tmp_path: Path,
) -> None:
    repository, case_path = _initialize_case(tmp_path)
    fake = FakeLLM(
        [
            _patch_call("regression-break-1", REGRESSION_BREAKING_PATCH),
            _patch_call("regression-fix-2", GOLDEN_PATCH.read_text(encoding="utf-8")),
        ]
    )

    report = repair_case(case_path, tmp_path / "artifacts", llm_client=fake)

    assert report.final_status is FinalStatus.RESOLVED
    assert report.total_patch_attempts == 2
    assert report.target_test_execution_count == 3
    assert report.regression_execution_count == 2
    regression_log = Path(report.artifacts["regression_test_log"]).read_text(
        encoding="utf-8"
    )
    assert '"outcome": "FAIL"' in regression_log
    assert '"outcome": "PASS"' in regression_log
    assert _git_status(repository)[1] == ""


@pytest.mark.integration
@pytest.mark.parametrize(
    ("patch", "expected_path"),
    [
        (TEST_MODIFYING_PATCH, TEST_PATH),
        (TRAVERSAL_PATCH, "../../outside.txt"),
    ],
)
def test_agent_patch_policy_rejects_test_and_traversal_attempts(
    tmp_path: Path, patch: str, expected_path: str
) -> None:
    repository, case_path = _initialize_case(tmp_path)
    outside = tmp_path / "outside.txt"
    fake = FakeLLM(
        [
            _patch_call("policy-1", patch),
            AgentResponse.finish("I cannot continue."),
        ]
    )

    report = repair_case(case_path, tmp_path / "artifacts", llm_client=fake)

    assert report.final_status is FinalStatus.POLICY_REJECTED
    assert report.patch_applied is False
    assert report.total_patch_attempts == 1
    assert len(report.patch_attempts) == 1
    assert report.patch_attempts[0].accepted is False
    assert report.patch_attempts[0].failure_reason is not None
    assert expected_path in report.patch_attempts[0].failure_reason or (
        expected_path in report.patch_attempts[0].affected_files
    )
    assert report.target_test_execution_count == 1
    assert not outside.exists()
    trace = Path(report.artifacts["trace"]).read_text(encoding="utf-8")
    assert "POLICY_REJECTED" in trace
    assert expected_path in trace
    assert _git_status(repository)[1] == ""


@pytest.mark.integration
def test_model_stops_after_ineffective_patch_without_false_success(tmp_path: Path) -> None:
    repository, case_path = _initialize_case(tmp_path)
    fake = FakeLLM(
        [
            _patch_call("ineffective-1", INEFFECTIVE_PATCH),
            AgentResponse.finish("No further changes."),
        ]
    )

    report = repair_case(case_path, tmp_path / "artifacts", llm_client=fake)

    assert report.final_status is FinalStatus.MODEL_STOPPED
    assert report.patch_applied is False
    assert report.patched_target_test_result.outcome is TestOutcome.FAIL
    assert report.regression_result.outcome is TestOutcome.NOT_RUN
    assert Path(report.artifacts["final_patch"]).stat().st_size == 0
    assert _git_status(repository)[1] == ""


@pytest.mark.integration
def test_repeated_equivalent_patch_exhausts_patch_budget(tmp_path: Path) -> None:
    repository, case_path = _initialize_case(tmp_path)
    fake = FakeLLM(
        [
            _patch_call("repeated-1", INEFFECTIVE_PATCH),
            _patch_call("repeated-2", INEFFECTIVE_PATCH),
            AgentResponse.finish("must not be reached"),
        ]
    )

    report = repair_case(
        case_path,
        tmp_path / "artifacts",
        llm_client=fake,
        max_patch_attempts=2,
    )

    assert report.final_status is FinalStatus.AGENT_BUDGET_EXHAUSTED
    assert report.total_patch_attempts == 2
    assert report.target_test_execution_count == 2
    assert fake.chat_count == 2
    trace = Path(report.artifacts["trace"]).read_text(encoding="utf-8")
    assert '"equivalent": true' in trace
    assert _git_status(repository)[1] == ""


@pytest.mark.integration
def test_malformed_tool_input_is_structured_and_loop_can_recover(tmp_path: Path) -> None:
    repository, case_path = _initialize_case(tmp_path)
    fake = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(
                    call_id="malformed-patch-1",
                    name="apply_patch",
                    arguments={"patch": 7},
                )
            ),
            _patch_call("fixed-after-error-2", GOLDEN_PATCH.read_text(encoding="utf-8")),
        ]
    )

    report = repair_case(case_path, tmp_path / "artifacts", llm_client=fake)

    assert report.final_status is FinalStatus.RESOLVED
    assert report.total_tool_calls == 2
    assert report.total_patch_attempts == 2
    assert report.patch_attempts[0].accepted is False
    assert report.patch_attempts[1].accepted is True
    trace = Path(report.artifacts["trace"]).read_text(encoding="utf-8")
    assert "INVALID_ARGUMENTS" in trace
    assert _git_status(repository)[1] == ""


@pytest.mark.integration
def test_missing_git_header_rejection_then_corrected_patch_resolves_with_real_maven(
    tmp_path: Path,
) -> None:
    repository, case_path = _initialize_case(tmp_path)
    golden = GOLDEN_PATCH.read_text(encoding="utf-8")
    headerless = golden.split("\n", maxsplit=1)[1]
    ambiguous_headerless = headerless + headerless
    fake = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(
                    call_id="read-before-patch-1",
                    name="read_file",
                    arguments={"path": SOURCE_PATH},
                )
            ),
            _patch_call("missing-header-2", ambiguous_headerless),
            _patch_call("corrected-patch-3", headerless),
        ]
    )

    report = repair_case(
        case_path,
        tmp_path / "artifacts",
        llm_client=fake,
        max_patch_attempts=2,
    )

    assert report.final_status is FinalStatus.RESOLVED
    assert report.total_tool_calls == 3
    assert report.total_patch_attempts == 2
    assert report.patch_attempts[0].accepted is False
    assert report.patch_attempts[0].error_code == "PATCH_GIT_HEADER_MISSING"
    assert report.patch_attempts[1].accepted is True
    assert report.patch_attempts[1].normalization_occurred is True
    assert report.patch_attempts[1].normalization_operations == [
        "SYNTHESIZED_SINGLE_FILE_GIT_HEADER"
    ]
    assert report.patch_attempts[1].original_patch_sha256 != (
        report.patch_attempts[1].normalized_patch_sha256
    )
    assert report.target_test_execution_count == 2
    assert report.patched_target_test_result.outcome is TestOutcome.PASS
    assert report.regression_execution_count == 1
    assert report.regression_result.outcome is TestOutcome.PASS
    trace_events = [
        json.loads(line)
        for line in Path(report.artifacts["trace"]).read_text(encoding="utf-8").splitlines()
    ]
    first_rejection = next(
        index
        for index, event in enumerate(trace_events)
        if event["event_type"] == "patch_attempted" and event["status"] == "REJECTED"
    )
    next_patch = next(
        index
        for index, event in enumerate(trace_events[first_rejection + 1 :], first_rejection + 1)
        if event["event_type"] == "patch_attempted"
    )
    assert not any(
        event["event_type"] in {"target_test_completed", "regression_test_completed"}
        for event in trace_events[first_rejection + 1 : next_patch]
    )
    assert _git_status(repository)[1] == ""


class RollbackFailureRunner(ProcessRunner):
    def __init__(self) -> None:
        super().__init__()
        self.final_diff_failed = False

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        input_bytes: bytes | None = None,
    ) -> ProcessResult:
        current = tuple(command)
        if current == ("git", "diff", "--binary", "--no-ext-diff", "--") and not (
            self.final_diff_failed
        ):
            self.final_diff_failed = True
            return _failed_process(current, cwd, "injected final diff failure")
        if self.final_diff_failed and current[:3] == ("git", "reset", "--hard"):
            return _failed_process(current, cwd, "injected rollback failure")
        return super().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
        )


def _failed_process(command: tuple[str, ...], cwd: Path, detail: str) -> ProcessResult:
    return ProcessResult(
        command=command,
        cwd=cwd,
        exit_code=1,
        duration_seconds=0.01,
        stdout="",
        stderr=detail,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_bytes_seen=0,
        stderr_bytes_seen=len(detail),
    )


@pytest.mark.integration
def test_rollback_failure_stops_repair_on_unknown_worktree_state(tmp_path: Path) -> None:
    repository, case_path = _initialize_case(tmp_path)
    fake = FakeLLM(
        [
            _patch_call("rollback-failure-1", GOLDEN_PATCH.read_text(encoding="utf-8")),
            AgentResponse.finish("must not be reached"),
        ]
    )

    report = repair_case(
        case_path,
        tmp_path / "artifacts",
        llm_client=fake,
        process_runner=RollbackFailureRunner(),
    )

    assert report.final_status is FinalStatus.INFRASTRUCTURE_ERROR
    assert report.total_patch_attempts == 1
    assert report.patch_attempts[0].error_code == "PATCH_ROLLBACK_FAILED"
    assert report.patched_target_test_result.outcome is TestOutcome.NOT_RUN
    assert report.regression_result.outcome is TestOutcome.NOT_RUN
    assert fake.chat_count == 1
    assert _git_status(repository)[1] == ""


@pytest.mark.integration
@pytest.mark.parametrize(
    ("limits", "responses", "expected_turns", "expected_tools"),
    [
        (
            {"max_turns": 1},
            [
                AgentResponse.request_tool(
                    ToolCall(
                        call_id="turn-list-1",
                        name="list_files",
                        arguments={"path": "."},
                    )
                ),
                AgentResponse.finish("not reached"),
            ],
            1,
            1,
        ),
        (
            {"max_tool_calls": 1},
            [
                AgentResponse.request_tool(
                    ToolCall(
                        call_id=f"tool-list-{index}",
                        name="list_files",
                        arguments={"path": "."},
                    )
                )
                for index in (1, 2)
            ],
            2,
            1,
        ),
    ],
)
def test_repair_model_and_tool_budgets_terminate_predictably(
    tmp_path: Path,
    limits: dict[str, int],
    responses: list[AgentResponse],
    expected_turns: int,
    expected_tools: int,
) -> None:
    repository, case_path = _initialize_case(tmp_path)

    report = repair_case(
        case_path,
        tmp_path / "artifacts",
        llm_client=FakeLLM(responses),
        **limits,
    )

    assert report.final_status is FinalStatus.AGENT_BUDGET_EXHAUSTED
    assert report.total_model_turns == expected_turns
    assert report.total_tool_calls == expected_tools
    assert report.failure_reason is not None
    assert "maximum" in report.failure_reason
    assert _git_status(repository)[1] == ""
