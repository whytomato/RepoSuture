# 第三方基准声明

RepoSuture 的可选真实缺陷基准引用以下项目，但不会提交这些项目的完整副本：

| 项目 | 许可证 | 源码 | 仓库中保留的基准材料 |
|---|---|---|---|
| Apache Commons Lang | Apache License 2.0 | https://github.com/apache/commons-lang | Commit/PR 元数据、哈希、有界 Issue 描述、上游 Test Diff 元数据、仅验证可见的生产 Patch |
| Apache Commons Collections | Apache License 2.0 | https://github.com/apache/commons-collections | Commit/PR 元数据、哈希、有界 Issue 描述、上游 Test Diff 元数据、仅验证可见的生产 Patch |
| Apache Commons Codec | Apache License 2.0 | https://github.com/apache/commons-codec | Commit/PR 元数据、哈希、有界 Issue 描述、上游 Test Diff 元数据、仅验证可见的生产 Patch |
| Apache Commons Text | Apache License 2.0 | https://github.com/apache/commons-text | Commit/PR 元数据、哈希、有界 Issue 描述、上游 Test Diff 元数据、仅验证可见的生产 Patch |
| Apache Commons IO | Apache License 2.0 | https://github.com/apache/commons-io | Commit/PR 元数据、哈希、有界 Issue 描述、上游 Test Diff 元数据、仅验证可见的生产 Patch |
| Apache Commons CSV | Apache License 2.0 | https://github.com/apache/commons-csv | Commit/PR 元数据、哈希、有界 Issue 描述、上游 Test Diff 元数据、仅验证可见的生产 Patch |
| Apache Commons BeanUtils | Apache License 2.0 | https://github.com/apache/commons-beanutils | Commit/PR 元数据、哈希、有界 Issue 描述、上游 Test Diff 元数据、仅验证可见的生产 Patch |

每个固定源码 Commit 的 Apache License 文本链接保存在
`benchmarks/real_world/sources.yaml`。下载的源码树和本地重建 Maven 仓库只存在于被忽略的 `benchmarks/real_world/.cache/`。

Apache、Apache Commons 及各项目名称是其权利人的商标。RepoSuture 与 Apache Software Foundation 没有关联，也未获得其背书。
