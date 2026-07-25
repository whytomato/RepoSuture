# OpenRouter GLM-5.2 真实评估：R1

> **历史结果。** 本次运行生成时项目仍名为 PatchPilot，之后更名为 RepoSuture。下方历史指标与标识未修改。

这是六个 MVP Case 的一次真实模型评估，不是 scripted 结果。每个 Case 只有一次尝试，因此观察到的 **6/6 不具备统计稳健性，也不是 pass@k**。

## 复现信息

- 完成时间：`2026-07-22T10:58:07.313297Z`
- PatchPilot Commit：`944fc6aab83c64848c4eae11f291db80ebc69041`
- 源码树：`dirty=false`
- Provider：OpenRouter-compatible Responses API
- Endpoint：`https://openrouter.ai/api/v1`
- 模型：`z-ai/glm-5.2`
- Suite：`mvp`
- 基准指纹：`20709966636b87d77e5a50fd0026557d405c7aa94955824ec80abb5e986a9ff0`
- 每个 Case 运行次数：`1`
- 环境：Windows、Python 3.11.15、Java 21.0.8 执行 Java 17 Fixture、Maven 3.9.9、Maven Wrapper 3.3.4、OpenAI SDK 2.46.0

使用当前 CLI 的等价命令：

```powershell
reposuture benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-live-m5-suite-r1 `
  --provider openai `
  --runs-per-case 1
```

凭据、Endpoint 和模型来自被忽略的本地环境。本报告不包含凭据值、Authorization Header、原始 Provider Body、隐藏推理、Golden Patch 或隐藏验证路径。

## 各 Case 结果

Tokens 格式为 `input / output / reasoning`。Provider Reasoning Token 已包含在其 Output Accounting 中，不会再次加入总量。

| Case | 终态 | 目标 | 回归 | Turns | Tools | Patches | Tokens | Duration | 失败类别 | 规范化 | Recount |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| null-input-validation | RESOLVED | PASS | PASS | 3 | 3 | 1 | 6,294 / 234 / 207 | 34.984s | RESOLVED | 无 | yes |
| pagination-boundary | RESOLVED | PASS | PASS | 5 | 5 | 2 | 12,638 / 1,003 / 610 | 63.187s | RESOLVED | 无 | no |
| status-filtering | RESOLVED | PASS | PASS | 6 | 6 | 1 | 13,403 / 418 / 367 | 79.531s | RESOLVED | 无 | yes |
| shipping-eligibility | RESOLVED | PASS | PASS | 3 | 3 | 1 | 6,071 / 281 / 229 | 41.234s | RESOLVED | 无 | yes |
| country-code-normalization | RESOLVED | PASS | PASS | 5 | 5 | 1 | 11,617 / 434 / 244 | 50.234s | RESOLVED | 无 | no |
| quota-regression-trap | RESOLVED | PASS | PASS | 6 | 6 | 1 | 13,251 / 430 / 324 | 184.453s | RESOLVED | 无 | no |

## 汇总证据

- 经验结果：**6/6 次尝试解决，6/6 个 Case 至少解决一次**；
- 基线复现 6/6，目标 PASS 6/6，完整回归 PASS 6/6；
- 模型请求 / API 错误：28 / 0；
- 模型 Turns：均值 4.67，中位数 5；
- 工具调用：均值 4.67，中位数 5；`read_file=13`、`apply_patch=7`、`list_files=4`、`search_code=4`；
- Patch 尝试：合计 7，均值 1.17，中位数 1，其中 1 次被拒绝；
- 耗时：均值 75.604s，中位数 56.710s，合计 453.623s；
- Tokens：Input 63,274、Output 2,800、Reasoning 1,981、Input+Output 66,074；
- 最终失败类别：`RESOLVED=6`。

分页 Case 的第一个 Patch 被安全拒绝为 `PATCH_GIT_RECOUNT_FAILED`。Agent 收到有界诊断，重新读取文件并提交第二个 Patch，随后通过目标与回归测试。详见[脱敏轨迹示例](../examples/live-pagination-replan-trajectory.md)。

没有运行需要文本规范化；三个被接受 Patch 使用有限 `git apply --recount`，只恢复不准确的 Hunk 行数。

尽管设置了 `parallel_tool_calls=false`，Provider 在五个 Case 中仍返回额外调用。Runtime 共记录并丢弃 13 个未执行调用，每轮只执行第一个动作，并要求模型在真实观察后重新决策。

## 完整性检查

六次运行分别创建独立 worktree 和全新模型对话。所有 worktree 均已移除，原始 Fixture Snapshot 保持不变，最终修改全部属于生产代码。真实 Maven/JUnit 执行，跳过测试数为 0。

六个报告共引用 36 个产物，记录的大小与 SHA-256 全部匹配；JSON/CSV Run Identity 与 Trace Sequence/Run ID 一致。

对本地原始产物的精确凭据扫描为 0 匹配。Agent 可见 Trace 与 Trajectory 中 Authorization、隐藏推理、Golden Patch 和隐藏验证路径匹配数均为 0。原始 `.artifacts-live*` 目录被忽略且未提交。

脱敏机器摘要：[`openrouter-glm-5.2-live-r1-summary.json`](openrouter-glm-5.2-live-r1-summary.json)
