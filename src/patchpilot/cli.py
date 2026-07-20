"""Typer command-line interface for PatchPilot."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from patchpilot.repair import repair_case
from patchpilot.reporting import FinalStatus, RunReport
from patchpilot.runner import verify_case

app = typer.Typer(
    name="patchpilot",
    help="Reproduce, repair, and deterministically verify Java Maven bug cases.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

EXIT_INVALID_CASE = 2
EXIT_INFRASTRUCTURE = 3
EXIT_VERIFICATION_FAILED = 4


@app.callback()
def main() -> None:
    """PatchPilot deterministic verification and bounded repair commands."""


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
    except (OSError, ValueError) as exc:
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
) -> None:
    """Repair a validated Agent Case through safe tools and deterministic tests."""

    try:
        report = repair_case(
            case_file,
            artifacts_dir,
            model_override=model,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_patch_attempts=max_patch_attempts,
            keep_worktree=keep_worktree,
            progress=typer.echo,
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Infrastructure error before report creation: {exc}", err=True)
        raise typer.Exit(code=EXIT_INFRASTRUCTURE) from exc

    _print_summary(report)
    code = _exit_code(report.final_status)
    if code:
        raise typer.Exit(code=code)


if __name__ == "__main__":
    app()
