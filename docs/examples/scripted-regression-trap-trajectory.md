# Scripted Provider 回归陷阱演示

> 本轨迹生成时项目仍名为 PatchPilot，之后更名为 RepoSuture。

**SCRIPTED PROVIDER 演示**

本文件来自真实 scripted Benchmark：Git worktree、Patch 应用、Maven、JUnit、目标测试与回归测试均实际执行。它证明 Agent Harness、反馈循环和轨迹渲染器可以工作，但不代表真实模型推理或模型修复能力。

## Agent 轨迹

- Run ID：`mvp-scripted-quota-regression-trap-r001-8ea46729cd`
- Case ID：`quota-regression-trap`
- Provider / 模型：`scripted` / `scripted-mvp`
- 最终状态：`RESOLVED`
- 开始：`2026-07-22T02:18:07.422594Z`
- 结束：`2026-07-22T02:18:27.719869Z`
- 耗时：`20.297s`
- 预算：`turns=6/8`、`tools=6/14`、`patches=2/3`

## 目标

Premium Account 的配额应为 100；Standard 与 Trial 行为必须保持不变。

## 时间线

| Seq | 阶段 | Turn | 动作或观察 | 结果 |
|---:|---|---:|---|---|
| 1 | PREPARE | 0 | 创建固定 Commit 的隔离 worktree | PASS |
| 2 | VERIFY | 0 | 执行基线目标测试 | FAIL，目标测试已确认执行 |
| 3 | PREPARE | 0 | 基线失败已复现，启动 Agent | PASS |
| 4 | DECIDE | 1 | 请求 scripted 模型动作 | 请求 `search_code` |
| 5 | ACT | 1 | `search_code` | query=`quota` |
| 6 | OBSERVE | 1 | 返回搜索结果 | 3 个匹配，未截断 |
| 7 | DECIDE | 2 | 请求下一动作 | 请求 `read_file` |
| 8 | ACT | 2 | `read_file` | 读取目标生产文件 |
| 9 | OBSERVE | 2 | 返回源码窗口 | 74 行，未截断 |
| 10 | DECIDE | 3 | 请求候选 Patch | `apply_patch` attempt=1 |
| 11 | ACT | 3 | 应用候选 Patch | Patch 被接受 |
| 12 | VERIFY | 3 | 执行目标测试 | PASS |
| 13 | VERIFY | 3 | 执行回归测试 | FAIL |
| 14 | REPLAN | 3 | 候选已回滚 | 原因：`REGRESSION_FAILED`、`CANDIDATE_REVERTED` |
| 15 | OBSERVE | 3 | 将回归证据返回 Agent | worktree 已恢复为空 |
| 16 | DECIDE | 4 | 请求更多证据 | 请求 `git_diff` |
| 17 | ACT | 4 | `git_diff` | 检查候选状态 |
| 18 | OBSERVE | 4 | 返回 Diff 统计 | 无待处理改动 |
| 19 | DECIDE | 5 | 请求修正后的 Patch | `apply_patch` attempt=2 |
| 20 | ACT | 5 | 应用第二个候选 | Patch 被接受 |
| 21 | VERIFY | 5 | 执行目标测试 | PASS |
| 22 | VERIFY | 5 | 执行回归测试 | PASS |
| 23 | FINISH | 5 | 确定性验证完成 | `RESOLVED` |

## 验证证据

- 基线目标测试：FAIL，并由 Surefire XML 确认执行；
- 第一个候选：目标 PASS、回归 FAIL；
- 第一个候选：完整回滚，worktree 恢复为空；
- 第二个候选：目标 PASS、回归 PASS；
- 原始仓库：保持不变；
- 临时 worktree：已清理。

## 指标

- 模型轮数：6
- 工具调用：6
- 工具分布：`search_code=1`、`read_file=1`、`apply_patch=2`、`git_diff=1`、`run_target_test=1`
- Patch 尝试：2
- 目标测试执行：3（含基线）
- 回归执行：2
- Token：scripted Provider 不提供

## 最终结果

`RESOLVED` 来自真实目标测试、回归测试和仓库完整性证据，而不是 scripted 模型文本。成功 Patch 只在本地运行产物中通过文件名与 SHA-256 引用，没有嵌入本演示。
