# RepoSuture 工程规则

- 禁止使用 `shell=True`。
- 每个子进程都必须使用参数数组、显式 `cwd` 和超时，并返回结构化结果。
- 不得修改用户的原始仓库；所有变更必须发生在隔离 Git worktree 中。
- 每条路径在解析 symlink 后仍必须位于允许目录内。
- 真实测试结果是成功或失败的唯一依据。
- 对测试、构建文件、Maven Wrapper 或 CI 配置的任何修改都必须分类并报告。
- 修改代码后运行 `python -m pytest -q`、`python -m ruff check .` 和 `python -m mypy src`。
- 不得声称或伪造未实际执行的测试结果。
- 不添加当前范围不需要的框架或抽象。
- 确定性验证层必须保持无 LLM、无 Agent Framework、无 MCP、无 Vector Database、无 Web UI、无 LSP、无 EvoMaster、无 Docker。
- Agent Runtime 必须保持 Provider 无关；模型文字不能产生 `RESOLVED`，也不能绕过确定性验证。

## Agent 工具约定

### 工作项跟踪

工作项以本地 Markdown 形式保存在 `.scratch/`。参见
`docs/agents/issue-tracker.md`。

### 分类标签

使用五个默认本地 Triage Role。参见
`docs/agents/triage-labels.md`。

### 领域文档

本仓库采用单 Context。参见 `docs/agents/domain.md`。
