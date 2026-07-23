# Real-world benchmark cache

This directory defines the optional RepoSuture `maven-real-world-v1` suite. Run:

```powershell
python benchmarks/real_world/bootstrap_real_world.py
reposuture validate-benchmark benchmarks/real_world/suites/maven-real-world-v1.yaml `
  --artifacts-dir .artifacts-real-validation
```

`sources.yaml` and `source-lock.json` pin upstream provenance and local deterministic base
commits. `cases/` is Agent-visible; `validation/` is harness-only. `.cache/` contains all
third-party clones and generated repositories and must never be committed.

See [`docs/REAL_WORLD_BENCHMARK.md`](../../docs/REAL_WORLD_BENCHMARK.md) for construction,
selection, licenses, secrecy boundaries, and maintenance rules.
