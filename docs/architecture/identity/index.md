# Identity: accounts and the setup guard

!!! abstract "TL;DR"

    - `identity` owns accounts, web sessions, API tokens, external sign-in links and library roles.
    - Passwords are hashed with argon2id. One use case checks every password, behind a throttle per
      client address and per username.
    - Until the first admin exists, `SetupGuard` answers `403 setup_required` for everything under
      `/api/v1`. There is no self-signup.
    - Roles per library: `viewer < contributor < admin < creator`. Operators are `creator` of every
      library. No caller means the instance's own work, which no role limits.

## Pages

| Page | What it covers |
|---|---|
| [External sign-in (OIDC)](oidc.md) | providers in settings, sign-in attempts, linking identities, groups and revalidation |
| [Library roles](library-roles.md) | viewer, contributor, admin and creator, groups, grants, transfers, the access log |
| [Role rules](role-rules.md) | provider groups, role values, GitHub organizations and teams mapped to roles; private libraries |

## Accounts and passwords

`identity` owns accounts (`identity_accounts`: username, password hash, `role`, created time). The
password hash is NULL for an account of an identity provider (see
[External sign-in](oidc.md)).

Passwords are hashed by the `PasswordHasher` driven port. Its adapter is **argon2id**:

- `argon2-cffi`, RFC 9106 low-memory profile: 64 MiB, 3 passes;
- run in a thread, with `verify` constant-time;
- at most 4 at a time. More calls queue; a dropped request keeps its slot until its thread is done.

The use cases take the password as a `SecretStr`. An unknown username costs one hash like a real
check, and wrong password and unknown user raise the same error.

## The sign-in throttle

`AuthenticateUseCase` is the one place a password is checked, so the session sign-in and the CLI's
token login share its throttle.

- **What is counted.** Attempts are counted per client address (IPv6 per /64) and per username in
  the `FailedSignInLog` driven port. `FailedSignIns` in `models.py` holds the free count and the
  doubling wait.
- **Check and count in one step.** `FailedSignInLog.charge` checks the wait and counts the attempt
  in one atomic step, before the hash, so concurrent attempts cannot all pass the check.
- **Refused attempts.** An attempt that must wait raises `SignInThrottledError` (kernel
  `RateLimitedError`, 429 with `Retry-After`) without a hash and without being counted.
- **A right password**:
    - refunds its attempt on the address, putting back the earlier `last_at` when no later attempt
      came, so the wait is not restarted;
    - clears the username's count;
    - is remembered as a known (username, address) pair for 30 days. From a known address, the
      username's count does not apply.

### Where the counts live

| Database | Adapter |
|---|---|
| SQLite (one process) | in-process memory, bounded to 10,000 counts and 10,000 pairs; evicts counts that hold no one back first |
| PostgreSQL (several processes serve one instance, TEAM-01) | `SqliteFailedSignInLog`: `identity_failed_sign_ins`, `identity_known_sign_ins`[^empty] |

[^empty]: ../These tables exist but stay empty on SQLite. The SQL is portable and the contract tests
    also run it on SQLite.

On PostgreSQL:

- Each read-then-write is one transaction that first takes a transaction-level advisory lock per key
  (`_SIGN_IN_LOCKS`, all in one statement ordered by lock id), so `charge` stays atomic across
  processes without taking the instance's write turn.
- Before it takes a connection, an attempt waits in the process: an `asyncio.Lock` per key, then one
  of `MAX_CONCURRENT_SIGN_IN_TURNS` slots. A flood on one username holds one pooled connection, not
  the pool.
- Each wait lasts at most `SIGN_IN_TURN_TIMEOUT` (in the process, then as `lock_timeout`). A
  `charge` that runs out fails closed (refused, uncounted), and a refund, reset or remembered sign-in
  is skipped.
- Old rows are pruned on write, with no background job, skipping rows another transaction has locked
  (`SKIP LOCKED`):
    - a charge deletes counts quiet for `FORGET_FAILURES_AFTER`;
    - a remembered sign-in deletes those older than `REMEMBER_SIGN_INS_FOR`.

## Creating and disabling accounts

- **The first admin.** `AccountRepository.add_first` stores an account only while the table is
  empty, in one atomic statement under `BEGIN IMMEDIATE`. Two concurrent setups (or
  `exactdocs admin create` next to the running server) can never create two admins.
- **Further accounts** (ACL-06) are created only by an operator: `CreateUser` behind
  `POST /api/v1/users` (session of an `admin`, else 403 `forbidden`) or `exactdocs user create`
  (local). There is no self-signup route.
- `AccountRepository.add` relies on the unique `username` column, so a race for one name stores one
  account.
- **`Role`** is `admin` (an operator: manages accounts, and holds the `creator` role on every
  library) or `user`. Library roles have [their own page](library-roles.md).
- **A disabled account** (`identity_accounts.disabled_at`) is refused:
    - at sign-in, after the password check, with the same `invalid_credentials`, so the answer
      reveals nothing;
    - by `IdentifyCaller` and by `IdentifyToken`.
- Disabling also deletes its sessions and tokens. Enabling deletes them again first: one stored
  while disabled raced the disable and must not come back.
- `set_disabled_at` checks for another enabled admin and disables in one `begin_immediate`
  transaction, so the last one can never be disabled, even by two concurrent requests.
- New usernames may not hold `@address:`, the separator of the throttle's remembered-sign-in keys
  (`known_sign_ins_prefix`), so one account's keys never prefix another's.

## The setup guard

`bootstrap/rest.py:SetupGuard` answers `403 setup_required` for everything under `/api/v1` until an
account exists (default deny), and stops asking the database once one does. The exemptions are
`POST /setup`, `GET /session` and `openapi.json`.

## Sessions

`POST /api/v1/session` starts a server-side session (`identity_sessions`).

- **The token.** A 256-bit random token goes to the browser in an HttpOnly, SameSite=Lax cookie
  (`Path=/api`, `Secure` over HTTPS). Only its SHA-256 is stored, so a leaked database holds no
  usable token.
- **Lifetime.** A session ends after 7 days without use or 30 days in all
  (`models.IDLE_TIMEOUT`/`ABSOLUTE_TIMEOUT`, checked against the kernel `Clock`). Using it writes
  `last_used_at` at most once an hour.
- **Last activity.** The account's own `last_active_at` (the users page, #515) is kept to the hour.
  The request that reads the account anyway moves it forward (a sign-in, a session, an API token, a
  provider's ID token, Cloudflare Access), only when the hour changed: at most one write per account
  and hour.
- **Signing out** deletes the row, so a copied cookie dies too.
- **A password reset** (`exactdocs admin|user reset-password`, or `PUT /api/v1/users/{id}/password`
  by an operator):
    1. changes the hash first;
    2. deletes all the account's sessions;
    3. drops the username's throttle count (`FailedSignInLog.forget`);
    4. drops every address remembered for the username (`FailedSignInLog.forget_remembered`, in each
       key's turn, a bounded batch of keys per transaction; the CLI has no client address, so none
       is kept).

    Steps 3 and 4 reach the servers only on PostgreSQL, where the log is shared. A busy or failing
    log only makes the command warn, as the reset is already done.
- **CSRF:** SameSite=Lax plus the app-wide `OriginCheck` (a foreign `Origin` on an unsafe request
  is 403).

### Who is the caller

- "Who is the caller" is one dependency, `identity.adapters.driving.http.build_current_caller`,
  applied to the whole protected router in `bootstrap/http.py`. New domain routers go there, and the
  open ones are pinned by a test.
- It accepts a bearer API token or the session cookie. Any `Authorization` header is judged on its
  own, never rescued by a cookie.
- `/mcp` never reads the cookie. It is guarded by `identity.adapters.driving.mcp.ApiTokenVerifier`
  (a FastMCP `TokenVerifier` over the `IdentifyToken` port), so the token acts as its account.
- **Tokens** (`ApiToken`, `identity_api_tokens`) are `exd_` plus 256 random bits, stored as
  SHA-256, with an optional expiry.
- **stdio MCP is not authenticated.** It runs on `ReadOnlyContainer` (database opened `mode=ro` +
  `query_only`, no identity, worker or migration), plus a second engine that may write the AI spend
  ledger alone (#274).

!!! tip "New read-path wiring"

    Read-side wiring lives in `_build_read_side` in `bootstrap/container.py`. Anything new on the
    read path goes there so stdio inherits it.
