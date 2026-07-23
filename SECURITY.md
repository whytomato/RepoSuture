# Security Policy

RepoSuture is a portfolio and research engineering project. It is not presented as a
production security boundary. Reports about command execution, path escape, credential
exposure, Patch-policy bypass, worktree isolation, rollback, or artifact-integrity failures
are nevertheless taken seriously.

## Reporting a security issue

Use the [public repository issue tracker](https://github.com/whytomato/RepoSuture/issues)
to request security coordination. In the initial public issue, include only a short impact
summary and the affected RepoSuture version or commit. Do not publish exploit details,
private repository content, API keys, authorization headers, credentials, sensitive traces,
raw provider payloads, or other secrets. The maintainer can use the issue to arrange an
appropriate follow-up channel before sensitive reproduction details are shared.

For non-sensitive hardening defects whose complete reproduction is safe to publish, a normal
GitHub issue is appropriate. Please state the operating system, Python/Java versions, exact
RepoSuture commit, and whether the source tree was clean, while redacting user-specific paths
and all credentials.

## Scope

Especially useful reports include:

- execution outside RepoSuture's fixed argument-array subprocess policy;
- repository, worktree, symlink, junction, or artifact path containment escapes;
- API key, authorization header, private source, raw Patch, or hidden-reasoning disclosure;
- modification of tests, build files, Maven Wrapper files, CI, or disallowed paths;
- partial Patch application, failed rollback, or mutation of the original repository;
- report, trace, trajectory, final-Patch, size, or SHA-256 integrity inconsistencies;
- a `RESOLVED` result not supported by real Git, Maven, and JUnit evidence.

Do not test against repositories or services you do not own or have explicit permission to
use. Revoke exposed credentials with their provider rather than including them in a report.
