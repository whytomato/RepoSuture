from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from reposuture.benchmark import validate_benchmark
from reposuture.benchmark_spec import load_benchmark_suite
from reposuture.case_spec import load_agent_case
from reposuture.process import ProcessRunner
from reposuture.real_world import (
    RealWorldBenchmarkError,
    RealWorldSourcesManifest,
    _contained_child,
    _git,
    bootstrap_real_world,
    load_real_world_lock,
    load_real_world_sources,
    validate_source_lock,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "benchmarks" / "real_world"
SOURCES = ROOT / "sources.yaml"
LOCK = ROOT / "source-lock.json"
V1_SUITE = ROOT / "suites" / "maven-real-world-v1.yaml"
V2_SUITE = ROOT / "suites" / "maven-real-world-v2.yaml"
ABLATION_SUITE = (
    ROOT / "suites" / "maven-real-world-v2-feedback-ablation.yaml"
)


def test_source_manifest_has_exactly_eight_cases_from_seven_projects() -> None:
    manifest, digest = load_real_world_sources(SOURCES)

    assert len(manifest.cases) == 8
    assert len({case.repository_url for case in manifest.cases}) == 7
    assert len(digest) == 64
    assert all(case.license_identifier == "Apache-2.0" for case in manifest.cases)
    assert all(len(case.buggy_commit) == len(case.fix_commit) == 40 for case in manifest.cases)
    assert len({case.bug_category for case in manifest.cases}) >= 5
    assert sum(case.cross_file_or_component for case in manifest.cases) >= 3
    assert any(case.regression_sensitive for case in manifest.cases[3:])
    assert all(case.regression_command[0] == "./mvnw" for case in manifest.cases)
    scoped = {
        case.case_id: case
        for case in manifest.cases
        if case.regression_scope == "selected-junit-tests"
    }
    assert set(scoped) == {
        "commons-codec-zero-big-integer",
        "commons-text-csv-lone-quote",
        "commons-io-bounded-reader-skip",
        "commons-csv-supplementary-delimiter",
    }
    assert all(case.regression_test_selectors for case in scoped.values())


def test_v1_remains_three_cases_and_v2_has_locked_distribution() -> None:
    v1 = yaml.safe_load(V1_SUITE.read_text(encoding="utf-8"))
    v2 = yaml.safe_load(V2_SUITE.read_text(encoding="utf-8"))
    assert isinstance(v1, dict) and isinstance(v2, dict)
    assert isinstance(v1["cases"], list) and isinstance(v2["cases"], list)

    assert len(v1["cases"]) == 3
    assert len(v2["cases"]) == 8
    source_by_id = {
        case.case_id: case.source_slug
        for case in load_real_world_sources(SOURCES)[0].cases
    }
    repositories = [
        source_by_id[case["id"]]
        for case in v2["cases"]
    ]
    assert max(repositories.count(repository) for repository in set(repositories)) <= 2


def test_feedback_ablation_subset_is_locked_to_six_diverse_cases() -> None:
    raw = yaml.safe_load(ABLATION_SUITE.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    cases = raw["cases"]
    assert isinstance(cases, list)
    ids = [case["id"] for case in cases]
    assert ids == [
        "commons-lang-mid-overflow",
        "commons-collections-int-value",
        "commons-codec-zero-big-integer",
        "commons-io-bounded-reader-skip",
        "commons-csv-supplementary-delimiter",
        "commons-beanutils-nondouble-number",
    ]
    source_by_id = {
        case.case_id: case
        for case in load_real_world_sources(SOURCES)[0].cases
    }
    selected = [source_by_id[case_id] for case_id in ids]
    assert len({case.repository_url for case in selected}) >= 4
    assert any(case.cross_file_or_component for case in selected)
    assert any(case.regression_sensitive for case in selected)
    assert len({case.bug_category for case in selected}) >= 4


def test_source_lock_matches_manifest_and_uses_full_commits() -> None:
    manifest, digest = load_real_world_sources(SOURCES)
    lock = load_real_world_lock(LOCK)

    validate_source_lock(manifest, digest, lock)
    assert len(lock.entries) == 8
    assert all(len(entry.benchmark_base_commit) == 40 for entry in lock.entries)


def test_public_cases_do_not_serialize_hidden_fix_metadata() -> None:
    manifest, _ = load_real_world_sources(SOURCES)
    hidden_values = {
        value
        for case in manifest.cases
        for value in (case.fix_commit, case.fix_pr_url, case.production_patch_sha256)
    }
    for path in sorted((ROOT / "cases").glob("*.yaml")):
        public = load_agent_case(path).model_dump_json()
        assert "golden_patch" not in public
        assert "validation/patches" not in public
        assert all(value not in public for value in hidden_values)


def test_cache_containment_rejects_traversal_and_external_symlink(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(RealWorldBenchmarkError, match="unsafe"):
        _contained_child(cache, "../escape")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = cache / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks require privileges on this host")
    with pytest.raises(RealWorldBenchmarkError, match=r"escape|symlink|junction"):
        _contained_child(cache, "linked")


def test_unsupported_build_system_is_rejected() -> None:
    raw = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    raw["cases"][0]["build_system"] = "gradle"
    with pytest.raises(ValidationError, match="maven"):
        RealWorldSourcesManifest.model_validate(raw)


def test_source_lock_contains_no_api_secret_shape() -> None:
    serialized = LOCK.read_text(encoding="utf-8")
    assert "Authorization" not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "sk-or-" not in serialized


@pytest.mark.network
@pytest.mark.integration
def test_network_bootstrap_is_deterministic_and_validation_is_eight_of_eight(
    tmp_path: Path,
) -> None:
    first = bootstrap_real_world(ROOT)
    manifest, _ = load_real_world_sources(SOURCES)
    runner = ProcessRunner(max_output_bytes=10 * 1024 * 1024)
    source_state: dict[str, tuple[str, str]] = {}
    for case in manifest.cases:
        source = ROOT / ".cache" / "candidates" / case.source_slug
        source_state[case.source_slug] = (
            _git(runner, source, "rev-parse", "HEAD"),
            _git(
                runner,
                source,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ),
        )
        fixture = ROOT / ".cache" / "fixtures" / case.case_id
        assert _git(runner, fixture, "rev-parse", "HEAD:src/main/java") == _git(
            runner,
            source,
            "rev-parse",
            f"{case.buggy_commit}:src/main/java",
        )
        for test_path in case.test_paths:
            assert _git(runner, fixture, "rev-parse", f"HEAD:{test_path}") == _git(
                runner,
                source,
                "rev-parse",
                f"{case.fix_commit}:{test_path}",
            )
    second = bootstrap_real_world(ROOT)
    assert first == second
    for slug, before in source_state.items():
        source = ROOT / ".cache" / "candidates" / slug
        assert (
            _git(runner, source, "rev-parse", "HEAD"),
            _git(
                runner,
                source,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ),
        ) == before
    summary = validate_benchmark(V2_SUITE, tmp_path / "validation")
    assert summary.total_cases == summary.valid_cases == 8
    assert summary.all_valid
    payload = json.loads(
        (tmp_path / "validation" / "validation-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["valid_cases"] == 8


@pytest.mark.network
def test_real_world_suite_fingerprint_is_stable_after_bootstrap() -> None:
    bootstrap_real_world(ROOT)
    first = load_benchmark_suite(V2_SUITE)
    second = load_benchmark_suite(V2_SUITE)
    assert first.fingerprint == second.fingerprint
