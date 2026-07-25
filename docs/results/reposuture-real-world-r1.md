# RepoSuture 真实 Java 缺陷评估：R1

> **历史结果。** 本报告保留 Release 0.3 的首次真实缺陷运行；当前 Release 0.4 的八 Case 最终评估见[最新报告](reposuture-real-v2-glm-deepseek.md)。

本实验对锁定的 `maven-real-world-v1` Suite 执行真实模型评估：三个上游 Bug、两个模型各一次，共 **六次分配尝试**。失败或零成功结果均保留，没有补跑。

每个 Case/模型只有一次，是 Smoke 级经验观察；它不是 pass@k，不具备统计稳健性，也不能代表广泛的真实 Java 修复能力。

## 复现信息

- 完成时间：`2026-07-24T09:17:48.356746Z`
- RepoSuture Commit：`6f0ced786524c7e4f3514a284b826eac9865bcac`
- 源码树：`dirty=false`
- Provider：OpenRouter-compatible Responses API
- Endpoint：`https://openrouter.ai/api/v1`
- 模型：`z-ai/glm-5.2`、`openai/gpt-5-mini`
- Suite：`maven-real-world-v1`
- 基准指纹：`345839d264b3b5c144fa8f9bbc75b419d917a4c0266d80c119c3dfb34ec19e82`
- 每个 Case/模型运行：`1`
- 调度：确定性、顺序、交错
- 计划 / 完成：`6 / 6`

## 上游来源与构造

| Case | 上游项目 | 公开记录 | 许可证 | Buggy Commit | Fix Commit | 类别 |
|---|---|---|---|---|---|---|
| `commons-lang-mid-overflow` | Apache Commons Lang | [PR 1699](https://github.com/apache/commons-lang/pull/1699) | Apache-2.0 | `e6b8bbd39505694012d869fa2107ef068b88d800` | `2240c1f93e5f96b12a83ec8615c29dfac46258e9` | 跨两个生产 API 的溢出边界 |
| `commons-collections-int-value` | Apache Commons Collections | [PR 704](https://github.com/apache/commons-collections/pull/704) | Apache-2.0 | `b219ccbe7b95250abd3ba3143edf340b7fad1943` | `6171ecbb1dc89f3e2d3bae659b6364995fbc6027` | 数值数据转换 |
| `commons-collections-flat3map-entry` | Apache Commons Collections | [PR 714](https://github.com/apache/commons-collections/pull/714) | Apache-2.0 | `68a3c306d81dffe5bad59443dba3a7f5513178f4` | `14375bdba38421c174d646c40b8b757cce52dd45` | Collection Entry 条件语义 |

每个 Fixture 从准确 Buggy Commit 开始，只应用上游回归测试变更，证明生产代码仍匹配 Buggy Commit，再创建确定性本地 Benchmark Commit。仅验证可见的生产 Patch 来自上游 Fix，并证明 `baseline FAIL → target PASS → regression PASS`；它不会进入 Agent Prompt、工具结果、Trace 或 Trajectory。

## 汇总对比

| 指标 | `z-ai/glm-5.2` | `openai/gpt-5-mini` |
|---|---:|---:|
| 分配尝试 | 3 | 3 |
| Provider 接受 / 拒绝 | 3 / 0 | 0 / 3 |
| 模型执行 / 模型 Tool Call Attempt | 3 / 3 | 0 / 0 |
| `RESOLVED` | 2/3 | 0/3 |
| 系统端到端率 | 0.667 | 0.000 |
| 系统描述性 Wilson 95% 区间 | [0.208, 0.939] | [0.000, 0.561] |
| 模型能力率 | 0.667 | N/A |
| 能力描述性 Wilson 95% 区间 | [0.208, 0.939] | N/A |
| 至少解决一次的 Case | 2/3 | 0/3 |
| 基线复现 | 3/3 | 3/3 |
| 目标 / 回归 PASS | 3 / 2 | 0 / 0 |
| 模型 Turns / Requests / API Errors | 27 / 27 / 0 | 3 / 3 / 3 |
| Tool Calls 生成 / 执行 / 丢弃 | 28 / 27 / 1 | 0 / 0 / 0 |
| Tool Call 丢弃率 | 3.57% | 0.0% |
| Patch 尝试 / 拒绝 | 6 / 2 | 0 / 0 |
| 规范化 / Recount Run | 0 / 1 | 0 / 0 |
| Tokens（Input / Output / Reasoning） | 218,835 / 14,510 / 14,504 | 0 / 0 / 0 |
| 平均模型延迟 | 288.294s | 0.000s |
| 平均测试耗时 | 489.750s | 61.521s |
| 平均墙钟耗时 | 792.677s | 70.922s |
| 平均 Final Patch 大小 | 788.667 bytes | 0 bytes |
| 原始仓库完整性 | 3/3 | 3/3 |

与 MVP R3 一样，GPT-5 Mini 的请求在模型 Tool Call 前因 Provider Terms of Service 返回 HTTP 403。三个 `MODEL_API_ERROR` 只代表端到端服务拒绝，不是修复质量证据。按修正后的口径，它有三次分配、三次 Provider 拒绝、零次模型执行，因此能力率与区间为 `N/A`。

## 完整 Attempt 证据

Tokens 格式为 `input/output/reasoning`。

| Seq | 模型 | Case | 终态 | 目标 | 回归 | Turns | Tools | Patches | Tokens | Duration | 主要失败 | 规范化 | Recount |
|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| 1 | `openai/gpt-5-mini` | `commons-lang-mid-overflow` | MODEL_API_ERROR | NOT_RUN | NOT_RUN | 1 | 0 | 0 | 0/0/0 | 95.406s | PROVIDER_REJECTED | no | no |
| 2 | `z-ai/glm-5.2` | `commons-lang-mid-overflow` | AGENT_BUDGET_EXHAUSTED | PASS | FAIL | 18 | 18 | 3 | 189069/13485/13778 | 1456.922s | REGRESSION_UNRESOLVED | no | yes |
| 3 | `z-ai/glm-5.2` | `commons-collections-int-value` | RESOLVED | PASS | PASS | 3 | 3 | 1 | 7291/385/342 | 518.313s | — | no | no |
| 4 | `openai/gpt-5-mini` | `commons-collections-int-value` | MODEL_API_ERROR | NOT_RUN | NOT_RUN | 1 | 0 | 0 | 0/0/0 | 54.422s | PROVIDER_REJECTED | no | no |
| 5 | `openai/gpt-5-mini` | `commons-collections-flat3map-entry` | MODEL_API_ERROR | NOT_RUN | NOT_RUN | 1 | 0 | 0 | 0/0/0 | 62.937s | PROVIDER_REJECTED | no | no |
| 6 | `z-ai/glm-5.2` | `commons-collections-flat3map-entry` | RESOLVED | PASS | PASS | 6 | 6 | 2 | 22475/640/384 | 402.797s | — | no | no |

Commons Lang 运行明确展示了反馈驱动的重新规划：第一个候选目标 PASS、回归 FAIL，因此 Runtime 回滚并返回失败；后续 Patch 被策略拒绝，另一个候选再次目标 PASS、回归 FAIL，最后在固定 18 Turn 预算终止。终态为 `AGENT_BUDGET_EXHAUSTED`，主要原因保留为 `REGRESSION_UNRESOLVED`；后续 `SEARCH_TOOL_ERROR` 与 `BUDGET_EXHAUSTED` 只作为有序观察事件存在，没有产生错误的 `RESOLVED`。

Flat3Map 的第一个畸形 Patch 未通过严格和 Recount 检查。Agent 收到结构化拒绝后提交第二个 Patch，目标与回归均通过；最终被接受 Patch 不需要 Recount。

GLM 已执行工具：`search_code=10`、`read_file=9`、`apply_patch=6`、`list_files=1`、`run_target_test=1`。

终态与主要失败：

- GLM：`RESOLVED=2`、`AGENT_BUDGET_EXHAUSTED=1`
- GPT-5 Mini：`MODEL_API_ERROR=3`
- `REGRESSION_UNRESOLVED=1`
- `PROVIDER_REJECTED=3`

## 完整性与限制

每个基线和被接受候选都执行真实 Maven/JUnit。六个报告使用相同干净 Commit、Suite 指纹、公开 Case、预算、工具、Patch 策略、Endpoint 和正确性判据。所有 worktree 已移除，上游缓存未变，原始仓库完整性为 6/6。

严格 `--resume` 在不发起新 API 请求的情况下复用六个完整观察。凭据、Authorization Header 和 Agent 可见隐藏 Fix 扫描均为 0 匹配。未提交第三方 Clone、原始 Patch、原始 Provider Body、完整 Maven 日志或 live 产物。

Windows 构建速度显著影响耗时；Apache 回归 Suite 远大于 MVP Fixture。每个 Case/模型只有一次，且只覆盖两个上游项目，不能进行广泛推断。

脱敏机器摘要：[`reposuture-real-world-r1-summary.json`](reposuture-real-world-r1-summary.json)
