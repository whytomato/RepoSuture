from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from reposuture.agent import (
    AgentExecutionStatus,
    AgentFinalResult,
    AgentLoop,
    AgentResponse,
    AgentState,
    FakeLLM,
    RepoSutureToolEnvironment,
    ToolCall,
    ToolErrorCode,
    create_reposuture_tool_executor,
)
from reposuture.case_spec import TargetTest
from reposuture.maven import MavenRunner
from reposuture.patching import PatchErrorCode
from reposuture.process import ProcessRunner
from reposuture.reporting import TestOutcome
from reposuture.workspace import GitWorktree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SOURCE = PROJECT_ROOT / "benchmarks/fixtures/null-email-repo"
GOLDEN_PATCH = PROJECT_ROOT / "benchmarks/fixtures/null-email-golden.patch"
TARGET = TargetTest(
    class_name="dev.patchpilot.fixture.UserRegistrationServiceTest",
    method_name="shouldRejectNullEmail",
)
SOURCE_PATH = "src/main/java/dev/patchpilot/fixture/UserRegistrationService.java"


def _git(runner: ProcessRunner, repository: Path, *arguments: str) -> str:
    result = runner.run(
        ["git", *arguments],
        cwd=repository,
        timeout_seconds=30,
    )
    assert result.infrastructure_error is None, result.infrastructure_error
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def _initialize_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "agent-java-repository"
    shutil.copytree(
        FIXTURE_SOURCE,
        repository,
        ignore=shutil.ignore_patterns(".git", "target"),
    )
    runner = ProcessRunner()
    _git(runner, repository, "init", "--quiet", "--initial-branch=main")
    _git(runner, repository, "config", "core.autocrlf", "false")
    _git(runner, repository, "config", "user.name", "RepoSuture Agent Tests")
    _git(
        runner,
        repository,
        "config",
        "user.email",
        "reposuture-agent@example.invalid",
    )
    _git(runner, repository, "add", "--all")
    _git(runner, repository, "update-index", "--chmod=+x", "mvnw")
    _git(runner, repository, "commit", "--quiet", "-m", "agent fixture base")
    return repository, _git(runner, repository, "rev-parse", "HEAD")


def _lightweight_environment(tmp_path: Path) -> RepoSutureToolEnvironment:
    worktree = tmp_path / "linked-worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(
        "gitdir: C:/test-repository/.git/worktrees/agent-test\n",
        encoding="utf-8",
    )
    source = worktree / SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_text("class UserRegistrationService { String email; }\n", encoding="utf-8")
    return RepoSutureToolEnvironment(
        worktree=worktree,
        target_test=TARGET,
        target_test_timeout_seconds=30,
        process_runner=ProcessRunner(),
    )


def _state(*, max_iterations: int = 8, max_tool_calls: int = 8) -> AgentState:
    return AgentState(
        task_id="agent-runtime-test",
        issue_description="Reject a null email.",
        max_iterations=max_iterations,
        max_tool_calls=max_tool_calls,
    )


@pytest.mark.integration
def test_apply_patch_rejection_returns_actionable_bounded_feedback(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    repository, commit = _initialize_repository(tmp_path)
    with tempfile.TemporaryDirectory(prefix="ppa-feedback-") as worktrees_root:
        manager = GitWorktree(
            repository=repository,
            base_commit=commit,
            runner=runner,
            worktrees_root=Path(worktrees_root),
        )
        with manager as worktree:
            environment = RepoSutureToolEnvironment(
                worktree=worktree,
                target_test=TARGET,
                target_test_timeout_seconds=300,
                process_runner=runner,
                production_java_only=True,
                max_patch_attempts=2,
            )
            executor = create_reposuture_tool_executor(environment)
            malformed = "@@ -1 +1 @@\n-old\n+new\n"

            result = executor.execute(
                ToolCall(
                    call_id="bad-patch-1",
                    name="apply_patch",
                    arguments={"patch": malformed},
                )
            )

            assert result.success is False
            assert result.error is not None
            assert result.error.code is PatchErrorCode.PATCH_FILE_HEADERS_MISSING
            assert result.output is not None
            assert result.output["status"] == "rejected"
            assert result.output["error_code"] == "PATCH_FILE_HEADERS_MISSING"
            assert result.output["worktree_modified"] is False
            assert result.output["patch_attempts_remaining"] == 1
            assert result.output["required_format"][0] == "diff --git a/<path> b/<path>"
            assert any("leading space" in rule for rule in result.output["rules"])
            assert len(str(result.output)) < 8_000
            assert environment.patch_attempts[0].accepted is False
            assert environment.patch_attempts[0].error_code is (
                PatchErrorCode.PATCH_FILE_HEADERS_MISSING
            )
            assert _git(runner, worktree, "status", "--porcelain=v1") == ""


@pytest.mark.integration
def test_patch_diagnostic_redacts_credential_shaped_text(tmp_path: Path) -> None:
    runner = ProcessRunner()
    repository, commit = _initialize_repository(tmp_path)
    secret = "sk-or-v1-" + "sentinelcredentialvalue"
    with tempfile.TemporaryDirectory(prefix="ppa-secret-") as worktrees_root:
        manager = GitWorktree(
            repository=repository,
            base_commit=commit,
            runner=runner,
            worktrees_root=Path(worktrees_root),
        )
        with manager as worktree:
            environment = RepoSutureToolEnvironment(
                worktree=worktree,
                target_test=TARGET,
                target_test_timeout_seconds=300,
                process_runner=runner,
                production_java_only=True,
                max_patch_attempts=2,
            )
            result = create_reposuture_tool_executor(environment).execute(
                ToolCall(
                    call_id="secret-patch-1",
                    name="apply_patch",
                    arguments={
                        "patch": (
                            f"diff --git a/../{secret}.java b/../{secret}.java\n"
                            f"--- a/../{secret}.java\n"
                            f"+++ b/../{secret}.java\n"
                            "@@ -1 +1 @@\n-old\n+new\n"
                        )
                    },
                )
            )

            assert secret not in result.model_dump_json()
            assert "<redacted>" in result.model_dump_json()


def test_apply_patch_tool_description_contains_a_safe_complete_example(
    tmp_path: Path,
) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    description = next(spec.description for spec in executor.specs if spec.name == "apply_patch")

    assert "Return only the Patch" in description
    assert "do not use Markdown code fences" in description
    assert "diff --git a/src/main/java/example/Example.java" in description
    assert "@@ -1,3 +1,3 @@" in description
    assert " public class Example {" in description


@pytest.mark.integration
def test_agent_executes_complete_fake_repair_workflow_with_real_tools(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    java = runner.run(["java", "-version"], cwd=tmp_path, timeout_seconds=10)
    if java.infrastructure_error is not None:
        pytest.skip(f"Java is unavailable: {java.infrastructure_error}")

    repository, commit = _initialize_repository(tmp_path)
    original_status = _git(runner, repository, "status", "--porcelain=v1")
    with tempfile.TemporaryDirectory(prefix="ppa-") as worktrees_root:
        manager = GitWorktree(
            repository=repository,
            base_commit=commit,
            runner=runner,
            worktrees_root=Path(worktrees_root),
        )
        with manager as worktree:
            baseline = MavenRunner(runner).run_target(
                worktree,
                TARGET,
                timeout_seconds=300,
            )
            assert baseline.outcome is TestOutcome.FAIL
            assert baseline.test_observed is True

            environment = RepoSutureToolEnvironment(
                worktree=worktree,
                target_test=TARGET,
                target_test_timeout_seconds=300,
                process_runner=runner,
            )
            executor = create_reposuture_tool_executor(environment)
            fake_llm = FakeLLM.repair_workflow(
                patch=GOLDEN_PATCH.read_text(encoding="utf-8"),
                source_path=SOURCE_PATH,
            )

            result = AgentLoop(llm=fake_llm, tool_executor=executor).run(_state())

            assert result.execution_status is AgentExecutionStatus.FINISHED
            assert result.iteration_count == 5
            assert result.tool_call_count == 4
            assert result.available_tools == [
                "list_files",
                "search_code",
                "read_file",
                "apply_patch",
                "run_target_test",
                "git_diff",
            ]
            assert [entry.tool_name for entry in result.tool_history] == [
                "search_code",
                "read_file",
                "apply_patch",
                "run_target_test",
            ]
            assert all(entry.success for entry in result.tool_history)
            assert result.last_verifier_passed is True
            assert result.final_result is not None
            assert result.final_result.repair_verified is False
            assert environment.latest_target_execution is not None
            assert environment.latest_target_execution.outcome is TestOutcome.PASS
            assert environment.final_patch is not None
            assert environment.final_patch.startswith("diff --git")
            assert environment.patch_inspection is not None
            assert environment.patch_inspection.affected_files == (SOURCE_PATH,)

            diff_result = executor.execute(
                ToolCall(call_id="fake-diff-5", name="git_diff", arguments={})
            )
            assert diff_result.success is True
            assert diff_result.output is not None
            assert diff_result.output["modified_files"] == [SOURCE_PATH]
            assert diff_result.output["insertions"] == 1
            assert diff_result.output["deletions"] == 1
            assert diff_result.output["policy_sensitive_files_changed"] is False

        assert manager.original_unchanged is True
        assert manager.path is not None
        assert not manager.path.exists()
    assert _git(runner, repository, "status", "--porcelain=v1") == original_status


def test_unknown_tool_call_is_a_structured_rejection(tmp_path: Path) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    fake_llm = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(call_id="unknown-1", name="arbitrary_shell", arguments={})
            ),
            AgentResponse.finish("stop after observing the rejection"),
        ]
    )

    result = AgentLoop(llm=fake_llm, tool_executor=executor).run(_state())

    assert result.execution_status is AgentExecutionStatus.FINISHED
    assert len(result.tool_history) == 1
    rejection = result.tool_history[0]
    assert rejection.success is False
    assert rejection.error is not None
    assert rejection.error.code is ToolErrorCode.UNKNOWN_TOOL


def test_invalid_tool_arguments_are_a_structured_rejection(tmp_path: Path) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    fake_llm = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(call_id="invalid-1", name="list_files", arguments={"path": 7})
            ),
            AgentResponse.finish("stop"),
        ]
    )

    result = AgentLoop(llm=fake_llm, tool_executor=executor).run(_state())

    rejection = result.tool_history[0]
    assert rejection.success is False
    assert rejection.error is not None
    assert rejection.error.code is ToolErrorCode.INVALID_ARGUMENTS
    assert "path" in rejection.error.message


def test_tool_execution_failure_is_structured(tmp_path: Path) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    fake_llm = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(
                    call_id="missing-1",
                    name="read_file",
                    arguments={"path": "does-not-exist.java"},
                )
            ),
            AgentResponse.finish("stop"),
        ]
    )

    result = AgentLoop(llm=fake_llm, tool_executor=executor).run(_state())

    failure = result.tool_history[0]
    assert failure.success is False
    assert failure.error is not None
    assert failure.error.code is ToolErrorCode.EXECUTION_ERROR
    assert "does not exist" in failure.error.message


def test_max_iteration_limit_stops_before_an_extra_model_call(tmp_path: Path) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    repeated_call = AgentResponse.request_tool(
        ToolCall(call_id="list-1", name="list_files", arguments={"path": "."})
    )
    fake_llm = FakeLLM([repeated_call, repeated_call, AgentResponse.finish("never")])

    result = AgentLoop(llm=fake_llm, tool_executor=executor).run(
        _state(max_iterations=1)
    )

    assert result.execution_status is AgentExecutionStatus.ITERATION_LIMIT_REACHED
    assert result.iteration_count == 1
    assert result.tool_call_count == 1
    assert fake_llm.chat_count == 1
    assert result.final_result is not None
    assert result.final_result.failure_reason == "maximum agent iterations reached"


def test_max_tool_call_limit_stops_before_execution(tmp_path: Path) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    fake_llm = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(call_id="list-1", name="list_files", arguments={"path": "."})
            ),
            AgentResponse.request_tool(
                ToolCall(call_id="list-2", name="list_files", arguments={"path": "."})
            ),
            AgentResponse.finish("never"),
        ]
    )

    result = AgentLoop(llm=fake_llm, tool_executor=executor).run(
        _state(max_tool_calls=1)
    )

    assert result.execution_status is AgentExecutionStatus.TOOL_CALL_LIMIT_REACHED
    assert result.iteration_count == 2
    assert result.tool_call_count == 1
    assert len(result.tool_history) == 1
    assert result.final_result is not None
    assert result.final_result.failure_reason == "maximum agent tool calls reached"


def test_llm_client_failure_stops_with_structured_state(tmp_path: Path) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    fake_llm = FakeLLM(
        [
            AgentResponse.request_tool(
                ToolCall(call_id="list-1", name="list_files", arguments={"path": "."})
            )
        ]
    )

    result = AgentLoop(llm=fake_llm, tool_executor=executor).run(_state())

    assert result.execution_status is AgentExecutionStatus.FAILED
    assert result.iteration_count == 2
    assert result.tool_call_count == 1
    assert result.final_result is not None
    assert result.final_result.failure_reason is not None
    assert "FakeLLMExhaustedError" in result.final_result.failure_reason


def test_model_finish_cannot_claim_verified_repair_without_verifier_result(
    tmp_path: Path,
) -> None:
    executor = create_reposuture_tool_executor(_lightweight_environment(tmp_path))
    fake_llm = FakeLLM([AgentResponse.finish("The repair succeeded.")])

    result = AgentLoop(llm=fake_llm, tool_executor=executor).run(_state())

    assert result.execution_status is AgentExecutionStatus.FINISHED
    assert result.last_verifier_passed is None
    assert result.final_result is not None
    assert result.final_result.message == "The repair succeeded."
    assert result.final_result.repair_verified is False


def test_runtime_final_result_cannot_represent_verified_repair() -> None:
    with pytest.raises(ValidationError, match="repair_verified"):
        AgentFinalResult.model_validate({"repair_verified": True})


def test_repository_read_tools_are_bounded_and_reject_metadata_paths(
    tmp_path: Path,
) -> None:
    environment = _lightweight_environment(tmp_path)
    (environment.worktree / "target").mkdir()
    (environment.worktree / "target/result.txt").write_text("email", encoding="utf-8")
    (environment.worktree / ".idea").mkdir()
    (environment.worktree / ".idea/workspace.xml").write_text(
        "email", encoding="utf-8"
    )
    (environment.worktree / "notes.txt").write_text("email", encoding="utf-8")
    executor = create_reposuture_tool_executor(environment)

    search = executor.execute(
        ToolCall(
            call_id="search-1",
            name="search_code",
            arguments={"query": "email", "path": "src"},
        )
    )
    read = executor.execute(
        ToolCall(
            call_id="read-1",
            name="read_file",
            arguments={"path": SOURCE_PATH, "start_line": 1, "end_line": 1},
        )
    )
    metadata = executor.execute(
        ToolCall(
            call_id="metadata-1",
            name="read_file",
            arguments={"path": ".git"},
        )
    )
    escape = executor.execute(
        ToolCall(
            call_id="escape-1",
            name="list_files",
            arguments={"path": "../"},
        )
    )
    listing = executor.execute(
        ToolCall(call_id="list-safe-1", name="list_files", arguments={"path": "."})
    )
    java_search = executor.execute(
        ToolCall(
            call_id="search-java-1",
            name="search_code",
            arguments={"query": "email", "path": ".", "file_type": "java"},
        )
    )

    assert search.success is True
    assert search.output is not None
    assert read.success is True
    assert read.output is not None
    assert metadata.success is False
    assert metadata.error is not None
    assert metadata.error.code is ToolErrorCode.EXECUTION_ERROR
    assert escape.success is False
    assert escape.error is not None
    assert escape.error.code is ToolErrorCode.EXECUTION_ERROR
    assert listing.success is True
    assert listing.output is not None
    listed = listing.output["files"]
    assert not any(path.startswith(("target/", ".idea/")) for path in listed)
    assert java_search.success is True
    assert java_search.output is not None
    assert {match["path"] for match in java_search.output["matches"]} == {SOURCE_PATH}


@pytest.mark.integration
def test_agent_patch_policy_rejects_test_changes_without_modifying_worktree(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner()
    repository, commit = _initialize_repository(tmp_path)
    test_path = "src/test/java/dev/patchpilot/fixture/UserRegistrationServiceTest.java"
    forbidden_patch = f"""diff --git a/{test_path} b/{test_path}
--- a/{test_path}
+++ b/{test_path}
@@ -6,7 +6,7 @@ import org.junit.jupiter.api.Test;
 
-class UserRegistrationServiceTest {{
+class UserRegistrationServiceTest {{ // forbidden weakening
     private final UserRegistrationService service = new UserRegistrationService();
 
     @Test
"""
    with tempfile.TemporaryDirectory(prefix="ppa-policy-") as worktrees_root:
        manager = GitWorktree(
            repository=repository,
            base_commit=commit,
            runner=runner,
            worktrees_root=Path(worktrees_root),
        )
        with manager as worktree:
            environment = RepoSutureToolEnvironment(
                worktree=worktree,
                target_test=TARGET,
                target_test_timeout_seconds=30,
                process_runner=runner,
                production_java_only=True,
            )
            result = create_reposuture_tool_executor(environment).execute(
                ToolCall(
                    call_id="forbidden-test-patch",
                    name="apply_patch",
                    arguments={"patch": forbidden_patch},
                )
            )

            assert result.success is False
            assert result.error is not None
            assert result.error.code is ToolErrorCode.POLICY_REJECTED
            assert len(environment.patch_attempts) == 1
            assert environment.patch_attempts[0].accepted is False
            assert environment.patch_attempts[0].affected_files == (test_path,)
            assert _git(runner, worktree, "status", "--porcelain=v1") == ""
