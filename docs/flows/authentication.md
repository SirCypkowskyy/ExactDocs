# Authentication

!!! abstract "TL;DR"

    - A fresh instance answers `403 setup_required` until the first admin is created, once and
      atomically.
    - The browser signs in with a server-side session in an HttpOnly cookie; agents and scripts use
      `exd_...` API tokens. Only SHA-256 hashes of either are stored.
    - `/mcp` accepts only the bearer token and never reads the cookie.
    - `exactdocs serve --stdio` skips all of this and is read-only.

```mermaid
sequenceDiagram
    autonumber
    actor U as Admin (browser)
    participant H as App-wide checks
    participant G as SetupGuard
    participant ID as Identity
    actor A as Agent or script

    Note over H: every request: Host must be allowed (localhost + EXACTDOCS_ALLOWED_HOSTS),<br/>an unsafe request with a foreign Origin is 403
    U->>H: GET /api/v1/libraries (fresh instance)
    H->>G: allowed
    G-->>U: 403 setup_required (only setup, session state and openapi.json are open)
    U->>ID: POST /api/v1/setup (username, password 12 to 1024 chars)
    ID-->>U: 201, the first admin (argon2id hash), atomically, only once
    U->>ID: POST /api/v1/session
    ID-->>U: 201 + HttpOnly SameSite=Lax cookie, Path=/api (token stored as SHA-256)
    U->>ID: POST /api/v1/tokens (session cookie only)
    ID-->>U: exd_... shown once (only its SHA-256 is stored)
    U->>A: hand over the token
    A->>ID: REST: Authorization: Bearer exd_...
    ID-->>A: acts as the account (401 for unknown, expired or revoked)
    A->>ID: MCP /mcp: Authorization: Bearer exd_... (the cookie is never read)
    ID-->>A: acts as the account
    Note over U,ID: Sessions end after 7 days unused or 30 days in all,<br/>sign-out and exactdocs admin reset-password delete them server-side
```

## stdio

`exactdocs serve --stdio` skips all of this:

- it opens the database read-only and exposes the read-only tools only;
- its one write is AI spend, added to the shared ledger over a second connection that may write that
  table alone (#274).

Sessions, tokens and external sign-in are described in [Identity](../architecture/identity.md).
