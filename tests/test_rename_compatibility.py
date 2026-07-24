from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reposuture import __version__, cli, legacy_cli
from reposuture.benchmark_reporting import ReproducibilityMetadata


def _legacy_payload() -> dict[str, object]:
    return {
        "patchpilot_git_commit": "a" * 40,
        "patchpilot_worktree_dirty": False,
        "operating_system": "test-os",
        "python_version": "3.11",
        "java_version": "17",
        "maven_version": "3.9.9",
        "openai_sdk_version": None,
        "provider": "scripted",
        "model": "scripted-v1",
        "run_timestamp_utc": datetime(2026, 7, 22, tzinfo=UTC).isoformat(),
        "cli_arguments": [],
        "budget_values": {"max_model_turns": 12},
        "random_seed": None,
    }


def test_legacy_report_fields_load_and_new_reports_serialize_neutral_names() -> None:
    metadata = ReproducibilityMetadata.model_validate(_legacy_payload())

    assert metadata.project_git_commit == "a" * 40
    assert metadata.project_worktree_dirty is False
    payload = metadata.model_dump(mode="json")
    assert payload["project_git_commit"] == "a" * 40
    assert payload["project_worktree_dirty"] is False
    assert payload["project_version"] == "0.4.0"
    assert "patchpilot_git_commit" not in payload
    assert "patchpilot_worktree_dirty" not in payload


def test_deprecated_cli_is_one_forwarder_with_one_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def fake_app(*, prog_name: str) -> None:
        calls.append(prog_name)

    monkeypatch.setattr(legacy_cli, "app", fake_app)
    legacy_cli.legacy_main()

    captured = capsys.readouterr()
    assert calls == ["patchpilot"]
    assert captured.out == ""
    assert captured.err.count("deprecated") == 1
    assert "reposuture" in captured.err


def test_deprecated_cli_preserves_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_app(*, prog_name: str) -> None:
        assert prog_name == "patchpilot"
        raise SystemExit(17)

    monkeypatch.setattr(legacy_cli, "app", failing_app)
    with pytest.raises(SystemExit, match="17"):
        legacy_cli.legacy_main()


def test_primary_and_deprecated_commands_share_one_cli_implementation() -> None:
    assert legacy_cli.app is cli.app
    assert __version__ == "0.4.0"
    assert "patchpilot.agent" not in sys.modules
    assert not (Path(__file__).resolve().parents[1] / "src" / "patchpilot").exists()
