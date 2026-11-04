# Security policy

Please report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/SirCypkowskyy/ExactDocs/security/advisories/new),
not in public issues. Include the affected version (`exactdocs --version` or the image tag), the
deployment mode, and steps to reproduce.

Only the latest minor release receives security fixes while the project is pre-1.0.

## Known, accepted exposure

`POST /api/v1/repositories/check` runs `git ls-remote` against a URL the caller supplies (https,
http, ssh and `file://`), by design: libraries come from any git host, and the smoke test uses
`file://`. Until authentication guards `/api/v1` (E2-03), anyone who can reach an instance that
finished setup can use it to probe hosts and ports reachable from the server (the distinct
"unreachable", "not a repository" and "authentication required" answers act as a scan oracle) and
to learn whether a git repository exists at a local path. Nothing from the remote is returned
except a validated branch name. Do not expose an instance to untrusted networks before then.
