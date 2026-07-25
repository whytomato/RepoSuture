# 真实缺陷基准缓存

本目录定义三个 Case 的历史 Suite `maven-real-world-v1`，以及八个 Case 的 Release 0.4 Suite `maven-real-world-v2`。

```powershell
python benchmarks/real_world/bootstrap_real_world.py

reposuture validate-benchmark benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-real-validation
```

目录职责：

- `sources.yaml` 与 `source-lock.json`：锁定上游来源和确定性本地 Base Commit；
- `cases/`：Agent 可见数据；
- `validation/`：只供 Harness 验证；
- `.cache/`：第三方 Clone 与重建仓库，禁止提交。

每个 Case 执行完整单模块 Maven Suite，或一组显式相关 JUnit 回归测试。Selector 固定在 `sources.yaml`，以参数数组传给 Maven；只有每个 Selector 都出现在 Surefire 证据中，回归才算有效。

构造方法、候选选择、许可证、保密边界和维护规则见[真实缺陷基准文档](../../docs/REAL_WORLD_BENCHMARK.md)。
