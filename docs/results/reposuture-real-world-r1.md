# RepoSuture real-world Java evaluation — R1

This is a genuine live-model evaluation of the locked `maven-real-world-v1` suite. It
contains exactly one attempt for each of three upstream Bugs and each of two models:
**six assigned attempts in total**. A zero-success or failed attempt was retained rather
than replaced.

One run per Case/model is a smoke-level empirical observation. It is not pass@k, is not
statistically robust, and does not establish broad real-world Java repair capability.

## Reproducibility

- Evaluation completed: `2026-07-24T09:17:48.356746Z`
- RepoSuture commit: `6f0ced786524c7e4f3514a284b826eac9865bcac`
- Source tree: `dirty=false`
- Provider: OpenRouter-compatible Responses API
- Endpoint: `https://openrouter.ai/api/v1`
- Models: `z-ai/glm-5.2` and `openai/gpt-5-mini`
- Suite: `maven-real-world-v1`
- Benchmark fingerprint:
  `345839d264b3b5c144fa8f9bbc75b419d917a4c0266d80c119c3dfb34ec19e82`
- Runs per Case/model: `1`
- Schedule: deterministic, sequential, interleaved
- Planned and completed attempts: `6`

## Upstream provenance and construction

| Case | Upstream project | Public bug/fix record | License | Buggy commit | Fix commit | Category |
|---|---|---|---|---|---|---|
| `commons-lang-mid-overflow` | Apache Commons Lang | [PR #1699](https://github.com/apache/commons-lang/pull/1699) | Apache-2.0 | `e6b8bbd39505694012d869fa2107ef068b88d800` | `2240c1f93e5f96b12a83ec8615c29dfac46258e9` | overflow boundary across two production APIs |
| `commons-collections-int-value` | Apache Commons Collections | [PR #704](https://github.com/apache/commons-collections/pull/704) | Apache-2.0 | `b219ccbe7b95250abd3ba3143edf340b7fad1943` | `6171ecbb1dc89f3e2d3bae659b6364995fbc6027` | numeric data conversion |
| `commons-collections-flat3map-entry` | Apache Commons Collections | [PR #714](https://github.com/apache/commons-collections/pull/714) | Apache-2.0 | `68a3c306d81dffe5bad59443dba3a7f5513178f4` | `14375bdba38421c174d646c40b8b757cce52dd45` | collection-entry conditional semantics |

Each fixture starts from the exact buggy commit, applies only the upstream regression-test
change, proves production code still matches the buggy commit, and creates a deterministic
local benchmark commit. The validation-only production Patch is derived from the upstream
fix and proves baseline FAIL → target PASS → regression PASS. It is never included in the
Agent prompt, tool output, trace, or trajectory. See
[`docs/REAL_WORLD_BENCHMARK.md`](../REAL_WORLD_BENCHMARK.md) for selection and construction
details.

## Aggregate comparison

| Metric | `z-ai/glm-5.2` | `openai/gpt-5-mini` |
|---|---:|---:|
| Resolved attempts | 2/3 | 0/3 |
| Empirical attempt rate | 0.667 | 0.000 |
| Descriptive 95% Wilson interval | [0.208, 0.939] | [0.000, 0.561] |
| Cases resolved at least once | 2/3 | 0/3 |
| Baseline failures reproduced | 3/3 | 3/3 |
| Target / regression PASS | 3 / 2 | 0 / 0 |
| Model turns / requests / API errors | 27 / 27 / 0 | 3 / 3 / 3 |
| Generated / executed / discarded tool calls | 28 / 27 / 1 | 0 / 0 / 0 |
| Tool-call discard rate | 3.57% | 0.0% |
| Patch attempts / rejected attempts | 6 / 2 | 0 / 0 |
| Normalization / recount-used attempts | 0 / 1 | 0 / 0 |
| Tokens (input / output / reasoning) | 218,835 / 14,510 / 14,504 | 0 / 0 / 0 |
| Average model latency | 288.294s | 0.000s |
| Average test duration | 489.750s | 61.521s |
| Average wall-clock duration | 792.677s | 70.922s |
| Average final Patch size | 788.667 bytes | 0 bytes |
| Original-repository integrity | 3/3 | 3/3 |

As in the MVP matrix, every GPT-5 Mini attempt was rejected by the upstream provider with
HTTP 403 for provider Terms of Service before a tool call. Those `MODEL_API_ERROR`
observations are not evidence about repair quality and make a capability head-to-head
comparison impossible for this run.

## Complete attempt evidence

Tokens are `input/output/reasoning`.

| Seq | Model | Case | Final | Target | Regression | Turns | Tools | Patches | Tokens | Duration | Failure | Normalize | Recount |
|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| 1 | `openai/gpt-5-mini` | `commons-lang-mid-overflow` | MODEL_API_ERROR | NOT_RUN | NOT_RUN | 1 | 0 | 0 | 0/0/0 | 95.406s | MODEL_API | no | no |
| 2 | `z-ai/glm-5.2` | `commons-lang-mid-overflow` | AGENT_BUDGET_EXHAUSTED | PASS | FAIL | 18 | 18 | 3 | 189069/13485/13778 | 1456.922s | SEARCH_FAILURE | no | yes |
| 3 | `z-ai/glm-5.2` | `commons-collections-int-value` | RESOLVED | PASS | PASS | 3 | 3 | 1 | 7291/385/342 | 518.313s | RESOLVED | no | no |
| 4 | `openai/gpt-5-mini` | `commons-collections-int-value` | MODEL_API_ERROR | NOT_RUN | NOT_RUN | 1 | 0 | 0 | 0/0/0 | 54.422s | MODEL_API | no | no |
| 5 | `openai/gpt-5-mini` | `commons-collections-flat3map-entry` | MODEL_API_ERROR | NOT_RUN | NOT_RUN | 1 | 0 | 0 | 0/0/0 | 62.937s | MODEL_API | no | no |
| 6 | `z-ai/glm-5.2` | `commons-collections-flat3map-entry` | RESOLVED | PASS | PASS | 6 | 6 | 2 | 22475/640/384 | 402.797s | RESOLVED | no | no |

The Commons Lang attempt visibly exercised feedback-driven replanning. Its first accepted
candidate passed the target but failed the regression suite, so RepoSuture reverted it and
returned the failure to the Agent. A later Patch was policy-rejected, another accepted
candidate again passed the target and failed regression, and the run ended at the fixed
18-turn budget. The final status remained `AGENT_BUDGET_EXHAUSTED`; the aggregate failure
taxonomy records `SEARCH_FAILURE` from the final failed search observation. No false
`RESOLVED` occurred.

The Flat3Map attempt's first malformed Patch failed the strict and recount checks. The Agent
received the structured rejection, submitted a second Patch, and then passed target and
regression tests. The accepted Patch did not require recount.

Executed GLM tool usage was `search_code=10`, `read_file=9`, `apply_patch=6`,
`list_files=1`, and `run_target_test=1`. Final failure categories were `RESOLVED=2` and
`SEARCH_FAILURE=1` for GLM, plus `MODEL_API=3` for GPT-5 Mini.

## Integrity and limitations

Real Maven and JUnit executed for every baseline and every accepted candidate. All six
reports used the same clean commit, suite fingerprint, public Case text, budgets, tools,
Patch policy, endpoint, and correctness oracle. Every worktree was removed, upstream
caches remained unchanged, and original repository integrity was 6/6.

Strict `--resume` reused all six completed observations without another API request.
Credential, Authorization-header, and Agent-visible hidden-fix scans returned zero
matches. No third-party clone, raw Patch, raw provider body, complete Maven log, or live
artifact directory is committed.

Windows build speed materially affected duration: the relevant Apache regression suites
are much larger than the MVP fixtures. One run per Case/model and two upstream projects are
far too small for broad generalization.

The sanitized machine-readable summary is
[`reposuture-real-world-r1-summary.json`](reposuture-real-world-r1-summary.json).
