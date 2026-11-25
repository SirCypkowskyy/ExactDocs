# E2 Accounts & tokens

!!! abstract "TL;DR"
    - **Goal:** A network-exposed instance is never open: a first-run admin, sessions and API tokens.
    - **Stories:** AUTH-01, AUTH-02
    - **Milestones:** MVP-1
    - **Issues, in build order:** E2-01, E2-02, E2-03
    - **Status:** the epic ([#2](https://github.com/SirCypkowskyy/ExactDocs/issues/2)) is closed; GitHub holds the current issue bodies.

## E2-01 · feat: a fresh instance only offers setup until the first admin account exists

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / identity | AUTH-01 | E1-01, E6-01 | M |

**Context.** Even a single-user instance on a network port must not be open to anyone. Until an
admin exists, the only thing a visitor may do is create that admin, in the UI or locally with
`exactdocs admin create`.

**Expected behavior**

```gherkin
Scenario: Everything but setup is refused before the first account exists
  Given a fresh instance
  When a client lists the libraries over the REST API
  Then the request is refused with "setup_required"

Scenario: Creating the admin from the command line
  Given a fresh instance
  When the operator runs "exactdocs admin create" with a username and password
  Then the admin can sign in
  And the setup endpoint is no longer available
```

**Criteria of success**

- [ ] new `identity` domain (standard module set) with `Account` (username, password hash, `role` column: `admin` for the first account); passwords hashed with a memory-hard KDF (argon2id), never stored or logged in clear
- [ ] `POST /api/v1/setup` works only while no account exists (then `409`); every other `/api/v1` route answers `403 setup_required` until then (`GET /api/v1/session`, `/api/health`, `openapi.json` and SPA assets excepted)
- [ ] `exactdocs admin create` (local command: opens the database directly, prompts for the password)
- [ ] unit tests (identity use cases), behave `setup.feature`, integration test for the guard
- [ ] docs: README *Quick start* matches the flow; `docs/architecture.md` lists the `identity` domain; remove `auth_mode` from `settings.py` and `EXACTDOCS_AUTH_MODE`/OIDC from the README and compose example (OIDC returns with E12-03)

**Notes.** One admin only (Decisions *Users and tenancy*); the `role` column keeps room for more
local users (ACL-06, E12-13) and roles (Next). The setup page itself is E8-01.

## E2-02 · feat: the admin signs in to the web UI with an expiring, HttpOnly session

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / identity | AUTH-01 | E2-01 | M |

**Context.** The browser UI needs a login that cannot be stolen by script or replayed cross-site,
and a way back in when the password is lost, without opening any remote recovery path.

**Expected behavior**

```gherkin
Scenario: Signing in and out
  Given an admin account exists
  When the admin signs in with the right password
  Then the UI session is active
  When the admin signs out
  Then the libraries are no longer reachable with that session

Scenario: A session cookie never authenticates MCP
  Given the admin is signed in to the UI
  When the browser calls the MCP endpoint with the session cookie only
  Then the call is refused as unauthenticated
```

**Criteria of success**

- [ ] `POST /api/v1/session` (login), `DELETE /api/v1/session` (logout), `GET /api/v1/session` (current state: `setup_required`, signed out, or signed in as whom; used by the UI, E8-01); server-side sessions with idle expiry after 7 days and absolute expiry after 30 days
- [ ] cookie is HttpOnly, SameSite=Lax, `Secure` behind HTTPS; wrong password and unknown user give the same error
- [ ] state-changing requests keep the existing Origin check (403 for a foreign `Origin`); test for login and logout
- [ ] `/mcp` ignores cookies (integration test)
- [ ] `exactdocs admin reset-password` (local) sets a new password and ends all sessions
- [ ] behave `login.feature`; unit tests for expiry with the kernel clock

**Notes.** Decisions *Web UI auth*, *Host and origin checks*. Login rate limiting is out of scope
(done in #182: a shared sign-in throttle per address and username).

## E2-03 · feat: API tokens give agents, the CLI and REST clients access

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / identity, MCP tools | AUTH-02 | E2-02 | M |

**Context.** Agents (MCP over HTTP), the CLI and scripts cannot use a browser session; they need
revocable credentials that are never stored in a readable form.

**Expected behavior**

```gherkin
Scenario: A token works once created and stops working once revoked
  Given the admin created a token named "laptop"
  Then the token value is shown once
  And an MCP client with that token can list the libraries
  When the admin revokes "laptop"
  Then the same MCP client is refused

Scenario: An expired token is refused
  Given a token that expired yesterday
  When a REST client uses it
  Then the request is refused as unauthenticated
```

**Criteria of success**

- [ ] tokens: high-entropy, recognizable prefix, stored hashed, optional expiry, name, created and last-used time
- [ ] REST: `POST/GET/DELETE /api/v1/tokens`; the value is returned only by `POST`
- [ ] REST auth dependency accepts session cookie or `Authorization: Bearer`; every route requires one except: `POST /api/v1/setup`, `/api/v1/session` (login, logout, state), `/api/health`, `openapi.json` and the SPA assets (test lists the exemptions)
- [ ] MCP over HTTP uses a FastMCP `TokenVerifier` backed by the identity domain; the token acts as its user
- [ ] unit tests, behave `tokens.feature`, MCP integration test with FastMCP `Client`
- [ ] docs: README *Connect your agent*

**Notes.** Decisions *MCP auth*. In MVP-1 tokens are managed in the UI (E8-02); CLI
`token create|list|revoke` and `exactdocs login` (with its exempt `POST /api/v1/tokens/login`)
are MVP-2 (E6-03, E6-02);
stdio MCP needs no token (E7-07).
