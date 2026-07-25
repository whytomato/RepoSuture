# 安全策略

RepoSuture 是作品集与研究性质的工程项目，不宣称自己是生产级安全边界。与命令执行、路径逃逸、凭据暴露、Patch 策略绕过、worktree 隔离、回滚或产物完整性有关的问题仍会被认真处理。

## 报告安全问题

请通过[公开仓库 Issue Tracker](https://github.com/whytomato/RepoSuture/issues)发起安全协调。首个公开 Issue 只应包含简短影响说明，以及受影响的 RepoSuture 版本或 Commit。

不要在公开 Issue 中提供：

- 利用细节；
- 私有仓库内容；
- API Key、Authorization Header 或其他凭据；
- 敏感 Trace；
- 原始 Provider Payload；
- 其他秘密信息。

Maintainer 可通过该 Issue 协调后续安全渠道，再接收敏感复现细节。

对可以安全公开完整复现的非敏感加固问题，可直接提交普通 GitHub Issue。请说明操作系统、Python/Java 版本、准确 RepoSuture Commit，以及源码树是否干净；同时删除用户路径和全部凭据。

## 关注范围

特别有价值的问题包括：

- 绕过固定参数数组子进程策略而执行命令；
- 仓库、worktree、symlink、junction 或产物路径逃逸；
- API Key、Authorization Header、私有源码、原始 Patch 或隐藏推理泄露；
- 修改测试、构建文件、Maven Wrapper、CI 或其他禁止路径；
- Patch 部分应用、回滚失败或原始仓库被修改；
- Report、Trace、Trajectory、Final Patch、文件大小或 SHA-256 不一致；
- 缺少真实 Git、Maven、JUnit 证据却得到 `RESOLVED`。

不要测试无权使用的仓库或服务。凭据一旦暴露，请直接在 Provider 侧撤销，而不是把它写入报告。
