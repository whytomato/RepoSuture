# RepoSuture Execution Record

Last updated: 2026-07-22

## 2026-07-22 RepoSuture Release 0.3 — rename, repeated evaluation, and real-world bugs

### Living progress

- [x] Confirm the primary checkout is clean `main` at
  `e2a8d4b89428344223d41a64cbe58f967e1b24a3`, synchronized with the fetched
  `whytomato/PatchPilot` `origin/main`, with no Git operation in progress.
- [x] Check the ignored local live configuration without printing values. The configured
  OpenRouter endpoint and primary model match the requested values; the comparison model
  variable is absent, so the documented `openai/gpt-5-mini` default applies.
- [x] Complete the exact-name collision preflight against GitHub repositories, PyPI, arXiv,
  and an obvious software-Agent search. No material exact collision was found; the dated
  queries and limitations are recorded in `docs/NAME_CHECK.md`.
- [x] Rename the distribution, source package, primary CLI, public identity, reports, CI,
  fixtures, and documentation to RepoSuture while retaining one deprecated `patchpilot`
  CLI forwarder and explicit legacy report/replay aliases.
- [x] Add a provider-neutral benchmark-matrix layer over the existing benchmark runner,
  with deterministic interleaving, dry-run, strict completed-run resume, Wilson intervals,
  per-model reports, and no second Agent loop.
- [x] Research and bootstrap exactly three immutable upstream Java/Maven bugs from at least
  two repositories, keeping clones/build output ignored and validation-only fix provenance
  outside all Agent-visible inputs.
- [x] Run the complete offline quality gates and real Maven/JUnit paths: 289 pytest tests
  passed (one explicit Windows symlink-privilege skip and two network-marked tests
  deselected), Ruff and mypy passed, MVP validation was 6/6, the scripted harness was 6/6,
  the complete two-identity offline matrix was 12/12, and the locked real-world suite
  completed deterministic validation 3/3 with Java 17, Maven 3.9.9, and JUnit.
- [ ] Commit the clean non-live implementation, rename the GitHub repository through the
  authenticated GitHub CLI, update origin/About/topics, push `main`, and require passing CI.
- [ ] From the same clean pushed commit, preflight the two exact OpenRouter models and run
  exactly 36 fresh MVP attempts plus exactly six fresh real-world attempts, without
  replacement attempts or budget tuning.
- [ ] Publish only reviewed sanitized R3/R1 summaries, rerun quality gates, commit and push
  the result documents, and verify clean matching local/remote `main` SHAs.

### Release invariants

- The existing `RepairRunner`, six tools, Patch transaction, Git worktree, Maven/JUnit
  verification, rollback, budgets, trace, and correctness oracle remain authoritative.
- The matrix changes only the model identifier; Case text, commit, fingerprint, prompts,
  schemas, budgets, endpoint, sequential policy, and verifier stay equal across models.
- Complete failed live runs are empirical observations and are never silently replaced.
  Scripted/offline records are never mixed with live capability aggregates.
- Third-party repositories exist only in an ignored cache. Public Cases contain bounded
  issue provenance but no fix commit, fix PR, expected file, production diff, golden Patch,
  hidden validation path, or solution note.
- The public remote is renamed only after name checks, deterministic validation, clean
  implementation commits, and a clean working tree. Live evaluation starts only after the
  renamed remote, local `main`, and CI agree on the same clean commit.

### Implementation evidence in progress

- Source moved from `src/patchpilot` to `src/reposuture`; distribution/primary CLI are
  `reposuture` 0.3.0. The deprecated `patchpilot` entry point delegates to the same Typer
  app, writes one stderr warning, and preserves exit status. New benchmark metadata uses
  neutral `project_*` fields while loading the two historical `patchpilot_*` aliases.
- The matrix plan produces 36 unique interleaved MVP attempts for two models and three
  runs. Two scripted identities completed independent real Git/Maven/JUnit repairs; strict
  live-mode resume reused completed observations without model calls and rejected a
  tampered Patch artifact.
- The exact release dry-run printed `6 Cases x 3 runs x 2 models = 36 live attempts`, the
  entire deterministic schedule, and created no live artifact directory.
- Real-world provenance is locked to Apache Commons Lang PR #1699 and Apache Commons
  Collections PRs #704/#714. The ignored bootstrap produced three parentless deterministic
  commits from buggy code plus upstream test-only overlays. The hidden production Patches
  match upstream diffs byte-for-byte.
- Initial manual validation exposed two harness/environment facts rather than Case results:
  the upstream commits lack Maven Wrapper launchers, and the Windows host compiles Commons
  Collections much more slowly than the micro fixtures. The bootstrap now attaches the
  existing SHA-pinned Maven 3.9.9 launcher without changing upstream `pom.xml` or production
  code, force-tracks its properties despite upstream ignore rules, and records bounded
  1200/2400-second target/regression limits. The completed validation reproduced all three
  baseline failures, applied only the locked hidden upstream production diffs, and then
  passed all three target tests and relevant regression suites. Its fingerprint is
  `345839d264b3b5c144fa8f9bbc75b419d917a4c0266d80c119c3dfb34ec19e82`.

## 2026-07-22 Milestone 5 — release hardening and first clean live evaluation

### Living progress

- [x] Confirm the primary checkout is the clean `main` branch at
  `7ee8912ca58225f734484c5139103cb763b77e99`, synchronized with the intended
  `whytomato/PatchPilot` remote, with no Git operation in progress.
- [x] Audit every deterministic and Agent artifact entry point and reproduce the
  configured-subdirectory Git-root containment gap before changing code.
- [x] Resolve Case repositories through Git's canonical top level before any artifact
  creation; share the same resolved/lexical containment rule across verify, repair,
  validation, benchmark, and worktree integrity code.
- [x] Serialize per-run artifact references relative to `report.json`, retain size/SHA-256
  authority, and safely remap coherent legacy all-absolute reports after relocation.
- [x] Add regression coverage for repository subdirectories, pre-write rejection, path
  normalization/case, symlink or junction escape, portable replay, legacy compatibility,
  relocation, traversal, and tampering.
- [x] Add Ubuntu/Windows Python 3.11 + Temurin Java 17 CI, an MIT license, a public-safe
  security reporting policy, and a stable CI badge.
- [x] Run all quality gates and fresh deterministic/FakeLLM/scripted real Maven/JUnit
  validations, including moved and tampered regression-trap replay.
- [x] Review and selectively commit release hardening as `0908e65` and repository policy/CI
  as `d65dfa2`; push only `main` and verify matching local/remote
  `d65dfa26dadaaf791ca93ef50a902bf39a56f084` SHAs. The local `gh` CLI is unavailable, so
  workflow execution could not be watched from this machine.
- [x] Load only the documented live variables from the ignored local `.env` without
  printing values, then execute the gated null-input, regression-trap, and six-Case live
  evaluations exactly as specified when configuration is valid.
- [x] Publish only sanitized genuine live evidence, rerun quality gates, commit it
  separately, and push verified clean `main`.

### Design decisions

- Artifact containment considers both the normalized lexical path and the fully resolved
  path, so neither `..`, case variants, a link into the repository, nor a link outward from
  the repository can bypass the canonical Git-root boundary.
- A valid Case may configure a directory below the Git top level. Git worktrees,
  repository snapshots, fixture separation, and artifact boundaries use the canonical
  top level returned by `git rev-parse --show-toplevel`.
- New `report.json` files use run-directory-relative artifact references. Replay never
  trusts an external absolute path; legacy remapping requires one coherent old run root,
  matching artifact/metadata references, local containment, size, and SHA-256 identity.
- CI contains no provider credentials and runs real Git/Maven/JUnit through the existing
  test suite. Scripted results continue to prove harness execution only.
- The provider boundary preserves the one-action Agent contract even when an
  OpenAI-compatible endpoint violates `parallel_tool_calls=false`: retain the first call,
  exclude output from the second call onward, record the bounded discarded-call count, and
  require a fresh model decision after the first real observation.

### Starting evidence

- Milestone 4B was committed and pushed as
  `7ee8912ca58225f734484c5139103cb763b77e99` after **245 passing tests**, Ruff, mypy,
  deterministic 6/6 validation, and scripted 6/6 repair evidence.
- At the start of Milestone 5, no clean post-hardening live benchmark or live resolution
  rate had been completed. The earlier malformed-Patch smoke remains an engineering
  finding rather than capability evidence.

### Non-live validation evidence

- Final pre-commit `python -m pytest -q`: **262 passed in 365.51s**, with no skips. Ruff reported
  **All checks passed** and mypy reported **Success: no issues found in 23 source files**.
- Fresh deterministic `verify-case` and FakeLLM repair both executed real Maven/JUnit and
  ended `RESOLVED` with baseline FAIL, target PASS, and regression PASS.
- Fresh `.artifacts-m5-validation` validated **6/6** Cases. Fresh
  `.artifacts-m5-scripted` resolved **6/6 scripted/offline** attempts; the latter is
  harness evidence, not live-model capability evidence.
- The scripted regression trap recorded target PASS, regression FAIL, rollback and
  explicit REPLAN, then target PASS and regression PASS. Original and relocated replay
  both succeeded; generated and replayed Markdown shared SHA-256
  `695b641847ca5599ed8434d58ca8cd6e6a39d140ebb2bdde8eaab6be7adfef2e`.
- A tampered relocated trajectory was rejected with exit code 2 for a checksum mismatch.
  Across six scripted reports, 42 artifact references were relative and all 36 recorded
  artifact size/hash entries matched. Test skips, cleanup failures, unsafe Agent-visible
  secret/hidden-path matches, and remaining temporary execution worktrees were all zero.
- Post-commit quality gates on clean `main` reported **262 passed in 376.42s**, Ruff
  **All checks passed**, and mypy **Success: no issues found in 23 source files** before
  release commits were pushed.

### Live evaluation and framework-fix cycle 1

- The ignored local configuration supplied the documented endpoint and model without
  printing or persisting credentials. The first clean `null-input-validation` attempt ran
  from pushed commit `d65dfa26dadaaf791ca93ef50a902bf39a56f084` with `dirty=false`.
- Baseline Maven/JUnit genuinely failed. The Agent completed three model requests and two
  `list_files` calls, with zero API errors, before OpenRouter returned more than one function
  call despite `parallel_tool_calls=false`. The adapter safely stopped with
  `MODEL_API_ERROR`; no Patch was attempted, candidate test or regression suite ran, or
  false `RESOLVED` occurred.
- A focused regression test reproduced the exact adapter failure. The generic compatibility
  fix retains and executes only the first call, removes later unexecuted calls from stateless
  continuation, preserves the matching first-call output, and emits a safe sequentialization
  trace count. The fix does not add parallel tools or relax policy, budgets, worktrees, Git,
  Maven, JUnit, or correctness authority.
- Fix-cycle validation reported **263 passed in 367.86s**, Ruff **All checks passed**, and
  mypy **Success: no issues found in 23 source files**. Fresh deterministic Case and
  FakeLLM repair runs resolved with real Maven/JUnit; benchmark validation remained **6/6
  VALID** and the scripted/offline benchmark remained **6/6 RESOLVED**. The fixture was
  clean, only its primary worktree remained, and 14 Agent-visible trace/trajectory files
  contained zero credential, Authorization, golden, validation-path, or hidden-solution
  matches. Replay of the original failed live run succeeded without provider access and
  accurately ended `MODEL_API_ERROR`.
- The generic provider compatibility fix was committed and pushed as
  `944fc6aab83c64848c4eae11f291db80ebc69041`. Post-commit validation again reported
  **263 passed**, Ruff passed, and mypy passed before the clean live rerun.

### Clean live evidence

- The two-Patch `null-input-validation` smoke completed without provider, protocol, artifact,
  worktree, or infrastructure failure. Both accepted candidates ran real target tests and
  failed, then rolled back; the final status was `AGENT_BUDGET_EXHAUSTED`. This is an honest
  model failure, not a framework failure. It used 5 requests, 5 tools, 2 Patches, and 13,038
  reported tokens; regression correctly did not run.
- The gated `quota-regression-trap` smoke resolved in 5 turns, 5 tools, and one Patch. Target
  and three-test regression both passed. Its second turn exercised the new provider
  compatibility path: one extra unexecuted call was discarded before the Agent continued.
- The complete sequential six-Case run then resolved **6/6** attempts with all six baseline
  failures reproduced and all six target and regression results passing. This is one
  empirical attempt per Case, not a statistically robust estimate and not pass@k.
- The suite used 28 model requests with zero API errors, 28 tools, seven Patch attempts, and
  66,074 reported input-plus-output tokens. Pagination's first Patch was safely rejected as
  `PATCH_GIT_RECOUNT_FAILED`; structured feedback produced a visible REPLAN and a successful
  second Patch. Five Cases recorded 13 discarded extra provider calls in total; none executed.
- All 36 recorded per-run artifact sizes and hashes matched. JSON/CSV identities and trace
  sequence/run IDs were consistent; skips, worktree leaks, fixture changes, credential hits,
  Authorization hits, and Agent-visible hidden-solution/reasoning hits were all zero.
- Sanitized public evidence is in `docs/results/openrouter-glm-5.2-live-r1.md`, its compact
  JSON companion, and `docs/examples/live-pagination-replan-trajectory.md`. Raw live
  artifact directories remain ignored and uncommitted.

### CI follow-up

- GitHub Actions run `29915003314` executed both matrix jobs for published commit
  `769ff6e`. Windows completed successfully. Ubuntu passed dependency setup, fixture
  bootstrap, the full pytest suite, explicit Maven/JUnit smoke, and Ruff, then failed only
  at mypy because Linux typeshed does not expose the Windows-only
  `subprocess.CREATE_NEW_PROCESS_GROUP` attribute.
- `python -m mypy --platform linux src` reproduced the exact failure locally. ProcessRunner
  now obtains that creation flag through a typed safe fallback; Windows retains the real
  nonzero flag and non-Windows retains its existing `start_new_session=True` behavior.
- Fix validation reported **263 passed in 369.89s**, Ruff passed, native-platform and Linux-
  platform mypy both passed, and `tests/test_process.py` passed 7/7. Fresh deterministic Case
  and FakeLLM runs resolved with real Maven/JUnit; benchmark validation remained **6/6
  VALID** and scripted/offline benchmark execution remained **6/6 RESOLVED**.

## 2026-07-22 Milestone 4B — Agent-first CLI and trajectory replay

### Living progress

- [x] Re-read repository rules and Milestones 1–4A documentation; inspect the existing
  Agent loop, sanitized trace, reporting, CLI, benchmark orchestration, and the real
  scripted regression-trap trace before editing.
- [x] Add a typed sanitized trace event and optional observer which receives exactly the
  durable event; observer exceptions disable presentation without changing execution.
- [x] Project canonical events into PREPARE, OBSERVE, DECIDE, ACT, VERIFY, REPLAN, and
  FINISH without exposing or reconstructing hidden reasoning.
- [x] Emit explicit feedback-driven `agent_replan_requested` events for Patch rejection,
  target failure, regression failure, and candidate rollback only when another model
  request follows.
- [x] Add compact/verbose/off live `repair` timeline controls and deterministic
  `--no-color` output without changing prompts, tools, budgets, or exit codes.
- [x] Generate `trajectory.md` plus size/SHA-256 metadata for successful and failed Agent
  runs; derive it from `trace.jsonl` and reference rather than embed `final.patch`.
- [x] Add offline `replay-run` for run directories, reports, and traces with strict schema,
  sequence, run-id, terminal-status, containment, size, and checksum checks.
- [x] Add unit and real Maven/JUnit integration coverage for rendering, replanning,
  observer isolation, artifact generation, replay failures, secrets, and regression-trap
  feedback.
- [x] Generate and review the committed sanitized regression-trap demonstration from a
  fresh real scripted benchmark run.
- [x] Run the complete pytest, ruff, mypy, deterministic Case, FakeLLM, six-Case validation,
  scripted benchmark, replay comparison, secret/worktree/fixture inspections, and record
  only newly observed results.
- [x] Commit the reviewed implementation on clean `main`, rerun post-commit gates, and
  push only verified `main` as `7ee8912ca58225f734484c5139103cb763b77e99`.
- [x] Inspect optional live configuration without printing it. Configuration was absent
  from that clean checkout, so no Milestone 4B live result was fabricated.

### Design decisions

- `trace.jsonl` remains the sole Agent-history authority. Live text, offline replay, and
  Markdown use one deterministic projection; they do not form a second orchestration
  state machine.
- Renderers receive only sanitized events after durable append. No renderer can stop a
  model request, tool, Patch transaction, verification, cleanup, or report outcome.
- REPLAN is public control-flow evidence, not a claim about model reasoning. It states
  that structured rejection/test/rollback feedback was returned before a later request.
- Replay is read-only and provider-free. It rejects any referenced artifact outside the
  run directory and any report/trace ordering, identity, status, size, or hash mismatch.
- `trajectory.md` contains the public Case goal, safe timeline, deterministic evidence,
  counters, token/timing telemetry, and final verifier-owned status. Raw Patches, source
  bodies, Maven logs, credentials, golden validation inputs, and hidden reasoning stay out.
- The scripted regression trap demonstrates the harness and feedback loop only; it is not
  live-model reasoning or a resolution-rate result.

### Observed evidence so far

- Renderer/reporting/replay/CLI focused suite: **61 passed** after the final safety and
  telemetry refinements.
- Real regression-trap TDD slice: target PASS, regression FAIL, candidate rollback,
  explicit REPLAN, second target PASS, second regression PASS, final `RESOLVED`.
- Real malformed-Patch recovery slice: structured `PATCH_GIT_HEADER_MISSING` feedback,
  explicit REPLAN, corrected Patch, target PASS, regression PASS, final `RESOLVED`.
- Final pre-commit `python -m pytest -q`: **245 passed in 359.47s**, with no skips.
- Final pre-commit `python -m ruff check .`: **All checks passed**.
- Final pre-commit `python -m mypy src`: **Success: no issues found in 23 source files**.
- Fresh final `verify-case` and FakeLLM commands both executed real Maven/JUnit and ended
  `RESOLVED` with baseline FAIL, target PASS, and regression PASS.
- Fresh `.artifacts-m4b-validation-final` validated **6/6** Cases; fresh
  `.artifacts-m4b-scripted-final` resolved **6/6 scripted/offline** attempts. These are
  harness results, not live-model capability data.
- Verbose replay exposed the regression-trap rollback and REPLAN cycle. Exported Markdown
  and generated `trajectory.md` had identical SHA-256
  `436444dc8099bba4ff603dcdafad1fd4fc3a8172dda803c71b4cb80c4ea75257`.
- All seven final Agent reports contained hashed trajectory metadata with zero mismatches.
  Fourteen Agent-visible trace/trajectory files had zero matches for secrets, raw Patches,
  source bodies, golden/hidden paths, or chain-of-thought. Fixture status was clean and
  temporary execution worktree children were zero.

## 2026-07-21 Milestone 4A — robust model Patch ingestion

### Living progress

- [x] Re-read the repository rules and Milestone 3 design, inspect the existing
  OpenRouter smoke report/trace, and confirm the two safe Patch rejections and absence
  of target/regression execution or false resolution.
- [x] Audit and retain the plaintext-to-`SecretStr` loader compatibility fix; make the
  configured endpoint explicit and distinguish OpenAI from OpenRouter without adding a
  second provider implementation.
- [x] Add a staged, auditable model Patch pipeline with raw/normalized hashes, bounded
  normalization, structural parsing, operation/path policy, strict Git check, limited
  recount fallback, transactional apply, and canonical final diff.
- [x] Add stable Patch error codes and actionable bounded rejection feedback containing
  exact remaining Patch attempts and a fictional complete format example.
- [x] Verify stateless continuation carries the prior function call and structured
  rejection into the next OpenRouter request without `previous_response_id`.
- [x] Add rollback verification and injected post-apply/rollback-failure coverage; a
  rollback failure becomes terminal infrastructure state.
- [x] Add real Git/Maven/JUnit FakeLLM coverage for read → malformed headerless Patch →
  structured rejection → corrected Patch → target PASS → regression PASS → `RESOLVED`.
- [x] Document the initial smoke finding, normalization/recount boundary, taxonomy, and
  controlled before/after live-smoke method.
- [x] Run the complete pytest, ruff, mypy, deterministic Case, benchmark validation,
  scripted benchmark, artifact/secret/worktree inspections, and record observed results.
- [x] Review and commit only intended files on `codex/milestone3`, confirming a clean tree.
  No post-change OpenRouter smoke was fabricated when configuration was unavailable.
- [x] Fast-forward clean `main`, revalidate the actual primary checkout, push only
  `main` to `origin/main`, and verify the remote SHA.

### Later validation of the historical 4A change

Milestone 4A correctly recorded that no post-change live result was fabricated at that
time. Milestone 5 later executed a clean six-Case R1 evaluation on commit
`944fc6aab83c64848c4eae11f291db80ebc69041`; all six single attempts resolved and the
hardened ingestion/replanning path was exercised. That one-attempt-per-Case observation
remains non-statistical and is not combined with Release 0.3's fresh R3 stability study.

### Safety and design decisions

- The model path supports modification of existing production Java files only. The
  deterministic golden-Patch path remains backward compatible and retains its existing
  validation behavior.
- Normalization is text-only and fully recorded: LF newlines, one leading UTF-8 BOM,
  whole-argument Patch fences, outer blank lines, and one final newline. Header synthesis
  is allowed only from one matching existing-file `---`/`+++` pair; no external hint can
  supply a path.
- Strict `git apply --check` remains first. `--recount` is attempted once only after
  structural and policy validation and can correct inaccurate counts only. The checked
  bytes and applied bytes are identical.
- Fine-grained `PATCH_*` evidence augments rather than replaces Milestone 2's top-level
  `POLICY_REJECTED` and Milestone 3's aggregate failure categories.
- OpenRouter uses the OpenAI-compatible Responses adapter with an explicit HTTPS base
  URL. The only key source remains `OPENAI_API_KEY`; `OPENROUTER_API_KEY` and other aliases
  are intentionally ignored.
- The initial OpenRouter result is not a capability statistic. Both malformed Patches
  were rejected before tests, and the interface change is not claimed successful until a
  new committed, `dirty=false` live run provides evidence.

### Observed implementation evidence so far

- Focused Patch-ingestion coverage exercises complete and fenced Patches, unambiguous
  header synthesis, ambiguous/missing/mismatched headers, traversal, test/build/CI
  policy, create/delete/rename/copy/binary/mode rejection, strict/recount behavior,
  invalid hunk prefixes/context, empty/encoding errors, bounded secret-redacted
  diagnostics, partial-apply rollback, post-apply rollback, and later recovery.
- A combined regression group covering patching, Agent tools, repair orchestration,
  OpenRouter continuation, run reporting, and benchmark reporting completed with
  **122 passed**. The dedicated ingestion module reached **24 passed** after the partial
  apply transaction test.
- The final pre-commit `python -m pytest -q` completed with **216 passed in 312.01s** and
  no skipped-test entry. `python -m ruff check .` reported **All checks passed** and
  `python -m mypy src` reported **Success: no issues found in 22 source files**.
- `verify-case` and the user-facing FakeLLM repair command both executed real Maven/JUnit
  and finished `RESOLVED` with baseline FAIL, patched target PASS, and regression PASS.
- Fresh `.artifacts-m4a-validation` evidence validated **6/6** Cases. Fresh
  `.artifacts-m4a-scripted` evidence resolved **6/6 scripted/offline** harness attempts;
  the trap recorded target PASS/regression FAIL before its second Patch passed both.
- Artifact inspection covered 90 files: the configured key, Authorization/Bearer text,
  Agent-visible hidden validation paths, and hidden reasoning each had zero matches.
  The fixture remained clean, temporary execution worktree children were zero, and all
  generated `.artifacts-m4a-*` roots were ignored by Git.

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
