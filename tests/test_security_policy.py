from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
AUDITED_PYTHON_ROOTS = (SOURCE_ROOT, PROJECT_ROOT / "tests", PROJECT_ROOT / "benchmarks")


def source_trees() -> list[tuple[Path, ast.AST]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for root in AUDITED_PYTHON_ROOTS
        for path in sorted(root.rglob("*.py"))
    ]


def dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def test_no_shell_true_or_os_system_and_subprocess_is_centralized() -> None:
    subprocess_calls: list[tuple[Path, ast.Call, str]] = []
    for path, tree in source_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = dotted_name(node.func)
            assert name != "os.system", f"os.system is forbidden: {path}:{node.lineno}"
            shell_keywords = [keyword for keyword in node.keywords if keyword.arg == "shell"]
            assert all(
                isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                for keyword in shell_keywords
            ), f"shell must be explicitly false: {path}:{node.lineno}"
            if name.startswith("subprocess."):
                subprocess_calls.append((path, node, name))

    assert subprocess_calls
    assert all(path.name == "process.py" for path, _, _ in subprocess_calls)
    for path, node, name in subprocess_calls:
        keyword_names = {keyword.arg for keyword in node.keywords}
        assert "cwd" in keyword_names, f"subprocess cwd missing: {path}:{node.lineno}"
        if name == "subprocess.run":
            assert "timeout" in keyword_names, (
                f"subprocess.run timeout missing: {path}:{node.lineno}"
            )


def test_forbidden_frameworks_are_absent_and_openai_is_provider_isolated() -> None:
    forbidden = {
        "docker",
        "langchain",
        "langgraph",
        "mcp",
    }
    imported_roots: set[str] = set()
    openai_source_imports: list[Path] = []
    for path, tree in source_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
                if path.is_relative_to(SOURCE_ROOT) and any(
                    alias.name.split(".", maxsplit=1)[0] == "openai"
                    for alias in node.names
                ):
                    openai_source_imports.append(path)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", maxsplit=1)[0])
                if (
                    path.is_relative_to(SOURCE_ROOT)
                    and node.module.split(".", maxsplit=1)[0] == "openai"
                ):
                    openai_source_imports.append(path)

    assert forbidden.isdisjoint(imported_roots)
    assert set(openai_source_imports) == {
        SOURCE_ROOT / "patchpilot/models/openai_responses.py"
    }
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8").casefold()
    assert all(f'"{dependency}' not in pyproject for dependency in forbidden)
    assert '"openai>=' in pyproject
