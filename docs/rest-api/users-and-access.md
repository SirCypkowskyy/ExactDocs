# Users, roles and access log

!!! abstract "TL;DR"
    - `/users` is for operators (role `admin`) signed in with the session cookie: an API token
      is 401, anyone else 403 `forbidden`. There is no self-signup route.
    - Library roles are `viewer < contributor < admin < creator`, granted to users and groups;
      an operator is `creator` of every library.
    - `/libraries/{owner}/{repo}/grants` and `/transfer` manage who holds a role.
    - Every creation, grant, revocation, transfer and removal of a library goes to the access log.

## Endpoints

| Method | Path | Purpose | Caller |
|---|---|---|---|
| `GET` | `/users` | list accounts | operator, session cookie |
| `POST` | `/users` | create an account | operator, session cookie |
| `POST` | `/users/{id}/disable` | lock an account out | operator, session cookie |
| `POST` | `/users/{id}/enable` | let it sign in again | operator, session cookie |
| `PUT` | `/users/{id}/password` | set a new password | operator, session cookie |
| `GET` | `/users/tokens` | every account's API tokens | operator, session cookie |
| `GET` | `/libraries/{owner}/{repo}/grants` | who holds a role | `admin` on the library |
| `PUT` | `/libraries/{owner}/{repo}/grants` | give or replace a role | `admin` on the library[^admin-grant] |
| `DELETE` | `/libraries/{owner}/{repo}/grants/{kind}/{subject}` | take a role away | `admin` on the library[^admin-grant] |
| `POST` | `/libraries/{owner}/{repo}/transfer` | hand the library over | `creator` or operator |
| `GET` | `/libraries/{owner}/{repo}/access-log` | a library's access log | `admin` on the library |
| `GET` | `/access-log` | every library's access log | operator, session cookie |

[^admin-grant]: `creator` is needed to give, change or remove an `admin`.

## Users

Users (ACL-06) are the local accounts, managed by an operator: an account with role `admin`. The
first admin is one.

There is no self-signup route. An account is made by:

- the setup (the first admin only)
- `exactdocs user create`
- a first sign-in through an identity provider
- `POST /users`

!!! warning "Operator session only"
    Every `/users` route needs the session cookie of an operator. An API token is 401 (a stolen
    token cannot create accounts), and a signed-in account that is not an `admin` gets 403
    `forbidden`. Library roles are separate: see [Library roles](#library-roles).

### `GET /users`

Lists a page of the accounts, oldest first.

| Field | Meaning |
|---|---|
| `id`, `username`, `role`, `created_at`, `disabled` | the account |
| `provider` | `null` for a local account |
| `groups` | the provider's, as of the latest sign-in or revalidation |
| `last_active_at` | the hour of the latest activity, see below |
| `token_count` | API tokens that have not expired |

| Parameter | Meaning |
|---|---|
| `q` | text |
| `role`, `disabled` | filters |
| `provider` | repeat for several; `password` for a local account,<br/>else the provider the account was created through |
| `sort` | `created_at`, `username`, `role`, `last_active_at` or `token_count` |

- No identity provider may be named `password`.
- `last_active_at` is the hour (UTC, minutes always zero: kept to the hour on purpose) of the
  account's latest activity, `null` until there is any. Activity is:
    - a sign-in (a password, an identity provider)
    - a request authenticated as the account: its session cookie, an API token, a provider's ID
      token over MCP, Cloudflare Access
- It is written at most once per hour per account, by the request that was reading the account
  anyway, best effort (a failed write is logged and the request goes on). Activity before the
  upgrade is not known.
- `token_count` is counted in one query for the whole list.

### `GET /users/tokens`

Lists every account's API tokens for an operator to tidy up.

- The fields of `GET /tokens` plus `owner_id` and `owner` (the username), never the secret or its
  hash.
- Expired tokens not yet purged are included.
- Newest first.
- Filters: `q` (the token's name), `owner_id`, `expired` and `unused` (`true` or `false`).
- `sort` by the token fields or `owner`.
- `cursor` or `offset` like every [list](pagination.md).

<figure class="xd-shot" markdown>

![The admin list of every account's API tokens, showing owner, token prefix, expiry and last use](../assets/screenshots/users-tokens-light.webp#only-light){ loading=lazy }
![The admin list of every account's API tokens, showing owner, token prefix, expiry and last use](../assets/screenshots/users-tokens-dark.webp#only-dark){ loading=lazy }

<figcaption>The admin's list of every account's tokens in the web UI.</figcaption>

</figure>

### `POST /users`

Body `{"username", "password", "role"?}`; role `user` (default) or `admin`. Answers 201 with the
account.

- A taken name (compared case-insensitively) is 409 `username_taken`.
- A name holding `@address:` (the sign-in throttle's own key separator) is 422
  `invalid_username`.

### Disable, enable and reset

| Route | Effect |
|---|---|
| `POST /users/{id}/disable` | locks the account out at once:<br/>sessions deleted, API tokens revoked |
| `POST /users/{id}/enable` | lets it sign in again with its password;<br/>revoked tokens stay revoked |
| `PUT /users/{id}/password` | `{"password"}`: new password, every session ended,<br/>tokens revoked, throttle cleared |

- A disabled account's sign-in gets the same 401 `invalid_credentials` as a wrong password. A
  session or token that slipped through is refused on use.
- Disabling the last enabled admin is 409 `last_operator`.
- `PUT /users/{id}/password` clears the username's sign-in throttle count and remembered
  addresses, like `exactdocs admin reset-password`.
    - It answers `{"account", "throttle"}`, where `throttle` is `cleared`, `busy` or `failed`. The
      password changed in every case.
    - An account of an identity provider has no password: 409 `external_account`.
- An unknown id is 404 `unknown_account`.

## Library roles

Library roles (ACL-02) are `viewer < contributor < admin < creator` on each library, granted to
users and to groups.

- An account's role is the highest it holds.
- An operator (role `admin`) is `creator` of every library.
- The one who adds a library is its creator.

Every library route asks for one role:

| Role | Adds |
|---|---|
| `viewer` | reads and searches: `GET`s, search, outline, jobs, the schedule |
| `contributor` | imports: `POST .../versions`, `.../versions/reimport`,<br/>`.../sync`, `PUT .../tags` |
| `admin` | configures: `PATCH` and `PUT .../settings`, `.../default-version`,<br/>`.../retrieval`, `.../auto-sync`; removes versions |
| `creator` | deletes the library |

- Below the role the answer is 403 `forbidden`, the same over MCP (a tool error `forbidden: ...`).
- `GET /libraries`, the searches across libraries and `resolve-library-id` list only libraries
  the caller holds a role on.

### Grants

`GET /libraries/{owner}/{repo}/grants` lists a page of who holds a role: users by username, then
groups. Filters `q`, `kind`, `role`, `sort`.

??? example "Response"
    ```text
    {
      "grants": [{"kind", "subject", "role"}],
      "next_cursor", "total",
      "caller_role",   // the caller's own role, admin or creator
      "creator"        // the creator's username whatever the filters, null when there is none
    }
    ```

- `PUT` with `{"kind": "user"|"group", "subject", "role": "viewer"|"contributor"|"admin"}` gives
  or replaces a role and answers the grants.
- `DELETE /libraries/{owner}/{repo}/grants/{user|group}/{subject}` takes one away.
- All three need `admin` on the library, and `creator` to give, change or remove an `admin`.
- The creator's own role is never changed there (422 `invalid_grant`).

### Transfer

`POST /libraries/{owner}/{repo}/transfer` with `{"username"}` hands the library over. It answers
the grants.

- That user becomes its creator, and the creator before stays an `admin`.
- Only the `creator` (or an operator) may.
- The user who is already the creator is a 422 `invalid_grant`.

### Notes

- The web UI's *Sharing* page of a library (`/libraries/{owner}/{repo}/sharing`) uses these
  routes.
- Group names are matched exactly (letter case included) against the groups the identity
  provider reports.
- A username nobody has is 404 `unknown_account`, a missing grant 404 `unknown_grant`.
- Libraries that existed before roles have no creator: operators manage them and share them.

## Access log

The access log (ACL-05) records every creation, grant (a new role, or another one than before),
revocation, ownership transfer and removal of a library, with who made it and when.

| Route | Reads | Caller |
|---|---|---|
| `GET /libraries/{owner}/{repo}/access-log` | a library's log, newest first | `admin` on the library |
| `GET /access-log` | every library's log, removed ones included;<br/>also filters with `library` | operator session cookie[^log-caller] |

[^log-caller]: Like `/users`: an API token is 401, anyone else 403.

On a library's log, operators see every event recorded under the library's ID; anyone else only
those since it was last removed.

??? example "Response"
    ```text
    {
      "events": [{"id", "library", "at", "actor", "change", "kind",
                  "subject", "role", "previous_role"}],
      "next_cursor", "total"
    }
    ```

    - `change` is `library_created`, `granted`, `revoked`, `ownership_transferred` or
      `library_deleted`.
    - `actor` is a username, null when the instance made the change.
    - `role` is the role given, or taken away for `revoked`.

### Sorting and filters

Both logs (#514) take `sort`: `at`, `library` or `change`, `-` for descending. The default is
`-at`, newest first. Ties go by the order the events were recorded in, in the same direction.

These filters compose with each other and with `offset` and the cursor:

| Filter | Keeps |
|---|---|
| `change` (repeated) | only those changes |
| `actor` | changes made by that person, see below |
| `subject` | changes about that user or group, see below |
| `at_after` / `at_before` | events at or after / before that time |

- `actor` names a person as the log shows them: a username (any case), or the account ID the log
  shows for an account that no longer exists. Changes the instance made (`actor` null) never
  match.
- `subject` names a user or group as the log shows them: a username (any case), the account ID of
  an account that no longer exists, or a group name (exact case, `group_prefix` included).
    - A user and a group with the same name both match (`kind` tells them apart).
    - A `library_deleted` event is about nobody and never matches.
- `at_after` and `at_before` are ISO 8601; no offset means UTC. The last 7 days are
  `at_after=<now − 7 days>`.

!!! warning "Cursors and sort"
    A cursor is made for one `sort`: sending it with another is a 422 `invalid_cursor`. Cursors
    from before this change, which held the event ID alone, are refused the same way; start again
    from the first page. An unknown sort field is a 422 `invalid_sort`.

### What gets recorded

- A transfer records:
    1. one `granted` entry per creator before (now `admin`, `previous_role` `creator`)
    2. then one `ownership_transferred` entry whose subject is the new creator (`role` `creator`,
       `previous_role` the role they held, if any), with the caller as actor
- Giving someone the role they already hold records nothing.
- Changes made before the upgrade that added the log are not in it.
