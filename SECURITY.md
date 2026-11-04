# Security policy

Please report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/SirCypkowskyy/ExactDocs/security/advisories/new),
not in public issues. Include the affected version (`exactdocs --version` or the image tag), the
deployment mode, and steps to reproduce.

Only the latest minor release receives security fixes while the project is pre-1.0.

## Known, accepted exposure

`POST /api/v1/repositories/check`, `GET /api/v1/repositories/refs` and `POST /api/v1/libraries`
run `git ls-remote` against a URL the caller supplies (https, http, ssh and `file://`), by design:
libraries come from any git host, and the smoke test and the fixture repository use `file://`.
ExactDocs is a self-hosted tool for its admin, and only a signed-in admin (session or API token)
can call these routes, so there is **no private-address or `file://` policy**: such a caller can
make the server probe hosts and ports it can reach (the distinct "unreachable", "not a
repository" and "authentication required" answers act as a scan oracle), and `refs` returns the
branch and tag names and commit SHAs of any git repository the server can read, including one on
a local path. `refs` lists at most 1000 branches and 1000 tags. Hardening of `git` itself (no
config, no credentials, no prompts, timeout, output cap, at most four processes) is in
`GitCli`. Do not give API tokens to people you would not trust with the server's network.
