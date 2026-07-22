# PatchPilot Java Bug Benchmark

## Purpose and boundary

Milestone 3 measures the existing single-Agent repair workflow against a small,
reproducible Java 17/Maven benchmark. It answers which attempts were resolved, which
failed, why they failed, and what bounded resources each attempt used. It does not add
Agent capabilities, generate tests, or treat model prose as proof of correctness.

The benchmark has two mutually exclusive execution modes:

- `scripted/offline` injects deterministic model actions to test orchestration. Git,
  `ToolExecutor`, Patch application, Maven, JUnit, target verification, and regression
  verification are real. These results are harness evidence, not model capability.
- `live model` uses the configured provider and a fresh model conversation for every
  attempt. Only results from a command actually run in this mode are live results.

A single aggregate can contain only one mode. PatchPilot rejects any attempt to mix
scripted and live records in one summary.

## MVP cases

The versioned suite is `benchmarks/suites/mvp.yaml`.

| Case id | Category | Production navigation | Behavior under test |
|---------|----------|-----------------------|---------------------|
| `null-input-validation` | Null input validation | One file | Missing email must produce the domain validation error. |
| `pagination-boundary` | Off-by-one pagination boundary | One file | A page includes every item inside its exclusive end boundary. |
| `status-filtering` | Incorrect enum/status filtering | Two related files | Active results include open and in-progress, but not closed, tickets. |
| `shipping-eligibility` | Incorrect boolean logic | One file | Address and payment approval are both required. |
| `country-code-normalization` | Normalization/case-insensitive comparison | Two related files | Harmless whitespace and case differences are normalized without accepting foreign codes. |
| `quota-regression-trap` | Target-pass/regression-fail trap | One file | Premium quota changes while standard and trial behavior remains intact. |

Every Case has a selected target JUnit method and at least one unrelated regression
test. The trap's scripted sequence first applies a naive candidate that passes the
target but fails another test, then submits a complete baseline-relative candidate that
passes the full suite.

Cases are intentionally small and offline after Maven dependencies are available. They
use no database, network service, timing behavior, generated source, or obscure build
configuration. They are an interview-readable MVP, not a representative sample of all
Java bugs.

## Manifest and integrity model

The suite manifest has a strict versioned schema, suite id and description, default
runs, default Agent budgets, tags, optional harness-only notes, and an ordered Case
list. Duplicate ids, missing files, unknown fields, invalid commits, escaped paths, and
public/hidden metadata disagreements invalidate the suite.

Each entry links three deliberately separate schemas:

1. `benchmarks/cases/<id>.yaml` is the schema-v2 Agent Case. It contains only the issue,
   target selector, fixed repository/commit, budgets, and allowed-file policy.
2. `benchmarks/validation/<id>.yaml` is schema-v1 validator input. It repeats the public
   fields and points to a hidden golden Patch.
3. `benchmarks/scripted/<id>.yaml` is harness-only deterministic action data for offline
   tests. It is not an Agent Case and is never serialized into a provider prompt.

The loader requires every public Agent field to equal the corresponding validation
field. The golden Patch must be outside the Agent repository. Only the public Agent Case
path is passed to `repair_case`; validation metadata and golden content never enter the
model prompt or any tool result. Golden Patches are correctness witnesses, not exact
output expectations, so any production-only Patch passing the executable oracle is
accepted.

The benchmark fingerprint is a SHA-256 over auditable components:

- canonical suite-manifest content;
- canonical Agent, validation, and scripted Case content;
- hidden validation and scripted Patch bytes;
- every fixed base commit;
- the complete Git tree listing for each fixture commit.

Reports retain the component hashes and overall fingerprint. Changing a Case or its
relevant fixture/support content changes the fingerprint. Absolute machine paths and
timestamps are not fingerprint inputs.

## Deterministic validation

Bootstrap the deterministic fixture repository, then validate all six Cases:

```powershell
python benchmarks/bootstrap_fixture.py

patchpilot validate-benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-benchmark-validation
```

For each Case, the validator performs schema and commit validation, creates a detached
worktree, runs the selected baseline target, proves from Surefire XML that the target
executed and failed, applies a nonempty hidden Patch, reruns the target, runs the full
Maven regression suite, verifies that only production code changed, fingerprints the
source repository before and after, removes the worktree, and verifies cleanup.

A Case is valid only if all checks pass. A compile error, missing/zero/skipped target,
timeout, dependency failure, empty Patch, test/build/Wrapper/CI change, target failure,
regression failure, repository mutation, or cleanup failure makes it invalid. The
command continues across Case-level invalidity so the report is complete, then returns
nonzero.

Validation artifacts are:

- `validation-summary.json` — structured aggregate and reproducibility metadata;
- `validation-summary.csv` — one row per Case;
- `validation-report.md` — compact human-readable table;
- `cases/<deterministic-id>/` — per-Case `report.json`, `trace.jsonl`, `final.patch`,
  and bounded Maven logs.

## Batch Agent execution

Live OpenAI execution requires explicit credentials and a model identifier and may
consume paid API quota:

```powershell
$env:OPENAI_API_KEY = "<your-api-key>"
$env:PATCHPILOT_MODEL = "<your-model-name>"

patchpilot benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-benchmark-live `
  --provider openai `
  --runs-per-case 1
```

The offline orchestration check requires no API key or network access after Maven
dependencies are cached:

```powershell
patchpilot benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-benchmark-scripted `
  --provider scripted `
  --runs-per-case 1
```

Useful live options include `--model`, repeatable `--case`, `--runs-per-case`,
`--random-seed`, `--max-turns`, `--max-tool-calls`, `--max-patch-attempts`,
`--max-target-test-executions`, `--max-regression-executions`, and
`--max-wall-clock-seconds`. `--continue-on-failure` is the default;
`--stop-on-failure` is available for an intentional early stop. Cases run sequentially.

Every attempt has a deterministic id derived from suite id, mode, Case id, run number,
and fingerprint. It uses a fresh detached worktree, fresh `LLMClient`/conversation, and
independent artifact directory. No worktree, conversation, candidate, or tool state is
reused across attempts. An unresolved attempt does not prevent later attempts under the
default policy.

The aggregate artifacts are:

- `benchmark-summary.json` — complete structured aggregate plus every run record;
- `benchmark-runs.csv` — one consistent tabular row per attempt;
- `benchmark-report.md` — deterministic metrics and failure-analysis tables;
- `runs/<deterministic-id>/` — per-run report, canonical trace, safe `trajectory.md`, final
  Patch, and Maven logs.

Artifact roots are never overwritten when aggregate files already exist. Choose a new
directory for a new run so prior evidence remains reproducible.

## Agent trajectory and replay

Each scripted or live Agent attempt derives `trajectory.md` from its sanitized
`trace.jsonl`; no second orchestration history is maintained. The document records the public
goal, PREPARE/OBSERVE/DECIDE/ACT/VERIFY/REPLAN/FINISH timeline, deterministic verification,
budgets, counters, timing, and final status. It never embeds the raw Patch, source-file
contents, complete Maven logs, credentials, hidden reasoning, golden Patch data, or hidden
validation metadata. A successful trajectory names `final.patch` and records its SHA-256.

Replay one successful or failed benchmark attempt without a provider, network, Git mutation,
or Maven execution:

```powershell
patchpilot replay-run .artifacts-benchmark-scripted/runs/<run-id> `
  --view verbose --format text --no-color

patchpilot replay-run .artifacts-benchmark-scripted/runs/<run-id>/trace.jsonl `
  --view verbose --format markdown `
  --output .artifacts-benchmark-scripted-replay.md --no-color
```

Replay validates report/trace schemas, contiguous sequence numbers, run ids, terminal status,
artifact path containment, sizes, and SHA-256 values. The Markdown replay uses the same event
projection as live rendering and the generated trajectory. Presentation does not change Agent
prompts, provider behavior, budgets, benchmark mode, or capability metrics. Scripted and live
attempts remain separate in aggregate reports.

## OpenRouter smoke and model Patch ingestion

The live adapter reads only `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and
`PATCHPILOT_MODEL`. An OpenRouter run uses `OPENAI_BASE_URL=https://openrouter.ai/api/v1`
and the existing CLI selector `--provider openai`; reports distinguish the actual
provider as `openrouter`. Scripted and deterministic commands inject their own model or
use no model and never initialize this live client.

The first OpenRouter smoke used one `null-input-validation` attempt, model
`z-ai/glm-5.2`, and the Case's two-Patch-attempt budget. It observed a real baseline
FAIL, three successful API requests, zero API errors, one `read_file`, and two rejected
`apply_patch` calls. The first Patch omitted `diff --git`; Git reported the second as
`corrupt patch at line 12`. No target or regression execution followed either rejection,
the worktree remained unchanged, and the run ended `AGENT_BUDGET_EXHAUSTED` without a
false `RESOLVED`. This is an interface engineering finding, not a model-resolution-rate
result.

The before/after comparison holds constant the suite fingerprint, Case, base commit,
model, one run, sequential execution, and two-Patch-attempt budget. It changes only the
Patch-ingestion interface, runs from a committed clean tree, and writes a fresh artifact
root. A post-change outcome is reported only after the command actually runs:

```powershell
patchpilot benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-openrouter-smoke-m4a `
  --provider openai `
  --case null-input-validation `
  --runs-per-case 1 `
  --max-patch-attempts 2
```

For model input, PatchPilot first computes the raw SHA-256, then applies only newline
normalization, UTF-8 BOM removal, whole-argument Patch-fence removal, outer blank-line
removal, and exactly one final newline. It may synthesize one `diff --git` header only
when exactly one matching `--- a/<path>` / `+++ b/<path>` pair names the same existing
repository-contained `src/main/java/**/*.java` file. The record retains the normalized
SHA-256 and every operation. No path is inferred from the issue, prior reads, prose,
hunks, expected files, or hidden validation data.

Structural, path, operation, and production-file policies run before Git. Strict
`git apply --check` always runs first. If it alone fails after those policies pass, one
`git apply --check --recount` may recover inaccurate hunk counts. The exact same
normalized bytes are then applied with `--recount`; no context fuzzing, three-way merge,
reject file, unsafe path, or whitespace rewrite is used. If recount fails, the Patch is
rejected. Source code, prefixes, context, filenames, creates/deletes, renames/copies,
binary/mode changes, and multi-file headers are never repaired.

Every rejection has one stable detailed code: `PATCH_EMPTY`, `PATCH_ENCODING_INVALID`,
`PATCH_FENCE_INVALID`, `PATCH_GIT_HEADER_MISSING`, `PATCH_FILE_HEADERS_MISSING`,
`PATCH_PATH_MISMATCH`, `PATCH_PATH_UNSAFE`, `PATCH_OPERATION_UNSUPPORTED`,
`PATCH_POLICY_REJECTED`, `PATCH_HUNK_INVALID`, `PATCH_GIT_CHECK_FAILED`,
`PATCH_GIT_RECOUNT_FAILED`, `PATCH_APPLICATION_FAILED`, `PATCH_POST_APPLY_FAILED`, or
`PATCH_ROLLBACK_FAILED`. Bounded model feedback includes the safe Git/policy diagnostic,
required format, rules, normalization evidence, unchanged-worktree flag, and remaining
Patch budget. Top-level benchmark failure categories remain the Milestone 3 taxonomy.

Responses continuation is stateless: the next request contains prior output items, the
matching function call and `function_call_output`, the structured rejection, and the
remaining Patch budget. It never uses `previous_response_id` for OpenRouter and never
writes hidden reasoning to reports. Patch application is transactional; any post-apply
failure rolls back and verifies a clean worktree. Rollback failure is terminal
infrastructure failure and cannot continue or resolve.

## Correctness oracle and metrics

`RESOLVED` requires observed baseline target failure, an accepted nonempty production
Java Patch, observed target PASS, observed full-regression PASS, unchanged original
repository, persisted evidence, and verified worktree cleanup. Final model text cannot
set or bypass this state.

Each run records suite/fingerprint/Case/run/provider/model/mode; final status and failure
reason; baseline, target, and regression evidence; model turns and request count; total
and per-tool calls; Patch and rejected-Patch attempts; target and regression executions;
input/output/reasoning tokens when supplied; API errors; wall-clock, model, and test
duration; modified files; inserted/deleted lines; Patch size/path; integrity; and
deterministic failure flags.

Aggregates include total Cases/attempts, resolved and unresolved attempts, raw
attempt-level resolution rate, Cases resolved at least once, baseline reproduction
rate, target/regression PASS counts, failures by category, average and median turns,
tools, Patches, and duration, total/average reported token use, average Patch size, tool
usage distribution, and per-Case successes/attempts/empirical rate. The empirical rate
is descriptive and is not labelled `pass@k`; no pass@k estimator is implemented.

No monetary cost is calculated from hardcoded model pricing. Token counts are evidence,
not a price. Any future cost estimate must use an explicit user-provided pricing
configuration and be labelled an estimate.

## Failure taxonomy and interpretation

Every run is assigned exactly one aggregate category:

- `INVALID_CASE` — linked Case/schema evidence is invalid.
- `BASELINE_NOT_REPRODUCED` — the target did not genuinely fail as specified.
- `MODEL_CONFIGURATION` — provider credentials/model configuration were unavailable or invalid.
- `MODEL_API` — a live provider request failed after the bounded policy.
- `MODEL_STOPPED` — the model stopped before deterministic resolution.
- `SEARCH_FAILURE` — bounded trace evidence shows repository search could not execute.
- `PATCH_REJECTED` — a candidate was syntactically or mechanically rejected.
- `TARGET_TEST_FAILED` — accepted candidates did not make the target pass.
- `REGRESSION_FAILED` — the target passed but a full regression did not.
- `POLICY_REJECTED` — a candidate violated allowed-file or Patch policy.
- `BUDGET_EXHAUSTED` — a configured Agent/test/wall-clock budget ended the run.
- `INFRASTRUCTURE` — Git, filesystem, Maven/JVM, cleanup, or artifact infrastructure failed.
- `RESOLVED` — the complete deterministic oracle passed.

The Markdown report separately lists target-pass/regression-fail, policy rejection,
budget exhaustion, model stop without verification, and infrastructure evidence. This
analysis is a deterministic aggregation of reports/traces; no LLM writes it. Inspect
the linked per-run report and bounded logs before deciding whether a failure reflects
model behavior, policy, budget, test infrastructure, or invalid benchmark data.

## Exit codes

The batch policy is intentionally simple and applies consistently to scripted and live
modes:

- `0`: execution completed and at least one attempt was deterministically resolved;
  partial failures remain visible in the aggregate.
- `2`: the suite, filter, manifest, linked Case, or fixed commit is invalid.
- `3`: setup infrastructure failed before a summary, or no requested attempt reached an
  executable test state.
- `4`: attempts executed but none resolved.

`validate-benchmark` returns `0` only when every Case is valid, `2` for an invalid suite,
`3` for pre-report infrastructure failure, and `4` when validation completed with one
or more invalid Cases.

## Reproducibility and secrets

Summaries record the PatchPilot Git commit and dirty flag, benchmark fingerprint, OS,
Python, Java, pinned Maven/Wrapper version, OpenAI SDK version when relevant, provider,
model, UTC timestamp, CLI arguments, effective budgets, and optional seed metadata.
They never record API keys, authorization headers, complete environment variables,
hidden reasoning, or user secrets. Trace keys that resemble credentials are redacted.

Exact live outcomes can still differ with model revisions/behavior, provider service,
network, rate limits, dependency caches, hardware, OS process semantics, and Java/Maven
environment. Compare fingerprints and reproducibility blocks before comparing reports.

## Adding a Case

1. Add a small Java 17/Maven fixture source under `benchmarks/fixture-sources/` with one
   intentionally failing target and at least one unrelated regression test. Avoid
   network, services, timing, generated files, or build tricks.
2. Extend `benchmarks/bootstrap_fixture.py` so it creates a fixed deterministic root
   commit/ref for the Case. Bootstrap twice and confirm the full SHA is stable.
3. Add a schema-v2 public Agent Case under `benchmarks/cases/`. Keep the issue and test
   names behavior-focused; include no solution, expected file, or implementation hint.
4. Create a production-only golden Unified Diff under
   `benchmarks/validation/patches/` and its separate schema-v1 validation Case. Never put
   the Patch in the Agent repository.
5. Add a scripted harness Case and independent scripted candidate under
   `benchmarks/scripted/`; do not reference the hidden golden path from Agent-facing
   data.
6. Add the three paths, tags, and id to the suite manifest. Keep public fields and
   default budgets identical across linked schemas.
7. Run the exact validation command above. Confirm baseline FAIL, target PASS, full
   regression PASS, production-only modification, unchanged repository, and cleaned
   worktree in JSON, CSV, Markdown, and per-Case evidence.
8. Add/adjust schema, fingerprint, reporting, and real Maven integration coverage; then
   run `python -m pytest -q`, `python -m ruff check .`, and `python -m mypy src`.

Do not accept a Case by comparing the submitted Patch with the golden Patch. Executable
tests and repository-integrity checks remain the only correctness oracle.
