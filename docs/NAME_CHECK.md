# RepoSuture name check

Search date: **2026-07-22 UTC**

This preflight checks for a material exact-name collision before the public project is
renamed from PatchPilot to RepoSuture. It is a reproducible engineering search, not legal
or trademark clearance.

## Queries and results

| Registry / index | Reproducible query | Result |
|---|---|---|
| GitHub repositories | `GET https://api.github.com/search/repositories?q=RepoSuture%20in%3Aname&per_page=100` | `total_count=0`; no repository whose name equals `RepoSuture` case-insensitively. |
| PyPI | `GET https://pypi.org/pypi/reposuture/json` | HTTP `404`; no published project at the exact normalized distribution name. |
| arXiv API | `GET https://export.arxiv.org/api/query?search_query=all%3A%22RepoSuture%22&start=0&max_results=10` | `opensearch:totalResults=0`. |
| General exact-name search | `"RepoSuture" software engineering agent` and exact GitHub/PyPI/arXiv variants | No exact-name software-engineering Agent result; one unrelated lowercase substring occurred in a poem. |

The GitHub query used the public REST Search API with `Accept:
application/vnd.github+json`; the PyPI and arXiv checks used their public read-only
endpoints. No credentials were sent in these requests.

## Decision

No material exact-name collision was found in the required sources on the search date, so
the RepoSuture rebrand may proceed. Substring matches and unrelated prose were not treated
as collisions. The intended identifiers are:

- display name: `RepoSuture`;
- GitHub repository: `whytomato/RepoSuture`;
- Python distribution and package: `reposuture`;
- primary CLI command: `reposuture`.
