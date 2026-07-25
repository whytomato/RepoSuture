# RepoSuture 真实 Java/Maven 缺陷基准

`maven-real-world-v2` 是 Release 0.4 冻结的真实缺陷 Suite：来自七个 Apache Commons 仓库的八个 Java/Maven Bug。V1 保持为不可变的三个 Case 历史子集。完整第三方仓库、重建 Fixture 和构建输出只保存在被忽略的 `benchmarks/real_world/.cache/` 中。

## 锁定用例

候选研究完成于 **2026-07-24**。五个新增 Case 满足分布与运行要求后停止继续扩展。下表的 Commit 均为完整、不可变的 Git SHA。

| Case | 上游项目 | 公开记录 | Buggy Commit | Fix Commit | 类别 | V2 角色 |
|---|---|---|---|---|---|---|
| `commons-lang-mid-overflow` | Apache Commons Lang | [PR 1699](https://github.com/apache/commons-lang/pull/1699) | `e6b8bbd39505694012d869fa2107ef068b88d800` | `2240c1f93e5f96b12a83ec8615c29dfac46258e9` | 边界运算 | 原有 |
| `commons-collections-int-value` | Apache Commons Collections | [PR 704](https://github.com/apache/commons-collections/pull/704) | `b219ccbe7b95250abd3ba3143edf340b7fad1943` | `6171ecbb1dc89f3e2d3bae659b6364995fbc6027` | 数据转换 | 原有 |
| `commons-collections-flat3map-entry` | Apache Commons Collections | [PR 714](https://github.com/apache/commons-collections/pull/714) | `68a3c306d81dffe5bad59443dba3a7f5513178f4` | `14375bdba38421c174d646c40b8b757cce52dd45` | 集合语义 | 原有、回归敏感 |
| `commons-codec-zero-big-integer` | Apache Commons Codec | [PR 441](https://github.com/apache/commons-codec/pull/441) | `b7d744302ecf8b5ae775f28b5889a8af0dd4e82c` | `9400525894adeb9a7edd5bd5ec4fe5eeb774d83b` | 二进制编码 | 新增、回归敏感 |
| `commons-text-csv-lone-quote` | Apache Commons Text | [PR 748](https://github.com/apache/commons-text/pull/748) | `1bba8e3b90a155afb4e26ac7a8a1483e33d85a57` | `e2eb7d1afddca1fac6f55a125bdf2cd007bda589` | CSV 解析 | 新增 |
| `commons-io-bounded-reader-skip` | Apache Commons IO | [PR 860](https://github.com/apache/commons-io/pull/860) | `cfe19ad9dcc9d0c7308e2dc187b2f8b57de21af0` | `e806e6b5926993ec6348a78542b1e1377a765e88` | 范围计数 | 新增、跨组件、回归敏感 |
| `commons-csv-supplementary-delimiter` | Apache Commons CSV | [PR 613](https://github.com/apache/commons-csv/pull/613) | `ed8dbf25ad73856cfa10cba4f5e9855fdcae0d88` | `1d89cd5f0aa454ef3853dfc7528242399ef26b74` | Unicode 字节跟踪 | 新增、跨组件 |
| `commons-beanutils-nondouble-number` | Apache Commons BeanUtils | [PR 422](https://github.com/apache/commons-beanutils/pull/422) | `a62b1d1cc1d67e8caf38133c7f81c91d08e5f476` | `068d12326d95d153b42b0f60d6dfb41a033fc27a` | 数值转换 | 新增、跨组件 |

七个项目均使用 Apache License 2.0。Suite 覆盖七类 Bug，每个仓库最多两个 Case，并包含四个需要跨文件或跨组件理解的 Case。

完整来源、许可证 URL、目标 Selector、Test Overlay 哈希、回归范围和确定性本地 Commit 锁定在：

- [`benchmarks/real_world/sources.yaml`](../benchmarks/real_world/sources.yaml)
- [`benchmarks/real_world/source-lock.json`](../benchmarks/real_world/source-lock.json)

## 候选筛选

共考察十二个候选。先通过仓库、许可证、Maven 构建和 Fix 来源做静态筛选，再对必要候选 Clone 和执行测试。

接受的五个新增 Case 均完成真实 Maven/JUnit 基线复现。其余候选的拒绝原因：

- Commons Codec PR 436：Base32 自解码改动范围过宽，且与已选编码 Case 重叠；
- Commons Text PR 754：增加同仓库重复，类别多样性较弱；
- Commons IO `UnsynchronizedBufferedReader.readLine`：回归 Overlay 范围异常大；
- Commons CSV PR 628：简单空值检查，类别价值不足；
- Gson Issue/PR 3006 与 3034：多模块 Reactor 不符合当前有界单根目录策略；
- Commons Validator PR 419：Wrapper/Merge 来源不如已锁定 BeanUtils Case 直接。

满足 V2 数量、仓库分布、类别和运行时间要求后，没有继续研究更多候选。

## 纳入条件与回归范围

每个 Case 都满足：

- OSI-compatible License；
- 公开 Issue/PR 或可识别 Fix；
- Maven 与 JUnit；
- 有界目标和回归超时；
- 生产代码即可修复；
- 不依赖数据库、网络服务、云账号、Docker、交互输入、Native 组件或计时 Oracle。

原有三个 Case 与 BeanUtils 执行完整单模块 Maven `test`。Codec、Text、IO 和 CSV 使用锁定的三个相关非目标 JUnit 测试，因为其历史完整 Suite 分别包含：

- Windows 行结尾/哈希假设；
- 外部 HTTP 查询；
- Windows symlink 权限假设；
- Windows 资源行结尾假设。

每个选定测试都必须出现在 Surefire XML 中，否则视为基础设施失败。这种设计保留真实、相关的回归 Oracle，同时排除外部服务和平台特定噪声。Selector 与 Maven 参数数组固定在 `sources.yaml`。

跨组件范围：

- Commons Lang Case 跨 String 与 Builder API；
- IO、CSV 与 BeanUtils Case 涉及 Reader、Parser 或 Converter 的共享行为；
- Codec、IO 和既有 Flat3Map Case 对只让目标测试通过的补丁保持敏感。

## 确定性 Fixture 构造

每个 Case 的 Bootstrap 会：

1. 验证 40 字符 Buggy/Fix Git Object；
2. 验证上游 URL、SPDX 许可证和不可变哈希；
3. 从 Buggy Commit 开始，只应用上游测试改动；
4. 证明生产路径仍与 Buggy Commit 相同；
5. 逐字节校验隐藏生产 Patch 与上游 Fix；
6. 加入固定 Maven 3.9.9 `only-script` Launcher，但不修改 `pom.xml`；
7. 使用固定身份和时间创建无 Parent 的本地 Benchmark Commit；
8. 验证上游缓存的 HEAD 与 Status 不变。

Agent 可见 Case 只包含：

- 公开行为描述；
- Benchmark-local Base Commit；
- Target Selector；
- 预算和文件策略；
- 不泄露解法的上游来源。

它不包含 Fix SHA、Fix PR、隐藏 Patch 路径、预期修改文件、生产 Diff 或 Solution Note。

## 运行命令

重建并确定性验证：

```powershell
python benchmarks/real_world/bootstrap_real_world.py

reposuture validate-benchmark `
  benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-r04-real-validation
```

Release 0.4 最终修复评估计划：

```powershell
reposuture benchmark-matrix `
  benchmarks/real_world/suites/maven-real-world-v2.yaml `
  --artifacts-dir .artifacts-live-r04-final-repair `
  --provider openai `
  --model z-ai/glm-5.2 `
  --model deepseek/deepseek-v4-pro `
  --runs-per-case 1 `
  --case-runs commons-lang-mid-overflow=3 `
  --case-runs commons-collections-int-value=3 `
  --case-runs commons-collections-flat3map-entry=3 `
  --schedule interleaved
```

反馈消融锁定子集包含：

- `commons-lang-mid-overflow`
- `commons-collections-int-value`
- `commons-codec-zero-big-integer`
- `commons-io-bounded-reader-skip`
- `commons-csv-supplementary-delimiter`
- `commons-beanutils-nondouble-number`

机器可读选择保存在 `benchmarks/real_world/suites/maven-real-world-v2-feedback-ablation.yaml`。

## 0.4 版最终真实证据

最终评估使用 Commit
`e3cafd30edec3802c6bf88177e9c6a702e9c7e03`、`dirty=false` 和指纹
`65d9547c2a05574d85a8d8689bd3e925ae7b24683bd22d417a05022dd8a7b1e2`。

修复评估完成 28/28 次尝试，没有补跑：

- `z-ai/glm-5.2`：12/14 `RESOLVED`
- `deepseek/deepseek-v4-pro`：11/14 `RESOLVED`
- 原有 Case：Lang 为 2/3 对 1/3，Collections Int 为 3/3 对 3/3，Flat3Map 为 3/3 对 3/3
- 新增 Case：两种模型都解决 4/5；都在 supplementary-delimiter Case 上未提交可接受 Patch 即停止

DeepSeek 消融完成 12/12：

- `full-agent`：6/6 `RESOLVED`
- `single-candidate-no-feedback`：3/6 `RESOLVED`
- 无反馈模式出现一次目标通过但回归失败的 False Repair

这些结果是描述性观察。三次重复仍是小样本；单次广度与消融结果不是稳定率或因果证明。

最终脱敏报告：

- [真实缺陷 GLM/DeepSeek 对比](results/reposuture-real-v2-glm-deepseek.md)
- [DeepSeek 反馈消融](results/reposuture-feedback-ablation-deepseek.md)

`--write-lock` 只允许 Maintainer 在人工核对来源后使用。默认 CI 不下载第三方仓库；手动 `Real-world benchmark validation` Workflow 只执行确定性 Bootstrap 与验证，不请求模型。

## 正确性与保密边界

隐藏生产 Patch 只用于验证 Case 完整性，不是 Expected Text Oracle。替代实现只有在目标测试、回归测试和仓库/产物完整性全部通过时才被接受。

验证元数据与 Source Lock 不会序列化到 Agent Prompt、Trace、Trajectory 或工具结果。完整第三方源码、隐藏生产 Patch 和构建输出均不会提交到仓库。
