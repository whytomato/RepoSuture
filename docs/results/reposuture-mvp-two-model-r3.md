# RepoSuture MVP 双模型重复评估：R3

> **历史结果。** 本报告保留 Release 0.3 的真实运行证据；当前 Release 0.4 的主动评估模型与最终结论见主 README。

本实验对六个 MVP Case、两个模型各运行三次，共 **36 次分配尝试**，没有替换失败尝试。结果不是 pass@k；每个 Case 三次仍是小样本，也不能证明通用 Java 修复能力。

## 复现信息

- 完成时间：`2026-07-24T08:30:38.559463Z`
- RepoSuture Commit：`6f0ced786524c7e4f3514a284b826eac9865bcac`
- 源码树：`dirty=false`
- Provider：OpenRouter-compatible Responses API
- Endpoint：`https://openrouter.ai/api/v1`
- 模型：`z-ai/glm-5.2`、`openai/gpt-5-mini`
- Suite：`mvp`
- 基准指纹：`2db5511043823b94edbeaa0fd7fc84dc9543fe59093ec8ce27f0f8c612973d4f`
- 每个 Case/模型运行：`3`
- 调度：确定性、顺序、交错
- 计划 / 完成：`36 / 36`

OpenRouter 模型页面检查时间为 `2026-07-24T09:22:10Z`。当时页面显示：

- [`z-ai/glm-5.2`](https://openrouter.ai/z-ai/glm-5.2)：1M Context，Input/Output 价格 `$0.7553/$2.374` 每百万 Token；
- [`openai/gpt-5-mini`](https://openrouter.ai/openai/gpt-5-mini/)：400K Context，Input/Output 价格 `$0.25/$2.00` 每百万 Token。

这只是带时间戳的目录快照，RepoSuture 没有据此计算费用。

目录可用不等于请求有权执行。GPT-5 Mini 的 18 次请求全部在模型产生 Tool Call 前，因上游 Provider Terms of Service 返回 HTTP 403。报告将其保留为 `MODEL_API_ERROR`，不解释为模型修复失败，也不补跑。

按 Release 0.4 修正后的分母口径：

- 分配尝试：18；
- Provider 拒绝：18；
- 模型执行：0；
- GPT 模型能力率与 Wilson 区间：`N/A`，不是 0%。

## 汇总对比

| 指标 | `z-ai/glm-5.2` | `openai/gpt-5-mini` |
|---|---:|---:|
| 分配尝试 | 18 | 18 |
| Provider 接受 / 拒绝 | 18 / 0 | 0 / 18 |
| 模型执行 / 模型 Tool Call Attempt | 18 / 18 | 0 / 0 |
| `RESOLVED` | 18/18 | 0/18 |
| 系统端到端率 | 1.000 | 0.000 |
| 系统描述性 Wilson 95% 区间 | [0.824, 1.000] | [0.000, 0.176] |
| 模型能力率 | 1.000 | N/A |
| 能力描述性 Wilson 95% 区间 | [0.824, 1.000] | N/A |
| 至少解决一次的 Case | 6/6 | 0/6 |
| 三次均解决的 Case | 6/6 | 0/6 |
| 基线复现 | 18/18 | 18/18 |
| 目标 / 回归 PASS | 18 / 18 | 0 / 0 |
| 模型 Turns / Requests / API Errors | 88 / 88 / 0 | 18 / 18 / 18 |
| Tool Calls 生成 / 执行 / 丢弃 | 125 / 88 / 37 | 0 / 0 / 0 |
| Tool Call 丢弃率 | 29.6% | 0.0% |
| Patch 尝试 / 拒绝 | 20 / 2 | 0 / 0 |
| 规范化 / Recount Run | 0 / 8 | 0 / 0 |
| Tokens（Input / Output / Reasoning） | 202,373 / 7,999 / 3,988 | 0 / 0 / 0 |
| 平均模型延迟 | 65.673s | 0.000s |
| 平均测试耗时 | 13.883s | 4.748s |
| 平均墙钟耗时 | 80.753s | 6.091s |
| 平均 Final Patch 大小 | 573.389 bytes | 0 bytes |
| 原始仓库完整性 | 18/18 | 18/18 |

GPT Token 与模型延迟为 0，因为 Provider 在生成响应前拒绝了请求；其墙钟与测试耗时包含真实基线复现。数据可以说明当时的服务端到端可用性差异，但**不能用于比较两个模型的修复能力**。

## 各 Case 与各次尝试

每个单元格为 `终态（目标/回归）`。

| Case | GLM 成功 | GLM Run 1 | GLM Run 2 | GLM Run 3 | GPT 成功 | GPT Run 1 | GPT Run 2 | GPT Run 3 |
|---|---:|---|---|---|---:|---|---|---|
| `null-input-validation` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `pagination-boundary` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `status-filtering` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `shipping-eligibility` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `country-code-normalization` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |
| `quota-regression-trap` | 3/3 | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | RESOLVED (PASS/PASS) | 0/3 | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) | MODEL_API_ERROR (NOT_RUN/NOT_RUN) |

## 工具协议与 Patch

GLM 在 Provider 生成的 125 个调用中执行 88 个。为保持单动作循环，RepoSuture 确定性丢弃 37 个额外调用，丢弃率 29.6%。已执行工具：

- `read_file=39`
- `apply_patch=20`
- `search_code=19`
- `list_files=10`

20 次 Patch 尝试产生 18 个验证修复；两次畸形 Patch 被安全拒绝后得到修正。没有运行需要文本规范化；八个被接受 Patch 使用有限 `git apply --recount`。被拒绝 Patch 均未触发目标或回归测试。

终态：

- GLM：`RESOLVED=18`
- GPT-5 Mini：`MODEL_API_ERROR=18`
- GPT 主要失败：`PROVIDER_REJECTED=18`
- GPT 观察事件：`PROVIDER_HTTP_403=18`

未发现 RepoSuture Framework Defect、重复 Resume 或混入其他 Commit 的尝试。

## 完整性审计

36 个报告使用相同干净 Commit、指纹、公开 Case、工具、预算、超时、Patch 策略、Endpoint、顺序策略和确定性验证器。每次尝试使用全新对话与 worktree；全部 worktree 已移除，原始仓库保持不变。

严格 `--resume` 成功复用 36 个完整观察，没有新增 API 请求。每个运行都检查了 Report/Trace/Trajectory Identity 和测试证据。凭据、Authorization Header 与 Agent 可见隐藏元数据精确扫描为 0 匹配。原始 live 产物保持忽略且未提交。

脱敏机器摘要：[`reposuture-mvp-two-model-r3-summary.json`](reposuture-mvp-two-model-r3-summary.json)
