# RepoSuture MVP two-model repeated evaluation — R3

This is a genuine live-model evaluation of RepoSuture's six-Case MVP suite. It contains
exactly three fresh attempts per Case and model: **36 assigned attempts in total**. No
failed attempt was replaced.

The result is descriptive. It is **not pass@k**, three attempts per Case remain a small
sample, and it does not establish universal Java repair capability.

## Reproducibility

- Evaluation completed: `2026-07-24T08:30:38.559463Z`
- RepoSuture commit: `6f0ced786524c7e4f3514a284b826eac9865bcac`
- Source tree: `dirty=false`
- Provider: OpenRouter-compatible Responses API
- Endpoint: `https://openrouter.ai/api/v1`
- Models: `z-ai/glm-5.2` and `openai/gpt-5-mini`
- Suite: `mvp`
- Benchmark fingerprint:
  `2db5511043823b94edbeaa0fd7fc84dc9543fe59093ec8ce27f0f8c612973d4f`
- Runs per Case/model: `3`
- Schedule: deterministic, sequential, interleaved
- Planned and completed attempts: `36`

The OpenRouter model pages were checked at `2026-07-24T09:22:10Z`. They listed
[`z-ai/glm-5.2`](https://openrouter.ai/z-ai/glm-5.2) with a 1M-token context and
[`openai/gpt-5-mini`](https://openrouter.ai/openai/gpt-5-mini/) with a 400K-token context.
The displayed input/output prices at that instant were respectively
`$0.7553/$2.374` and `$0.25/$2.00` per million tokens. These values are a dated catalog
snapshot only; RepoSuture did not calculate monetary cost.

Catalog availability did not guarantee request permission. Every GPT-5 Mini request was
rejected by the upstream provider with HTTP 403 for provider Terms of Service before the
model produced a tool call. The report therefore preserves those attempts as
`MODEL_API_ERROR`; it does not reinterpret them as model repair failures or replace them.

## Aggregate comparison

| Metric | `z-ai/glm-5.2` | `openai/gpt-5-mini` |
|---|---:|---:|
| Resolved attempts | 18/18 | 0/18 |
| Empirical attempt rate | 1.000 | 0.000 |
| Descriptive 95% Wilson interval | [0.824, 1.000] | [0.000, 0.176] |
| Cases resolved at least once | 6/6 | 0/6 |
| Cases resolved in all three attempts | 6/6 | 0/6 |
| Baseline failures reproduced | 18/18 | 18/18 |
| Target / regression PASS | 18 / 18 | 0 / 0 |
| Model turns / requests / API errors | 88 / 88 / 0 | 18 / 18 / 18 |
| Generated / executed / discarded tool calls | 125 / 88 / 37 | 0 / 0 / 0 |
| Tool-call discard rate | 29.6% | 0.0% |
| Patch attempts / rejected attempts | 20 / 2 | 0 / 0 |
| Normalization / recount-used attempts | 0 / 8 | 0 / 0 |
| Tokens (input / output / reasoning) | 202,373 / 7,999 / 3,988 | 0 / 0 / 0 |
| Average model latency | 65.673s | 0.000s |
| Average test duration | 13.883s | 4.748s |
| Average wall-clock duration | 80.753s | 6.091s |
| Average final Patch size | 573.389 bytes | 0 bytes |
| Original-repository integrity | 18/18 | 18/18 |

The GPT latency and token values are zero because the provider rejected each request before
a response was generated. Its wall-clock and test durations include genuine baseline
reproduction. This makes the observed system-level reliability difference clear, but it
does **not** provide a valid head-to-head comparison of repair capability.

## Per-Case and per-attempt outcomes

Each run cell is `final status (target/regression)`.

| Case | GLM success | GLM run 1 | GLM run 2 | GLM run 3 | GPT-5 Mini success | GPT run 1 | GPT run 2 | GPT run 3 |
|---|---:|---|---|---|---:|---|---|---|
| `null-input-validation` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `pagination-boundary` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `status-filtering` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `shipping-eligibility` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `country-code-normalization` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `quota-regression-trap` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |

## Tool protocol and Patch evidence

GLM executed 88 of 125 generated calls. RepoSuture deterministically discarded 37 extra
provider calls to preserve the single-action loop, for a 29.6% discard rate. Executed tool
usage was:

- `read_file=39`
- `apply_patch=20`
- `search_code=19`
- `list_files=10`

Twenty Patch attempts produced 18 verified repairs. Two malformed attempts were safely
rejected and later corrected. No textual normalization was needed; eight accepted Patches
used the narrow `git apply --recount` path. No rejected Patch triggered target or regression
tests.

Final failure categories were `RESOLVED=18` for GLM and `MODEL_API=18` for GPT-5 Mini.
There was no confirmed RepoSuture framework defect, no duplicate resume execution, and no
attempt from another commit in this dataset.

## Integrity review

All 36 reports used the same clean commit, fingerprint, public Case text, tools, budgets,
timeouts, Patch policy, endpoint, sequential policy, and deterministic verifier. Each
attempt used a fresh Agent conversation and worktree. All worktrees were removed and all
original repositories remained unchanged.

The completed matrix was replayed through strict `--resume`; all 36 observations were
reused without another API request. Report/trace/trajectory identity and deterministic
test evidence were checked for every run. Exact credential, Authorization-header, and
Agent-visible hidden-metadata scans returned zero matches. Raw live artifacts remain
ignored and are not committed.

The sanitized machine-readable summary is
[`reposuture-mvp-two-model-r3-summary.json`](reposuture-mvp-two-model-r3-summary.json).
