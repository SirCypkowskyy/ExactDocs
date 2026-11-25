# E6 REST API & CLI

!!! abstract "TL;DR"
    - **Goal:** `/api/v1` and OpenAPI as the single API, with the CLI as its client.
    - **Stories:** CLI-01, LIB-08, AUTH-02, C7-03, C7-04
    - **Milestones:** MVP-1, MVP-2
    - **Issues, in build order:** E6-01; MVP-2: E6-02 to E6-05
    - **Status:** the epic ([#6](https://github.com/SirCypkowskyy/ExactDocs/issues/6)) is closed; GitHub holds the current issue bodies.

## E6 · MVP-1

### E6-01 · feat: the REST API is versioned under `/api/v1` with a published OpenAPI description

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: chore`<br/>`status: ready`<br/>`area: backend` | backend / catalog, docs | Decisions *REST API*, *Refs containing `/`* | - | S |

**Context.** The UI and the CLI must behave identically and work against remote instances; that
is only possible if both use one documented API with stable conventions from the first endpoint.

**Expected behavior**

```gherkin
Scenario: The API describes itself
  When a client fetches the OpenAPI description
  Then every "/api/v1" operation has a stable operation ID and documented error responses

Scenario: Errors have one shape
  When a client requests an unknown library
  Then the response status is 404 with error code "not_found" and a message
```

**Criteria of success**

- [ ] `/api/v1/openapi.json` published; operation IDs stable (`<tag>-<name>`), tags per domain
- [ ] one error envelope (`error`, `detail`) for every `DomainError`; validation errors mapped to `422` with field details
- [ ] list endpoints share `limit` + opaque `cursor` pagination
- [ ] route rule: `/libraries/{owner}/{repo}/...`, a ref only as the last path segment (`{ref:path}`) or as a query parameter; a route that needs a ref and an article path takes `?ref=` and `?path=`
- [ ] web: typed client generated from the OpenAPI file (`openapi-typescript`) in `web/src/shared/lib`, with a CI check that it is up to date
- [ ] integration tests for the envelope and pagination helper

## E6 · MVP-2

### E6-02 · feat: the CLI is a client of the REST API and `exactdocs login` stores its credentials

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / identity | CLI-01, AUTH-02 (login) | E2-03, E6-01 | M |

**Context.** Users script their setup and run the CLI against remote instances; the CLI must not
reach into the database behind the server's back.

**Expected behavior**

```gherkin
Scenario: Logging in stores a named token
  Given a running instance with an admin account
  When the user runs "exactdocs login <url>" with the admin's username and password
  Then the CLI config holds the server URL and a new token named after the machine
  And "exactdocs libraries" works without further flags

Scenario: An existing token can be used instead
  When the user runs "exactdocs login <url> --token <token>"
  Then no new token is created
```

**Criteria of success**

- [ ] REST `POST /api/v1/tokens/login` (username, password, token name) issues a token; the auth-exemption test (E2-03) includes `POST /api/v1/tokens/login`
- [ ] config resolution: flags > `EXACTDOCS_URL`/`EXACTDOCS_TOKEN` env > config file in the platform config dir (mode 0600)
- [ ] shared CLI HTTP client (`httpx2`) with error mapping to non-zero exit codes and readable messages
- [ ] local commands stay local: `serve`, `admin create`, `admin reset-password`; an architecture/unit test lists every command and asserts the rest use only the REST client
- [ ] tests against an in-process server (ASGI transport)
- [ ] docs: README *Quick start*

### E6-03 · feat: users add, list, sync and remove libraries and manage tokens from the CLI

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion, backend / identity | LIB-08, LIB-11 (CLI), AUTH-02 (CLI), CLI-01, SYNC-01 (CLI) | E6-02, E3-07, E3-04, E9-01, E9-03 | M |

**Context.** A CLI action and the same UI action must produce identical results, so scripted
setups and the UI never drift.

**Expected behavior**

```gherkin
Scenario: Adding a library from the CLI
  When the user runs "exactdocs add <fixture-url> --id /fixture/docs-repo --ref v1.4.0 --path docs/"
  Then "exactdocs libraries" lists "/fixture/docs-repo" with version "v1.4.0"
  And the REST API returns the same library as for a library added in the UI
```

**Criteria of success**

- [ ] `exactdocs add <git-url> [--id] [--ref] [--path ...] [--exclude ...] [--token|--ssh-key] [--wait]`
- [ ] `exactdocs libraries`, `exactdocs version add <library> <ref>`, `exactdocs token create|list|revoke`
- [ ] `exactdocs sync <library> [--wait]` (E9-01's REST route) and `exactdocs remove <library>[/<ref>]` (E9-03's `DELETE` routes)
- [ ] `--json` output for scripting; human tables otherwise
- [ ] parity test: the same command via CLI and via the REST calls the UI makes yields equal stored libraries
- [ ] docs: README CLI examples verified by a test (doctest-style or behave)

**Notes.** `--token|--ssh-key` need the credential handling of E3-04.

### E6-04 · feat: CLI commands mirror `ctx7`

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / retrieval | C7-03 | E6-05 | S |

**Context.** Users want to check from the terminal what their agent would get.

```gherkin
Scenario: The CLI shows what the agent gets
  When the user runs "exactdocs docs /fixture/docs-repo retry policy"
  Then the output equals the text of "query-docs" for the same arguments
```

- [ ] `exactdocs library <name> <query>` and `exactdocs docs <libraryId> <query>` call the C7-04 endpoints
- [ ] equality test against the MCP tool results

### E6-05 · feat: integrations get context7's library search and docs over REST

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / retrieval | C7-04 | E7-05, E7-06 | S |

**Context.** Not every integration speaks MCP.

```gherkin
Scenario: REST returns the same docs as MCP
  When a client with an API token calls the docs endpoint for "/fixture/docs-repo/v1.4.0" and "retry policy"
  Then the payload equals the "query-docs" payload
```

- [ ] `GET /api/v1/c7/search?libraryName=&query=` and `GET /api/v1/c7/docs?libraryId=&query=&language=`, documented in OpenAPI
- [ ] same use cases and tokens as MCP; equality tests
