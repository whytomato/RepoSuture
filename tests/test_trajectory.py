from __future__ import annotations

from datetime import UTC, datetime

from reposuture.reporting import SanitizedTraceEvent
from reposuture.trajectory import LiveTrajectoryRenderer, TrajectoryView, render_trajectory_text

NOW = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
RUN_ID = "run-trajectory"


def _event(
    sequence: int,
    event_type: str,
    status: str,
    metadata: dict[str, object] | None = None,
    *,
    duration: float | None = None,
) -> SanitizedTraceEvent:
    return SanitizedTraceEvent(
        sequence=sequence,
        timestamp=NOW,
        event_type=event_type,
        status=status,
        duration=duration,
        run_id=RUN_ID,
        metadata=metadata or {},
    )


def test_compact_trajectory_renders_agent_actions_observations_and_verification() -> None:
    events = [
        _event(
            1,
            "worktree_created",
            "OK",
            {"base_commit": "a" * 40, "worktree_name": "reposuture-safe"},
        ),
        _event(
            2,
            "target_test_completed",
            "FAIL",
            {"phase": "baseline", "test_observed": True},
        ),
        _event(
            3,
            "agent_execution_started",
            "STARTED",
            {"max_model_turns": 12},
        ),
        _event(
            4,
            "model_request_started",
            "STARTED",
            {"model_turn": 1, "max_model_turns": 12},
        ),
        _event(
            5,
            "tool_call_requested",
            "REQUESTED",
            {
                "model_turn": 1,
                "tool_name": "search_code",
                "arguments": {"query": "email", "path": "src/main/java"},
            },
        ),
        _event(
            6,
            "tool_execution_completed",
            "OK",
            {
                "model_turn": 1,
                "tool_name": "search_code",
                "observation": {"match_count": 3, "truncated": False},
            },
        ),
        _event(
            7,
            "patch_attempted",
            "ACCEPTED",
            {"patch_attempt_id": 1, "affected_files": ["src/main/java/Example.java"]},
        ),
        _event(
            8,
            "target_test_completed",
            "PASS",
            {"phase": "patched", "patch_attempt_id": 1},
        ),
        _event(9, "regression_test_completed", "PASS", {"patch_attempt_id": 1}),
        _event(
            10,
            "agent_finished",
            "RESOLVED",
            {
                "model_turns": 1,
                "tool_calls": 2,
                "patch_attempts": 1,
                "duration_seconds": 3.2,
            },
        ),
    ]

    rendered = render_trajectory_text(events, view=TrajectoryView.COMPACT)

    assert "[PREPARE] Creating isolated worktree at commit aaaaaaaa" in rendered
    assert "[VERIFY]  Baseline target test" in rendered
    assert "[TURN 1/12] DECIDE" in rendered
    assert '[ACTION]  search_code query="email" path="src/main/java"' in rendered
    assert "[OBSERVE] search_code returned 3 matches; truncated=false" in rendered
    assert "[OBSERVE] Patch attempt 1 accepted; 1 production file changed" in rendered
    assert "[VERIFY]  Target test (Patch 1)" in rendered
    assert "[VERIFY]  Regression suite (Patch 1)" in rendered
    assert "[FINISH]  RESOLVED" in rendered
    assert "turns=1 tools=2 patches=1 duration=3.2s" in rendered


def test_regression_failure_and_candidate_revert_render_before_next_decision() -> None:
    events = [
        _event(1, "regression_test_completed", "FAIL", {"patch_attempt_id": 1}),
        _event(
            2,
            "agent_replan_requested",
            "REGRESSION_FAILED",
            {
                "reasons": ["REGRESSION_FAILED", "CANDIDATE_REVERTED"],
                "patch_attempt_id": 1,
                "next_model_turn": 4,
            },
        ),
        _event(
            3,
            "model_request_started",
            "STARTED",
            {"model_turn": 4, "max_model_turns": 12},
        ),
    ]

    rendered = render_trajectory_text(events, view=TrajectoryView.COMPACT)

    replan = (
        "[REPLAN] Candidate reverted; regression diagnostic returned to Agent "
        "reasons=REGRESSION_FAILED,CANDIDATE_REVERTED"
    )
    assert replan in rendered
    assert rendered.index("Regression suite (Patch 1)") < rendered.index(replan)
    assert rendered.index(replan) < rendered.index("[TURN 4/12] DECIDE")


def test_rejected_patch_renders_error_code_and_feedback_replan() -> None:
    events = [
        _event(
            1,
            "patch_attempted",
            "REJECTED",
            {
                "patch_attempt_id": 1,
                "error_code": "PATCH_HUNK_INVALID",
                "git_diagnostic": "raw diagnostic must not be rendered",
            },
        ),
        _event(
            2,
            "agent_replan_requested",
            "PATCH_REJECTED",
            {
                "reasons": ["PATCH_REJECTED"],
                "error_code": "PATCH_HUNK_INVALID",
                "next_model_turn": 2,
            },
        ),
    ]

    rendered = render_trajectory_text(events, view=TrajectoryView.VERBOSE)

    assert "Patch attempt 1 rejected; error_code=PATCH_HUNK_INVALID" in rendered
    assert (
        "[REPLAN] Patch rejection diagnostic returned to Agent reasons=PATCH_REJECTED"
        in rendered
    )
    assert "raw diagnostic must not be rendered" not in rendered


def test_budget_exhaustion_renders_a_bounded_finish_event() -> None:
    event = _event(
        1,
        "agent_finished",
        "AGENT_BUDGET_EXHAUSTED",
        {
            "model_turns": 12,
            "tool_calls": 8,
            "patch_attempts": 2,
            "duration_seconds": 44.0,
            "failure_reason": "maximum model turns reached" + "x" * 10_000,
        },
    )

    rendered = render_trajectory_text([event], view=TrajectoryView.VERBOSE)

    assert "[FINISH]  AGENT_BUDGET_EXHAUSTED" in rendered
    assert "turns=12 tools=8 patches=2 duration=44.0s" in rendered
    assert len(rendered) < 500


def test_verbose_arguments_are_bounded_and_hidden_reasoning_is_never_rendered() -> None:
    secret = "sk-or-v1-" + "credentialmaterialthatmustnotappear"
    events = [
        _event(
            1,
            "model_response_received",
            "OK",
            {
                "model_turn": 1,
                "reasoning": "private chain of thought must not appear",
                "visible_message": "also not used to reconstruct reasoning",
            },
        ),
        _event(
            2,
            "tool_call_requested",
            "REQUESTED",
            {
                "model_turn": 1,
                "tool_name": "search_code",
                "arguments": {
                    "query": "Authorization: Bearer " + secret + "x" * 5_000,
                    "path": "src/main/java",
                    "file_type": "java",
                },
            },
        ),
        _event(
            3,
            "tool_call_requested",
            "REQUESTED",
            {
                "model_turn": 1,
                "tool_name": "apply_patch",
                "arguments": {
                    "patch": "diff --git a/Secret.java b/Secret.java\n+secret body",
                    "patch_size": 57,
                    "patch_sha256": "a" * 64,
                },
            },
        ),
    ]

    rendered = render_trajectory_text(events, view=TrajectoryView.VERBOSE)

    assert "private chain of thought" not in rendered
    assert "reconstruct reasoning" not in rendered
    assert secret not in rendered
    assert "Authorization: Bearer" not in rendered
    assert "diff --git" not in rendered
    assert "secret body" not in rendered
    assert "patch_size=57" in rendered
    assert len(rendered) < 1_000


def test_live_renderer_matches_batch_semantics() -> None:
    events = [
        _event(1, "agent_execution_started", "STARTED"),
        _event(
            2,
            "model_request_started",
            "STARTED",
            {"model_turn": 1, "max_model_turns": 2},
        ),
        _event(
            3,
            "agent_finished",
            "AGENT_BUDGET_EXHAUSTED",
            {"model_turns": 1},
        ),
    ]
    chunks: list[str] = []
    renderer = LiveTrajectoryRenderer(view=TrajectoryView.COMPACT, sink=chunks.append)

    for event in events:
        renderer(event)

    assert "".join(chunks) == render_trajectory_text(
        events,
        view=TrajectoryView.COMPACT,
    )


def test_verbose_view_includes_durations_error_codes_and_budget_counters() -> None:
    events = [
        _event(
            1,
            "model_request_started",
            "STARTED",
            {
                "model_turn": 2,
                "max_model_turns": 12,
                "tool_calls": 1,
                "max_tool_calls": 30,
                "patch_attempts": 0,
                "max_patch_attempts": 4,
            },
        ),
        _event(
            2,
            "tool_call_requested",
            "REQUESTED",
            {
                "model_turn": 2,
                "tool_name": "search_code",
                "arguments": {"query": "quota", "path": "src/main/java"},
                "tool_call_number": 2,
                "max_tool_calls": 30,
                "patch_attempts_remaining": 4,
            },
        ),
        _event(
            3,
            "tool_execution_completed",
            "OK",
            {
                "model_turn": 2,
                "tool_name": "search_code",
                "observation": {"match_count": 1, "truncated": False},
            },
            duration=0.125,
        ),
        _event(
            4,
            "patch_attempted",
            "REJECTED",
            {
                "patch_attempt_id": 1,
                "model_turn": 2,
                "error_code": "PATCH_HUNK_INVALID",
                "patch_attempts_remaining": 3,
            },
        ),
        _event(5, "target_test_completed", "FAIL", duration=1.25),
    ]

    rendered = render_trajectory_text(events, view=TrajectoryView.VERBOSE)

    assert "tools=1/30 patches=0/4" in rendered
    assert "tools=2/30 patches_remaining=4" in rendered
    assert "duration=0.125s" in rendered
    assert "error_code=PATCH_HUNK_INVALID; patches_remaining=3" in rendered
    assert "FAIL (1.250s)" in rendered
