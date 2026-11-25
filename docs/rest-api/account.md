# Account

!!! abstract "TL;DR"
    - `/account/preferences` stores the caller's interface preferences per account; a session or
      an API token may read and write them.
    - `PUT /account/password` changes the caller's own password under the sign-in throttle.
    - `/account/providers` links and unlinks identities of other sign-in providers.
    - The password and provider routes need the session cookie, so a stolen API token cannot take
      the account over.

## Endpoints

| Method | Path | Purpose | Caller |
|---|---|---|---|
| `GET` | `/account/preferences` | read interface preferences | session or API token |
| `PUT` | `/account/preferences` | save interface preferences | session or API token |
| `PUT` | `/account/password` | change own password | session cookie |
| `GET` | `/account/providers` | list sign-in providers and links | session cookie |
| `POST` | `/account/providers/{provider}/link` | start linking an identity | session cookie |
| `DELETE` | `/account/providers/{provider}` | unlink an identity | session cookie |

The caller's own usage report, `GET /account/usage`, is on [Usage](usage.md).

## Interface preferences

Interface preferences (#487) live at `/api/v1/account/preferences`.

- `GET` answers the caller's `{"saved", "preferences"}`.
    - `saved` is `false` while the account never saved any, and `preferences` then holds the
      defaults. So the UI keeps, and saves, what the browser already applies on a first sign-in.
- `PUT` takes the whole `preferences` object and answers the same shape with `saved: true`.

| Key | Values | Default |
|---|---|---|
| `theme` | `light`, `dark`, `system` | `system` |
| `contrast` | `standard`, `more` | `standard` |
| `text_scale` | 90, 100, 110, 125 or 150 (percent) | 100 |
| `text_spacing` | `standard`, `wide` | `standard` |
| `motion` | `system`, `reduced`, `full` | `system` |
| `font` | `default`, `hyperlegible`, `dyslexic`, `system` | `default` |
| `underline_links` | boolean | `false` |
| `large_targets` | boolean | `false` |
| `language` | `system` (follows the browser's), `en`, `pl` | `system` |
| `library_logos` | boolean; `false` hides library logos<br/>and generic icons (#504) | `true` |
| `leaderboard_opt_in` | boolean; `true` agrees to be shown by name<br/>on the people leaderboard while the operator has it on (#510) | `false` |

- Every key is required except `leaderboard_opt_in`. A `PUT` without it (an interface older than
  #510) keeps the choice already saved (`false` if none), so it neither opts the person in nor
  drops their opt-in.
- An unknown key or a value not listed is 422 `validation_error` naming the field, and nothing is
  saved.
- They are stored per account (`identity_preferences`, one JSON object), so they follow the person
  to every browser. A key a stored row lacks, or a value no longer offered, reads as its default.
- A session or an API token may call both, and each acts as its own account only.

## Own password

`PUT /account/password` (#505) with `{"current_password", "new_password"}` changes the signed-in
account's own password.

- The new one follows the setup's limits: 12 to 1024 characters, else 422 `validation_error`.
- The current password is checked like a sign-in, under the same
  [throttle](authentication.md#sign-in-throttle):
    - A wrong one is 403 `wrong_password` (the caller stays signed in) and counts as a failed
      sign-in of its address and username.
    - Once they are past the free failures the change, like `POST /session`, is 429
      `rate_limited` with `Retry-After`, its password unchecked.
- On success it answers 204:
    - every other session of the account ends; the one that made the change stays
    - API tokens keep working (revoke them under `/tokens` if they may have leaked)
    - the username's throttle count and every address remembered for it (they signed in with the
      old password) are dropped, as after an operator's reset
    - the caller's own address is remembered again
- An account without a password (it signs in through an identity provider or Cloudflare Access)
  is 409 `external_account`. `has_password` in the `account` of `GET /session` (and of
  `GET /users`) is `false` for it, so the UI hides the form.

!!! warning "Session cookie only"
    It needs the session cookie. An API token is 401, so a stolen token cannot take the account
    over.

## Linked sign-in providers

An account (#506) keeps the identity it was created through, its *origin*. An account without a
password follows its origin for role, groups and access. It may link one identity of every other
configured provider, which then only signs it in: the account's own role and groups stand.

### `GET /account/providers`

Answers `{"has_password", "providers"}`:

- every configured provider in configuration order
- then each identity linked through a provider no longer configured (`configured: false`)

Each entry has `name`, `display_name`, `icon`, `icon_url`, `linked`, `origin`, `linked_at`
(`null` for the origin), `last_signed_in_at`, `can_link` and `can_unlink`.

### `POST /account/providers/{provider}/link`

- Body optional: `{"return_to": "/path"}`, default `/account`. `return_to` is a path on this
  server (anything else is `/`).
- Answers `{"redirect_url"}` and sets the `exactdocs_sign_in` binding cookie exactly as
  `GET /auth/{provider}/start` does. The attempt also holds the SHA-256 of the session that
  started it.
- The start is refused with:
    - 409 `provider_linked` when the account has an identity of the provider already
    - 404 `unknown_provider`
    - 429 `provider_unavailable`

The browser goes to `redirect_url`, and the provider comes back to
`GET /auth/{provider}/callback`. For a link, the callback:

1. needs the binding cookie, the `state` and the same session cookie
2. links the identity to that session's account
3. sets no cookie but clears the binding one
4. redirects to `return_to` with `?linked=<provider>`, or `?link_error=<code>`

| `link_error` | When |
|---|---|
| `sign_in_failed` | another session, or none, or a callback that fails a check |
| `sign_in_cancelled` | as at [sign-in](authentication.md#refusals) |
| `not_allowed` | as at [sign-in](authentication.md#refusals) |
| `identity_linked_elsewhere` | the identity is another account's |
| `provider_linked` | as at the start, above |
| `unauthenticated` | the session ended meanwhile |
| `provider_unavailable` | as at [sign-in](authentication.md#refusals) |

### `DELETE /account/providers/{provider}`

Unlinks the account's identity of the provider. It no longer signs the account in; sessions stay.
Answers the list again.

- 404 `provider_not_linked`
- 409 `last_sign_in_method` for the origin of an account without a password (its only way in)

!!! warning "Session cookie only"
    Every `/account/providers` route needs the session cookie. An API token is 401, so a stolen
    token cannot link an identity that signs in as its account.

!!! note "Providers that create no accounts"
    A provider with `auto_create_users = false` (the default of the Discord, Google and Microsoft
    presets) signs in linked identities only. Anyone else is refused with `not_linked`, at sign-in
    and over MCP OAuth.

### Provider icons

`GET /auth/{provider}/icon` serves a provider's own icon (`icon_file`). It needs no caller.

- It is the `icon_url` the provider lists (`?v=<version>`, which changes with the icon).
- Types: `image/png`, `image/webp` or a sanitised `image/svg+xml`.
- Headers:
    - `ETag` (304 on `If-None-Match`)
    - `Cache-Control: public, max-age=86400`
    - `X-Content-Type-Options: nosniff`
    - a `Content-Security-Policy` that runs and loads nothing
- A built-in icon (`icon`: `discord`, `github`, `google` or `microsoft`) is the web UI's own and
  has no `icon_url`.
- A provider without an icon file is 404 `no_icon`.
