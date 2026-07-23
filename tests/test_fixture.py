from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from benchmarks.bootstrap_fixture import EXPECTED_COMMIT, bootstrap_fixture
from reposuture.process import ProcessRunner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SOURCE = PROJECT_ROOT / "benchmarks/fixtures/null-email-repo"


def test_fixture_bootstrap_recreates_exact_case_commit_in_new_path(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(
        FIXTURE_SOURCE,
        fixture,
        ignore=shutil.ignore_patterns(".git", "target"),
    )
    assert not (fixture / ".git").exists()

    first = bootstrap_fixture(fixture)
    second = bootstrap_fixture(fixture)

    assert first == EXPECTED_COMMIT
    assert second == EXPECTED_COMMIT
    runner = ProcessRunner()
    status = runner.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=fixture,
        timeout_seconds=10,
    )
    assert status.succeeded
    assert status.stdout == ""


def test_case_commit_and_wrapper_checksum_are_pinned() -> None:
    case = yaml.safe_load(
        (PROJECT_ROOT / "benchmarks/cases/null-email.yaml").read_text(encoding="utf-8")
    )
    properties = (
        PROJECT_ROOT
        / "benchmarks/fixtures/null-email-repo/.mvn/wrapper/maven-wrapper.properties"
    ).read_text(encoding="utf-8")

    assert case["base_commit"] == EXPECTED_COMMIT
    assert "apache-maven/3.9.9/apache-maven-3.9.9-bin.zip" in properties
    checksum = re.search(r"^distributionSha256Sum=([0-9a-f]{64})$", properties, re.MULTILINE)
    assert checksum is not None
    assert checksum.group(1) == (
        "4ec3f26fb1a692473aea0235c300bd20f0f9fe741947c82c1234cefd76ac3a3c"
    )

