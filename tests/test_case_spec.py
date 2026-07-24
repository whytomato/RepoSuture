from pathlib import Path

import pytest
import yaml

from reposuture.case_spec import CaseValidationError, load_agent_case, load_case


def valid_case_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "null-email",
        "repository": "repo",
        "base_commit": "a" * 40,
        "issue_title": "Reject a null email",
        "issue_description": "Registration must reject null email with a domain error.",
        "target_test": {
            "class_name": "com.example.UserRegistrationServiceTest",
            "method_name": "shouldRejectNullEmail",
        },
        "target_test_timeout_seconds": 120,
        "regression_timeout_seconds": 300,
        "golden_patch": "golden.patch",
        "expected_baseline_failure": "test_failure",
    }


def valid_agent_case_data() -> dict[str, object]:
    return {
        "schema_version": 2,
        "workflow": "agent_repair",
        "id": "null-email-agent",
        "repository": "repo",
        "base_commit": "a" * 40,
        "issue_title": "Reject a null email",
        "issue_description": "Registration must reject null email with a domain error.",
        "target_test": {
            "class_name": "com.example.UserRegistrationServiceTest",
            "method_name": "shouldRejectNullEmail",
        },
        "target_test_timeout_seconds": 120,
        "regression_timeout_seconds": 300,
        "expected_baseline_failure": "test_failure",
        "agent_budgets": {
            "max_model_turns": 12,
            "max_tool_calls": 30,
            "max_patch_attempts": 4,
            "max_target_test_executions": 8,
            "max_regression_executions": 4,
            "max_wall_clock_seconds": 1800,
            "api_timeout_seconds": 60,
            "api_max_retries": 2,
            "max_output_tokens": 4096,
            "max_retained_model_output_bytes": 65536,
            "max_retained_tool_output_bytes": 65536,
        },
        "allowed_file_policy": {"production_java_only": True},
    }


def write_case(path: Path, data: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_load_case_validates_and_resolves_paths(tmp_path: Path) -> None:
    case_path = tmp_path / "case.yaml"
    write_case(case_path, valid_case_data())

    loaded = load_case(case_path)

    assert loaded.id == "null-email"
    assert loaded.repository == (tmp_path / "repo").resolve()
    assert loaded.golden_patch == (tmp_path / "golden.patch").resolve()
    assert loaded.target_test.maven_selector == (
        "com.example.UserRegistrationServiceTest#shouldRejectNullEmail"
    )


def test_case_accepts_bounded_unrelated_regression_tests(tmp_path: Path) -> None:
    data = valid_case_data()
    data["regression_tests"] = [
        {
            "class_name": "com.example.UserRegistrationServiceTest",
            "method_name": "registersValidEmail",
        },
        {
            "class_name": "com.example.UserRegistrationServiceTest",
            "method_name": "rejectsBlankEmail",
        },
    ]
    case_path = tmp_path / "case.yaml"
    write_case(case_path, data)

    loaded = load_case(case_path)

    assert [test.maven_selector for test in loaded.regression_tests or ()] == [
        "com.example.UserRegistrationServiceTest#registersValidEmail",
        "com.example.UserRegistrationServiceTest#rejectsBlankEmail",
    ]


@pytest.mark.parametrize(
    "regression_tests",
    [
        [],
        [
            {
                "class_name": "com.example.UserRegistrationServiceTest",
                "method_name": "shouldRejectNullEmail",
            }
        ],
        [
            {
                "class_name": "com.example.UserRegistrationServiceTest",
                "method_name": "registersValidEmail",
            },
            {
                "class_name": "com.example.UserRegistrationServiceTest",
                "method_name": "registersValidEmail",
            },
        ],
    ],
)
def test_case_rejects_empty_target_or_duplicate_regression_scope(
    tmp_path: Path,
    regression_tests: list[dict[str, str]],
) -> None:
    data = valid_case_data()
    data["regression_tests"] = regression_tests
    case_path = tmp_path / "invalid.yaml"
    write_case(case_path, data)

    with pytest.raises(CaseValidationError):
        load_case(case_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", "1"),
        ("schema_version", True),
        ("id", "contains spaces"),
        ("base_commit", "main"),
        ("target_test", {"class_name": "Test; whoami", "method_name": "works"}),
        ("target_test_timeout_seconds", 0),
        ("target_test_timeout_seconds", "120"),
        ("expected_baseline_failure", "anything"),
    ],
)
def test_load_case_rejects_invalid_values(
    tmp_path: Path, field: str, value: object
) -> None:
    data = valid_case_data()
    data[field] = value
    case_path = tmp_path / "invalid.yaml"
    write_case(case_path, data)

    with pytest.raises(CaseValidationError):
        load_case(case_path)


def test_load_case_rejects_unknown_fields(tmp_path: Path) -> None:
    data = valid_case_data()
    data["command"] = "mvn test; rm -rf ."
    case_path = tmp_path / "invalid.yaml"
    write_case(case_path, data)

    with pytest.raises(CaseValidationError):
        load_case(case_path)


def test_load_agent_case_validates_separate_schema_and_resolves_repository(
    tmp_path: Path,
) -> None:
    case_path = tmp_path / "agent.yaml"
    write_case(case_path, valid_agent_case_data())

    loaded = load_agent_case(case_path)

    assert loaded.schema_version == 2
    assert loaded.workflow == "agent_repair"
    assert loaded.repository == (tmp_path / "repo").resolve()
    assert loaded.agent_budgets.max_model_turns == 12
    assert loaded.allowed_file_policy.production_java_only is True
    assert "golden_patch" not in loaded.model_fields_set


def test_agent_case_cannot_expose_a_golden_patch(tmp_path: Path) -> None:
    data = valid_agent_case_data()
    data["golden_patch"] = "secret-golden.patch"
    case_path = tmp_path / "agent.yaml"
    write_case(case_path, data)

    with pytest.raises(CaseValidationError, match="golden_patch"):
        load_agent_case(case_path)


@pytest.mark.parametrize(
    ("budget", "value"),
    [
        ("max_model_turns", 0),
        ("max_tool_calls", 10_000),
        ("max_patch_attempts", True),
        ("max_wall_clock_seconds", 86_401),
        ("api_max_retries", 6),
        ("max_output_tokens", "4096"),
    ],
)
def test_agent_case_rejects_unbounded_or_non_strict_budgets(
    tmp_path: Path, budget: str, value: object
) -> None:
    data = valid_agent_case_data()
    budgets = data["agent_budgets"]
    assert isinstance(budgets, dict)
    budgets[budget] = value
    case_path = tmp_path / "agent.yaml"
    write_case(case_path, data)

    with pytest.raises(CaseValidationError):
        load_agent_case(case_path)


def test_agent_case_rejects_relaxed_file_policy(tmp_path: Path) -> None:
    data = valid_agent_case_data()
    data["allowed_file_policy"] = {"production_java_only": False}
    case_path = tmp_path / "agent.yaml"
    write_case(case_path, data)

    with pytest.raises(CaseValidationError):
        load_agent_case(case_path)


def test_case_loaders_do_not_silently_accept_the_other_schema(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent.yaml"
    deterministic_path = tmp_path / "deterministic.yaml"
    write_case(agent_path, valid_agent_case_data())
    write_case(deterministic_path, valid_case_data())

    with pytest.raises(CaseValidationError):
        load_case(agent_path)
    with pytest.raises(CaseValidationError):
        load_agent_case(deterministic_path)
