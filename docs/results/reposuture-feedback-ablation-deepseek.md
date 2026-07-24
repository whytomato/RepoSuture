# RepoSuture DeepSeek feedback ablation — not executed

> **No live ablation result exists for this task.** The 12-attempt plan was
> locked and dry-run verified, but zero ablation attempts were assigned.

## Locked plan

- Model: `deepseek/deepseek-v4-pro`
- Provider: OpenRouter-compatible Responses API
- Cases: 6
- Modes: `full-agent` and `single-candidate-no-feedback`
- Runs per Case/mode: 1
- Planned attempts: `6 × 2 = 12`
- Schedule: deterministic, sequential, interleaved
- Assigned attempts: `0`
- Completed attempts: `0`

The locked Cases were:

1. `commons-lang-mid-overflow`
2. `commons-collections-int-value`
3. `commons-codec-zero-big-integer`
4. `commons-io-bounded-reader-skip`
5. `commons-csv-supplementary-delimiter`
6. `commons-beanutils-nondouble-number`

The dry run alternated the two modes across Cases and produced 12 unique,
mode-specific run identifiers. Both modes would use the same public Case,
baseline evidence, exploration tools, Patch policy, Maven/JUnit verifier,
budgets, and model. The only intended difference is whether verification
feedback can return to the model and a second candidate can be attempted.

## Why execution did not start

The preceding repair evaluation exposed a generic framework defect after
15 paid attempts had already been assigned. The task policy required the
repair dataset to be invalidated and restarted after the correction.
Restarting 28 repair attempts and then assigning 12 ablation attempts would
raise the cumulative total to 55, above the hard cap of 40. The policy also
allowed ablation only after the repair evaluation completed without generic
framework corruption.

RepoSuture therefore made no further paid request. It did not replace
failures, reduce the subset, change the model, or report scripted results as
live evidence.

## Metrics

| Metric | Full Agent | Single candidate, no feedback |
|---|---:|---:|
| Assigned attempts | 0 | 0 |
| Completed attempts | 0 | 0 |
| Resolved attempts | N/A | N/A |
| Target PASS | N/A | N/A |
| Regression PASS | N/A | N/A |
| Target-only false repairs | N/A | N/A |
| Patch rejections | N/A | N/A |
| Turns / tools / Patches | N/A | N/A |
| Tokens / latency | N/A | N/A |
| Primary failures | N/A | N/A |
| Observed failures | N/A | N/A |

No Case can be said to have benefited from Patch-rejection feedback,
target-test feedback, regression feedback, rollback, or replanning in a
live controlled comparison, because no live paired observation was made.

The pre-live scripted integration remains harness evidence only: it used
real Git, Maven, JUnit, target verification, regression verification, and
rollback; full-agent resolved the regression trap while the no-feedback
mode ended after target PASS/regression FAIL. That result is not model
capability evidence and is not included in this live report.

## Required future evaluation

A valid ablation requires a fresh authorization and budget, one clean
committed implementation, all 12 locked attempts, and no mixing with the
invalidated partial repair observations. One run per mode remains a small
controlled engineering ablation and cannot establish causal certainty.
