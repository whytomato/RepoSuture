# RepoSuture Java 缺陷基准

## 目的与边界

RepoSuture 使用可复现的 Java 17/Maven Case 评估单 Agent 修复流程。Harness 记录每次尝试是否解决、失败原因和有界资源消耗，但不会生成测试，也不会把模型文字当作正确性证据。

基准运行分为两种互斥模式：

- `scripted/offline`：注入确定性模型动作，用于验证编排。Git、`ToolExecutor`、Patch、Maven、JUnit、目标与回归验证都真实执行，但结果只证明 Harness 工作正常，不代表模型能力。
- `live model`：使用配置的 Provider，每次尝试创建全新模型对话。只有实际以该模式执行的结果才属于真实模型结果。

同一个汇总只能包含一种模式；scripted 与 live 记录不能混合。

## MVP 基准

版本化 Manifest 为 `benchmarks/suites/mvp.yaml`。

| Case ID | 类别 | 生产代码导航 | 验证行为 |
|---|---|---|---|
| `null-input-validation` | 空输入校验 | 单文件 | 缺失邮箱产生领域校验错误 |
| `pagination-boundary` | 分页边界 Off-by-one | 单文件 | 页面包含排他结束边界内的全部元素 |
| `status-filtering` | 枚举/状态过滤 | 两个相关文件 | Active 结果包含 open 与 in-progress，不包含 closed |
| `shipping-eligibility` | 布尔条件错误 | 单文件 | 地址与支付必须同时批准 |
| `country-code-normalization` | 字符串规范化 | 两个相关文件 | 忽略无害空白与大小写，但不接受其他国家代码 |
| `quota-regression-trap` | 目标通过、回归失败陷阱 | 单文件 | 只改变 Premium 配额，保持 Standard 与 Trial 行为 |

每个 Case 都有一个目标 JUnit Method 和至少一个无关回归测试。`quota-regression-trap` 的 scripted 轨迹先提交只让目标测试通过的错误候选，再根据回归反馈提交完整修复。

这些 Case 小且可读；依赖缓存后可离线运行，不需要数据库、网络服务、计时条件、生成代码或特殊构建。它们用于验证流程，不代表全部 Java Bug。

## 清单与隐藏数据边界

Suite Manifest 使用严格版本化 Schema，包含 Suite ID、描述、默认运行次数、默认 Agent 预算、标签、Harness-only Note 和有序 Case 列表。重复 ID、缺失文件、未知字段、无效 Commit、路径逃逸或公开/隐藏元数据不一致都会使 Suite 无效。

MVP 每项链接三种分离的数据：

1. `benchmarks/cases/<id>.yaml`：Agent 可见的 Schema-v2 Case，只包含 Issue、目标 Selector、固定仓库/Commit、预算和允许文件策略。
2. `benchmarks/validation/<id>.yaml`：仅验证器可见的 Schema-v1 数据，保存公开字段和隐藏 Golden Patch 引用。
3. `benchmarks/scripted/<id>.yaml`：仅离线 Harness 使用的确定性动作，不是 Agent Case，也不会进入 Provider Prompt。

真实缺陷 Case 不提供 scripted 解法。Loader 要求公开字段与验证字段完全一致；Golden Patch 必须位于 Agent 仓库之外。`repair_case` 只接收公开 Case，验证元数据和 Golden 内容不会进入 Prompt、工具结果、Trace 或 Trajectory。

Golden Patch 只用于证明 Case 本身有效，不是 Expected Text。任何生产代码 Patch 只要通过可执行 Oracle 都可接受。

## 基准指纹

指纹是对以下可审计内容计算的 SHA-256：

- 规范化 Suite Manifest；
- 规范化公开 Case、验证 Case 与 scripted Case；
- 隐藏验证 Patch 与 scripted Patch 字节；
- 每个固定 Base Commit；
- Fixture Commit 的完整 Git Tree Listing。

报告保存各组件哈希和总指纹。修改相关 Case、Fixture 或支持文件会改变指纹；绝对机器路径和时间戳不参与计算。

## 确定性验证

验证六个 MVP Case：

```powershell
python benchmarks/bootstrap_fixture.py

reposuture validate-benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-benchmark-validation
```

每个 Case 的验证步骤：

1. 校验 Schema、仓库和固定 Commit；
2. 创建 detached worktree；
3. 运行基线目标测试；
4. 从 Surefire XML 证明指定测试确实执行并失败；
5. 应用非空隐藏生产代码 Patch；
6. 重新运行目标测试；
7. 运行配置的回归范围；
8. 证明只修改允许的生产代码；
9. 对比原始仓库前后指纹；
10. 删除 worktree 并验证清理。

默认回归范围是完整 Maven Suite。真实缺陷 Case 可以锁定一组无关 JUnit Selector，以排除需要外部服务或不支持平台能力的上游测试；每个 Selector 都必须出现在 Surefire 证据中。

编译错误、目标测试缺失/为零/被跳过、超时、依赖失败、空 Patch、测试/构建/Wrapper/CI 修改、目标失败、回归失败、原始仓库变化或清理失败都会使 Case 无效。命令会继续验证后续 Case，最后以非零状态返回。

产物：

- `validation-summary.json`：结构化汇总与复现元数据；
- `validation-summary.csv`：每个 Case 一行；
- `validation-report.md`：可读表格；
- `cases/<deterministic-id>/`：单 Case 的 `report.json`、`trace.jsonl`、`final.patch` 和有界 Maven 日志。

## 批量 Agent 执行

真实 OpenAI-compatible 运行需要显式凭据和模型 ID，并可能产生费用：

```powershell
$env:OPENAI_API_KEY = "<your-api-key>"
$env:OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
$env:REPOSUTURE_MODEL = "<provider/model-id>"

reposuture benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-benchmark-live `
  --provider openai `
  --runs-per-case 1
```

离线编排验证：

```powershell
reposuture benchmark benchmarks/suites/mvp.yaml `
  --artifacts-dir .artifacts-benchmark-scripted `
  --provider scripted `
  --runs-per-case 1
```

常用选项包括 `--model`、可重复的 `--case`、`--runs-per-case`、`--random-seed`、`--max-turns`、`--max-tool-calls`、`--max-patch-attempts`、`--max-target-test-executions`、`--max-regression-executions` 和 `--max-wall-clock-seconds`。默认 `--continue-on-failure`，所有 Case 顺序执行。

每次尝试都有由 Suite、模式、Case、Run Number 和指纹派生的确定性 ID，并使用：

- 全新 detached worktree；
- 全新 `LLMClient` 与对话；
- 独立产物目录；
- 独立候选和工具状态。

汇总产物：

- `benchmark-summary.json`
- `benchmark-runs.csv`
- `benchmark-report.md`
- `runs/<deterministic-id>/` 下的单次报告、Trace、Trajectory、最终 Patch 与 Maven 日志

已有汇总文件不会被覆盖；新实验应使用新目录。

## 跨模型矩阵

`benchmark-matrix` 复用现有 `repair_case`，没有第二套 Agent Loop。至少需要两个显式模型 ID，并支持按 Case 覆盖运行次数：

```powershell
reposuture benchmark-matrix benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-live-r04-final-repair `
  --provider openai `
  --model z-ai/glm-5.2 `
  --model deepseek/deepseek-v4-pro `
  --runs-per-case 1 `
  --case-runs commons-lang-mid-overflow=3 `
  --case-runs commons-collections-int-value=3 `
  --case-runs commons-collections-flat3map-entry=3 `
  --schedule interleaved `
  --dry-run
```

`--dry-run` 不请求模型，也不创建产物。上述计划恰好包含 28 次尝试：原有三个 Case 的 18 次重复观察，加新增五个 Case 的 10 次单次广度观察。

执行是顺序且交错的。除模型 ID 外，两种模型使用相同 Commit、指纹、公开 Issue、Prompt、工具 Schema、预算、超时、Endpoint、策略和验证器。每项都有独立对话、worktree、模型绑定 Run ID 和模型专属产物目录。

矩阵根目录包含：

- `matrix-plan.json`
- `matrix-summary.json`
- `matrix-runs.csv`
- `matrix-report.md`

每个模型目录还包含普通 Benchmark 的三个汇总文件。报告统计工具生成/执行/丢弃、Patch 规范化与 recount、Token、延迟、测试、Patch 大小、失败分类、每 Case 结果和描述性 95% Wilson 区间。这些区间不是 pass@k。

### 严格续跑

`--resume` 只接受与当前计划完全相同且完整的 live 观察。以下内容必须匹配：

- 项目 Commit 与 `dirty=false`；
- Suite 与指纹；
- Case、Run Number、模型和 Provider；
- 预算与确定性 Run ID；
- Report Schema 与终态；
- Report/Trace 哈希；
- 每个产物的大小与 SHA-256。

完整失败运行也是有效观察，不能静默重跑。Dirty、scripted、部分、损坏、不同 Commit、不同模型或不同指纹的数据会被拒绝；Resume 不信任手工修改的汇总文件。

未传入 `--model` 时，RepoSuture 读取 `REPOSUTURE_MODEL` 和 `REPOSUTURE_COMPARISON_MODEL`。旧变量 `PATCHPILOT_MODEL` 与 `PATCHPILOT_COMPARISON_MODEL` 仅作弃用兼容，并在使用时每进程输出一次 stderr 警告；新变量始终优先。

Release 0.4 最终执行 28/28 次分配尝试：GLM 解决 12/14，DeepSeek 解决 11/14。详见[最终真实缺陷报告](results/reposuture-real-v2-glm-deepseek.md)。

## 真实缺陷套件

`benchmarks/real_world/suites/maven-real-world-v2.yaml` 与六个合成 MVP Case 分离。它包含七个 Apache Commons 仓库中的八个固定 Bug，不提供 scripted 解法，并使用相同的确定性验证、指纹、单模型和矩阵接口。V1 是不可变的三个 Case 历史子集。

```powershell
python benchmarks/real_world/bootstrap_real_world.py

reposuture validate-benchmark benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-real-validation
```

Clone 和重建 Fixture 只保存在被忽略的 `.cache/` 中；默认 pytest/CI 不下载它们。来源、许可证、Test-only Overlay、隐藏 Fix 分离、候选选择和手动无模型验证流程见[真实缺陷基准](REAL_WORLD_BENCHMARK.md)。

## Agent 轨迹与重放

每次 scripted 或 live 尝试都从脱敏 `trace.jsonl` 派生 `trajectory.md`，不会维护第二套历史。轨迹包含公开目标、`PREPARE/OBSERVE/DECIDE/ACT/VERIFY/REPLAN/FINISH` 时间线、确定性验证、预算、计数、耗时和终态，但不包含：

- 原始 Patch；
- 完整源码或 Maven 日志；
- 凭据或 Authorization Header；
- 隐藏推理；
- Golden Patch 或验证元数据。

成功轨迹只记录 `final.patch` 的相对路径和 SHA-256。

```powershell
reposuture replay-run .artifacts-benchmark-scripted/runs/<run-id> `
  --view verbose `
  --format text `
  --no-color
```

重放不访问 Provider、网络、Git 或 Maven。它校验 Report/Trace Schema、连续 Sequence、Run ID、终态、解析后的路径 containment、文件大小和 SHA-256。新报告使用相对产物路径，因此完整目录复制或移动后仍可重放；旧绝对路径报告只有在身份与哈希证据一致时才会安全重映射。

## 模型 Patch 接入

Live Adapter 读取：

- `OPENAI_API_KEY`
- 可选 `OPENAI_BASE_URL`
- `REPOSUTURE_MODEL`

OpenRouter 使用 `OPENAI_BASE_URL=https://openrouter.ai/api/v1`，CLI 仍选择 `--provider openai`，报告会记录实际 Provider 为 `openrouter`。确定性和 scripted 命令不会初始化 Live Client。

### 允许的规范化

RepoSuture 先记录原始 SHA-256，再只允许：

- 将 CRLF/CR 转为 LF；
- 移除 UTF-8 BOM；
- 仅在整个参数是单个 Patch Code Fence 时移除 Fence；
- 移除 Patch 外围空行；
- 保证恰好一个结尾换行。

只有一个既有文件，且 `--- a/<path>` 与 `+++ b/<path>` 明确指向同一个仓库内 `src/main/java/**/*.java` 时，才可合成一个缺失的 `diff --git` Header。路径不能从 Issue、历史读取、模型 prose、Hunk、预期文件或隐藏数据推断。

系统不会自动修复源码内容、行前缀、上下文、文件名、创建/删除、Rename/Copy、Binary/Mode 变化或多文件 Header。

### Git 检查与事务

结构、路径、操作和生产文件策略先于 Git。系统始终先执行严格 `git apply --check`；只有此前策略均通过且严格检查失败时，才尝试一次 `git apply --check --recount`，用于恢复不准确的 Hunk 行数。应用时使用完全相同的规范化字节，不允许 Fuzzy Context、`--3way`、`--reject`、`--unsafe-paths` 或 Whitespace Rewrite。

Patch 应用是事务。任何 Post-apply 步骤失败都会回滚并确认 worktree 为空；回滚失败属于终止性基础设施错误。

### Patch 错误码

稳定详细错误码包括：

`PATCH_EMPTY`、`PATCH_ENCODING_INVALID`、`PATCH_FENCE_INVALID`、
`PATCH_GIT_HEADER_MISSING`、`PATCH_FILE_HEADERS_MISSING`、
`PATCH_PATH_MISMATCH`、`PATCH_PATH_UNSAFE`、
`PATCH_OPERATION_UNSUPPORTED`、`PATCH_POLICY_REJECTED`、
`PATCH_HUNK_INVALID`、`PATCH_GIT_CHECK_FAILED`、
`PATCH_GIT_RECOUNT_FAILED`、`PATCH_APPLICATION_FAILED`、
`PATCH_POST_APPLY_FAILED`、`PATCH_ROLLBACK_FAILED`。

模型只收到有界 Git/策略诊断、所需格式、规则、规范化记录、worktree 未修改标记和剩余预算。下一次无状态请求包含前序输出、对应 Function Call、`function_call_output`、结构化拒绝和剩余预算；OpenRouter 不使用 `previous_response_id`。

## 正确性与指标

`RESOLVED` 要求基线目标失败、接受非空生产 Java Patch、目标 PASS、回归 PASS、原始仓库不变、证据持久化与 worktree 清理成功。模型最终文字不能设置该状态。

每次运行记录：

- Suite、指纹、Case、Run、Provider、模型和模式；
- `terminal_status`、`primary_failure`、`observed_failures`；
- 基线、目标与回归证据；
- Provider/模型生命周期计数；
- 模型轮数、请求数、工具调用；
- Patch 与拒绝次数；
- 测试执行次数；
- Provider 提供的 Token；
- API 错误、墙钟/模型/测试耗时；
- 修改文件与增删行；
- Patch 大小/路径和完整性证据。

汇总分别计算：

- `system_end_to_end_resolution_rate = resolved_attempts / assigned_attempts`
- `provider_acceptance_rate = provider_accepted_attempts / assigned_attempts`
- `capability_resolution_rate = resolved_attempts / model_executed_attempts`

`model_tool_call_attempts` 统计至少观察到一个有效模型工具请求的尝试。若没有模型响应进入 Agent 执行，能力率和 Wilson 区间在 JSON 中为 `null`、CSV 中为空或 `N/A`、Markdown 中为 `N/A`，不能写成 0%。系统级与能力级 Wilson 区间只在对应分母大于零时计算。

RepoSuture 不按硬编码价格计算费用。Token 是用量证据，不是价格。

## 失败分类

新报告分开保存：

- `terminal_status`：执行如何结束，继续兼容 CLI Exit Code；
- `primary_failure`：集中分类器基于证据选出的主要原因；
- `observed_failures`：按顺序去重、可同时出现的全部失败事件。

完整性与基础设施失败优先于 Provider 拒绝；模型执行前的 Provider 拒绝优先于模型行为；一旦候选进入测试，目标或回归证据不能被后续搜索错误或预算事件覆盖。

例如：目标 PASS、回归 FAIL、回滚、后续搜索失败、预算耗尽，应得到：

- `terminal_status=AGENT_BUDGET_EXHAUSTED`
- `primary_failure=REGRESSION_UNRESOLVED`
- `observed_failures` 同时保留回归、回滚、搜索与预算事件

旧 `failure_category` 记录仍可加载，但新报告只序列化三个新维度。聚合分析是确定性的，不由 LLM 生成。

## 反馈循环消融

`single-candidate-no-feedback` 复用相同 Provider、公开 Case、探索工具、`ToolExecutor`、Patch 策略、worktree、测试、报告和正确性判据。模型最多提交一个 Patch；Patch 被拒绝即结束。Patch 被接受后仍执行验证，但结果不返回模型，不允许 `REPLAN` 或第二个候选。

```powershell
reposuture benchmark-ablation `
  benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-live-r04-final-ablation `
  --provider openai `
  --model deepseek/deepseek-v4-pro `
  --mode full-agent `
  --mode single-candidate-no-feedback `
  --case commons-lang-mid-overflow `
  --case commons-collections-int-value `
  --case commons-codec-zero-big-integer `
  --case commons-io-bounded-reader-skip `
  --case commons-csv-supplementary-delimiter `
  --case commons-beanutils-nondouble-number `
  --schedule interleaved `
  --dry-run
```

Resume 身份包含执行模式，因此完整 Agent 结果不能复用为无反馈结果。最终 live 消融完成 12/12：`full-agent` 解决 6/6，`single-candidate-no-feedback` 解决 3/6，并出现一次只通过目标测试的 False Repair。详见[反馈消融报告](results/reposuture-feedback-ablation-deepseek.md)。

## 退出码

批量执行：

- `0`：执行完成且至少一次确定性解决；部分失败仍保留在汇总中；
- `2`：Suite、Filter、Manifest、关联 Case 或固定 Commit 无效；
- `3`：汇总生成前发生 Setup 基础设施失败，或没有尝试进入可执行测试状态；
- `4`：尝试已执行，但没有任何一次解决。

`validate-benchmark`：

- `0`：所有 Case 有效；
- `2`：Suite 无效；
- `3`：报告前基础设施失败；
- `4`：验证完成但至少一个 Case 无效。

## 复现与敏感信息

汇总记录项目 Git Commit 与 Dirty Flag、基准指纹、OS、Python、Java、Maven/Wrapper、相关 OpenAI SDK 版本、Provider、模型、UTC 时间、CLI 参数、有效预算和可选 Seed 元数据。

不记录 API Key、Authorization Header、完整环境变量、隐藏推理或用户秘密；疑似凭据的 Trace Key 会被脱敏。

真实结果仍会受到模型版本、Provider、网络、限流、依赖缓存、硬件、OS 进程语义和 Java/Maven 环境影响。比较报告前应先比较指纹和复现元数据。

## 新增 Case

### 合成 MVP Case

1. 在 `benchmarks/fixture-sources/` 添加小型 Java 17/Maven Fixture，包含一个失败目标和至少一个无关回归测试。
2. 扩展 `benchmarks/bootstrap_fixture.py`，创建固定、可重复的 Root Commit；连续 Bootstrap 两次确认完整 SHA 稳定。
3. 在 `benchmarks/cases/` 添加 Schema-v2 公开 Agent Case，不写解法、预期文件或实现提示。
4. 在 `benchmarks/validation/patches/` 添加仅生产代码的 Golden Unified Diff，并建立分离的 Schema-v1 验证 Case。
5. 如需离线 Harness 覆盖，在 `benchmarks/scripted/` 添加独立 scripted Case；不得从 Agent 可见数据引用 Golden Path。
6. 把相关路径、标签和 ID 加入 Suite Manifest，并保持三种 Schema 的公开字段和默认预算一致。
7. 执行确定性验证，检查基线 FAIL、目标 PASS、回归 PASS、仅生产代码修改、原始仓库不变和 worktree 清理。
8. 增补 Schema、指纹、报告和真实 Maven 集成测试，再运行质量门。

### 真实缺陷 Case

真实 Case 还必须固定上游 URL、许可证、公开 Issue/PR、Buggy/Fix SHA、Target Selector、Regression Scope、Test-only Overlay、内容哈希和确定性本地 Commit。完整第三方仓库不能提交，隐藏 Fix 不得进入 Agent 可见内容。详细规则见[真实缺陷基准](REAL_WORLD_BENCHMARK.md)。

任何 Case 都不能通过与 Golden Patch 的文本相等来判定成功；唯一正确性依据仍是可执行测试与仓库完整性。
