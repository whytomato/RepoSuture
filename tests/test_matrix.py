from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reposuture.benchmark import _scripted_llm
from reposuture.benchmark_reporting import (
    BenchmarkExecutionMode,
    BenchmarkRunRecord,
    BenchmarkSummary,
    FailureCategory,
    aggregate_benchmark_runs,
)
from reposuture.benchmark_spec import load_benchmark_suite
from reposuture.cli import app
from reposuture.matrix import (
    MatrixPlan,
    _model_metrics,
    build_matrix_plan,
    prepare_matrix_plan,
    run_benchmark_matrix,
    wilson_interval,
)
from reposuture.reporting import FinalStatus, TestOutcome

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITE = PROJECT_ROOT / "benchmarks" / "suites" / "mvp.yaml"
MODELS = ("z-ai/glm-5.2", "openai/gpt-5-mini")


def _plan() -> MatrixPlan:
    suite = load_benchmark_suite(SUITE)
    return build_matrix_plan(
        suite,
        selected_cases=suite.cases,
        models=MODELS,
        runs_per_case=3,
        provider="openai",
        budget_values=suite.manifest.default_agent_budgets.model_dump(),
        project_git_commit="a" * 40,
        project_worktree_dirty=False,
        random_seed=7,
    )


def test_two_model_three_run_mvp_plan_is_exactly_36_and_deterministic() -> None:
    first = _plan()
    second = _plan()

    assert first == second
    assert first.total_attempts == 36
    assert len(first.items) == 36
    assert {item.model for item in first.items} == set(MODELS)
    assert len({item.run_id for item in first.items}) == 36
    assert len({item.artifact_directory for item in first.items}) == 36


def test_interleaving_alternates_model_order_across_neighboring_cases() -> None:
    plan = _plan()
    pairs = [plan.items[index : index + 2] for index in range(0, 12, 2)]

    assert [item.model for item in pairs[0]] == list(reversed(MODELS))
    assert [item.model for item in pairs[1]] == list(MODELS)
    assert all(pair[0].case_id == pair[1].case_id for pair in pairs)


def test_prepare_plan_filters_cases_without_creating_artifacts(tmp_path: Path) -> None:
    _, selected, plan = prepare_matrix_plan(
        SUITE,
        provider="scripted",
        models=("scripted/a", "scripted/b"),
        runs_per_case=3,
        case_ids=("pagination-boundary",),
    )

    assert [case.reference.id for case in selected] == ["pagination-boundary"]
    assert plan.total_attempts == 6
    assert not any(tmp_path.iterdir())


def test_cli_dry_run_reports_exact_mvp_formula_without_artifacts(tmp_path: Path) -> None:
    artifacts = tmp_path / "must-not-exist"
    result = CliRunner().invoke(
        app,
        [
            "benchmark-matrix",
            str(SUITE),
            "--artifacts-dir",
            str(artifacts),
            "--provider",
            "openai",
            "--model",
            MODELS[0],
            "--model",
            MODELS[1],
            "--runs-per-case",
            "3",
            "--schedule",
            "interleaved",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "6 Cases x 3 runs x 2 models = 36 live attempts" in result.stdout
    assert "Schedule: interleaved, sequential" in result.stdout
    assert not artifacts.exists()


def test_resume_rejects_scripted_mode_before_any_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="live-model"):
        run_benchmark_matrix(
            SUITE,
            tmp_path / "scripted-resume",
            provider="scripted",
            models=("scripted/a", "scripted/b"),
            runs_per_case=1,
            case_ids=("null-input-validation",),
            resume=True,
        )


def _write_live_plan(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, commit: str = "c" * 40
) -> MatrixPlan:
    monkeypatch.setattr(
        "reposuture.matrix._git_metadata", lambda _runner, _root: (commit, False)
    )
    _, _, plan = prepare_matrix_plan(
        SUITE,
        provider="openai",
        models=("test/model-a", "test/model-b"),
        runs_per_case=1,
        case_ids=("null-input-validation",),
    )
    root.mkdir()
    (root / "matrix-plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return plan


def test_resume_rejects_another_commit_before_model_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "commit-mismatch"
    _write_live_plan(root, monkeypatch, commit="c" * 40)
    monkeypatch.setattr(
        "reposuture.matrix._git_metadata", lambda _runner, _root: ("d" * 40, False)
    )
    with pytest.raises(ValueError, match="plan does not match"):
        run_benchmark_matrix(
            SUITE,
            root,
            provider="openai",
            models=("test/model-a", "test/model-b"),
            runs_per_case=1,
            case_ids=("null-input-validation",),
            resume=True,
        )


def test_resume_rejects_another_model_before_model_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "model-mismatch"
    _write_live_plan(root, monkeypatch)
    with pytest.raises(ValueError, match="plan does not match"):
        run_benchmark_matrix(
            SUITE,
            root,
            provider="openai",
            models=("test/model-a", "test/model-c"),
            runs_per_case=1,
            case_ids=("null-input-validation",),
            resume=True,
        )


def test_resume_rejects_another_fingerprint_before_model_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fingerprint-mismatch"
    _write_live_plan(root, monkeypatch)
    path = root / "matrix-plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["benchmark_fingerprint"] = "e" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="plan does not match"):
        run_benchmark_matrix(
            SUITE,
            root,
            provider="openai",
            models=("test/model-a", "test/model-b"),
            runs_per_case=1,
            case_ids=("null-input-validation",),
            resume=True,
        )


@pytest.mark.parametrize(
    ("successes", "attempts"), [(0, 18), (9, 18), (18, 18)]
)
def test_wilson_interval_is_bounded(successes: int, attempts: int) -> None:
    interval = wilson_interval(successes, attempts)

    assert 0 <= interval.lower <= interval.upper <= 1
    assert interval.lower <= successes / attempts <= interval.upper


def test_matrix_plan_rejects_duplicate_models() -> None:
    suite = load_benchmark_suite(SUITE)
    with pytest.raises(ValueError, match="unique"):
        build_matrix_plan(
            suite,
            selected_cases=suite.cases,
            models=("same", "same"),
            runs_per_case=3,
            provider="openai",
            budget_values=suite.manifest.default_agent_budgets.model_dump(),
            project_git_commit="a" * 40,
            project_worktree_dirty=False,
            random_seed=None,
        )


@pytest.mark.integration
def test_two_scripted_identities_execute_real_independent_repairs(
    tmp_path: Path,
) -> None:
    summary = run_benchmark_matrix(
        SUITE,
        tmp_path / "matrix",
        provider="scripted",
        models=("scripted/identity-a", "scripted/identity-b"),
        runs_per_case=1,
        case_ids=("null-input-validation",),
    )

    assert summary.execution_mode is BenchmarkExecutionMode.SCRIPTED_OFFLINE
    assert summary.total_attempts == 2
    assert all(run.final_status is FinalStatus.RESOLVED for run in summary.runs)
    assert {run.model for run in summary.runs} == {
        "scripted/identity-a",
        "scripted/identity-b",
    }
    assert len({Path(run.report_path).parent for run in summary.runs}) == 2
    assert all(run.original_repository_unchanged for run in summary.runs)
    assert all(run.failure_category is FailureCategory.RESOLVED for run in summary.runs)
    assert summary.requested_provider == summary.provider == "scripted"
    assert all(model.total_attempts == 1 for model in summary.per_model)
    matrix_json = json.loads(
        (tmp_path / "matrix" / "matrix-summary.json").read_text(encoding="utf-8")
    )
    assert len(matrix_json["runs"]) == 2
    csv_lines = (tmp_path / "matrix" / "matrix-runs.csv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(csv_lines) == 3
    markdown = (tmp_path / "matrix" / "matrix-report.md").read_text(
        encoding="utf-8"
    )
    assert "scripted/identity-a" in markdown
    assert "scripted/identity-b" in markdown
    serialized = json.dumps(matrix_json)
    assert "OPENAI_API_KEY" not in serialized
    assert "Authorization" not in serialized
    assert (tmp_path / "matrix" / "matrix-completion.json").is_file()

    source_model_metrics = next(
        item for item in summary.per_model if item.model == summary.runs[0].model
    )
    first_model_summary = BenchmarkSummary.model_validate_json(
        Path(source_model_metrics.benchmark_summary_path).read_text(encoding="utf-8")
    )
    failed_payload = summary.runs[0].model_dump(mode="python")
    failed_payload.update(
        {
            "run_id": summary.runs[0].run_id + "-complete-failure",
            "final_status": FinalStatus.MODEL_STOPPED,
            "failure_category": FailureCategory.MODEL_STOPPED,
            "target_test_result": TestOutcome.NOT_RUN,
            "regression_result": TestOutcome.NOT_RUN,
            "generated_tool_calls": summary.runs[0].total_tool_calls + 3,
            "executed_tool_calls": summary.runs[0].total_tool_calls,
            "discarded_extra_tool_calls": 3,
            "model_stopped_without_verification": True,
        }
    )
    complete_failure = BenchmarkRunRecord.model_validate(failed_payload)
    aggregate = aggregate_benchmark_runs(
        suite_id=summary.suite_id,
        fingerprint=summary.benchmark_fingerprint,
        execution_mode=summary.execution_mode,
        provider="scripted",
        model=summary.runs[0].model,
        runs_per_case=2,
        selected_case_ids=[summary.runs[0].case_id],
        runs=[summary.runs[0], complete_failure],
        reproducibility=first_model_summary.reproducibility,
        artifacts={},
    )
    metrics = _model_metrics(
        summary.runs[0].model,
        aggregate,
        model_root=tmp_path / "metrics",
        runs_per_case=2,
    )
    assert aggregate.total_attempts == 2
    assert aggregate.unresolved_attempts == 1
    assert aggregate.per_case[0].attempt_count == 2
    assert aggregate.failure_counts_by_category[FailureCategory.MODEL_STOPPED] == 1
    assert metrics.discarded_extra_tool_calls == 3
    assert metrics.generated_tool_calls == metrics.executed_tool_calls + 3
    assert metrics.tool_call_discard_rate == pytest.approx(
        3 / metrics.generated_tool_calls
    )


@pytest.mark.integration
def test_live_mode_injected_matrix_resume_accepts_complete_runs_and_rejects_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "reposuture.matrix._git_metadata", lambda _runner, _root: ("b" * 40, False)
    )
    root = tmp_path / "live-matrix"

    def factory(_model: str, loaded: object, _run_number: int):
        return _scripted_llm(loaded)  # type: ignore[arg-type]

    initial = run_benchmark_matrix(
        SUITE,
        root,
        provider="openai",
        models=("test/model-a", "test/model-b"),
        runs_per_case=1,
        case_ids=("null-input-validation",),
        llm_factory=factory,
    )
    resumed = run_benchmark_matrix(
        SUITE,
        root,
        provider="openai",
        models=("test/model-a", "test/model-b"),
        runs_per_case=1,
        case_ids=("null-input-validation",),
        resume=True,
        llm_factory=lambda *_arguments: (_ for _ in ()).throw(
            AssertionError("resume made a model request")
        ),
    )

    assert [run.run_id for run in resumed.runs] == [run.run_id for run in initial.runs]
    first_manifest = json.loads(
        (
            Path(initial.runs[0].report_path).parent / "matrix-attempt.json"
        ).read_text(encoding="utf-8")
    )
    assert first_manifest["requested_provider"] == "openai"
    assert first_manifest["runtime_provider"] == "openai"

    matrix_summary_path = root / "matrix-summary.json"
    original_summary = matrix_summary_path.read_text(encoding="utf-8")
    matrix_summary_path.write_text(original_summary + " ", encoding="utf-8")
    with pytest.raises(ValueError, match=r"completion artifact hash mismatch"):
        run_benchmark_matrix(
            SUITE,
            root,
            provider="openai",
            models=("test/model-a", "test/model-b"),
            runs_per_case=1,
            case_ids=("null-input-validation",),
            resume=True,
            llm_factory=factory,
        )
    matrix_summary_path.write_text(original_summary, encoding="utf-8")

    first_patch = Path(initial.runs[0].final_patch_path)
    first_patch.write_text(first_patch.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"integrity|checksum|hash"):
        run_benchmark_matrix(
            SUITE,
            root,
            provider="openai",
            models=("test/model-a", "test/model-b"),
            runs_per_case=1,
            case_ids=("null-input-validation",),
            resume=True,
            llm_factory=factory,
        )
