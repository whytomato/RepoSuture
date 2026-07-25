# RepoSuture Real-World Maven Benchmark

Release 0.4 adds the locked `maven-real-world-v2` suite: exactly eight upstream
Java/Maven bugs from seven Apache Commons repositories. V1 remains unchanged and is a
three-Case historical subset. Complete third-party repositories, generated fixtures, and
build output live under the ignored `benchmarks/real_world/.cache/` directory.

## Locked cases

Research was performed on **2026-07-24** and stopped after five valid additions were
locked. Every commit identifier below is a full immutable Git SHA.

| Case | Upstream project | Public record | Buggy commit | Fix commit | Category | V2 role |
|---|---|---|---|---|---|---|
| `commons-lang-mid-overflow` | Apache Commons Lang | [PR 1699](https://github.com/apache/commons-lang/pull/1699) | `e6b8bbd39505694012d869fa2107ef068b88d800` | `2240c1f93e5f96b12a83ec8615c29dfac46258e9` | boundary arithmetic | original |
| `commons-collections-int-value` | Apache Commons Collections | [PR 704](https://github.com/apache/commons-collections/pull/704) | `b219ccbe7b95250abd3ba3143edf340b7fad1943` | `6171ecbb1dc89f3e2d3bae659b6364995fbc6027` | data conversion | original |
| `commons-collections-flat3map-entry` | Apache Commons Collections | [PR 714](https://github.com/apache/commons-collections/pull/714) | `68a3c306d81dffe5bad59443dba3a7f5513178f4` | `14375bdba38421c174d646c40b8b757cce52dd45` | collection semantics | original, regression-sensitive |
| `commons-codec-zero-big-integer` | Apache Commons Codec | [PR 441](https://github.com/apache/commons-codec/pull/441) | `b7d744302ecf8b5ae775f28b5889a8af0dd4e82c` | `9400525894adeb9a7edd5bd5ec4fe5eeb774d83b` | binary encoding | new, regression-sensitive |
| `commons-text-csv-lone-quote` | Apache Commons Text | [PR 748](https://github.com/apache/commons-text/pull/748) | `1bba8e3b90a155afb4e26ac7a8a1483e33d85a57` | `e2eb7d1afddca1fac6f55a125bdf2cd007bda589` | CSV parsing | new |
| `commons-io-bounded-reader-skip` | Apache Commons IO | [PR 860](https://github.com/apache/commons-io/pull/860) | `cfe19ad9dcc9d0c7308e2dc187b2f8b57de21af0` | `e806e6b5926993ec6348a78542b1e1377a765e88` | range accounting | new, cross-component, regression-sensitive |
| `commons-csv-supplementary-delimiter` | Apache Commons CSV | [PR 613](https://github.com/apache/commons-csv/pull/613) | `ed8dbf25ad73856cfa10cba4f5e9855fdcae0d88` | `1d89cd5f0aa454ef3853dfc7528242399ef26b74` | Unicode byte tracking | new, cross-component |
| `commons-beanutils-nondouble-number` | Apache Commons BeanUtils | [PR 422](https://github.com/apache/commons-beanutils/pull/422) | `a62b1d1cc1d67e8caf38133c7f81c91d08e5f476` | `068d12326d95d153b42b0f60d6dfb41a033fc27a` | numeric conversion | new, cross-component |

All seven projects use Apache License 2.0. The suite contains seven distinct bug
categories, no repository contributes more than two Cases, and four Cases require
cross-file or multi-component reasoning. Full provenance, license URLs, target selectors,
test-overlay hashes, relevant regression scope, and deterministic local commits are locked
in [`sources.yaml`](../benchmarks/real_world/sources.yaml) and
[`source-lock.json`](../benchmarks/real_world/source-lock.json).

## Candidate filtering

Twelve candidates were investigated, using repository/license/build/provenance metadata
before cloning or building:

- The five additions above were accepted after real Maven/JUnit baseline reproduction.
- Commons Codec PR 436 was rejected because its broad Base32 self-decoding change
  overlapped the selected encoding Case.
- Commons Text PR 754 was rejected because it duplicated an already represented
  repository and offered less category diversity.
- Commons IO's `UnsynchronizedBufferedReader.readLine` candidate was rejected because the
  regression overlay was unusually broad.
- Commons CSV PR 628 was rejected as a trivial null-check with weak diversity value.
- Gson issues/PRs 3006 and 3034 were rejected because their multi-module reactor did not
  fit the current bounded single-root policy.
- Commons Validator PR 419 was rejected because wrapper/merge provenance was less direct
  than the locked BeanUtils conversion Case.

No more candidates were researched after the five additions met the V2 distribution and
runtime requirements.

## Inclusion and regression scope

Every Case has an OSI-compatible license, public fix record, Maven/JUnit test, bounded
timeout, production-only repair, and no database, network service, cloud account, Docker,
interactive input, native dependency, or timing-based oracle. The original three Cases and
BeanUtils use the complete single-module Maven `test` suite. Codec, Text, IO, and CSV use
locked lists of three related, non-target JUnit tests because their historical full suites
contain respectively Windows line-ending/hash assumptions, an external HTTP lookup,
Windows symbolic-link privilege assumptions, and Windows line-ending resource assumptions.
Every selected test must appear as executed in Surefire XML or the run is an infrastructure
failure. This keeps the regression oracle real and meaningful without admitting external
services or platform-specific failures. The exact selectors and Maven argument arrays are
recorded in `sources.yaml`; the complete upstream repositories are not redistributed.

The Commons Lang Case spans the String and builder APIs. The IO, CSV, and BeanUtils Cases
exercise behavior shared across reader/parser/converter components. The Codec and IO
additions, plus the existing Flat3Map Case, preserve regression-sensitive behavior where a
target-only repair is insufficient evidence.

## Deterministic construction

For each Case the bootstrap:

1. verifies exact 40-character buggy and fix Git objects;
2. verifies the upstream URL, SPDX license metadata, and immutable hashes;
3. starts from the buggy commit and applies only the upstream test change;
4. proves production paths still match the buggy commit;
5. checks the hidden production Patch byte-for-byte against the upstream fix;
6. adds the pinned Maven 3.9.9 `only-script` launcher without changing `pom.xml`;
7. creates a parentless benchmark commit with fixed identity and timestamp; and
8. verifies the upstream cache HEAD and status are unchanged.

The Agent-visible Case contains only public behavior, the benchmark-local base commit,
target selector, budgets, policy, and non-solution provenance. It never contains the fix
SHA, fix PR, hidden Patch path, expected modified file, production diff, or solution notes.

## Commands

```powershell
python benchmarks/real_world/bootstrap_real_world.py

reposuture validate-benchmark `
  benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-r04-real-validation
```

The locked Release 0.4 repair plan uses three runs for the original Cases and one for each
new Case:

```powershell
reposuture benchmark-matrix `
  benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-live-r04-final-repair `
  --provider openai `
  --model z-ai/glm-5.2 `
  --model deepseek/deepseek-v4-pro `
  --runs-per-case 1 `
  --case-runs commons-lang-mid-overflow=3 `
  --case-runs commons-collections-int-value=3 `
  --case-runs commons-collections-flat3map-entry=3 `
  --schedule interleaved
```

The locked feedback-ablation subset contains Commons Lang mid overflow, Commons
Collections int conversion, Codec zero BigInteger, IO bounded-reader skip, CSV
supplementary delimiter, and BeanUtils non-Double conversion. It spans six Cases, six
repositories, several categories, cross-component behavior, and regression-sensitive
behavior. The exact machine-readable selection is
`benchmarks/real_world/suites/maven-real-world-v2-feedback-ablation.yaml`.

## Final Release 0.4 live evidence

The final clean evaluation ran at commit
`e3cafd30edec3802c6bf88177e9c6a702e9c7e03` with `dirty=false` and the
locked fingerprint
`65d9547c2a05574d85a8d8689bd3e925ae7b24683bd22d417a05022dd8a7b1e2`.
It completed exactly 28/28 repair attempts with no replacements:

- `z-ai/glm-5.2`: 12/14 RESOLVED;
- `deepseek/deepseek-v4-pro`: 11/14 RESOLVED;
- original Cases: Lang 2/3 versus 1/3, Collections int 3/3 versus 3/3,
  and Flat3Map 3/3 versus 3/3;
- new Cases: each model resolved 4/5 one-run breadth observations; both
  stopped without a Patch on the supplementary-delimiter Case.

The controlled DeepSeek ablation completed 12/12 attempts. Full-agent
resolved 6/6; single-candidate-no-feedback resolved 3/6 and produced one
target-only false repair. These are descriptive observations: three
repetitions remain a small stability sample, and one-run breadth or
ablation outcomes are not stable rates or causal proof.

Canonical sanitized evidence:

- [`results/reposuture-real-v2-glm-deepseek.md`](results/reposuture-real-v2-glm-deepseek.md)
- [`results/reposuture-feedback-ablation-deepseek.md`](results/reposuture-feedback-ablation-deepseek.md)

`--write-lock` is a maintainer-only operation after manual provenance review. Default CI
does not fetch third-party repositories. The manual `Real-world benchmark validation`
workflow performs deterministic bootstrap and validation without a model API request.

## Correctness and secrecy boundary

Hidden production Patches validate Case integrity; they are not expected-text oracles.
Alternative production repairs are accepted only when target and regression tests pass and
repository/artifact integrity holds. Validation metadata and source locks are never
serialized into the Agent prompt, trace, trajectory, or tool results.
