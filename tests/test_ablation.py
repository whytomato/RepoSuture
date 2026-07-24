from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from reposuture.ablation import (
    AblationPlan,
    build_ablation_plan,
    prepare_ablation_plan,
    run_benchmark_ablation,
)
from reposuture.benchmark_spec import load_benchmark_suite
from reposuture.cli import app
from reposuture.reporting import AgentExecutionMode, FinalStatus, TestOutcome

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MVP_SUITE = PROJECT_ROOT / "benchmarks" / "suites" / "mvp.yaml"
MODES = (
    AgentExecutionMode.FULL_AGENT,
    AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK,
)


def _plan() -> AblationPlan:
    suite = load_benchmark_suite(MVP_SUITE)
    return build_ablation_plan(
        suite,
        selected_cases=suite.cases,
        provider="openai",
        model="deepseek/deepseek-v4-pro",
        execution_modes=MODES,
        budget_values=suite.manifest.default_agent_budgets.model_dump(),
        project_git_commit="a" * 40,
        project_worktree_dirty=False,
    )


def test_six_case_ablation_plan_is_interleaved_and_exactly_twelve() -> None:
    first = _plan()
    second = _plan()

    assert first == second
    assert first.total_attempts == 12
    assert len({item.run_id for item in first.items}) == 12
    assert [item.execution_mode for item in first.items[:2]] == list(MODES)
    assert [item.execution_mode for item in first.items[2:4]] == list(
        reversed(MODES)
    )


def test_ablation_cli_dry_run_performs_no_execution_or_artifact_write(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "not-created"
    result = CliRunner().invoke(
        app,
        [
            "benchmark-ablation",
            str(MVP_SUITE),
            "--artifacts-dir",
            str(artifacts),
            "--provider",
            "openai",
            "--model",
            "deepseek/deepseek-v4-pro",
            "--case",
            "pagination-boundary",
            "--mode",
            "full-agent",
            "--mode",
            "single-candidate-no-feedback",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "1 Cases x 2 modes = 2 live attempts" in result.stdout
    assert not artifacts.exists()


def test_ablation_resume_rejects_changed_mode_schedule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "reposuture.ablation._git_metadata",
        lambda _runner, _root: ("c" * 40, False),
    )
    root = tmp_path / "resume"
    _, _, plan = prepare_ablation_plan(
        MVP_SUITE,
        provider="openai",
        model="deepseek/deepseek-v4-pro",
        execution_modes=MODES,
        case_ids=("pagination-boundary",),
    )
    root.mkdir()
    (root / "ablation-plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="plan does not match"):
        run_benchmark_ablation(
            MVP_SUITE,
            root,
            provider="openai",
            model="deepseek/deepseek-v4-pro",
            execution_modes=tuple(reversed(MODES)),
            case_ids=("pagination-boundary",),
            resume=True,
        )


@pytest.mark.integration
def test_scripted_regression_trap_compares_feedback_with_real_maven(
    tmp_path: Path,
) -> None:
    summary = run_benchmark_ablation(
        MVP_SUITE,
        tmp_path / "ablation",
        provider="scripted",
        model="scripted/feedback-ablation",
        execution_modes=MODES,
        case_ids=("quota-regression-trap",),
    )

    assert summary.total_attempts == 2
    by_mode = {run.agent_execution_mode: run for run in summary.runs}
    full = by_mode[AgentExecutionMode.FULL_AGENT]
    single = by_mode[AgentExecutionMode.SINGLE_CANDIDATE_NO_FEEDBACK]
    assert full.terminal_status is FinalStatus.RESOLVED
    assert full.target_test_result is TestOutcome.PASS
    assert full.regression_result is TestOutcome.PASS
    assert full.patch_attempts == 2
    assert single.terminal_status is FinalStatus.REGRESSION_FAILED
    assert single.target_test_result is TestOutcome.PASS
    assert single.regression_result is TestOutcome.FAIL
    assert single.patch_attempts == 1
    assert (tmp_path / "ablation" / "ablation-summary.json").is_file()
    assert (tmp_path / "ablation" / "ablation-report.md").is_file()
