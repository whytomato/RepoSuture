# RepoSuture real-world V2 evaluation — GLM-5.2 and DeepSeek V4 Pro

This is the canonical RepoSuture 0.4 live repair evaluation. It contains
**28 fresh assigned and completed attempts** from one immutable clean source commit.
No failed attempt was replaced, no prior partial observation was resumed, and no GPT
model was used.

The result is descriptive. It is **not pass@k**: the original three Bugs have three
repetitions per model, while each of the five additions has one breadth observation per
model. Three repetitions remain a small sample and one observation is not a stable
success-rate estimate. This suite does not establish universal Java repair capability.

## Reproducibility

- Evaluation window: `2026-07-25T10:36:17.369224Z` to
  `2026-07-25T13:19:47.992738Z`
- RepoSuture experiment commit:
  `e3cafd30edec3802c6bf88177e9c6a702e9c7e03`
- Source tree: `dirty=false`
- Provider: OpenRouter-compatible Responses API
- Endpoint: `https://openrouter.ai/api/v1`
- Models: `z-ai/glm-5.2` and `deepseek/deepseek-v4-pro`
- Suite: `maven-real-world-v2`
- Benchmark fingerprint:
  `65d9547c2a05574d85a8d8689bd3e925ae7b24683bd22d417a05022dd8a7b1e2`
- Schedule: deterministic, sequential, interleaved
- Original Cases: `3 Cases × 3 runs × 2 models = 18 attempts`
- Added Cases: `5 Cases × 1 run × 2 models = 10 attempts`
- Total: `28 assigned = 28 completed`
- Dry-run plan SHA-256:
  `7c65663bc8a98614b3d5a4175293dbc5d2221e98fbe686f32b2655fd6bb607cf`

The public OpenRouter catalog was checked on `2026-07-25` before execution. Both exact
model ids were present, each advertised `tools` and `tool_choice`, and each advertised a
1,048,576-token context. Catalog availability was not treated as execution evidence;
Provider/model lifecycle counts below come from the completed run reports.

An earlier partial run on a pre-correction commit exposed a generic classification defect:
a model-generated candidate compilation failure was incorrectly classified as
infrastructure. That dataset was invalidated, the defect was fixed before this clean
rerun, and **none of its observations are included here**.

## Denominators and aggregate result

RepoSuture reports three different rates:

- system end-to-end resolution = resolved / assigned;
- Provider acceptance = Provider-accepted / assigned;
- capability resolution = resolved / model-executed.

When model-executed is zero, capability and its Wilson interval are N/A rather than 0%.
That zero-denominator case did not occur in this experiment: all 28 attempts entered real
model execution and produced at least one valid model-requested Tool Call.

| Metric | GLM-5.2 | DeepSeek V4 Pro | Combined |
|---|---:|---:|---:|
| Assigned / completed | 14 / 14 | 14 / 14 | 28 / 28 |
| Baseline reproduced | 14 | 14 | 28 |
| Provider accepted | 14 | 14 | 28 |
| Model executed | 14 | 14 | 28 |
| Model Tool Call observed | 14 | 14 | 28 |
| Resolved | 12 | 11 | 23 |
| System end-to-end rate | 0.857 | 0.786 | 0.821 |
| System descriptive Wilson 95% | [0.601, 0.960] | [0.524, 0.924] | [0.644, 0.921] |
| Provider acceptance rate | 1.000 | 1.000 | 1.000 |
| Capability rate | 0.857 | 0.786 | 0.821 |
| Capability descriptive Wilson 95% | [0.601, 0.960] | [0.524, 0.924] | [0.644, 0.921] |
| Target PASS | 13 | 13 | 26 |
| Regression PASS | 12 | 11 | 23 |
| Original-repository integrity | 14/14 | 14/14 | 28/28 |

The intervals are descriptive Wilson intervals over attempt-level observations. The
overlap is substantial; the resolved-count difference is not evidence of a statistically
conclusive winner.

## Original three-Bug stability

Each cell shows the three terminal statuses in run order.

| Case | GLM success | GLM runs | DeepSeek success | DeepSeek runs |
|---|---:|---|---:|---|
| `commons-lang-mid-overflow` | 2/3 | RESOLVED, RESOLVED, AGENT_BUDGET_EXHAUSTED | 1/3 | MODEL_STOPPED, RESOLVED, AGENT_BUDGET_EXHAUSTED |
| `commons-collections-int-value` | 3/3 | RESOLVED, RESOLVED, RESOLVED | 3/3 | RESOLVED, RESOLVED, RESOLVED |
| `commons-collections-flat3map-entry` | 3/3 | RESOLVED, RESOLVED, RESOLVED | 3/3 | RESOLVED, RESOLVED, RESOLVED |

Both models were stable on the two Commons Collections Bugs in these three repetitions.
Commons Lang remained regression-sensitive: GLM resolved two of three and DeepSeek one of
three. The unresolved runs retained target-PASS/regression-FAIL evidence and were not
replaced.

## Five new-Bug breadth observations

Each result is one attempt only and must not be read as a stable success rate.

| Case | Category | GLM | DeepSeek |
|---|---|---|---|
| `commons-codec-zero-big-integer` | binary encoding boundary | RESOLVED | RESOLVED |
| `commons-text-csv-lone-quote` | CSV quote parsing | RESOLVED | RESOLVED |
| `commons-io-bounded-reader-skip` | range accounting | RESOLVED | RESOLVED |
| `commons-csv-supplementary-delimiter` | Unicode delimiter byte tracking | MODEL_STOPPED | MODEL_STOPPED |
| `commons-beanutils-nondouble-number` | numeric conversion | RESOLVED | RESOLVED |

Both models resolved four of the five breadth observations. Neither submitted an accepted
candidate for the Commons CSV supplementary-delimiter Case before stopping.

## Complete attempt evidence

Tools are `generated/executed/discarded`; tokens are
`input/output/reasoning`. Reasoning tokens are provider telemetry and are not hidden
reasoning content.

| Seq | Case | Run | Model | Terminal | Primary failure | Target | Regression | Turns | Tools | Patches (rejected) | Tokens | Wall s |
|---:|---|---:|---|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | `commons-lang-mid-overflow` | 1 | DeepSeek | MODEL_STOPPED | REGRESSION_UNRESOLVED | PASS | FAIL | 11 | 11/10/1 | 1 (0) | 55,341/2,628/1,426 | 445.781 |
| 2 | `commons-lang-mid-overflow` | 1 | GLM | RESOLVED | — | PASS | PASS | 18 | 21/18/3 | 3 (0) | 181,143/5,840/4,701 | 1,133.266 |
| 3 | `commons-collections-int-value` | 1 | GLM | RESOLVED | — | PASS | PASS | 7 | 8/7/1 | 2 (1) | 22,589/1,123/539 | 498.625 |
| 4 | `commons-collections-int-value` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 5 | 7/5/2 | 1 (0) | 16,918/1,197/400 | 372.234 |
| 5 | `commons-collections-flat3map-entry` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 9 | 9/9/0 | 1 (0) | 56,684/2,187/1,228 | 275.265 |
| 6 | `commons-collections-flat3map-entry` | 1 | GLM | RESOLVED | — | PASS | PASS | 8 | 8/8/0 | 1 (0) | 22,174/599/97 | 183.532 |
| 7 | `commons-codec-zero-big-integer` | 1 | GLM | RESOLVED | — | PASS | PASS | 5 | 6/5/1 | 1 (0) | 15,595/1,099/711 | 58.797 |
| 8 | `commons-codec-zero-big-integer` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 1 (0) | 77,223/5,653/4,408 | 177.610 |
| 9 | `commons-text-csv-lone-quote` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 3 | 4/3/1 | 1 (0) | 10,201/1,482/966 | 88.469 |
| 10 | `commons-text-csv-lone-quote` | 1 | GLM | RESOLVED | — | PASS | PASS | 2 | 2/2/0 | 1 (0) | 4,990/444/198 | 41.781 |
| 11 | `commons-io-bounded-reader-skip` | 1 | GLM | RESOLVED | — | PASS | PASS | 4 | 6/4/2 | 1 (0) | 10,982/1,000/635 | 72.250 |
| 12 | `commons-io-bounded-reader-skip` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 1 (0) | 76,018/6,366/5,250 | 204.594 |
| 13 | `commons-csv-supplementary-delimiter` | 1 | DeepSeek | MODEL_STOPPED | NO_PATCH_ACCEPTED | NOT_RUN | NOT_RUN | 9 | 10/8/2 | 0 (0) | 63,858/10,991/10,108 | 247.235 |
| 14 | `commons-csv-supplementary-delimiter` | 1 | GLM | MODEL_STOPPED | NO_PATCH_ACCEPTED | NOT_RUN | NOT_RUN | 8 | 9/7/2 | 0 (0) | 49,791/5,081/4,779 | 94.109 |
| 15 | `commons-beanutils-nondouble-number` | 1 | GLM | RESOLVED | — | PASS | PASS | 11 | 15/11/4 | 1 (0) | 58,471/1,024/292 | 148.969 |
| 16 | `commons-beanutils-nondouble-number` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 12 | 15/12/3 | 1 (0) | 61,365/2,529/976 | 230.453 |
| 17 | `commons-lang-mid-overflow` | 2 | GLM | RESOLVED | — | PASS | PASS | 10 | 10/10/0 | 2 (0) | 46,835/1,442/752 | 476.953 |
| 18 | `commons-lang-mid-overflow` | 2 | DeepSeek | RESOLVED | — | PASS | PASS | 13 | 14/13/1 | 2 (0) | 86,941/4,856/3,286 | 758.719 |
| 19 | `commons-collections-int-value` | 2 | DeepSeek | RESOLVED | — | PASS | PASS | 4 | 5/4/1 | 1 (0) | 12,778/922/284 | 363.797 |
| 20 | `commons-collections-int-value` | 2 | GLM | RESOLVED | — | PASS | PASS | 3 | 3/3/0 | 1 (0) | 7,334/322/46 | 331.672 |
| 21 | `commons-collections-flat3map-entry` | 2 | GLM | RESOLVED | — | PASS | PASS | 13 | 14/13/1 | 3 (1) | 79,610/1,304/253 | 421.110 |
| 22 | `commons-collections-flat3map-entry` | 2 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 2 (0) | 89,924/2,240/713 | 345.344 |
| 23 | `commons-lang-mid-overflow` | 3 | DeepSeek | AGENT_BUDGET_EXHAUSTED | REGRESSION_UNRESOLVED | PASS | FAIL | 18 | 19/18/1 | 1 (0) | 128,759/5,022/3,104 | 512.984 |
| 24 | `commons-lang-mid-overflow` | 3 | GLM | AGENT_BUDGET_EXHAUSTED | REGRESSION_UNRESOLVED | PASS | FAIL | 18 | 19/18/1 | 2 (0) | 203,190/6,670/5,840 | 816.422 |
| 25 | `commons-collections-int-value` | 3 | GLM | RESOLVED | — | PASS | PASS | 5 | 6/5/1 | 1 (0) | 11,861/392/48 | 341.093 |
| 26 | `commons-collections-int-value` | 3 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 1 (0) | 45,628/1,744/692 | 390.875 |
| 27 | `commons-collections-flat3map-entry` | 3 | DeepSeek | RESOLVED | — | PASS | PASS | 5 | 6/5/1 | 1 (0) | 31,409/1,401/596 | 385.563 |
| 28 | `commons-collections-flat3map-entry` | 3 | GLM | RESOLVED | — | PASS | PASS | 7 | 7/7/0 | 1 (0) | 23,490/586/131 | 390.438 |

## Failure analysis

The three failure dimensions remain separate:

| Distribution | GLM-5.2 | DeepSeek V4 Pro |
|---|---|---|
| Terminal status | RESOLVED=12, MODEL_STOPPED=1, AGENT_BUDGET_EXHAUSTED=1 | RESOLVED=11, MODEL_STOPPED=2, AGENT_BUDGET_EXHAUSTED=1 |
| Primary failure | NO_PATCH_ACCEPTED=1, REGRESSION_UNRESOLVED=1 | NO_PATCH_ACCEPTED=1, REGRESSION_UNRESOLVED=2 |
| Observed failures (non-exclusive) | SEARCH_TOOL_ERROR=6, READ_TOOL_ERROR=3, PATCH_REJECTED=2, PATCH_GIT_CHECK_FAILED=1, TARGET_TEST_FAILED=1, REGRESSION_FAILED=3, CANDIDATE_REVERTED=4, MODEL_STOPPED=1, BUDGET_EXHAUSTED=1 | SEARCH_TOOL_ERROR=8, READ_TOOL_ERROR=1, TARGET_TEST_FAILED=1, REGRESSION_FAILED=3, CANDIDATE_REVERTED=4, MODEL_STOPPED=2, BUDGET_EXHAUSTED=1 |

The two budget terminals retain `REGRESSION_UNRESOLVED` as the primary cause. A later
search error or budget event did not overwrite stronger target-PASS/regression-FAIL
evidence. There were no Provider rejections, API failures, infrastructure failures,
repository-integrity failures, or artifact-integrity failures.

## Tool, Patch, token, and timing evidence

| Metric | GLM-5.2 | DeepSeek V4 Pro |
|---|---:|---:|
| Model turns / requests | 119 / 119 | 129 / 129 |
| Tool Calls generated / executed / discarded | 134 / 118 / 16 | 144 / 127 / 17 |
| Executed tools | read=48, search=43, patch=20, list=3, target=2, diff=2 | read=55, search=51, patch=15, list=3, target=2, diff=1 |
| Patch attempts / rejected | 20 / 2 | 15 / 0 |
| Runs using normalization | 0 | 13 |
| Normalization operations | 0 | 15 × `ENSURED_FINAL_NEWLINE` |
| Runs using recount | 7 | 4 |
| Input / output / reasoning tokens | 738,055 / 26,926 / 19,022 | 813,047 / 49,218 / 33,437 |
| Total model latency | 781.233s | 1,447.262s |
| Average model latency | 55.802s | 103.376s |
| Total test duration | 4,066.507s | 3,199.171s |
| Average test duration | 290.465s | 228.512s |
| Total wall-clock duration | 5,009.017s | 4,798.923s |
| Average wall-clock duration | 357.787s | 342.780s |

DeepSeek generated more output/reasoning tokens and had higher model latency in this
sample. GLM submitted more candidate Patches and used recount more often. Tool-protocol
discarding occurred for both models because only the first provider call per turn is
executed by the single-action Agent loop.

## Integrity review

- All 28 individual reports, traces, trajectories, attempt manifests, artifact sizes,
  and SHA-256 values were reloaded and validated.
- All reports record the exact experiment commit and `dirty=false`.
- All 28 baselines genuinely reproduced; real Maven/JUnit ran for baselines and accepted
  candidates.
- Every temporary worktree was removed. All eight fixture repositories remained clean
  with only their original registered worktree.
- Exact API-key and Authorization-header scans across the raw local artifact root found
  zero matches.
- Agent-visible trace/trajectory scans found zero hidden-fix, golden-Patch, validation
  metadata, or raw Patch-body markers.
- Raw live artifacts and third-party caches remain ignored and are not committed.

The sanitized machine-readable companion is
[`reposuture-real-v2-glm-deepseek-summary.json`](reposuture-real-v2-glm-deepseek-summary.json).
