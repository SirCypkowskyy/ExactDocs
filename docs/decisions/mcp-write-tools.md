# Adding libraries over MCP

!!! abstract "TL;DR"
    - `/mcp` gets two write tools, `add_docs` and `import_status`, built on the existing ingestion
      driving ports. There is no new ingestion path.
    - Whoever may create libraries (instance admins and `[library_creation].groups`, #110) sees
      them. Everyone else does not: FastMCP's component-level `auth=` hides them.
    - Nothing over MCP removes libraries or versions.
    - Sources are `https://` only, from an allowlist of hosts, and never a private or metadata
      address.

| | |
|---|---|
| **Status** | Accepted, implemented in #613 |
| **Scope** | The MCP server (`bootstrap/mcp.py`, a new `ingestion/adapters/driving/mcp.py`) |
| **Issue** | #613 |
| **Decided by** | The owner decided who gets the tools and how they are hidden; the rest was proposed in #613 |

## Context

Every tool on `/mcp` is read-only. An agent that finds a library missing can't add it, so the
person leaves the agent for the web UI or `POST /api/v1/libraries`, waits for the import and comes
back, although the agent already knows the repository and the version it needs.

## Decision

**Two tools.** `add_docs(source, ref?, paths?)` creates a library, adds a version or syncs an
existing library, depending on what already exists. `import_status(job_id?)` reports one job, or
the caller's latest five. Both call the driving ports the REST adapter uses (`add_library`,
`add_version`, `sync_library`, `get_job`, `list_jobs`, `list_library_jobs`) under the same access checks, and
answer in a line or two per job. Imports are asynchronous, so the agent needs `import_status` to
know when to search; without it the agent would poll `list_libraries` and get a large payload.

**Who.** The tools follow the library-creation permission: instance admins plus the members of
`[library_creation].groups` (#110), through the same `IdentityAccessPolicy.can_create` check as
REST. They are not limited to admins. A token restricted to some libraries does not get them, and
stdio MCP never registers them.

**Hidden, not refused.** Both tools carry FastMCP's component-level `auth=` (documented for FastMCP v4.2.3 and present in the pinned v4.1.6,
`docs/servers/authorization.mdx`, "Component-Level Authorization"). For a caller without the
permission they are missing from `tools/list` and a direct call answers not-found, so that agent
never spends tokens on their schemas. If the pinned FastMCP turns out not to hide them, the
fallback is to list them and refuse the call with a tool error that says the caller may not add
libraries.

**No removal.** Deleting libraries or versions stays in the web UI and REST. It is destructive,
and it is the action a prompt injection in fetched docs would aim for.

**Sources.** Only `https://` URLs (or `owner/repo` for GitHub, or an existing library), never
`file://`, `ssh://`, `http://` or a URL with credentials. The host must be in
`EXACTDOCS_MCP_IMPORT_HOSTS` (default `github.com,gitlab.com,codeberg.org,bitbucket.org`), and
the addresses the name resolves to must not be loopback, private, link-local or the metadata
address. They are resolved and checked when the call is made, right before git first contacts the
host; the import job and later syncs fetch from the same host without a new check, so the
allowlist is what keeps those fetches on public forges (git also follows a redirect on its first
request, as for every import). No credential argument: private repositories are added in the web UI.

## Consequences

- An agent can fill a gap in the index without the person leaving it, and the import is recorded
  as theirs (`created_by`, the `library_created` access-log entry), as on the REST path.
- Cancelling jobs, editing library settings and resolving package names (`npm:`, `pypi:`) stay
  out of MCP. Each would be its own issue.
