# RepoSuture Real-World Maven Benchmark

The `maven-real-world-v1` suite contains exactly three unmodified upstream production bugs
from two Apache projects. Complete third-party repositories are fetched into
`benchmarks/real_world/.cache/`, which is ignored by Git. Only provenance metadata, public
Case files, test-overlay hashes, and hidden validation Patches are redistributed.

## Selection record

Research date: **2026-07-22**.

| Case | Project | Public bug/fix record | Buggy commit | Fix commit | Category |
|---|---|---|---|---|---|
| `commons-lang-mid-overflow` | Apache Commons Lang | [PR #1699](https://github.com/apache/commons-lang/pull/1699) | `e6b8bbd39505694012d869fa2107ef068b88d800` | `2240c1f93e5f96b12a83ec8615c29dfac46258e9` | integer-overflow boundary across two production APIs |
| `commons-collections-int-value` | Apache Commons Collections | [PR #704](https://github.com/apache/commons-collections/pull/704) | `b219ccbe7b95250abd3ba3143edf340b7fad1943` | `6171ecbb1dc89f3e2d3bae659b6364995fbc6027` | numeric data conversion |
| `commons-collections-flat3map-entry` | Apache Commons Collections | [PR #714](https://github.com/apache/commons-collections/pull/714) | `68a3c306d81dffe5bad59443dba3a7f5513178f4` | `14375bdba38421c174d646c40b8b757cce52dd45` | collection-entry conditional semantics |

Both projects use the Apache License 2.0. Full provenance, license URLs, paths, target
selectors, immutable diff hashes, and retrieval date are locked in
[`sources.yaml`](../benchmarks/real_world/sources.yaml) and
[`source-lock.json`](../benchmarks/real_world/source-lock.json).

At least one Case deliberately requires coordinating two related production implementations:
the Commons Lang target covers the String API, while the full regression suite also carries
the upstream mutable-builder regression. The other two Cases are not null-check variants.

## Inclusion criteria

Each selected bug has a public GitHub report/fix PR, complete buggy and fix SHAs, an
OSI-compatible license, a Maven build, a deterministic JUnit regression, no service/database/
Docker requirement, and a production-only upstream fix that fits the existing Java policy.
The target and relevant regression suite have bounded timeouts. The current Windows host is
unusually slow when compiling the complete Apache projects, so those environment-dependent
durations are reported rather than hidden.

The Apache Commons Lang regression emits 313 Surefire XML files for more than 40,000 JUnit
executions. On the release-validation host those files total 14.968 MiB and the largest is
5.935 MiB. RepoSuture therefore retains explicit evidence bounds of 16 MiB per report,
64 MiB total, and 1,000 report files; these are evidence-ingestion limits, not test-result
shortcuts.

Candidates rejected during research included:

- Gson issue/PR #3006: genuine duplicate-null-key behavior, but its multi-module reactor and
  serialization build increased environment/setup risk for this three-Case release.
- Commons Lang PR #1737: genuine boundary behavior, but it overlapped the chosen boundary
  category and did not add the required two-production-file navigation path.
- documentation-only, timing-sensitive, service-backed, Gradle, and fixes requiring build/CI
  changes were rejected by construction.

## Deterministic construction

For each Case the bootstrap:

1. verifies the exact 40-character buggy and fix Git objects;
2. checks the upstream URL and Apache license content hash;
3. starts from the buggy commit;
4. applies only the upstream test diff;
5. proves the resulting production paths are identical to the buggy commit;
6. checks the committed hidden production Patch byte-for-byte against the upstream diff;
7. adds RepoSuture's pinned Maven 3.9.9 `only-script` launcher as benchmark infrastructure
   without altering the upstream `pom.xml`;
8. creates a parentless local commit with fixed identity and timestamp; and
9. verifies the upstream cache HEAD/status is unchanged.

The resulting repository and source clone remain ignored. The Agent-visible Case contains
the local base commit and public behavior only. It contains no fix SHA, fix PR, golden Patch
path, expected modified file, production diff, or solution note.

## Commands

```powershell
python benchmarks/real_world/bootstrap_real_world.py

reposuture validate-benchmark `
  benchmarks/real_world/suites/maven-real-world-v1.yaml `
  --artifacts-dir .artifacts-r03-real-validation

reposuture benchmark-matrix `
  benchmarks/real_world/suites/maven-real-world-v1.yaml `
  --artifacts-dir .artifacts-live-r03-real-world-matrix `
  --provider openai `
  --model z-ai/glm-5.2 `
  --model openai/gpt-5-mini `
  --runs-per-case 1 `
  --schedule interleaved
```

`--write-lock` is a maintainer operation used only after manually reviewing a deliberate
upstream provenance change. Normal users and CI run the locked command without it.

Default CI does not fetch these repositories. The manual `Real-world benchmark validation`
workflow performs deterministic bootstrap/validation and makes no model API request.

## Correctness and secrecy boundary

The validation-only golden Patch is not an expected-text oracle. Alternative production
repairs are accepted when the target and full regression suite pass and repository/artifact
integrity holds. `sources.yaml`, `source-lock.json`, validation YAML, and hidden Patches are
never serialized into the Agent prompt or tool results. Agent tools remain confined to
production Java paths in the isolated local fixture worktree.
