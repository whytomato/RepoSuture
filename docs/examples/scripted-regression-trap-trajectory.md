# SCRIPTED PROVIDER DEMONSTRATION

> This is a deterministic scripted-provider demonstration generated from a real PatchPilot
> run on 2026-07-22. Git worktree creation, both Patch transactions, Maven, JUnit, the target
> test, regression suites, candidate rollback, and artifact verification all executed for
> real. It proves the Agent harness, feedback loop, and renderer. It does **not** represent
> live-model reasoning or model resolution capability.

# Agent Trajectory

- Run ID: `bench-mvp-scripted-quota-regression-trap-r001-20709966636b`
- Case ID: `quota-regression-trap`
- Provider and model: `scripted` / `deterministic-script-v1`
- Final deterministic status: **RESOLVED**
- Start time: `2026-07-22T08:32:17.135049+00:00`
- End time: `2026-07-22T08:32:37.440655+00:00`
- Duration: `20.297s`
- Budget usage: turns<=12, tools<=30, patches<=4, target-tests<=8, regressions<=4, wall-seconds<=1800

## Goal

Grant the configured premium upload quota

Non-trial premium plans should receive an upload quota of 100. Standard-plan and trial quota behavior must remain unchanged.

## Timeline

| Seq | Phase | Turn | Action / Observation | Result |
|---:|---|---:|---|---|
| 2 | PREPARE |  | Creating isolated worktree at commit d54d13bf |  |
| 3 | VERIFY |  | Baseline target test | FAIL (3.985s) |
| 4 | PREPARE |  | Failure reproduced; Agent execution started |  |
| 5 | DECIDE | 1 | Model turn 1/12 tools=0/30 patches=0/4 |  |
| 7 | ACT | 1 | list_files path="src/main/java" max_depth=8 tools=1/30 patches_remaining=4 | REQUESTED |
| 9 | OBSERVE | 1 | list_files returned 2 files; truncated=false; duration=0.000s | OK |
| 10 | DECIDE | 2 | Model turn 2/12 tools=1/30 patches=0/4 |  |
| 12 | ACT | 2 | search_code query="quotaFor" path="src/main/java" file_type="java" tools=2/30 patches_remaining=4 | REQUESTED |
| 14 | OBSERVE | 2 | search_code returned 1 match; truncated=false; duration=0.015s | OK |
| 15 | DECIDE | 3 | Model turn 3/12 tools=2/30 patches=0/4 |  |
| 17 | ACT | 3 | read_file path="src/main/java/dev/patchpilot/fixture/UploadQuotaService.java" start_line=1 end_line=160 tools=3/30 patches_remaining=4 | REQUESTED |
| 19 | OBSERVE | 3 | read_file returned 10 lines, 204 bytes; truncated=false; duration=0.000s | OK |
| 20 | DECIDE | 4 | Model turn 4/12 tools=3/30 patches=0/4 |  |
| 22 | ACT | 4 | read_file path="src/main/java/dev/patchpilot/fixture/Plan.java" start_line=1 end_line=160 tools=4/30 patches_remaining=4 | REQUESTED |
| 24 | OBSERVE | 4 | read_file returned 6 lines, 79 bytes; truncated=false; duration=0.000s | OK |
| 25 | DECIDE | 5 | Model turn 5/12 tools=4/30 patches=0/4 |  |
| 27 | ACT | 5 | apply_patch patch_size=434 patch_sha256="1e415eb27af34aee52b07362c26b202cff69572819e2f0006e216e1c9bcfe686" tools=5/30 patches_remaining=4 | REQUESTED |
| 29 | OBSERVE | 5 | Patch attempt 1 accepted; 1 production file changed | ACCEPTED |
| 30 | VERIFY |  | Target test (Patch 1) | PASS (4.047s) |
| 31 | VERIFY |  | Regression suite (Patch 1) | FAIL (3.422s) |
| 32 | OBSERVE | 5 | apply_patch returned OK; duration=7.922s | OK |
| 33 | REPLAN |  | Candidate reverted; regression diagnostic returned to Agent reasons=REGRESSION_FAILED,CANDIDATE_REVERTED next_turn=6 | FEEDBACK_RETURNED |
| 34 | DECIDE | 6 | Model turn 6/12 tools=5/30 patches=1/4 |  |
| 36 | ACT | 6 | apply_patch patch_size=554 patch_sha256="fbf67681bebb4fec66f9d1964ffd697e5be812be42ca69360f36f6473a48845e" tools=6/30 patches_remaining=3 | REQUESTED |
| 38 | OBSERVE | 6 | Patch attempt 2 accepted; 1 production file changed | ACCEPTED |
| 39 | VERIFY |  | Target test (Patch 2) | PASS (3.953s) |
| 40 | VERIFY |  | Regression suite (Patch 2) | PASS (3.375s) |
| 41 | OBSERVE | 6 | apply_patch returned OK; duration=7.796s | OK |
| 43 | FINISH |  | RESOLVED | turns=6 tools=6 patches=2 duration=20.3s |

## Verification

- Baseline target test: **FAIL**
- Candidate target tests: 2; latest **PASS**
- Regression executions: 2; latest **PASS**
- Candidate rollback events: 1
- Final correctness evidence: deterministic Git, Maven, JUnit, and repository-integrity checks

## Metrics

- Model turns: 6
- Tool calls: 6
- Tool calls by name: `apply_patch`=2, `list_files`=1, `read_file`=2, `search_code`=1
- Patch attempts: 2
- Target-test executions: 3
- Regression executions: 2
- Tokens: input=0, output=0, reasoning=0
- Model latency: 0.000s
- Test duration: 18.782s

## Final Result

**RESOLVED**. This status is determined by deterministic verification, never by the model's final message.

Verified Patch artifact: `final.patch` (SHA-256 `7814130efaf636f8856072cac2b7dcc9981e36d7820e983f262f9a4891a8253e`).
