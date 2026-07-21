from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from benchmarks.bootstrap_fixture import bootstrap_fixture
from patchpilot.benchmark_spec import BenchmarkSuiteError, load_benchmark_suite

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def copied_benchmarks(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destination = tmp_path_factory.mktemp("benchmark-spec") / "benchmarks"
    shutil.copytree(
        PROJECT_ROOT / "benchmarks",
        destination,
        ignore=shutil.ignore_patterns(".git", "target", "__pycache__"),
    )
    bootstrap_fixture(destination / "fixtures" / "null-email-repo")
    return destination


def _copy_suite(copied_benchmarks: Path, tmp_path: Path) -> Path:
    destination = tmp_path / "benchmarks"
    shutil.copytree(
        copied_benchmarks,
        destination,
        ignore=shutil.ignore_patterns(".git", "target", "__pycache__"),
    )
    source_repository = copied_benchmarks / "fixtures" / "null-email-repo"
    destination_repository = destination / "fixtures" / "null-email-repo"
    shutil.copytree(source_repository / ".git", destination_repository / ".git")
    return destination / "suites" / "mvp.yaml"


def _yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_yaml(path: Path, value: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_suite_manifest_loads_six_strictly_linked_cases(
    copied_benchmarks: Path,
) -> None:
    suite = load_benchmark_suite(copied_benchmarks / "suites" / "mvp.yaml")

    assert suite.manifest.schema_version == 1
    assert suite.manifest.suite_id == "mvp"
    assert len(suite.cases) == 6
    assert len(suite.fingerprint.value) == 64


def test_duplicate_case_ids_are_rejected(
    copied_benchmarks: Path,
    tmp_path: Path,
) -> None:
    suite_path = _copy_suite(copied_benchmarks, tmp_path)
    manifest = _yaml(suite_path)
    cases = manifest["cases"]
    assert isinstance(cases, list)
    assert isinstance(cases[1], dict)
    cases[1]["id"] = cases[0]["id"]  # type: ignore[index]
    _write_yaml(suite_path, manifest)

    with pytest.raises(BenchmarkSuiteError, match="case ids must be unique"):
        load_benchmark_suite(suite_path)


def test_missing_case_file_is_rejected(
    copied_benchmarks: Path,
    tmp_path: Path,
) -> None:
    suite_path = _copy_suite(copied_benchmarks, tmp_path)
    manifest = _yaml(suite_path)
    cases = manifest["cases"]
    assert isinstance(cases, list) and isinstance(cases[0], dict)
    cases[0]["agent_case"] = "../cases/does-not-exist.yaml"
    _write_yaml(suite_path, manifest)

    with pytest.raises(BenchmarkSuiteError, match="missing benchmark case file"):
        load_benchmark_suite(suite_path)


def test_invalid_base_commit_is_rejected(
    copied_benchmarks: Path,
    tmp_path: Path,
) -> None:
    suite_path = _copy_suite(copied_benchmarks, tmp_path)
    for relative in (
        "cases/null-input-validation.yaml",
        "validation/null-input-validation.yaml",
    ):
        case_path = suite_path.parent.parent / relative
        case = _yaml(case_path)
        case["base_commit"] = "0" * 40
        _write_yaml(case_path, case)

    with pytest.raises(BenchmarkSuiteError, match="invalid base commit"):
        load_benchmark_suite(suite_path)


def test_hidden_solution_metadata_is_not_serialized_to_agent(
    copied_benchmarks: Path,
) -> None:
    suite = load_benchmark_suite(copied_benchmarks / "suites" / "mvp.yaml")
    for loaded in suite.cases:
        serialized = json.dumps(loaded.agent_case.model_dump(mode="json"), sort_keys=True)
        golden_content = loaded.validation_case.golden_patch.read_text(encoding="utf-8")

        assert "golden" not in serialized.casefold()
        assert "validation_case" not in serialized
        assert str(loaded.validation_case.golden_patch) not in serialized
        assert golden_content not in serialized
        assert "expected_modified_file" not in serialized


@pytest.mark.parametrize(
    "relative_path",
    ["README.md", "docs/EXEC_PLAN.md", "docs/BENCHMARK.md"],
)
def test_reproducibility_docs_have_no_machine_specific_absolute_paths(
    relative_path: str,
) -> None:
    content = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    machine_path = re.compile(
        r"(?<![A-Za-z])(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp)/)",
        flags=re.IGNORECASE,
    )

    assert machine_path.search(content) is None


def test_benchmark_fingerprint_is_stable(
    copied_benchmarks: Path,
) -> None:
    suite_path = copied_benchmarks / "suites" / "mvp.yaml"

    first = load_benchmark_suite(suite_path).fingerprint
    second = load_benchmark_suite(suite_path).fingerprint

    assert first == second


def test_benchmark_fingerprint_changes_when_a_case_changes(
    copied_benchmarks: Path,
    tmp_path: Path,
) -> None:
    suite_path = _copy_suite(copied_benchmarks, tmp_path)
    before = load_benchmark_suite(suite_path).fingerprint.value
    script_path = suite_path.parent.parent / "scripted" / "pagination-boundary.yaml"
    script = _yaml(script_path)
    script["search_query"] = "fromIndex"
    _write_yaml(script_path, script)

    after = load_benchmark_suite(suite_path).fingerprint.value

    assert after != before


def test_invalid_suite_schema_version_is_rejected(
    copied_benchmarks: Path,
    tmp_path: Path,
) -> None:
    suite_path = _copy_suite(copied_benchmarks, tmp_path)
    manifest = _yaml(suite_path)
    manifest["schema_version"] = 2
    _write_yaml(suite_path, manifest)

    with pytest.raises(BenchmarkSuiteError, match="invalid benchmark suite"):
        load_benchmark_suite(suite_path)
