# RepoSuture Engineering Rules

- Never use `shell=True`.
- Every subprocess must use an argument array, an explicit `cwd`, a timeout, and return a structured result.
- Never modify a user's original repository; all changes belong in an isolated Git worktree.
- Validate every path is contained within its allowed directory, including after symlink resolution.
- Real test results are the sole authority for success or failure.
- Classify and report every change to tests, build files, Maven Wrapper files, or CI configuration.
- After code changes, run `python -m pytest -q`, `python -m ruff check .`, and `python -m mypy src`.
- Never claim or fabricate a test result that was not actually executed.
- Do not add frameworks or abstractions that the current MVP does not need.
- Milestone 1 must remain deterministic and must not use an LLM, agent framework, MCP, vector database, Web UI, LSP, EvoMaster, or Docker.
- Milestone 2 Agent code must remain provider-independent; model text cannot produce a
  `RESOLVED` result or bypass Milestone 1 deterministic verification.

## Agent skills

### Issue tracker

Work is tracked as local Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default local triage role names. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.
