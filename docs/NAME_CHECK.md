# RepoSuture 名称检查

检索日期：**2026-07-22 UTC**

本检查用于在项目从 PatchPilot 更名为 RepoSuture 前发现实质性的同名冲突。它是可复现的工程检索，不构成法律或商标审查。

## 查询与结果

| Registry / Index | 可复现查询 | 结果 |
|---|---|---|
| GitHub Repository | `GET https://api.github.com/search/repositories?q=RepoSuture%20in%3Aname&per_page=100` | `total_count=0`；没有忽略大小写后名称等于 `RepoSuture` 的仓库 |
| PyPI | `GET https://pypi.org/pypi/reposuture/json` | HTTP `404`；规范化 Distribution Name 不存在 |
| arXiv API | `GET https://export.arxiv.org/api/query?search_query=all%3A%22RepoSuture%22&start=0&max_results=10` | `opensearch:totalResults=0` |
| 通用精确名称检索 | `"RepoSuture" software engineering agent` 及 GitHub/PyPI/arXiv 精确变体 | 未发现同名软件工程 Agent；只出现一个无关诗歌中的小写子串 |

GitHub 查询使用公开 REST Search API 和 `Accept: application/vnd.github+json`；PyPI 与 arXiv 使用公开只读 Endpoint。请求未携带凭据。

## 结论

检索日期内未在要求来源中发现实质性同名冲突，因此可以采用 RepoSuture。无关子串和普通文本不视为冲突。最终标识：

- 展示名称：`RepoSuture`
- GitHub 仓库：`whytomato/RepoSuture`
- Python Distribution 与 Package：`reposuture`
- 主 CLI：`reposuture`
