# RepoSuture 0.4 发布记录

状态：**已完成并冻结**

最后更新：2026-07-25

本文只记录当前发布状态、验证证据和仍然存在的限制。开发过程与旧版任务清单由 Git 历史保存，不在这里重复维护。

## 发布标识

- 仓库：`whytomato/RepoSuture`
- 主分支：`main`
- 版本线：`0.4`
- 真实评估使用的不可变 Commit：
  `e3cafd30edec3802c6bf88177e9c6a702e9c7e03`
- 首次发布最终结果的 Commit：
  `8d93e72f0b1c0805f89b794ca115ef231d514d40`
- 真实缺陷 V2 指纹：
  `65d9547c2a05574d85a8d8689bd3e925ae7b24683bd22d417a05022dd8a7b1e2`

最终 40 次真实尝试全部使用同一评估 Commit，并记录 `dirty=false`。

## 已发布能力

RepoSuture 0.4 包含：

- 面向 Java/Maven 修复的单 Agent 工具循环；
- 六个严格 Schema 的仓库工具；
- detached Git worktree 隔离；
- 只允许生产 Java 文件的事务化 Patch 应用；
- 真实 Maven/JUnit 目标测试与回归验证；
- 候选回滚和结构化重新规划反馈；
- 可配置预算与稳定的终止、失败分类；
- 脱敏的 `report.json`、`trace.jsonl` 和 `trajectory.md`；
- 无网络、无模型的轨迹重放；
- 确定性基准验证；
- 顺序单模型、跨模型矩阵和反馈消融执行器；
- 六个合成 MVP Case 与八个锁定真实缺陷 Case。

当前版本不提供任意 Shell、Gradle、多 Agent、自动测试生成、MCP、RAG、LSP、EvoMaster 或 Web UI。

## 正确性约束

只有同时满足以下条件，运行才可标记为 `RESOLVED`：

1. 基线阶段确实执行并复现指定目标测试失败；
2. 至少一个非空生产 Java Patch 被接受；
3. Patch 后目标测试确实通过；
4. 配置的回归范围确实通过；
5. 最终 Git diff 仍符合策略；
6. 原始仓库保持不变；
7. 临时 worktree 按配置清理；
8. 必需产物成功写入并通过完整性检查。

模型文本不能设置或绕过最终状态。

其他长期约束：

- 路径在解析后检查，包含 symlink 与 junction 逃逸；
- Agent 不得修改测试、构建文件、Maven Wrapper、CI 或 Git 元数据；
- 畸形或被拒绝的 Patch 不得部分修改 worktree；
- 被拒绝的 Patch 不触发测试；
- 验证失败的候选必须在下一轮前回滚；
- Provider 拒绝不得解释为模型修复能力为 0%；
- scripted 与 live 结果不得混合；
- Golden Patch 与上游 Fix 元数据不得进入 Agent 可见输入。

## 评估口径

报告分别统计：

- 分配尝试；
- 基线复现；
- Provider 接受与拒绝；
- 模型执行；
- 模型是否请求有效工具；
- 确定性解决；
- 基础设施失败。

公开比率：

- 系统端到端解决率：`resolved / assigned`
- Provider 接受率：`provider accepted / assigned`
- 模型能力解决率：`resolved / model executed`

当没有模型响应进入 Agent 循环时，能力解决率及其 Wilson 区间为 `N/A`，而不是 0%。

失败信息保留三个独立维度：

- `terminal_status`：执行如何结束；
- `primary_failure`：证据支持的最强主要原因；
- `observed_failures`：按发生顺序去重、可同时出现的失败事件。

后出现的搜索错误或预算耗尽不能覆盖已有的目标测试或回归失败证据。

## 实现验证

进入真实评估前，最终实现质量门记录为：

- pytest：**312 passed, 1 skipped, 2 deselected**
- Ruff：通过
- mypy：27 个源文件通过
- 合成 MVP 确定性验证：**6/6**
- 真实缺陷 V2 确定性验证：**8/8**
- 代表性 scripted 矩阵：**4/4**
- scripted 反馈消融：`full-agent` 为 `RESOLVED`，无反馈模式为目标 PASS、回归 FAIL
- 旧报告迁移与重放：通过
- 集成路径真实执行 Git、Maven、Java 和 JUnit

唯一 skipped 项是 Windows symlink 权限测试；两个 deselected 项需要访问上游网络。

## 最终真实缺陷评估

设计：

- 八个锁定的上游 Java/Maven Bug；
- 模型为 `z-ai/glm-5.2` 与 `deepseek/deepseek-v4-pro`；
- 原有三个 Case 每个模型运行三次；
- 新增五个 Case 每个模型运行一次；
- 确定性、顺序、交错调度；
- 共分配 28 次尝试；
- 不补跑失败结果。

结果：

| 模型 | 分配 | Provider 接受 | 模型执行 | `RESOLVED` |
|---|---:|---:|---:|---:|
| GLM-5.2 | 14 | 14 | 14 | 12 |
| DeepSeek V4 Pro | 14 | 14 | 14 | 11 |
| 合计 | 28 | 28 | 28 | 23 |

原有 Case 的三次重复：

| Case | GLM | DeepSeek |
|---|---:|---:|
| Commons Lang 中点溢出 | 2/3 | 1/3 |
| Commons Collections 整数转换 | 3/3 | 3/3 |
| Commons Collections Flat3Map Entry | 3/3 | 3/3 |

对五个新增 Case，两种模型都在单次广度观察中解决 4/5；两者都在 supplementary-delimiter Case 上停止，且未接受 Patch。

证据：

- [可读报告](results/reposuture-real-v2-glm-deepseek.md)
- [脱敏机器摘要](results/reposuture-real-v2-glm-deepseek-summary.json)

## 最终反馈消融

设计：

- 六个锁定真实 Case；
- 仅使用 DeepSeek V4 Pro；
- 比较 `full-agent` 与 `single-candidate-no-feedback`；
- 每个 Case/模式运行一次；
- 共分配 12 次尝试；
- 不补跑失败结果。

结果：

| 模式 | 分配 | 目标测试 PASS | 回归 PASS | `RESOLVED` |
|---|---:|---:|---:|---:|
| `full-agent` | 6 | 6 | 6 | 6 |
| `single-candidate-no-feedback` | 6 | 4 | 3 | 3 |

BeanUtils 的完整 Agent 运行先后利用目标测试失败、候选回滚、结构化 Patch 拒绝和 `REPLAN`，最终完成修复。Lang 的单候选运行通过目标测试但未通过回归，且按实验设计不能重新规划。

证据：

- [可读报告](results/reposuture-feedback-ablation-deepseek.md)
- [脱敏机器摘要](results/reposuture-feedback-ablation-deepseek-summary.json)

## 完整性审计

最终证据审计确认：

- 40/40 个运行报告可成功重放；
- 40/40 的 report、trace、trajectory、文件大小与 SHA-256 校验通过；
- 所有基线均成功复现；
- 所有报告使用同一干净评估 Commit；
- 原始 Fixture 仓库全部保持不变；
- 临时 worktree 全部清理；
- 没有替换任何失败尝试；
- 最终 Release 0.4 数据集不含 GPT 模型；
- API Key、Authorization Header、隐藏答案与原始 Patch 正文匹配数均为 0；
- 原始 live 产物、缓存、第三方 Clone 与 Maven 输出均未提交。

本地忽略的证据目录：

- `.artifacts-live-r04-final-repair`
- `.artifacts-live-r04-final-ablation`

## 文档索引

- [项目概览](../README.md)
- [Agent Runtime](AGENT_RUNTIME.md)
- [基准协议](BENCHMARK.md)
- [真实缺陷来源](REAL_WORLD_BENCHMARK.md)
- [安全策略](../SECURITY.md)
- [第三方声明](../THIRD_PARTY_NOTICES.md)

## 仍然存在的限制

- 原有 Case 每个模型仅重复三次，稳定性样本仍小；
- 新增 Case 与消融模式都只有一次观察；
- 结果是描述性的，不是 pass@k，也不能证明通用 Java 修复能力或因果关系；
- 基准面向已有确定性测试的有界 Maven/JUnit 项目，不代表任意 Java 仓库；
- 模型版本、Provider、网络、缓存、操作系统、Java/Maven 和硬件都会影响复现。

RepoSuture 0.4 已冻结。后续工作应建立新的发布计划，不修改本数据集。
