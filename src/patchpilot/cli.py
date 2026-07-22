"""Typer command-line interface for PatchPilot."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from patchpilot.benchmark import (
    benchmark_exit_code,
    run_benchmark,
    validate_benchmark,
)
from patchpilot.benchmark_spec import BenchmarkSuiteError
from patchpilot.repair import repair_case
from patchpilot.reporting import FinalStatus, RunReport
from patchpilot.runner import verify_case
from patchpilot.trajectory import (
    LiveTrajectoryRenderer,
    ReplayView,
    TrajectoryFormat,
    TrajectoryView,
    load_replay_run,
    render_replay,
    write_replay_output,
)
from patchpilot.workspace import WorkspaceError

app = typer.Typer(
    name="patchpilot",
    help="Run and inspect a test-grounded Java/Maven software engineering Agent.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

EXIT_INVALID_CASE = 2
EXIT_INFRASTRUCTURE = 3
EXIT_VERIFICATION_FAILED = 4


@app.callback()
def main() -> None:
    """PatchPilot Agent repair, deterministic verification, benchmark, and replay."""


def _print_summary(report: RunReport) -> None:
    typer.echo(f"Case ID: {report.task_id}")
    typer.echo(f"Baseline target test: {report.baseline_test_result.outcome.value}")
    typer.echo(f"Patched target test: {report.patched_target_test_result.outcome.value}")
    typer.echo(f"Regression: {report.regression_result.outcome.value}")
    typer.echo("Affected files:")
    if report.affected_files:
        for file_path in report.affected_files:
            classification = report.file_classifications.get(file_path, "other")
            typer.echo(f"  - {file_path} ({classification})")
    else:
        typer.echo("  - (none)")
    report_path = Path(report.artifacts["report"])
    typer.echo(f"Artifacts: {report_path.parent}")
    typer.echo(f"Final status: {report.final_status.value}")
    if report.failure_reason:
        typer.echo(f"Failure reason: {report.failure_reason}")


def _exit_code(status: FinalStatus) -> int:
    if status is FinalStatus.RESOLVED:
        return 0
    if status is FinalStatus.INVALID_CASE:
        return EXIT_INVALID_CASE
    if status is FinalStatus.INFRASTRUCTURE_ERROR:
        return EXIT_INFRASTRUCTURE
    return EXIT_VERIFICATION_FAILED


@app.command("verify-case")
def verify_case_command(
    case_file: Annotated[
        Path,
        typer.Argument(help="Path to a versioned PatchPilot Bug Case YAML file."),
    ],
    artifacts_dir: Annotated[
        Path,
        typer.Option(
            "--artifacts-dir",
            help="Directory in which a unique per-run artifact directory is created.",
        ),
    ] = Path(".artifacts"),
    keep_worktree: Annotated[
        bool,
        typer.Option(
            "--keep-worktree",
            help="Keep the isolated worktree after the run for debugging.",
        ),
    ] = False,
) -> None:
    """Reproduce a target failure, apply its golden patch, and run regression tests."""

    try:
        report = verify_case(
            case_file,
            artifacts_dir,
            keep_worktree=keep_worktree,
        )
    except (OSError, ValueError, WorkspaceError) as exc:
        typer.echo(f"Infrastructure error before report creation: {exc}", err=True)
        raise typer.Exit(code=EXIT_INFRASTRUCTURE) from exc

    _print_summary(report)
    code = _exit_code(report.final_status)
    if code:
        raise typer.Exit(code=code)


@app.command("repair")
def repair_command(
    case_file: Annotated[
        Path,
        typer.Argument(help="Path to a versioned PatchPilot Agent Case YAML file."),
    ],
    artifacts_dir: Annotated[
        Path,
        typer.Option(
            "--artifacts-dir",
            help="Directory in which a unique per-run artifact directory is created.",
        ),
    ] = Path(".artifacts-live"),
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="Model name for this run; overrides PATCHPILOT_MODEL.",
        ),
    ] = None,
    max_turns: Annotated[
        int | None,
        typer.Option("--max-turns", min=1, max=50, help="Maximum model turns."),
    ] = None,
    max_tool_calls: Annotated[
        int | None,
        typer.Option(
            "--max-tool-calls", min=1, max=200, help="Maximum total tool calls."
        ),
    ] = None,
    max_patch_attempts: Annotated[
        int | None,
        typer.Option(
            "--max-patch-attempts", min=1, max=10, help="Maximum Patch attempts."
        ),
    ] = None,
    keep_worktree: Annotated[
        bool,
        typer.Option(
            "--keep-worktree",
            help="Keep the isolated worktree after the run for debugging.",
        ),
    ] = False,
    trace_view: Annotated[
        TrajectoryView,
        typer.Option(
            "--trace-view",
            help="Live Agent timeline detail: compact, verbose, or off.",
        ),
    ] = TrajectoryView.COMPACT,
    no_color: Annotated[
        bool,
        typer.Option(
            "--no-color",
            help="Render deterministic plain text without terminal color.",
        ),
    ] = False,
) -> None:
    """Repair a validated Agent Case through safe tools and deterministic tests."""

    observer = None
    if trace_view is not TrajectoryView.OFF:
        observer = LiveTrajectoryRenderer(
            view=trace_view,
            sink=lambda content: typer.echo(content, nl=False, color=not no_color),
        )
    try:
        report = repair_case(
            case_file,
            artifacts_dir,
            model_override=model,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_patch_attempts=max_patch_attempts,
            keep_worktree=keep_worktree,
            trace_observer=observer,
        )
    except (OSError, ValueError, WorkspaceError) as exc:
        typer.echo(f"Infrastructure error before report creation: {exc}", err=True)
        raise typer.Exit(code=EXIT_INFRASTRUCTURE) from exc

    _print_summary(report)
    code = _exit_code(report.final_status)
    if code:
        raise typer.Exit(code=code)


@app.command("replay-run")
def replay_run_command(
    path: Annotated[
        Path,
        typer.Argument(help="Completed run directory, report.json, or trace.jsonl."),
    ],
    view: Annotated[
        ReplayView,
        typer.Option("--view", help="Replay detail: compact or verbose."),
    ] = ReplayView.COMPACT,
    output_format: Annotated[
        TrajectoryFormat,
        typer.Option("--format", help="Replay output format: text or markdown."),
    ] = TrajectoryFormat.TEXT,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write output outside the original run directory."),
    ] = None,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Render deterministic plain text."),
    ] = False,
) -> None:
    """Replay a completed Agent trajectory without credentials or execution."""

    try:
        replay = load_replay_run(path)
        content = render_replay(
            replay,
            view=TrajectoryView(view.value),
            markdown=output_format is TrajectoryFormat.MARKDOWN,
        )
        if output is None:
            typer.echo(content, nl=False, color=not no_color)
        else:
            destination = write_replay_output(replay, output, content)
            typer.echo(f"Replay written: {destination}")
    except (OSError, ValueError) as exc:
        typer.echo(f"Replay error: {exc}", err=True)
        raise typer.Exit(code=EXIT_INVALID_CASE) from exc


@app.command("validate-benchmark")
def validate_benchmark_command(
    suite_file: Annotated[
        Path,
        typer.Argument(help="Path to a versioned PatchPilot benchmark suite YAML file."),
    ],
    artifacts_dir: Annotated[
        Path,
        typer.Option(
            "--artifacts-dir",
            help="Directory for validation aggregates and deterministic per-case evidence.",
        ),
    ] = Path(".artifacts-benchmark-validation"),
) -> None:
    """Validate every benchmark Case with its hidden Patch and real Maven/JUnit."""

    try:
        summary = validate_benchmark(
            suite_file,
            artifacts_dir,
            progress=typer.echo,
            cli_arguments=sys.argv[1:],
        )
    except BenchmarkSuiteError as exc:
        typer.echo(f"Invalid benchmark suite: {exc}", err=True)
        raise typer.Exit(code=EXIT_INVALID_CASE) from exc
    except (OSError, ValueError) as exc:
        typer.echo(f"Benchmark validation infrastructure error: {exc}", err=True)
        raise typer.Exit(code=EXIT_INFRASTRUCTURE) from exc

    typer.echo(f"Validated cases: {summary.valid_cases}/{summary.total_cases}")
    typer.echo(f"Validation report: {summary.artifacts['validation_report_markdown']}")
    if not summary.all_valid:
        raise typer.Exit(code=EXIT_VERIFICATION_FAILED)


@app.command("benchmark")
def benchmark_command(
    suite_file: Annotated[
        Path,
        typer.Argument(help="Path to a versioned PatchPilot benchmark suite YAML file."),
    ],
    artifacts_dir: Annotated[
        Path,
        typer.Option(
            "--artifacts-dir",
            help="Directory for per-run evidence and aggregate benchmark reports.",
        ),
    ] = Path(".artifacts-benchmark"),
    provider: Annotated[
        str,
        typer.Option("--provider", help="Provider: openai (live) or scripted (offline)."),
    ] = "openai",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Live model override; otherwise PATCHPILOT_MODEL."),
    ] = None,
    runs_per_case: Annotated[
        int | None,
        typer.Option("--runs-per-case", min=1, max=20, help="Attempts per selected Case."),
    ] = None,
    case_ids: Annotated[
        list[str] | None,
        typer.Option("--case", help="Case id filter; repeat to select multiple Cases."),
    ] = None,
    continue_on_failure: Annotated[
        bool,
        typer.Option(
            "--continue-on-failure/--stop-on-failure",
            help="Continue after unresolved attempts (default) or stop at the first one.",
        ),
    ] = True,
    random_seed: Annotated[
        int | None,
        typer.Option("--random-seed", help="Optional reproducibility metadata for providers."),
    ] = None,
    max_turns: Annotated[
        int | None,
        typer.Option("--max-turns", min=1, max=50, help="Per-run maximum model turns."),
    ] = None,
    max_tool_calls: Annotated[
        int | None,
        typer.Option("--max-tool-calls", min=1, max=200, help="Per-run tool-call limit."),
    ] = None,
    max_patch_attempts: Annotated[
        int | None,
        typer.Option("--max-patch-attempts", min=1, max=10, help="Per-run Patch limit."),
    ] = None,
    max_target_test_executions: Annotated[
        int | None,
        typer.Option(
            "--max-target-test-executions",
            min=1,
            max=25,
            help="Per-run target-test execution limit, including baseline.",
        ),
    ] = None,
    max_regression_executions: Annotated[
        int | None,
        typer.Option(
            "--max-regression-executions",
            min=1,
            max=10,
            help="Per-run full-regression execution limit.",
        ),
    ] = None,
    max_wall_clock_seconds: Annotated[
        int | None,
        typer.Option(
            "--max-wall-clock-seconds",
            min=1,
            max=86_400,
            help="Per-run wall-clock limit in seconds.",
        ),
    ] = None,
) -> None:
    """Run sequential fresh Agent attempts and aggregate deterministic outcomes."""

    try:
        summary = run_benchmark(
            suite_file,
            artifacts_dir,
            provider=provider,
            model_override=model,
            runs_per_case=runs_per_case,
            case_ids=case_ids,
            continue_on_failure=continue_on_failure,
            random_seed=random_seed,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_patch_attempts=max_patch_attempts,
            max_target_test_executions=max_target_test_executions,
            max_regression_executions=max_regression_executions,
            max_wall_clock_seconds=max_wall_clock_seconds,
            progress=typer.echo,
            cli_arguments=sys.argv[1:],
        )
    except BenchmarkSuiteError as exc:
        typer.echo(f"Invalid benchmark suite: {exc}", err=True)
        raise typer.Exit(code=EXIT_INVALID_CASE) from exc
    except (OSError, ValueError) as exc:
        typer.echo(f"Benchmark infrastructure error: {exc}", err=True)
        raise typer.Exit(code=EXIT_INFRASTRUCTURE) from exc

    typer.echo(
        f"Resolved attempts: {summary.resolved_attempts}/{summary.total_attempts}"
    )
    typer.echo(f"Benchmark report: {summary.artifacts['benchmark_report_markdown']}")
    code = benchmark_exit_code(summary)
    if code:
        raise typer.Exit(code=code)


if __name__ == "__main__":
    app()
