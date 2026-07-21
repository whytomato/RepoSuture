# PatchPilot Execution Record

Last updated: 2026-07-21

## 2026-07-21 Milestone 3 — reproducible Java benchmark and evaluation harness

### Living progress

- [x] Re-read `AGENTS.md`, `README.md`, this plan, the deterministic verifier,
  Agent tool runtime, repair orchestration, reporting invariants, and OpenAI provider.
- [x] Create an implementation-only Git worktree from the clean `main` commit; keep the
  user's original checkout free of source edits.
- [x] Add six deterministic Java 17/Maven cases spanning the required bug categories,
  including two navigation cases and a target-pass/regression-fail repair case.
- [x] Add a versioned suite schema, strict public/hidden Case separation, stable
  fingerprinting, and deterministic repository/base-commit validation.
- [x] Add sequential deterministic validation and Agent benchmark commands with
  per-case artifacts, aggregate JSON/CSV/Markdown, reproducibility metadata, and an
  explicit failure taxonomy.
- [x] Add a clearly labelled scripted/offline provider that still executes the real
  worktree, tool, Patch, Maven, Surefire, target, and regression paths.
- [x] Add unit and integration coverage for suite integrity, isolation, aggregation,
  exit policies, secret absence, all six golden validations, and scripted repair.
- [x] Run every required quality gate and CLI workflow, inspect representative artifacts,
  repair observed failures, and record only results actually executed.

### Design decisions

- Milestone 3 is an evaluation layer over Milestones 1 and 2. `verify_case` remains the
  golden-patch correctness path and `repair_case` remains the only Agent execution path.
- Agent-visible schema-v2 Case files and hidden schema-v1 validation Case files remain
  separate. Suite loading requires their public issue, target, timeout, repository,
  and base-commit fields to agree. Only the Agent Case path can enter `repair_case` or a
  provider prompt; validation paths and golden content never enter model messages or
  tool results.
- The six small fixtures share pinned Maven infrastructure but use distinct immutable
  Git commits. Fingerprints cover canonical suite/Case data, referenced scripted and
  golden inputs, every base commit, and each complete fixture tree.
- Batch attempts run sequentially with fresh deterministic run IDs, fresh detached
  worktrees, fresh model instances, and separate directories. A failed attempt is data,
  not a reason to skip later attempts under the default continue policy.
- Scripted/offline and live-model aggregates are mutually exclusive report modes. The
  scripted mode is orchestration evidence only and will never be presented as model
  capability.
- Aggregate success comes only from deterministic `RunReport` evidence. Final model text
  has no role in `RESOLVED`, failure classification, or resolution-rate calculation.
- No monetary cost is inferred. Token counts are retained when providers expose them;
  an estimate would require an explicit future pricing input.

### Observed acceptance evidence

- The final benchmark fingerprint was
  `20709966636b87d77e5a50fd0026557d405c7aa94955824ec80abb5e986a9ff0` in both
  validation and scripted aggregates.
- `validate-benchmark` executed real Maven/JUnit and validated all six Cases: each
  baseline target was observed failing, each hidden production Patch made the target
  pass, each full regression passed, each source repository stayed unchanged, and every
  temporary worktree was removed.
- The final scripted/offline batch resolved 6/6 harness attempts. This is not a live
  model capability result. The regression-trap run recorded its first target PASS plus
  regression FAIL before a second complete Patch passed both tests.
- The representative trap run used 6 model turns, 6 tool calls, 2 Patch attempts,
  3 target-test executions (including baseline), and 2 regression executions. All six
  scripted runs reported zero tokens because `FakeLLM` has no provider token usage.
- The existing deterministic Case and existing FakeLLM repair workflow both completed
  as `RESOLVED` after the Milestone 3 changes.
- Final quality gates: `python -m pytest -q` reported 182 passed with no skips;
  `python -m ruff check .` passed; `python -m mypy src` found no issues in 22 files.
  Java/Maven integration ran with Java 21.0.8 compiling the fixtures at Java release 17,
  Maven 3.9.9, and Maven Wrapper 3.3.4.
- No live benchmark was executed because neither `OPENAI_API_KEY` nor
  `PATCHPILOT_MODEL` was configured. No live result or resolution rate is claimed.
- During implementation, artifact inspection caught one malformed scripted Patch hunk;
  it was corrected and the full batch rerun. Full integration testing also caught a
  Windows CRLF mismatch in the legacy golden Patch after deterministic checkout rules;
  normalizing that Patch restored all Milestone 1 integration tests.

## 2026-07-20 Milestone 2 Part 2 — OpenAI Responses API repair

### Living progress

- [x] Re-read `AGENTS.md`, `README.md`, this execution record, the Milestone 1
  deterministic runner, and the Milestone 2 Part 1 runtime and tests.
- [x] Confirmed the existing `verify-case` workflow remains the immutable foundation
  and must never require model configuration.
- [x] Verified the current official Responses API function-calling, continuation,
  strict-schema, timeout, retry, request-id, and usage semantics.
- [x] Added the separate versioned Agent Case schema and conservative repair budgets.
- [x] Added provider-neutral continuation fields and the OpenAI Responses provider.
- [x] Hardened and exposed exactly six repository tools, including `git_diff`.
- [x] Added `RepairRunner` with automatic target/regression verification after every
  accepted Patch and deterministic-only `RESOLVED` authority.
- [x] Added safe Agent report/trace telemetry and the `patchpilot repair` command.
- [x] Added provider, policy, state-machine, and real Git/Maven/JUnit regression tests.
- [x] Completed the final acceptance commands and on-disk artifact inspection.

### Design decisions

- The official `openai` SDK is isolated in `patchpilot.models`; core Agent models retain
  only JSON-compatible provider continuation state and never expose SDK response types.
- Responses requests use `store=False`, `parallel_tool_calls=False`, bounded
  `max_output_tokens`, strict custom function schemas, and explicit timeout/retry limits.
- Manual continuation preserves every response output item needed by reasoning-capable
  models, but private reasoning is never copied into PatchPilot trace or report output.
- The SDK's internal retries will be disabled. PatchPilot will retry only connection,
  timeout, rate-limit, and retryable server errors within a small bounded policy.
- A separate schema-version-2 Agent Case contains no golden Patch. The existing
  schema-version-1 Case and `verify-case` remain backward compatible.
- The model sees only `list_files`, `search_code`, `read_file`, `apply_patch`,
  `run_target_test`, and `git_diff`; local Pydantic validation and worktree policy remain
  authoritative even though API schemas are strict.
- Agent patches are limited to production Java files. Each accepted Patch triggers the
  harness target test automatically and, on target PASS, the complete regression suite.
- Model-visible completion text is informational. Only baseline failure evidence,
  non-empty policy-compliant diff, target PASS, regression PASS, source-repository
  equality, artifact durability, and cleanup can produce `RESOLVED`.

### Current environment and validation status

- User-provided `patchpilot` Conda environment: Python 3.11.15.
- Official PyPI inspection on 2026-07-20 reported `openai` 2.46.0 as current; validation
  will use a maintainable `openai>=2.46.0,<3` dependency range and record the installed
  SDK version.
- `OPENAI_API_KEY` and `PATCHPILOT_MODEL` are currently absent. Default and FakeLLM
  validation will run without network; a live call will be reported as not executed
  unless both variables are genuinely present at final validation time.
- Required final gates remain `python -m pytest -q`, `python -m ruff check .`,
  `python -m mypy src`, deterministic `verify-case`, and a real Maven/JUnit FakeLLM
  repair through the user-facing orchestration.

### TDD progress and observed results

- Agent Case RED: focused collection failed because `load_agent_case` did not exist;
  GREEN: **21 passed**.
- Responses provider RED: collection failed because `patchpilot.models` did not exist;
  GREEN: **9 passed** using an injected fake SDK client and no network.
- Tool policy RED: ignored `target` and IDE files appeared in `list_files`; GREEN:
  **9 non-integration Agent tests passed**, plus real Git policy rejection and the
  original real Maven/JUnit Agent test both passed.
- RepairRunner first RED exposed a machine-specific Git ownership check in the test
  fixture. The test now copies the fixture, initializes a fresh real repository, and is
  independent of global `safe.directory`; the basic workflow then passed with actual
  baseline FAIL, patched target PASS, and full regression PASS.
- The revision paths passed with real Maven/JUnit: ineffective target Patch followed by
  a corrected Patch, and target-passing/regression-failing Patch followed by a corrected
  Patch.
- Policy/error group initially had **4 passed, 1 failed** because a rejected traversal
  reason was absent from Trace. After adding bounded rejection metadata, the traversal
  path passed; test modification, repeated Patch, model stop, and malformed arguments
  also passed.
- Latest no-network/non-integration suite: **145 passed, 15 deselected in 24.13s**.
- Latest focused `ruff` result: **All checks passed**.
- Latest `mypy src` result: **Success: no issues found in 19 source files**.
- Installed and inspected official SDK version: **openai 2.46.0**.

### Responses API continuation and error policy

- Each call manually sends the accumulated input because storage is disabled. The next
  input is the prior input plus every JSON-compatible response output item and one
  `function_call_output` with the exact pending `call_id`.
- Requests ask for `reasoning.encrypted_content` so stateless reasoning-capable model
  continuation remains possible. Neither encrypted reasoning nor summaries are emitted
  by RepairRunner telemetry.
- Unexpected multiple function calls, missing call IDs, and non-serializable output are
  protocol errors. Malformed argument JSON becomes a local `INVALID_ARGUMENTS` tool
  result so the bounded loop can continue.
- The SDK is constructed with internal retries disabled. PatchPilot retries only
  connection/timeout/rate-limit and retryable HTTP failures; authentication is a model
  configuration failure and invalid requests are non-retryable API failures.

### Final validation and artifact inspection

- `python -m pytest -q` with the host's default TEMP first exited **1** before most test
  bodies because the pre-existing `pytest-of-whytomato` directory rejects the current
  Windows SID. This is the already-known external ACL condition, not a product failure.
- With `TEMP` and `TMP` pointed to a unique newly created directory, the exact command
  `python -m pytest -q` completed **162 passed, 0 skipped, 1 warning in 205.09s**.
  The warning is the independent pre-existing workspace `.pytest_cache` ACL.
- `python -m pytest --collect-only -q -m integration -p no:cacheprovider` collected
  **17/162 integration tests**. They include 11 RepairRunner scenarios and six existing
  Milestone 1/Part 1 real Git/Maven paths.
- `python -m ruff check .` completed **All checks passed**.
- `python -m mypy src` completed **Success: no issues found in 19 source files**.
- `python benchmarks/bootstrap_fixture.py` verified the fixture at fixed commit
  `5f31109dd8742b5515baae16c9f7eefb0ed3deba`.
- `patchpilot verify-case benchmarks/cases/null-email.yaml --artifacts-dir
  .artifacts-m2-verify` exited **0** with baseline **FAIL**, patched target **PASS**,
  regression **PASS**, and final status **RESOLVED**. Report:
  `.artifacts-m2-verify/null-email-20260720T163415566061Z-e76145598b62/report.json`.
- `python benchmarks/run_fake_repair.py benchmarks/cases/null-email-agent.yaml
  --patch-file benchmarks/fixtures/null-email-golden.patch --artifacts-dir
  .artifacts-m2-fake` exited **0** after three FakeLLM model turns and three real tools.
  It produced real baseline **FAIL**, target **PASS**, regression **PASS**, and
  **RESOLVED**. Report:
  `.artifacts-m2-fake/null-email-agent-20260720T163447052969Z-ee1f3203275b/report.json`.
- Both successful runs were reopened from disk. All declared artifact sizes and SHA-256
  values matched, JSONL sequences were contiguous, schema-v2 run IDs matched every
  Trace event, final Patch files were 749 bytes, worktrees were absent, and original
  repository before/after fingerprints were equal.
- Neither `OPENAI_API_KEY` nor `PATCHPILOT_MODEL` was present, so no live OpenAI request
  was executed. The no-configuration `patchpilot repair` path was executed separately;
  it returned exit **4**, status **MODEL_CONFIGURATION_ERROR**, zero test executions,
  and no worktree. Report:
  `.artifacts-m2-no-config/null-email-agent-20260720T164148763246Z-ab359c231137/report.json`.
- Final fixture audit found a clean status, the fixed HEAD above, and only its original
  main worktree registered.

## 2026-07-20 Milestone 2 Part 1 — Agent Runtime Foundation

### Current progress

- [x] Re-read `AGENTS.md`, `README.md`, and this execution record after completing the
  Milestone 1 audit.
- [x] Added provider-independent message, `LLMClient`, `ToolCall`, `ToolResult`, and tool
  schema contracts without any model SDK or network dependency.
- [x] Added structured Agent state, iteration/tool-call limits, structured termination,
  and a runtime status vocabulary that does not equate loop completion with repair
  success.
- [x] Added five bounded tools: `list_files`, `search_code`, `read_file`, `apply_patch`,
  and `run_target_test`.
- [x] Reused `safe_worktree_path`, `PatchApplier`, immutable Patch bytes,
  file classification, `MavenRunner`, Surefire interpretation, and `ProcessRunner`.
- [x] Added a configurable deterministic `FakeLLM` script for
  search → read → apply → target-test → finish.
- [x] Proved the script against a real linked Git worktree and real Java 17,
  Maven Wrapper, Surefire XML, and JUnit; only the model decision sequence is fake.
- [x] Kept `patchpilot verify-case` unchanged and exposed Agent Runtime only through
  internal Python APIs and tests.
- [x] Complete the final all-suite `pytest`, `ruff`, and `mypy` acceptance after the
  documentation update.

### Architecture and key decisions

- `agent/base.py` owns provider-neutral messages, responses, calls, results, tool specs,
  errors, and the synchronous `LLMClient` protocol. It imports no provider SDK.
- `agent/state.py` owns the bounded mutable execution state. `FINISHED` means the model
  requested termination, not that the repair is resolved.
- `agent/tools.py` owns registration and dispatch. Pydantic rejects unknown fields and
  wrong argument types before handlers run; unknown tools and handler exceptions become
  bounded structured errors.
- Repository read tools reject `.git`, absolute, drive, UNC, backslash, traversal, and
  resolved symlink/reparse escapes. File counts, scanned paths, bytes, lines, matches,
  test output, and error messages all have explicit limits.
- `apply_patch` freezes the FakeLLM string into the same immutable `PatchDocument` used
  by Milestone 1, then delegates validation/application/classification/final diff to
  `PatchApplier`. It does not implement text replacement.
- `run_target_test` delegates to `MavenRunner`; its verifier flag is derived from a real
  observed Surefire target PASS, never from model text.
- `PatchPilotToolEnvironment` accepts only a linked-worktree `.git` marker, preventing
  these mutating tools from being pointed at an ordinary source checkout through the
  supported API.
- `FakeLLM` exists to make the control flow fully deterministic, locally reproducible,
  and independent of credentials, provider behavior, quotas, or network availability.
- Final deterministic verification remains outside the Agent because target-test PASS
  alone is insufficient. Milestone 1 must still prove baseline failure, non-empty Patch,
  patched target PASS, full regression PASS, original repository equality, cleanup, and
  artifact/report integrity before it can emit `RESOLVED`.
- `AgentFinalResult.repair_verified` is currently the literal value `false`; therefore a
  finish response saying “succeeded” cannot become verified repair state.

### TDD and validation executed so far

- Initial focused Agent test collection — expected RED: `ModuleNotFoundError` for the
  not-yet-created `patchpilot.agent` package.
- First focused retry — **7 setup errors** before test execution because pytest selected
  a stale cross-SID temp root; this was an external ACL failure, not counted as RED/GREEN.
- Focused non-integration Agent slice with a unique short `--basetemp` — **7 passed,
  1 deselected**.
- Real Agent workflow only — **1 passed in 7.59s**, with actual baseline FAIL and patched
  target PASS through Java/Maven/JUnit.
- Agent file after the first implementation pass — **8 passed in 7.49s**; focused ruff
  and strict mypy both passed.
- Full non-integration repository suite after final Agent state tests — **123 passed,
  5 deselected in 15.58s**.
- Latest pre-documentation `python -m ruff check .` — **All checks passed**.
- Latest pre-documentation `python -m mypy src` — **Success: no issues found in 15
  source files**.
- Final exact `python -m pytest -q` in the user-provided Conda environment — **128
  passed in 61.77s**, exit 0, no skips. The sole warning was the already documented
  workspace `.pytest_cache` cross-SID ACL warning.
- Final exact `python -m ruff check .` — **All checks passed**, exit 0.
- Final exact `python -m mypy src` — **Success: no issues found in 15 source files**,
  exit 0.
- `python -m pytest --collect-only -q -m integration -p no:cacheprovider` — **5/128
  integration tests collected**, naming the real Agent workflow plus four Milestone 1
  Git/Java/Maven paths.

### Post-change CLI compatibility and artifact inspection

- Successful CLI rerun: `patchpilot verify-case benchmarks/cases/null-email.yaml
  --artifacts-dir .artifacts-audit` — actual exit **0**, final status **RESOLVED**.
- Latest success report:
  `.artifacts-audit/null-email-20260720T124728511510Z-226dc99ba57c/report.json`.
  Baseline target was observed **FAIL** (1/1), patched target was observed **PASS**
  (1/0), and regression was observed **PASS** (3/0). The final Patch was 749 bytes.
- Intentional failure rerun: `patchpilot verify-case
  benchmarks/cases/null-email-missing-test.yaml --artifacts-dir
  .artifacts-audit-failure` — actual CLI exit **3**, report status
  **INFRASTRUCTURE_ERROR**.
- Latest failure report:
  `.artifacts-audit-failure/null-email-missing-test-20260720T124754088563Z-130e02f3f019/report.json`.
  Its reason is `matching target JUnit result was not found in Surefire reports`;
  patched/regression remain `NOT_RUN` and `final.patch` is empty.
- Both new runs were reopened from disk. Every declared artifact existed; every recorded
  non-report size and SHA-256 matched; all JSONL lines parsed; sequences were contiguous;
  timestamps were UTC; durations were nonnegative; trace final statuses matched reports;
  worktrees were absent; and before/after original-repository snapshots were equal.
- Fixture post-check: HEAD remained
  `5f31109dd8742b5515baae16c9f7eefb0ed3deba` and porcelain status had zero lines.

### Problems encountered

- The host's pre-existing `pytest-of-whytomato` directory is not readable by the current
  Windows SID. Focused runs use a fresh, unique, short temp root; the exact final command
  is still executed separately as required.
- A target-test PASS is deliberately not promoted to overall repair success. This is a
  safety boundary, not a missing inference: the Agent workflow does not run the complete
  Milestone 1 verifier yet.

### Remaining limitations

- Synchronous, one-tool-call-per-response runtime only.
- Configurable deterministic FakeLLM only; no real LLM provider or network call.
- No Agent CLI, persistent Agent report/trace, streaming, retry policy, or parallelism.
- No automatic patch generation or test generation.
- No Agent-to-Milestone-1 final verifier handoff yet; Agent `FINISHED` is not
  `FinalStatus.RESOLVED`.

## 2026-07-20 strict audit and hardening (current run)

### Current audit progress

- [x] Re-read `AGENTS.md`, `README.md`, this execution record, every source module,
  every test, the Case, and the Java fixture.
- [x] Re-established the unmodified baseline: `47 passed` with one pre-existing
  `.pytest_cache` ACL warning.
- [x] Reproduced Patch TOCTOU, `.git` path acceptance, rename/copy acceptance,
  ignored-file/empty-diff risk, full-class Surefire mismatch, HEAD/index fingerprint
  gaps, and cleanup failure masking with failing regression tests.
- [x] Hardened bounded subprocess stdin/stdout/stderr, timeout process-tree cleanup,
  cross-platform path semantics, worktree snapshots/lifecycle, immutable Patch use,
  Git-authoritative affected files, Maven evidence, state invariants, report hashes,
  atomic report writes, and trace redaction.
- [x] Added deterministic fixture bootstrap for clean checkouts and verified that it
  recreates the exact Case commit.
- [x] Ran real Maven/JUnit success, unrelated-regression-failure, and Patch-mutation
  integration paths; none uses fake Maven output.
- [x] Completed the exact-form `pytest`, `ruff`, and `mypy` quality gates, successful CLI,
  intentional failing CLI, and direct on-disk artifact inspection.

### Confirmed defects and decisions

- **Critical:** `git apply --check` and `git apply` reopened a Case-controlled Patch
  path, so the file could be replaced between them. The runner now freezes bytes before
  baseline and sends those same bounded bytes to both Git invocations over stdin.
- **Critical:** Patch containment allowed `.git/...`; rename/copy metadata and gitlink or
  symlink modes were not explicitly rejected. These are now rejected before Git runs.
- **High:** affected files came from untrusted diff headers and an ignored new file could
  lead to an empty final diff. Actual paths now come from NUL-delimited Git diff output;
  ignored targets and empty diffs are rejected.
- **High:** original-repository equality did not include HEAD or logical index flags.
  The snapshot now covers HEAD, staged entries, index flags, porcelain status, and a
  non-following worktree content/mode fingerprint.
- **High:** cleanup could hide `git worktree remove` failure by deleting the directory and
  globally pruning metadata. Cleanup failure is now reported, never returns `RESOLVED`,
  and never runs global `git worktree prune`.
- **High:** Surefire target matching accepted the same simple class name from another
  package. Fully qualified selectors now require an exact XML classname.
- **High:** the report model allowed a constructed `RESOLVED` with an empty Patch,
  affected-file list, or artifact map. State-specific phase evidence, non-empty final
  diff, cleanup policy, original snapshots, and artifact metadata are now mandatory.
- **Medium:** report atomic-write failure left a temporary JSON file; cleanup is now
  guaranteed without replacing an existing report with partial content.
- **Medium:** a nested fixture `.git` cannot be relied upon in a clean outer checkout.
  `benchmarks/bootstrap_fixture.py` deterministically recreates and validates the fixed
  commit without changing the product CLI.

### Audit validation executed so far

- `python -m pytest -q` before changes — **47 passed**, one cache ACL warning.
- Patch security RED — **4 failed, 11 passed**; after fixes — **23 passed**.
- Process execution — **4 passed**, then bounded-stdin coverage added.
- Path containment — **11 passed**.
- Worktree lifecycle — initial RED **2 failed, 7 passed**; after fixes and index-flag
  coverage — **10 passed**.
- Maven evidence — initial RED **1 failed, 10 passed**; after exact matching —
  **11 passed**.
- Reporting/state — initial RED **7 failed, 7 passed**; current focused run —
  **26 passed**.
- Non-integration suite before the latest evidence additions — **102 passed,
  4 deselected**.
- Real Maven integration after core runner changes — initially **3 passed in 29.83s**;
  the final full suite includes a fourth real `--keep-worktree` integration path.
- Deterministic clean-path fixture bootstrap — **2 passed**.
- Intermediate `ruff check .` — issues found and corrected; next run passed before later
  edits.
- `python -m pytest -q -p no:cacheprovider --basetemp <short-temp>` — **118 passed in
  54.50s**, with all four real Maven/JUnit integration paths and no skips.
- `python -m ruff check .` — **All checks passed** after the latest source edits.
- `python -m mypy src` — **Success: no issues found in 9 source files** after the latest
  source edits.
- Final exact `python -m pytest -q` — **118 passed in 54.44s**, exit 0; one known
  `.pytest_cache` cross-SID ACL warning, no skipped tests.
- Final exact audit rerun after the last process-tree test cleanup — **118 passed in
  54.95s**, exit 0; the same single cache ACL warning and no skips.
- Final exact `python -m ruff check .` — **All checks passed**, exit 0.
- Final exact `python -m mypy src` — **Success: no issues found in 9 source files**,
  exit 0.

### Audit CLI executions and artifact inspection

- Success command: `patchpilot verify-case benchmarks/cases/null-email.yaml
  --artifacts-dir .artifacts-audit` — actual exit **0**, final status **RESOLVED**.
- Success outcomes: baseline target **FAIL** (1 executed/1 failure), patched target
  **PASS** (1 executed/0 failures), regression **PASS** (3 executed/0 failures).
- Success report: `.artifacts-audit/null-email-20260720T122009279724Z-fa477357c704/report.json`.
  All six required files were reopened; all five non-report metadata sizes and SHA-256
  values matched disk; trace had 11 valid, ordered UTC events; worktree did not exist;
  original HEAD/status and report snapshots were unchanged.
- Intentional failure command: `patchpilot verify-case
  benchmarks/cases/null-email-missing-test.yaml --artifacts-dir
  .artifacts-audit-failure` — actual exit **3**, final status **INFRASTRUCTURE_ERROR**.
- Failure reason: `matching target JUnit result was not found in Surefire reports`;
  target was unobserved, Patch/patched/regression phases were not run, and final.patch
  remained empty.
- Failure report:
  `.artifacts-audit-failure/null-email-missing-test-20260720T122131505672Z-eeac6d7d8bae/report.json`.
  All failure artifacts and recorded hashes matched disk; worktree was removed and the
  original fixture HEAD/status/snapshots remained unchanged.

The commands below under “Initial implementation history” are retained as historical
evidence. General reproduction commands remain in README and the final audit commands
above will be updated with their actual results; no prior result is treated as current.

## Current progress

- [x] Inspected the initial workspace and host toolchain.
- [x] Added persistent engineering rules in `AGENTS.md`.
- [x] Used the user-provided `patchpilot` Python 3.11 Conda environment.
- [x] Implemented strict, versioned Bug Case validation.
- [x] Implemented bounded subprocess execution and process-tree timeout handling.
- [x] Implemented Git worktree isolation, path containment, cleanup, and source-repository fingerprints.
- [x] Implemented Unified Diff inspection, classification, `git apply --check`, application, and final diff capture.
- [x] Implemented Maven Wrapper/system Maven selection and Surefire XML result evidence.
- [x] Implemented guarded reports, bounded JSONL traces, orchestration, and Typer CLI.
- [x] Added a real Java 17/JUnit 5 fixture with two passing regression tests and one failing target test.
- [x] Added unit and real Git/Maven/JUnit integration tests.
- [x] Completed README installation, CLI, schema, artifact, safety, test, limitation, and next-stage documentation.
- [x] Ran the full required quality gate and the documented CLI example.

## Key design decisions

- Public workflow: `patchpilot verify-case CASE_FILE --artifacts-dir PATH [--keep-worktree]`.
- Case data contains only a Java class/method selector, never executable Maven or Shell text.
- Commands use argument arrays, explicit cwd/timeouts, new process groups, bounded pipe readers, and structured results.
- A non-zero Maven exit is a reproduced failure only when matching Surefire XML proves the selected JUnit test failed.
- The original repository is treated as immutable. Its Git status and all non-`.git` working-tree path/content bytes are fingerprinted before and after execution.
- Worktrees use a short system-temp root to avoid Windows Git path-length failures; run artifacts remain under the requested root.
- Patch paths and file markers must be contained and mutually consistent before Git checks applicability.
- Patch changes are classified as production, test, build, CI, documentation, or other, with explicit sensitive-change flags.
- Each run creates a unique artifact directory containing all required logs, report, trace, and `git diff --binary` output.
- The Pydantic report model itself rejects `RESOLVED` unless baseline failure was observed, the Patch was applied, target and regression tests passed, and the original repository remained unchanged.
- The Java fixture uses Apache Maven Wrapper 3.3.4 `only-script`, Maven 3.9.9, and a pinned Maven distribution SHA-256.
- Fixture base commit: `5f31109dd8742b5515baae16c9f7eefb0ed3deba`.

## Problems encountered and resolutions

- The initial shell used Python 3.9.13 without project tools. The existing `patchpilot`
  Conda environment provides Python 3.11.15; all implementation validation used it.
- No system `mvn` was installed. The fixture now includes the official Wrapper scripts and a fixed Maven distribution.
- A first Windows integration run placed the worktree below a long pytest artifact path and Git failed with `'$GIT_DIR' too big`. Worktrees now use a short system-temp root.
- Managed sandbox and desktop-user SIDs differ. The fixture Git repository was initialized under explicit approval, and PatchPilot uses an exact per-command `safe.directory` value instead of changing global Git configuration.
- The sandbox identity could not write the desktop user's `.m2/wrapper/dists`. The real Maven validations were rerun with approval under the desktop user and succeeded.
- The first elevated pytest retry collided with temp directories owned by the sandbox SID. Final elevated test runs used a fresh, short, exclusive TEMP directory.
- Native `conda activate patchpilot` hit a Conda 24.9.1 `UnicodeEncodeError` because the user's existing PATH contains a character not representable in GBK. Final commands explicitly put the same Conda environment paths first; `python` resolved to Python 3.11.15 and `patchpilot` to that environment's entry point.
- Final pytest passed but reported one non-test warning because the elevated identity could not update `.pytest_cache` previously created by the sandbox identity.
- Initial file classification removed leading dots from `.mvn`/`.github`; a failing test exposed this and normalization was corrected.
- Initial Typer configuration collapsed the sole command into the root command. Adding a root callback preserved the required `patchpilot verify-case` syntax.

## Initial implementation history: validation commands executed

Environment and dependency checks:

- `python --version`, `python -m pytest --version`, `python -m ruff --version`, `python -m mypy --version` under the initial shell — Python 3.9.13; the three tools were absent.
- `java -version` — Java 17.0.6 available.
- `mvn -version` — system Maven absent.
- `git --version` — Git 2.47.1.windows.2 available.
- `python --version` in the `patchpilot` Conda environment — Python 3.11.15.
- `python -m pip install --disable-pip-version-check -e ".[dev]"` in the `patchpilot` environment — succeeded.

TDD and focused validation (expected RED failures were followed by the listed GREEN results):

- `python -m pytest tests\test_case_spec.py -q` — initially missing module; then 8 passed; final strict schema run 11 passed.
- `python -m pytest tests\test_process.py -q` — initially missing module; then 3 passed.
- `python -m pytest tests\test_workspace_paths.py -q` — initially missing module; then 4 passed/1 skipped; junction fallback later made the final result 5 passed.
- `python -m pytest tests\test_workspace.py -q` — initially missing class; then 2 passed; final lifecycle coverage 4 passed.
- `python -m pytest tests\test_patching.py -q` — initially missing module; then exposed two classification failures; after correction 10 passed (an additional marker-consistency test was added afterward).
- `python -m pytest tests\test_reporting.py -q` — initially missing module, then exposed a missing import; after correction 7 passed.
- `python -m pytest tests\test_maven.py tests\test_reporting.py -q` — 11 passed.
- `python -m pytest tests\test_cli.py -q` — initially missing module, then exposed Typer command collapsing; after correction 1 passed.
- `python -m pytest -q -m 'not integration'` — first 39 passed/1 skipped/1 deselected; final focused run 46 passed/1 deselected.

Real integration validation:

- `python -m pytest tests\test_integration.py -q -s` — first exposed Windows worktree path length; second exposed sandbox Maven-cache permissions.
- Elevated retry with the default pytest temp root — stopped during setup by cross-SID temp-directory ACLs; Maven was not run in that retry.
- `python -m pytest tests\test_integration.py -q -s -p no:cacheprovider --basetemp <exclusive-temp>` — **1 passed in 18.20s**, with real Git, Java 17, Maven Wrapper, and JUnit.

Static checks and final acceptance:

- Intermediate `python -m ruff check .` — first reported 4 issues, second reported 3 issues; each was fixed.
- Intermediate `python -m mypy src` — first reported 7 issues; each was fixed.
- `python -m pytest -q` — **47 passed in 12.91s**, including the real integration test; one `.pytest_cache` ACL warning only.
- `python -m ruff check .` — **All checks passed**.
- `python -m mypy src` — **Success: no issues found in 9 source files**.

Documented CLI example:

- Native `conda activate patchpilot` — failed before project execution due the external PATH/GBK Conda error described above.
- With the `patchpilot` Conda environment paths explicitly active, `patchpilot verify-case benchmarks/cases/null-email.yaml --artifacts-dir .artifacts` — exit code 0 and **RESOLVED**.
- CLI outcomes: baseline `FAIL`, patched target `PASS`, regression `PASS`.
- Persistent run artifacts:
  `.artifacts/null-email-20260720T104358155084Z-092bf5f403da`.
- Post-run evidence: all six required files exist, original repository unchanged is `true`, Patch applied is `true`, worktree no longer exists, fixture Git status is clean at the fixed commit.
- Final read-only delivery audit — **PASS**; Case commit equals fixture HEAD, only the fixture's main worktree is registered, and all required artifact paths were re-opened successfully.

## TDD behavior slices

- Case schema and structured target selector
- Process timeout, truncation, and missing executable
- Lexical, absolute, symlink, and junction path escape
- Normal, exceptional, dirty-source, and kept worktree lifecycle
- Patch format, marker consistency, path escape, classification, real Git check/application/diff
- Report serialization, trace sequencing/limits, and illegal `RESOLVED` states
- Maven command structure and Surefire evidence interpretation
- CLI invalid-case artifacts and exit behavior
- Full real Java/Maven/JUnit resolution path

## Remaining limitations

- Local non-bare Git repositories and full 40-character commit hashes only.
- Standard single-module Maven/Surefire layout only.
- Existing deterministic JUnit 5 target tests only; no test generation.
- UTF-8 Git-style textual Unified Diff only; quoted special Git paths are rejected.
- Case input is limited to 1 MiB; Patch/final retained output is limited to 10 MiB.
- First Maven Wrapper/dependency use can require network access.
- Kept debug worktrees require manual cleanup.
- No autonomous patch generation or LLM/tool-calling Agent exists in Milestone 1.
- This host's Conda activation encoding and cross-SID cache warning are external environment issues, not unresolved test failures.
