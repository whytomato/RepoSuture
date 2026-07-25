# RepoSuture DeepSeek 测试反馈消融

这是 RepoSuture 0.4 的最终反馈循环消融结果。它是一组受控工程对比，不构成统计或因果结论。

## 实验信息

- UTC 时间：`2026-07-25T13:22:39.963223Z` 至 `2026-07-25T14:16:01.817650Z`
- 评估 Commit：`e3cafd30edec3802c6bf88177e9c6a702e9c7e03`
- 源码树：`dirty=false`
- Provider：OpenRouter-compatible Responses API
- 模型：`deepseek/deepseek-v4-pro`
- Suite：`maven-real-world-v2`
- 基准指纹：`65d9547c2a05574d85a8d8689bd3e925ae7b24683bd22d417a05022dd8a7b1e2`
- 调度：确定性、顺序、交错
- Dry-run Plan SHA-256：`6f7f9181cd50fc622e373b3c4585bc0ae8e78da353de563af05ed1a58f52616c`
- 分配 / 完成：`12 / 12`
- 替换尝试：`0`
- 发现 Framework Defect：`0`

## 模式对比

| 指标 | `full-agent` | `single-candidate-no-feedback` |
|---|---:|---:|
| 分配 / 完成 | 6 / 6 | 6 / 6 |
| Provider 接受 | 6 | 6 |
| 模型执行 | 6 | 6 |
| 模型请求有效工具 | 6 | 6 |
| `RESOLVED` | 6 | 3 |
| 目标测试 PASS | 6 | 4 |
| 回归 PASS | 6 | 3 |
| 只通过目标的 False Repair | 0 | 1 |
| 模型 Turns / Requests | 55 / 55 | 45 / 45 |
| Tool Calls 生成 / 执行 / 丢弃 | 62 / 55 / 7 | 51 / 43 / 8 |
| Patch 尝试 / 拒绝 | 9 / 1 | 4 / 0 |
| Input / Output / Reasoning Tokens | 379,508 / 27,836 / 20,104 | 270,533 / 18,539 / 11,394 |
| 模型延迟 | 752.657s | 507.117s |
| 测试耗时 | 945.188s | 903.517s |
| 墙钟耗时 | 1,745.722s | 1,455.062s |

两种模式使用相同 Commit、模型、公开 Case、基线证据、探索工具、Patch 策略、目标测试、回归测试、超时、预算与确定性验证器。唯一计划差异：

- `full-agent` 可接收 Patch 后观察、回滚、重新规划，并在原预算内提交后续候选；
- `single-candidate-no-feedback` 最多提交一个候选，且不接收 Patch 后反馈。

## 各 Case 结果

| Case | `full-agent` | 目标 / 回归 | 无反馈 | 目标 / 回归 |
|---|---|---|---|---|
| `commons-lang-mid-overflow` | RESOLVED | PASS / PASS | REGRESSION_FAILED | PASS / FAIL |
| `commons-collections-int-value` | RESOLVED | PASS / PASS | RESOLVED | PASS / PASS |
| `commons-codec-zero-big-integer` | RESOLVED | PASS / PASS | RESOLVED | PASS / PASS |
| `commons-io-bounded-reader-skip` | RESOLVED | PASS / PASS | MODEL_STOPPED | NOT_RUN / NOT_RUN |
| `commons-csv-supplementary-delimiter` | RESOLVED | PASS / PASS | MODEL_STOPPED | NOT_RUN / NOT_RUN |
| `commons-beanutils-nondouble-number` | RESOLVED | PASS / PASS | RESOLVED | PASS / PASS |

Lang 的无反馈尝试是唯一只通过目标测试的 False Repair：目标 PASS、回归 FAIL，候选随后回滚。按实验设计，该反馈不会返回模型，也不会发生 `REPLAN` 或第二个 Patch。

## 反馈、回滚与重新规划证据

最明显的反馈循环出现在 `commons-beanutils-nondouble-number` 的 `full-agent` 运行：

1. 两个被接受候选先后未通过目标测试；
2. 两个候选都被回滚；
3. 每次确定性失败都触发 `REPLAN`；
4. 后续候选被策略拒绝，结构化拒绝信息返回 Agent；
5. 第四次 Patch 让目标与回归测试都通过。

该运行记录了 `TARGET_TEST_FAILED`、`CANDIDATE_REVERTED`、`PATCH_REJECTED` 和 `PATCH_POLICY_REJECTED`。`REPLAN` 原因包括两次 `TARGET_TEST_FAILED`、两次 `CANDIDATE_REVERTED` 和一次 `PATCH_REJECTED`。

本样本中没有完整 Agent 运行消费回归失败反馈：唯一回归失败发生在 Lang 无反馈模式，而 Lang 的完整 Agent 在第一个候选即解决。因此可以确认实验观察到目标测试与 Patch 拒绝后的恢复路径，但不能把总差异归因于回归反馈，也不能声称反馈导致了所有 Pair Difference。

## 失败维度

### `terminal_status`

| 状态 | `full-agent` | 无反馈 |
|---|---:|---:|
| RESOLVED | 6 | 3 |
| MODEL_STOPPED | 0 | 2 |
| REGRESSION_FAILED | 0 | 1 |

### `primary_failure`

| 主要失败 | `full-agent` | 无反馈 |
|---|---:|---:|
| NO_PATCH_ACCEPTED | 0 | 2 |
| REGRESSION_UNRESOLVED | 0 | 1 |

### `observed_failures`

| 观察事件 | `full-agent` | 无反馈 |
|---|---:|---:|
| CANDIDATE_REVERTED | 1 | 1 |
| PATCH_POLICY_REJECTED | 1 | 0 |
| PATCH_REJECTED | 1 | 0 |
| SEARCH_TOOL_ERROR | 1 | 2 |
| TARGET_TEST_FAILED | 1 | 0 |
| MODEL_STOPPED | 0 | 2 |
| REGRESSION_FAILED | 0 | 1 |

终态、主要原因和非互斥观察事件始终分开统计。

## 单次运行证据

| Case | 模式 | 状态 | Turns | Tools | Patches | 目标 | 回归 | Tokens | Latency | Duration |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|
| `commons-lang-mid-overflow` | full-agent | RESOLVED | 8 | 8 | 1 | PASS | PASS | 50,646 | 74.017s | 401.407s |
| `commons-lang-mid-overflow` | no-feedback | REGRESSION_FAILED | 3 | 3 | 1 | PASS | FAIL | 10,838 | 59.805s | 407.359s |
| `commons-collections-int-value` | no-feedback | RESOLVED | 10 | 10 | 1 | PASS | PASS | 46,284 | 67.242s | 407.609s |
| `commons-collections-int-value` | full-agent | RESOLVED | 4 | 4 | 1 | PASS | PASS | 13,670 | 39.681s | 348.969s |
| `commons-codec-zero-big-integer` | full-agent | RESOLVED | 9 | 9 | 1 | PASS | PASS | 57,644 | 100.679s | 167.329s |
| `commons-codec-zero-big-integer` | no-feedback | RESOLVED | 5 | 5 | 1 | PASS | PASS | 39,680 | 71.004s | 133.812s |
| `commons-io-bounded-reader-skip` | no-feedback | MODEL_STOPPED | 5 | 4 | 0 | NOT_RUN | NOT_RUN | 22,924 | 74.379s | 117.703s |
| `commons-io-bounded-reader-skip` | full-agent | RESOLVED | 11 | 11 | 1 | PASS | PASS | 82,014 | 115.363s | 207.032s |
| `commons-csv-supplementary-delimiter` | full-agent | RESOLVED | 9 | 9 | 1 | PASS | PASS | 69,417 | 270.875s | 319.938s |
| `commons-csv-supplementary-delimiter` | no-feedback | MODEL_STOPPED | 9 | 8 | 0 | NOT_RUN | NOT_RUN | 64,887 | 129.908s | 148.266s |
| `commons-beanutils-nondouble-number` | no-feedback | RESOLVED | 13 | 13 | 1 | PASS | PASS | 104,459 | 104.779s | 240.313s |
| `commons-beanutils-nondouble-number` | full-agent | RESOLVED | 14 | 14 | 4 | PASS | PASS | 133,953 | 152.042s | 301.047s |

## 完整性与限制

12 个 Report、Trace、Trajectory、文件大小和 SHA-256 均通过重放验证。每次尝试记录相同评估 Commit 和 `dirty=false`；所有基线复现，原始仓库不变，临时 worktree 全部移除。

扫描未发现 API Key、Authorization Header、隐藏 Fix、隐藏 Patch、原始 Patch 正文或隐藏推理暴露。

每个 Case/模式只有一次运行。Provider 非确定性、模型采样、Case 差异和样本规模都不允许得出统计或因果结论。所有 `RESOLVED` 都由验证器而不是模型文本决定。

脱敏机器摘要：[`reposuture-feedback-ablation-deepseek-summary.json`](reposuture-feedback-ablation-deepseek-summary.json)
