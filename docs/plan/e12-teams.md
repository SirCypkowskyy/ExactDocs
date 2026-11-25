# E12 Teams & integrations

!!! abstract "TL;DR"
    - **Goal:** PostgreSQL, OIDC, local users, roles, sharing, audit, declarative sources, webhooks, MCP Apps.
    - **Stories:** TEAM-01 to TEAM-03, ACL-01 to ACL-06, MCP-08
    - **Milestones:** Next: Teams & integrations
    - **Issues, in build order:** E12-01 to E12-04, E12-13, E12-05 to E12-12
    - **Status:** the epic ([#12](https://github.com/SirCypkowskyy/ExactDocs/issues/12)) is closed; GitHub holds the current issue bodies.

All E12 issues: milestone **Next: Teams & integrations**, labels `type: feature`
`status: triage` and the area noted.

## E12-01 · feat: a shared instance runs on PostgreSQL with several server processes

**Stories** TEAM-01 · **Area** backend / catalog, CI · `area: backend` `area: infra` · **Depends on** MVP-1 · **Size** L

**Context.** The whole team should work on the same libraries.

```gherkin
Scenario: Two processes share one PostgreSQL database
  Given two ExactDocs processes use the same PostgreSQL database
  When a library is imported through the first
  Then the second serves it, and the import ran exactly once
```

- [ ] PostgreSQL adapters for every repository, run by the existing adapter contract tests in CI (ParadeDB image)
- [ ] job claiming safe across processes (`FOR UPDATE SKIP LOCKED`, or DBOS from E3-11)
- [ ] manual tags ordered across processes: a lock shared by the processes (e.g. a PostgreSQL advisory lock per library) around `TagArticle` and an import's activation, or the retrieval re-tag re-reads the catalog's tags inside its write; until then `serve` pins one worker (`TagLocks`, E4-06)
- [ ] migrations for both databases; docker-compose example in README verified in CI

## E12-02 · feat: the ranking suite passes on ParadeDB as on SQLite

**Stories** TEAM-01, SRCH-01, RET-01 (pgvector) · **Area** backend / retrieval · `area: backend` · **Depends on** E12-01, E5-04, E11-03 (pgvector part only) · **Size** M

```gherkin
Scenario: The same ranking on both engines
  When the ranking suite runs on ParadeDB
  Then every expected query ranks its section first, as on SQLite
```

- [ ] `pg_search` adapter of the search port with the same identifier column (E5-01)
- [ ] pgvector adapter of the `VectorIndex` port (E11-03); can land after the BM25 part if E11-03 is not merged yet

## E12-03 · feat: users sign in through OIDC with groups from the identity provider

**Stories** ACL-01 · **Area** backend / identity, web UI · `area: backend` `area: web` · **Depends on** E12-01 · **Size** L

```gherkin
Scenario: Groups follow the identity provider on every sign-in
  Given the IdP puts "alice" in group "payments"
  When "alice" signs in through OIDC
  Then she is a member of ExactDocs group "payments"
  And when the IdP removes her from it, her next sign-in removes her membership
```

- [ ] OIDC and local accounts coexist: OIDC sign-in is offered when OIDC is configured, local sign-in stays available (no `AUTH_MODE` switch); group claim mapping; the local admin keeps working as break-glass
- [ ] OIDC settings documented in the README and compose example; whether OIDC is offered follows "OIDC configured or not" (`EXACTDOCS_AUTH_MODE` stays removed, E2-01)
- [ ] tests against a mock OIDC provider

## E12-04 · feat: MCP clients connect with OAuth as well as API tokens

**Stories** ACL-01, Decisions *MCP auth* · **Area** MCP tools · `area: backend` · **Depends on** E12-03 · **Size** M

```gherkin
Scenario: A web host connects with OAuth
  When a web MCP host discovers the OAuth metadata and signs the user in
  Then it can call "list_libraries" as that user
  And API tokens keep working
```

- [ ] FastMCP `OIDCProxy` + token verifier via `MultiAuth`; `/.well-known/...` served at the root; host/origin allowlist still applies

## E12-13 · feat: operators create, disable and reset local user accounts

**Stories** ACL-06 · **Area** backend / identity, web UI · `area: backend` `area: web` · **Depends on** E2-02, E8-01 · **Size** M

**Context.** Not every team member signs in through OIDC; operators need local accounts beyond
the first admin, without opening self-signup.

```gherkin
Scenario: An operator creates a local user
  When the operator runs "exactdocs user create bob"
  Then "bob" can sign in with the password set at creation
  And there is no sign-up page

Scenario: A disabled user is locked out
  Given "bob" is signed in and has an API token
  When the operator disables "bob" in the UI
  Then bob's session and token are refused
```

- [ ] `user create|disable|reset-password` (local CLI commands, like `admin create`) and an operator-only users page in the UI (list, create, disable, reset password)
- [ ] uses the `role` column of `Account` (E2-01); disabling ends sessions and refuses tokens; reset ends sessions
- [ ] no self-signup route; unit, behave and vitest tests

## E12-05 · feat: library roles are enforced on every UI action, REST call and MCP tool

**Stories** ACL-02 · **Area** backend / identity, backend / catalog · `area: backend` · **Depends on** E12-03, E12-13 · **Size** L

**Context.** Docs belong to teams, not to whoever imported them.

```gherkin
Scenario: A viewer can read but not edit
  Given "bob" is a viewer of "/fixture/docs-repo"
  Then "bob" can search and read it in the UI and over MCP
  But changing its paths is refused
```

- [ ] roles viewer < contributor < admin < creator; grants to users and groups; effective role = highest
- [ ] an authorization check in every use case via an `AccessPolicy` driven port (identity bridge); test matrix role × action

## E12-06 · feat: owners share libraries and transfer ownership in the UI

**Stories** ACL-02 · **Area** web UI · `area: web` · **Depends on** E12-05 · **Size** M

```gherkin
Scenario: Transferring ownership
  When the creator transfers "/fixture/docs-repo" to "carol"
  Then "carol" is the creator and the previous owner becomes admin
```

- [ ] sharing dialog (users, groups, roles); only the creator removes admins and transfers ownership; vitest

## E12-07 · feat: operators control who may create libraries

**Stories** ACL-03 · **Area** backend / identity · `area: backend` · **Depends on** E12-05 · **Size** S

```gherkin
Scenario: Only permitted users create libraries
  Given only group "docs-admins" may create libraries
  When "bob" outside that group adds a library
  Then it is refused
```

- [ ] instance permission mapped from users or groups; the creator becomes owner

## E12-08 · feat: tokens act as their user, optionally narrowed, and hidden libraries stay invisible

**Stories** ACL-04 · **Area** backend / identity, MCP tools · `area: backend` · **Depends on** E12-05 · **Size** M

```gherkin
Scenario: No access looks like not found
  Given "bob" has no access to "/acme/secret"
  When bob's agent calls "query-docs" for "/acme/secret"
  Then the error is the same as for a library that does not exist
  And "/acme/secret" never appears in listings
```

- [ ] tokens scoped to their user and optionally to chosen libraries; listings, `resolve-library-id`, errors and caches filtered

## E12-09 · feat: access changes and deletions are logged

**Stories** ACL-05 · **Area** backend / identity · `area: backend` `area: web` · **Depends on** E12-05 · **Size** M

```gherkin
Scenario: A grant is recorded
  When "alice" grants "bob" the viewer role
  Then the library's audit log shows actor "alice", the grant and the time
```

- [ ] grants, revocations, deletions, ownership transfers recorded; visible to library admins and operators (REST + UI)

## E12-10 · feat: libraries are declared in `exactdocs.sources.yaml` and applied with a dry-run diff

**Stories** TEAM-02 · **Area** backend / ingestion · `area: backend` · **Depends on** E9-05, E4-05, E6-02 · **Size** L

```gherkin
Scenario: Apply is idempotent
  Given a sources file declaring "/fixture/docs-repo" with tag pattern "v*"
  When the operator runs "exactdocs sources plan"
  Then the diff is printed and nothing changes
  When the operator runs "apply" twice
  Then the second apply reports no changes
```

- [ ] schema (URL, ID, ref or tag pattern, paths, tags, chunking) with JSON Schema; plan/apply via REST

## E12-11 · feat: a push to the docs repository triggers a sync

**Stories** TEAM-03 · **Area** backend / ingestion · `area: backend` · **Depends on** E9-01 · **Size** M

```gherkin
Scenario: A signed webhook starts a sync
  When GitHub sends a signed push webhook for the library's branch
  Then a sync starts within 30 seconds
  And unsigned or unknown webhooks are rejected
```

- [ ] per-library webhook secret; GitHub, GitLab and Bitbucket signature formats; deduplicated deliveries

## E12-12 · feat: MCP hosts that support Apps render articles and results as UI

**Stories** MCP-08 · **Area** MCP tools · `area: backend` · **Depends on** E12-04 · **Size** L

```gherkin
Scenario: App tools add UI without changing existing tools
  When a host that supports MCP Apps calls "view_article"
  Then it renders the article with headings and code
  And hosts without Apps support get a text fallback
  And "read_article" is unchanged
```

- [ ] `view_article`, `view_search` with `@mcp.tool(app=True)`, `fastmcp[apps]` with a pinned `prefab-ui`; explicit text fallback
