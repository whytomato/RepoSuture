from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reposuture.cli import app
from reposuture.reporting import RunReport


def test_invalid_case_exits_nonzero_and_writes_report(tmp_path: Path) -> None:
    case_file = tmp_path / "invalid.yaml"
    case_file.write_text("schema_version: 999\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    result = CliRunner().invoke(
        app,
        ["verify-case", str(case_file), "--artifacts-dir", str(artifacts)],
    )

    assert result.exit_code != 0
    assert "Final status: INVALID_CASE" in result.stdout
    reports = list(artifacts.glob("*/report.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["final_status"] == (
        "INVALID_CASE"
    )


def test_report_commit_failure_cannot_return_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_file = tmp_path / "invalid.yaml"
    case_file.write_text("schema_version: 999\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    def fail_report_commit(report: RunReport, report_path: Path) -> None:
        del report, report_path
        raise OSError("deliberate atomic report commit failure")

    monkeypatch.setattr("reposuture.runner.write_report", fail_report_commit)

    result = CliRunner().invoke(
        app,
        ["verify-case", str(case_file), "--artifacts-dir", str(artifacts)],
    )

    assert result.exit_code != 0
    assert result.exit_code == 3
    assert "deliberate atomic report commit failure" in result.stderr
    assert list(artifacts.glob("*/report.json")) == []


def test_repair_missing_model_configuration_fails_before_worktree_with_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PATCHPILOT_MODEL", raising=False)
    project_root = Path(__file__).resolve().parents[1]
    case_file = project_root / "benchmarks/cases/null-email-agent.yaml"
    artifacts = tmp_path / "artifacts"

    result = CliRunner().invoke(
        app,
        ["repair", str(case_file), "--artifacts-dir", str(artifacts)],
    )

    assert result.exit_code == 4
    assert "[FINISH]  MODEL_CONFIGURATION_ERROR" in result.stdout
    assert "Final status: MODEL_CONFIGURATION_ERROR" in result.stdout
    reports = list(artifacts.glob("*/report.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["final_status"] == "MODEL_CONFIGURATION_ERROR"
    assert payload["worktree_path"] is None
    assert payload["target_test_execution_count"] == 0
    serialized = reports[0].read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" in serialized
    assert "sk-" not in serialized


def test_repair_trace_view_off_preserves_final_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PATCHPILOT_MODEL", raising=False)
    project_root = Path(__file__).resolve().parents[1]

    result = CliRunner().invoke(
        app,
        [
            "repair",
            str(project_root / "benchmarks/cases/null-email-agent.yaml"),
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
            "--trace-view",
            "off",
            "--no-color",
        ],
    )

    assert result.exit_code == 4
    assert "[FINISH]" not in result.stdout
    assert "Final status: MODEL_CONFIGURATION_ERROR" in result.stdout


def test_trajectory_commit_failure_cannot_return_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PATCHPILOT_MODEL", raising=False)
    project_root = Path(__file__).resolve().parents[1]

    def fail_trajectory_commit(path: Path, content: str) -> None:
        del path, content
        raise OSError("deliberate trajectory commit failure")

    monkeypatch.setattr(
        "reposuture.repair.write_trajectory_markdown",
        fail_trajectory_commit,
    )

    result = CliRunner().invoke(
        app,
        [
            "repair",
            str(project_root / "benchmarks/cases/null-email-agent.yaml"),
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
        ],
    )

    assert result.exit_code == 3
    assert "deliberate trajectory commit failure" in result.stderr
    assert list((tmp_path / "artifacts").glob("*/report.json")) == []


def test_validate_benchmark_missing_suite_exits_nonzero(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "validate-benchmark",
            str(tmp_path / "missing-suite.yaml"),
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
        ],
    )

    assert result.exit_code == 2
    assert "Invalid benchmark suite" in result.stderr
