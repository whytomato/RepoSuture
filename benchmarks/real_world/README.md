# Real-world benchmark cache

This directory defines the historical three-Case `maven-real-world-v1` suite and the
eight-Case Release 0.4 `maven-real-world-v2` suite. Run:

```powershell
python benchmarks/real_world/bootstrap_real_world.py
reposuture validate-benchmark benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-real-validation
```

`sources.yaml` and `source-lock.json` pin upstream provenance and local deterministic base
commits. `cases/` is Agent-visible; `validation/` is harness-only. `.cache/` contains all
third-party clones and generated repositories and must never be committed.

Each Case either runs the full single-module Maven suite or an explicit list of related
JUnit regressions. Selected scopes are fixed in `sources.yaml`, passed to Maven as an
argument array, and accepted only when every selector is present in Surefire evidence.

See [`docs/REAL_WORLD_BENCHMARK.md`](../../docs/REAL_WORLD_BENCHMARK.md) for construction,
selection, licenses, secrecy boundaries, and maintenance rules.
