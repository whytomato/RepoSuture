# OpenRouter GLM-5.2 live evaluation — run 1

> Generated under the former project name PatchPilot; the project was subsequently
> renamed to RepoSuture. Historical metrics and identifiers below are unchanged.

This is a genuine live-model evaluation of PatchPilot's six-Case MVP benchmark. It is not
a scripted result. Each Case has exactly one attempt, so the observed **6/6 empirical
result is not statistically robust and is not pass@k**.

## Reproducibility

- Evaluation completed: `2026-07-22T10:58:07.313297Z`
- PatchPilot commit: `944fc6aab83c64848c4eae11f291db80ebc69041`
- Source tree: `dirty=false`
- Provider: OpenRouter-compatible Responses API
- Endpoint: `https://openrouter.ai/api/v1`
- Model: `z-ai/glm-5.2`
- Suite: `mvp`
- Benchmark fingerprint:
  `20709966636b87d77e5a50fd0026557d405c7aa94955824ec80abb5e986a9ff0`
- Runs per Case: `1`
- Environment: Windows, Python 3.11.15, Java 21.0.8 executing Java 17 fixtures,
  Maven 3.9.9 via Maven Wrapper 3.3.4, OpenAI SDK 2.46.0

Equivalent command using the current CLI:

```powershell
reposuture benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-live-m5-suite-r1 `
  --provider openai `
  --runs-per-case 1
```

The ignored local environment supplied the API credential, endpoint, and model. No
credential value, Authorization header, raw provider body, hidden reasoning, golden Patch,
or hidden validation path is included here.

## Per-Case results

Tokens are shown as `input / output / reasoning`; provider reasoning tokens are also part of
the provider's output accounting and are not added again to the reported total.

| Case | Final | Target | Regression | Turns | Tools | Patches | Tokens (in/out/reasoning) | Duration | Failure category | Normalization | Recount |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| null-input-validation | RESOLVED | PASS | PASS | 3 | 3 | 1 | 6,294 / 234 / 207 | 34.984s | RESOLVED | none | yes |
| pagination-boundary | RESOLVED | PASS | PASS | 5 | 5 | 2 | 12,638 / 1,003 / 610 | 63.187s | RESOLVED | none | no |
| status-filtering | RESOLVED | PASS | PASS | 6 | 6 | 1 | 13,403 / 418 / 367 | 79.531s | RESOLVED | none | yes |
| shipping-eligibility | RESOLVED | PASS | PASS | 3 | 3 | 1 | 6,071 / 281 / 229 | 41.234s | RESOLVED | none | yes |
| country-code-normalization | RESOLVED | PASS | PASS | 5 | 5 | 1 | 11,617 / 434 / 244 | 50.234s | RESOLVED | none | no |
| quota-regression-trap | RESOLVED | PASS | PASS | 6 | 6 | 1 | 13,251 / 430 / 324 | 184.453s | RESOLVED | none | no |

## Aggregate evidence

- Empirically resolved: **6/6 attempts and 6/6 Cases at least once**.
- Baseline reproduced: 6/6. Target passed: 6/6. Full regression passed: 6/6.
- Model requests/API errors: 28/0.
- Model turns: average 4.67, median 5.
- Tool calls: average 4.67, median 5; distribution was `read_file=13`,
  `apply_patch=7`, `list_files=4`, and `search_code=4`.
- Patch attempts: average 1.17, median 1; seven total, with one rejected attempt.
- Duration: average 75.604s, median 56.710s; summed run duration 453.623s.
- Tokens: 63,274 input, 2,800 output, 1,981 reasoning, and 66,074 reported
  input-plus-output tokens.
- Final failure categories: `RESOLVED=6`; there were no unresolved final categories.
- The first pagination Patch was safely rejected as `PATCH_GIT_RECOUNT_FAILED`. The Agent
  received the bounded diagnostic, reread the file, submitted a second Patch, and then passed
  target and regression tests. See the sanitized
  [live trajectory example](../examples/live-pagination-replan-trajectory.md).
- No textual Patch normalization was needed. Three accepted Patches required the limited
  `git apply --recount` path; it only recovered inaccurate hunk counts.
- The provider returned extra calls despite `parallel_tool_calls=false` in five Cases.
  PatchPilot recorded and discarded 13 unexecuted calls in total, executed only the first
  action per turn, and required a new decision after the real observation.

## Integrity checks

All six runs created distinct isolated worktrees and fresh model conversations. Every
worktree was removed, every original fixture snapshot remained unchanged, and every final
modification was classified as production code. Real Maven/JUnit executed with zero skipped
tests. The six run reports contained 36 referenced artifacts; every recorded byte size and
SHA-256 matched. JSON/CSV run identities and trace sequence/run IDs were consistent.

An exact credential scan across the raw local artifacts found zero matches. Agent-visible
trace and trajectory files contained zero Authorization, hidden-reasoning, golden-Patch, or
hidden-validation-path matches. Raw `.artifacts-live*` directories remain ignored and are
not committed.

The small machine-readable publication is
[`openrouter-glm-5.2-live-r1-summary.json`](openrouter-glm-5.2-live-r1-summary.json).
Correctness came from observed Git/Maven/JUnit evidence, never from model text.
