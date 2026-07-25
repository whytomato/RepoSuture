# RepoSuture DeepSeek feedback-loop ablation

This is the canonical RepoSuture 0.4 feedback-loop ablation result. It is
a controlled engineering comparison, not a causal or statistically
conclusive estimate.

## Result

- Evaluation window (UTC): `2026-07-25T13:22:39.963223Z` to
  `2026-07-25T14:16:01.817650Z`
- Experiment commit:
  `e3cafd30edec3802c6bf88177e9c6a702e9c7e03`
- Source tree: `dirty=false`
- Provider: OpenRouter-compatible Responses API
- Model: `deepseek/deepseek-v4-pro`
- Suite: `maven-real-world-v2`
- Benchmark fingerprint:
  `65d9547c2a05574d85a8d8689bd3e925ae7b24683bd22d417a05022dd8a7b1e2`
- Schedule: deterministic, sequential, interleaved
- Dry-run plan SHA-256:
  `6f7f9181cd50fc622e373b3c4585bc0ae8e78da353de563af05ed1a58f52616c`
- Assigned/completed attempts: `12 / 12`
- Replacement attempts: `0`
- Framework defects detected: `0`

## Mode comparison

| Metric | Full Agent | Single candidate, no feedback |
|---|---:|---:|
| Assigned / completed | 6 / 6 | 6 / 6 |
| Provider accepted | 6 | 6 |
| Model executed | 6 | 6 |
| Model requested a valid tool | 6 | 6 |
| Resolved | 6 | 3 |
| Target PASS | 6 | 4 |
| Regression PASS | 6 | 3 |
| Target-only false repairs | 0 | 1 |
| Model turns / requests | 55 / 55 | 45 / 45 |
| Generated / executed / discarded tool calls | 62 / 55 / 7 | 51 / 43 / 8 |
| Patch attempts / rejected | 9 / 1 | 4 / 0 |
| Input / output / reasoning tokens | 379,508 / 27,836 / 20,104 | 270,533 / 18,539 / 11,394 |
| Model latency | 752.657 s | 507.117 s |
| Test duration | 945.188 s | 903.517 s |
| Wall-clock duration | 1,745.722 s | 1,455.062 s |

Both modes used the same commit, model, public Cases, initial failure
evidence, exploration tools, Patch policy, target tests, regression tests,
timeouts, budgets, and deterministic verifier. The intended difference
was only that full-agent mode could receive post-Patch observations,
rollback, replan, and submit another Patch within its existing budget.
Single-candidate mode could submit at most one candidate and received no
post-Patch feedback.

## Per-Case outcomes

| Case | Full Agent | Target / regression | No feedback | Target / regression |
|---|---|---|---|---|
| `commons-lang-mid-overflow` | RESOLVED | PASS / PASS | REGRESSION_FAILED | PASS / FAIL |
| `commons-collections-int-value` | RESOLVED | PASS / PASS | RESOLVED | PASS / PASS |
| `commons-codec-zero-big-integer` | RESOLVED | PASS / PASS | RESOLVED | PASS / PASS |
| `commons-io-bounded-reader-skip` | RESOLVED | PASS / PASS | MODEL_STOPPED | NOT_RUN / NOT_RUN |
| `commons-csv-supplementary-delimiter` | RESOLVED | PASS / PASS | MODEL_STOPPED | NOT_RUN / NOT_RUN |
| `commons-beanutils-nondouble-number` | RESOLVED | PASS / PASS | RESOLVED | PASS / PASS |

The single-candidate Lang attempt is the one target-only false repair:
the target passed, the regression suite failed, and the candidate was
rolled back. By design, that observation did not return to the model and
no REPLAN or second Patch occurred.

## Feedback, rollback, and replanning evidence

The strongest observed feedback loop occurred on
`commons-beanutils-nondouble-number` in full-agent mode:

1. two accepted candidates failed the target test;
2. both candidates were reverted;
3. each deterministic failure produced a REPLAN request;
4. a later candidate was policy-rejected and its structured rejection was
   returned to the Agent;
5. the fourth Patch attempt passed both target and regression tests.

That run recorded `TARGET_TEST_FAILED`, `CANDIDATE_REVERTED`,
`PATCH_REJECTED`, and `PATCH_POLICY_REJECTED`. Its REPLAN reasons were two
`TARGET_TEST_FAILED`, two `CANDIDATE_REVERTED`, and one `PATCH_REJECTED`.

No full-agent run consumed regression-failure feedback in this sample:
the only regression failure occurred in the no-feedback Lang attempt.
The full-agent Lang attempt resolved on its first candidate. It is
therefore accurate to say that the experiment observed a target-test and
Patch-rejection recovery path, but not to attribute the aggregate
difference to regression feedback or to claim that feedback caused every
paired difference.

## Failure dimensions

### Terminal status

| Status | Full Agent | No feedback |
|---|---:|---:|
| RESOLVED | 6 | 3 |
| MODEL_STOPPED | 0 | 2 |
| REGRESSION_FAILED | 0 | 1 |

### Primary failure

| Primary failure | Full Agent | No feedback |
|---|---:|---:|
| NO_PATCH_ACCEPTED | 0 | 2 |
| REGRESSION_UNRESOLVED | 0 | 1 |

### Observed-failure occurrences

| Observed failure | Full Agent | No feedback |
|---|---:|---:|
| CANDIDATE_REVERTED | 1 | 1 |
| PATCH_POLICY_REJECTED | 1 | 0 |
| PATCH_REJECTED | 1 | 0 |
| SEARCH_TOOL_ERROR | 1 | 2 |
| TARGET_TEST_FAILED | 1 | 0 |
| MODEL_STOPPED | 0 | 2 |
| REGRESSION_FAILED | 0 | 1 |

Terminal status, primary causal classification, and the ordered
non-exclusive observed-failure list remain separate.

## Per-attempt evidence

| Case | Mode | Status | Turns | Tools | Patches | Target | Regression | Tokens | Latency | Duration |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|
| `commons-lang-mid-overflow` | full-agent | RESOLVED | 8 | 8 | 1 | PASS | PASS | 50,646 | 74.017 s | 401.407 s |
| `commons-lang-mid-overflow` | no-feedback | REGRESSION_FAILED | 3 | 3 | 1 | PASS | FAIL | 10,838 | 59.805 s | 407.359 s |
| `commons-collections-int-value` | no-feedback | RESOLVED | 10 | 10 | 1 | PASS | PASS | 46,284 | 67.242 s | 407.609 s |
| `commons-collections-int-value` | full-agent | RESOLVED | 4 | 4 | 1 | PASS | PASS | 13,670 | 39.681 s | 348.969 s |
| `commons-codec-zero-big-integer` | full-agent | RESOLVED | 9 | 9 | 1 | PASS | PASS | 57,644 | 100.679 s | 167.329 s |
| `commons-codec-zero-big-integer` | no-feedback | RESOLVED | 5 | 5 | 1 | PASS | PASS | 39,680 | 71.004 s | 133.812 s |
| `commons-io-bounded-reader-skip` | no-feedback | MODEL_STOPPED | 5 | 4 | 0 | NOT_RUN | NOT_RUN | 22,924 | 74.379 s | 117.703 s |
| `commons-io-bounded-reader-skip` | full-agent | RESOLVED | 11 | 11 | 1 | PASS | PASS | 82,014 | 115.363 s | 207.032 s |
| `commons-csv-supplementary-delimiter` | full-agent | RESOLVED | 9 | 9 | 1 | PASS | PASS | 69,417 | 270.875 s | 319.938 s |
| `commons-csv-supplementary-delimiter` | no-feedback | MODEL_STOPPED | 9 | 8 | 0 | NOT_RUN | NOT_RUN | 64,887 | 129.908 s | 148.266 s |
| `commons-beanutils-nondouble-number` | no-feedback | RESOLVED | 13 | 13 | 1 | PASS | PASS | 104,459 | 104.779 s | 240.313 s |
| `commons-beanutils-nondouble-number` | full-agent | RESOLVED | 14 | 14 | 4 | PASS | PASS | 133,953 | 152.042 s | 301.047 s |

## Integrity and limitations

All 12 reports, traces, trajectories, artifact sizes, and SHA-256 hashes
were replay-validated. Every attempt recorded the same experiment commit
with `dirty=false`; all baselines reproduced; original repositories
remained unchanged; temporary worktrees were removed. Scans found zero
API-key, Authorization-header, hidden-fix, hidden-Patch, raw-Patch-body,
or hidden-reasoning exposure.

One run per Case and mode is a small controlled engineering ablation.
Provider nondeterminism, model sampling, Case differences, and the small
sample prevent causal or statistical certainty. The verifier, not model
text, determined every RESOLVED result.
