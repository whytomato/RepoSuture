# RepoSuture 真实缺陷 V2 评估：GLM-5.2 与 DeepSeek V4 Pro

这是 RepoSuture 0.4 的最终真实修复评估。全部 **28 次分配尝试均为新运行且已完成**，并来自同一个不可变、干净的源码 Commit。没有替换失败尝试，没有续跑旧的部分数据，也没有使用 GPT 模型。

结果仅作描述性工程证据，不是 pass@k。原有三个 Bug 每个模型重复三次，新增五个 Bug 每个模型只有一次广度观察。三次重复仍是小样本，单次观察不能视为稳定成功率；本 Suite 也不能证明通用 Java 修复能力。

## 复现信息

- 评估时间：`2026-07-25T10:36:17.369224Z` 至 `2026-07-25T13:19:47.992738Z`
- RepoSuture 评估 Commit：`e3cafd30edec3802c6bf88177e9c6a702e9c7e03`
- 源码树：`dirty=false`
- Provider：OpenRouter-compatible Responses API
- Endpoint：`https://openrouter.ai/api/v1`
- 模型：`z-ai/glm-5.2`、`deepseek/deepseek-v4-pro`
- Suite：`maven-real-world-v2`
- 基准指纹：`65d9547c2a05574d85a8d8689bd3e925ae7b24683bd22d417a05022dd8a7b1e2`
- 调度：确定性、顺序、交错
- 原有 Case：`3 Cases × 3 runs × 2 models = 18 attempts`
- 新增 Case：`5 Cases × 1 run × 2 models = 10 attempts`
- 总数：`28 assigned = 28 completed`
- Dry-run Plan SHA-256：`7c65663bc8a98614b3d5a4175293dbc5d2221e98fbe686f32b2655fd6bb607cf`

执行前于 `2026-07-25` 查询 OpenRouter 公开目录。两个准确模型 ID 均存在，均声明支持 `tools` 与 `tool_choice`，并标注 1,048,576 Token Context。目录可用性不作为模型实际执行证据；下方 Provider 与模型生命周期计数来自单次运行报告。

更早的一组部分运行暴露了一个通用分类缺陷：模型候选导致的编译失败被错误归为基础设施失败。该数据集已作废；修复后才执行本次干净重跑，**下列指标不包含任何旧观察**。

## 分母与汇总结果

RepoSuture 分开报告三类比率：

- 系统端到端解决率：`resolved / assigned`
- Provider 接受率：`provider accepted / assigned`
- 模型能力解决率：`resolved / model executed`

当 `model executed = 0` 时，能力率及其 Wilson 区间为 `N/A`，而不是 0%。本实验没有零分母：28 次尝试全部进入真实模型执行，并至少产生一个有效的模型工具请求。

| 指标 | GLM-5.2 | DeepSeek V4 Pro | 合计 |
|---|---:|---:|---:|
| 分配 / 完成 | 14 / 14 | 14 / 14 | 28 / 28 |
| 基线复现 | 14 | 14 | 28 |
| Provider 接受 | 14 | 14 | 28 |
| 模型执行 | 14 | 14 | 28 |
| 观察到模型 Tool Call | 14 | 14 | 28 |
| `RESOLVED` | 12 | 11 | 23 |
| 系统端到端率 | 0.857 | 0.786 | 0.821 |
| 系统描述性 Wilson 95% 区间 | [0.601, 0.960] | [0.524, 0.924] | [0.644, 0.921] |
| Provider 接受率 | 1.000 | 1.000 | 1.000 |
| 模型能力率 | 0.857 | 0.786 | 0.821 |
| 能力描述性 Wilson 95% 区间 | [0.601, 0.960] | [0.524, 0.924] | [0.644, 0.921] |
| 目标测试 PASS | 13 | 13 | 26 |
| 回归 PASS | 12 | 11 | 23 |
| 原始仓库完整性 | 14/14 | 14/14 | 28/28 |

Wilson 区间以 Attempt 为观察单位，仅作描述。两者区间高度重叠，`RESOLVED` 数量差异不足以说明存在统计上确定的胜者。

## 原有三个 Bug 的重复结果

每格按 Run 顺序列出三个终态。

| Case | GLM 成功 | GLM 运行 | DeepSeek 成功 | DeepSeek 运行 |
|---|---:|---|---:|---|
| `commons-lang-mid-overflow` | 2/3 | RESOLVED, RESOLVED, AGENT_BUDGET_EXHAUSTED | 1/3 | MODEL_STOPPED, RESOLVED, AGENT_BUDGET_EXHAUSTED |
| `commons-collections-int-value` | 3/3 | RESOLVED, RESOLVED, RESOLVED | 3/3 | RESOLVED, RESOLVED, RESOLVED |
| `commons-collections-flat3map-entry` | 3/3 | RESOLVED, RESOLVED, RESOLVED | 3/3 | RESOLVED, RESOLVED, RESOLVED |

在这三次重复中，两种模型都稳定解决了两个 Commons Collections Bug。Commons Lang 仍对回归敏感：GLM 解决 2/3，DeepSeek 解决 1/3。未解决运行保留了目标 PASS、回归 FAIL 证据，没有被替换。

## 新增五个 Bug 的广度观察

每格只有一次尝试，不能解释为稳定成功率。

| Case | 类别 | GLM | DeepSeek |
|---|---|---|---|
| `commons-codec-zero-big-integer` | 二进制编码边界 | RESOLVED | RESOLVED |
| `commons-text-csv-lone-quote` | CSV 引号解析 | RESOLVED | RESOLVED |
| `commons-io-bounded-reader-skip` | 范围计数 | RESOLVED | RESOLVED |
| `commons-csv-supplementary-delimiter` | Unicode 分隔符字节跟踪 | MODEL_STOPPED | MODEL_STOPPED |
| `commons-beanutils-nondouble-number` | 数值转换 | RESOLVED | RESOLVED |

两种模型都解决 4/5。Commons CSV supplementary-delimiter Case 中，两者都在提交可接受候选前停止。

## 完整 Attempt 证据

Tools 格式为 `generated/executed/discarded`；Tokens 格式为 `input/output/reasoning`。Reasoning Token 只是 Provider Telemetry，不包含隐藏推理正文。

| Seq | Case | Run | 模型 | 终态 | 主要失败 | 目标 | 回归 | Turns | Tools | Patches（拒绝） | Tokens | Wall s |
|---:|---|---:|---|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | `commons-lang-mid-overflow` | 1 | DeepSeek | MODEL_STOPPED | REGRESSION_UNRESOLVED | PASS | FAIL | 11 | 11/10/1 | 1 (0) | 55,341/2,628/1,426 | 445.781 |
| 2 | `commons-lang-mid-overflow` | 1 | GLM | RESOLVED | — | PASS | PASS | 18 | 21/18/3 | 3 (0) | 181,143/5,840/4,701 | 1,133.266 |
| 3 | `commons-collections-int-value` | 1 | GLM | RESOLVED | — | PASS | PASS | 7 | 8/7/1 | 2 (1) | 22,589/1,123/539 | 498.625 |
| 4 | `commons-collections-int-value` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 5 | 7/5/2 | 1 (0) | 16,918/1,197/400 | 372.234 |
| 5 | `commons-collections-flat3map-entry` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 9 | 9/9/0 | 1 (0) | 56,684/2,187/1,228 | 275.265 |
| 6 | `commons-collections-flat3map-entry` | 1 | GLM | RESOLVED | — | PASS | PASS | 8 | 8/8/0 | 1 (0) | 22,174/599/97 | 183.532 |
| 7 | `commons-codec-zero-big-integer` | 1 | GLM | RESOLVED | — | PASS | PASS | 5 | 6/5/1 | 1 (0) | 15,595/1,099/711 | 58.797 |
| 8 | `commons-codec-zero-big-integer` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 1 (0) | 77,223/5,653/4,408 | 177.610 |
| 9 | `commons-text-csv-lone-quote` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 3 | 4/3/1 | 1 (0) | 10,201/1,482/966 | 88.469 |
| 10 | `commons-text-csv-lone-quote` | 1 | GLM | RESOLVED | — | PASS | PASS | 2 | 2/2/0 | 1 (0) | 4,990/444/198 | 41.781 |
| 11 | `commons-io-bounded-reader-skip` | 1 | GLM | RESOLVED | — | PASS | PASS | 4 | 6/4/2 | 1 (0) | 10,982/1,000/635 | 72.250 |
| 12 | `commons-io-bounded-reader-skip` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 1 (0) | 76,018/6,366/5,250 | 204.594 |
| 13 | `commons-csv-supplementary-delimiter` | 1 | DeepSeek | MODEL_STOPPED | NO_PATCH_ACCEPTED | NOT_RUN | NOT_RUN | 9 | 10/8/2 | 0 (0) | 63,858/10,991/10,108 | 247.235 |
| 14 | `commons-csv-supplementary-delimiter` | 1 | GLM | MODEL_STOPPED | NO_PATCH_ACCEPTED | NOT_RUN | NOT_RUN | 8 | 9/7/2 | 0 (0) | 49,791/5,081/4,779 | 94.109 |
| 15 | `commons-beanutils-nondouble-number` | 1 | GLM | RESOLVED | — | PASS | PASS | 11 | 15/11/4 | 1 (0) | 58,471/1,024/292 | 148.969 |
| 16 | `commons-beanutils-nondouble-number` | 1 | DeepSeek | RESOLVED | — | PASS | PASS | 12 | 15/12/3 | 1 (0) | 61,365/2,529/976 | 230.453 |
| 17 | `commons-lang-mid-overflow` | 2 | GLM | RESOLVED | — | PASS | PASS | 10 | 10/10/0 | 2 (0) | 46,835/1,442/752 | 476.953 |
| 18 | `commons-lang-mid-overflow` | 2 | DeepSeek | RESOLVED | — | PASS | PASS | 13 | 14/13/1 | 2 (0) | 86,941/4,856/3,286 | 758.719 |
| 19 | `commons-collections-int-value` | 2 | DeepSeek | RESOLVED | — | PASS | PASS | 4 | 5/4/1 | 1 (0) | 12,778/922/284 | 363.797 |
| 20 | `commons-collections-int-value` | 2 | GLM | RESOLVED | — | PASS | PASS | 3 | 3/3/0 | 1 (0) | 7,334/322/46 | 331.672 |
| 21 | `commons-collections-flat3map-entry` | 2 | GLM | RESOLVED | — | PASS | PASS | 13 | 14/13/1 | 3 (1) | 79,610/1,304/253 | 421.110 |
| 22 | `commons-collections-flat3map-entry` | 2 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 2 (0) | 89,924/2,240/713 | 345.344 |
| 23 | `commons-lang-mid-overflow` | 3 | DeepSeek | AGENT_BUDGET_EXHAUSTED | REGRESSION_UNRESOLVED | PASS | FAIL | 18 | 19/18/1 | 1 (0) | 128,759/5,022/3,104 | 512.984 |
| 24 | `commons-lang-mid-overflow` | 3 | GLM | AGENT_BUDGET_EXHAUSTED | REGRESSION_UNRESOLVED | PASS | FAIL | 18 | 19/18/1 | 2 (0) | 203,190/6,670/5,840 | 816.422 |
| 25 | `commons-collections-int-value` | 3 | GLM | RESOLVED | — | PASS | PASS | 5 | 6/5/1 | 1 (0) | 11,861/392/48 | 341.093 |
| 26 | `commons-collections-int-value` | 3 | DeepSeek | RESOLVED | — | PASS | PASS | 10 | 11/10/1 | 1 (0) | 45,628/1,744/692 | 390.875 |
| 27 | `commons-collections-flat3map-entry` | 3 | DeepSeek | RESOLVED | — | PASS | PASS | 5 | 6/5/1 | 1 (0) | 31,409/1,401/596 | 385.563 |
| 28 | `commons-collections-flat3map-entry` | 3 | GLM | RESOLVED | — | PASS | PASS | 7 | 7/7/0 | 1 (0) | 23,490/586/131 | 390.438 |

## 失败分析

三个失败维度保持独立：

| 分布 | GLM-5.2 | DeepSeek V4 Pro |
|---|---|---|
| `terminal_status` | RESOLVED=12, MODEL_STOPPED=1, AGENT_BUDGET_EXHAUSTED=1 | RESOLVED=11, MODEL_STOPPED=2, AGENT_BUDGET_EXHAUSTED=1 |
| `primary_failure` | NO_PATCH_ACCEPTED=1, REGRESSION_UNRESOLVED=1 | NO_PATCH_ACCEPTED=1, REGRESSION_UNRESOLVED=2 |
| `observed_failures`（非互斥） | SEARCH_TOOL_ERROR=6, READ_TOOL_ERROR=3, PATCH_REJECTED=2, PATCH_GIT_CHECK_FAILED=1, TARGET_TEST_FAILED=1, REGRESSION_FAILED=3, CANDIDATE_REVERTED=4, MODEL_STOPPED=1, BUDGET_EXHAUSTED=1 | SEARCH_TOOL_ERROR=8, READ_TOOL_ERROR=1, TARGET_TEST_FAILED=1, REGRESSION_FAILED=3, CANDIDATE_REVERTED=4, MODEL_STOPPED=2, BUDGET_EXHAUSTED=1 |

两个预算耗尽运行都保留 `REGRESSION_UNRESOLVED` 为主要原因；后续搜索错误或预算事件没有覆盖目标 PASS、回归 FAIL 证据。实验中没有 Provider 拒绝、API 错误、基础设施错误、仓库完整性错误或产物完整性错误。

## 工具、Patch、Token 与耗时

| 指标 | GLM-5.2 | DeepSeek V4 Pro |
|---|---:|---:|
| 模型 Turns / Requests | 119 / 119 | 129 / 129 |
| Tool Calls 生成 / 执行 / 丢弃 | 134 / 118 / 16 | 144 / 127 / 17 |
| 已执行工具 | read=48, search=43, patch=20, list=3, target=2, diff=2 | read=55, search=51, patch=15, list=3, target=2, diff=1 |
| Patch 尝试 / 拒绝 | 20 / 2 | 15 / 0 |
| 使用规范化的 Run | 0 | 13 |
| 规范化操作 | 0 | 15 × `ENSURED_FINAL_NEWLINE` |
| 使用 Recount 的 Run | 7 | 4 |
| Input / Output / Reasoning Tokens | 738,055 / 26,926 / 19,022 | 813,047 / 49,218 / 33,437 |
| 模型延迟合计 | 781.233s | 1,447.262s |
| 模型延迟均值 | 55.802s | 103.376s |
| 测试耗时合计 | 4,066.507s | 3,199.171s |
| 测试耗时均值 | 290.465s | 228.512s |
| 墙钟耗时合计 | 5,009.017s | 4,798.923s |
| 墙钟耗时均值 | 357.787s | 342.780s |

在本样本中，DeepSeek 产生更多 Output/Reasoning Token，模型延迟也更高；GLM 提交更多候选 Patch，使用 Recount 更频繁。两种模型都出现 Tool Call 丢弃，因为单动作 Agent Loop 每轮只执行 Provider 返回的第一个调用。

## 完整性审计

- 28 个 Report、Trace、Trajectory、Attempt Manifest、文件大小和 SHA-256 均重新加载并通过验证；
- 所有报告记录准确评估 Commit 与 `dirty=false`；
- 28 个基线全部真实复现；基线与被接受候选均执行真实 Maven/JUnit；
- 临时 worktree 全部移除，八个 Fixture 仓库均保持干净；
- 原始本地产物中 API Key 与 Authorization Header 精确匹配数为 0；
- Agent 可见 Trace/Trajectory 中隐藏 Fix、Golden Patch、验证元数据与原始 Patch 标记匹配数为 0；
- 原始 live 产物和第三方缓存均被忽略且未提交。

脱敏机器摘要：[`reposuture-real-v2-glm-deepseek-summary.json`](reposuture-real-v2-glm-deepseek-summary.json)
