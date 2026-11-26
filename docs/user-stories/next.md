# Next and later: agents, teams, operations, more sources

!!! abstract "TL;DR"
    - MCP-08: rendered UI in chat through FastMCP Apps tools, with the existing tools unchanged.
    - ACL-01 to ACL-06: sign-in through OIDC, OAuth2, ADFS or GitHub, library roles (viewer,
      contributor, admin, creator), creation rights, scoped tokens, an audit log and local accounts.
    - TEAM-01 to TEAM-03: a shared PostgreSQL instance, libraries declared in
      `exactdocs.sources.yaml`, and push webhooks that start a sync within 30 seconds.
    - OPS-01 to OPS-02: optional OpenTelemetry and Prometheus export, health endpoints, backup and
      restore.
    - Later: `llms.txt`, website crawling, package registries, index snapshots and more formats.

## Next: richer agent experience

- **[MCP-08]** As a user chatting in Claude or ChatGPT, I want the MCP server to return rendered UI ([FastMCP Apps](https://gofastmcp.com/apps/overview) with Prefab components), e.g. an article with its headings and code, or a result list with links, because reading docs inside the chat is better than reading raw Markdown.
    - Acceptance:
        - separate app tools (`view_article`, `view_search`, `@mcp.tool(app=True)`, `fastmcp[apps]` with a pinned `prefab-ui`) render in hosts that support MCP Apps
        - the existing tools are unchanged, so other hosts keep plain results
        - app tools return an explicit text fallback
        - depends on ACL-01, because web hosts connect with OAuth.

## Next: teams, sharing and roles

- **[ACL-01]** As an operator, I want sign-in through OIDC, OAuth2, ADFS or GitHub / GitHub Enterprise (next to local accounts), with groups taken from the identity provider or from GitHub organization and team membership, because access should follow our existing identity setup.
    - Acceptance:
        - users sign in via OIDC (ADFS included), generic OAuth2 or GitHub / GitHub Enterprise (Server or `*.ghe.com`)
        - IdP group claims, or GitHub organization and team memberships (`github:<org>/<team>`), map to ExactDocs groups on every sign-in and are re-checked at least hourly (OIDC/OAuth2 through a refresh token; without one the session ends after a grace period), so a removed member loses access without anyone touching ExactDocs
        - a GitHub organization that has not approved the app, or needs SAML SSO authorization, is reported as such
        - MCP accepts both OAuth (FastMCP `OIDCProxy`) and API tokens through `MultiAuth`.
- **[ACL-02]** As a library owner, I want to share a library with users and groups in a role, because docs belong to teams, not to whoever imported them:
    - **viewer**: sees the library in the UI and in MCP (search, browse, read);
    - **contributor**: viewer + edits it (tags, paths, chunking, re-sync, versions);
    - **admin**: contributor + deletes it and manages access (except the owner);
    - **creator**: the single owner (whoever created it); admin + removes admins and transfers ownership.
    - Acceptance:
        - viewer, contributor and admin can be granted to users and groups
        - the effective role is the highest granted
        - every UI action, REST call and MCP tool checks it.
- **[ACL-03]** As an operator, I want to control who may create libraries (users or IdP groups), because not everyone on a shared instance should import repositories.
    - Acceptance:
        - an instance-level "can create libraries" permission is mapped from users or groups
        - the creator of a library becomes its owner.
- **[ACL-04]** As a user, I want my tokens to see exactly the libraries I may view, because my agent should have my access, not more.
    - Acceptance:
        - tokens act as their user (optionally narrowed to chosen libraries)
        - a library without view access is invisible, not even its name appears in listings or errors (MCP masks unexpected errors; only domain errors pass, and "not found" and "no access" look the same).
- **[ACL-05]** As a library owner or operator, I want a log of access changes and deletions, because we need to know who shared or deleted what.
    - Acceptance: grants, revocations, deletions and ownership transfers are recorded with actor and time and visible to library admins and operators.
- **[ACL-06]** As an operator, I want to create, disable and reset local user accounts in the UI and with `exactdocs user create|disable|reset-password`, because not every team member signs in through OIDC; no self-signup.
    - Acceptance:
        - only an operator creates local accounts (there is no sign-up page)
        - a disabled user's sessions and tokens are refused
        - a password reset ends the user's sessions.
- **[TEAM-01]** As an operator, I want a shared instance on PostgreSQL, because the whole team should work on the same libraries.
    - Acceptance:
        - `EXACTDOCS_DATABASE_URL=postgresql+psycopg://…` (PostgreSQL with ParadeDB `pg_search`, e.g. the `paradedb/paradedb` image, or Supabase, where search falls back to PostgreSQL full-text search) works with all MVP features, and the search ranking suite passes on it as on SQLite
        - several server processes can run against one database.
- **[TEAM-02]** As an operator, I want to declare libraries in an `exactdocs.sources.yaml` kept in our own repo (URL, ID, ref or tag pattern, paths, tags, chunking) and apply it with a dry-run diff, because the set of imported docs should go through code review.
    - Acceptance:
        - `exactdocs sources plan` prints the diff and changes nothing
        - `apply` makes the instance match
        - a second `apply` reports no changes.
- **[TEAM-03]** As a user, I want a push to the docs repository (webhook from GitHub/Bitbucket/GitLab) to trigger a sync, because teammates should read merged docs, not last night's.
    - Acceptance:
        - a signed webhook for the library's repo and branch starts a sync within 30 seconds
        - unsigned or unknown webhooks are rejected.

## Next: operations

- **[OPS-01]** As an operator, I want an optional OpenTelemetry export (OTLP to a collector) and a Prometheus scrape endpoint for metrics, because I monitor ExactDocs with the same stack as everything else.
    - Acceptance:
        - off by default
        - when on, it exports request, search (per retrieval mode and stage), import, sync and LLM-usage metrics and traces
        - query text is excluded unless explicitly enabled
        - implemented as in the Telemetry decision (OpenTelemetry SDK, FastAPI built-in OpenTelemetry, pydantic-ai [instrumentation](https://pydantic.dev/docs/ai/capabilities/instrumentation/) with `include_content=False`, one span per tool call nested in `run_code`)
        - health checks are excluded from request traces.
- **[OPS-02]** As an operator, I want health and readiness endpoints and a backup/restore command, because the instance becomes something the team depends on.
    - Acceptance:
        - `/healthz` reports the process is up and `/readyz` that the database is reachable
        - `exactdocs backup` / `restore` round-trips libraries, versions, settings, accounts and tokens.

## Later: beyond Markdown in git

These are good ideas that do not belong to the main loop yet.

| Idea | Why later |
|---|---|
| Import from `llms.txt` / `llms-full.txt` | A second source type; the git importer comes first |
| Crawl documentation websites | Needs a crawler, rate limiting and HTML-to-Markdown conversion |
| Resolve library docs from package registries (PyPI, npm) and lockfiles | Requires a curated registry that maps packages to repos and paths |
| Prebuilt, signed index snapshots and a public registry of popular libraries | Depends on the registry and a stable index format |
| Backup LLM ([model fallback](https://pydantic.dev/docs/ai/capabilities/model-fallback/)) and a remote Monty sandbox worker for multi-process setups | Only matters once agentic mode runs in production at scale |
| Pattern-based prompt-injection flags on imported docs ([defender](https://pydantic.dev/docs/ai/harness/prompt-injection-defender/), no ML model) | Report-only nice-to-have |
| Other formats: AsciiDoc, Jupyter notebooks (reStructuredText: IMP-06) | Markdown and reStructuredText cover most repositories |
