# Sign-in and access

!!! abstract "TL;DR"

    - Sign-in providers are `[auth.providers.<name>]` tables: OpenID Connect, plain OAuth2, GitHub, or the Discord, Google and Microsoft presets.
    - A provider needs `EXACTDOCS_PUBLIC_URL`; register `<public_url>/api/v1/auth/<name>/callback` at the provider.
    - Each provider admits people by `allowed_groups`, by GitHub membership filters, or by `allow_any_user = true`.
    - Behind Cloudflare Access, ExactDocs can sign people in by the identity Access already checked.
    - `[auth.library_creation]` limits who may create libraries; by default every signed-in user may.

## Pages

| Page | What it covers |
|---|---|
| [GitHub, Discord, Google and Microsoft](providers.md) | GitHub and GitHub Enterprise, organizations and teams, the Discord, Google and Microsoft presets |
| [Cloudflare Access](cloudflare-access.md) | Access tokens, linking people by `sub`, service tokens |

## Sign-in providers

People can sign in through OpenID Connect providers as well as with a password;
[Getting started](../../getting-started/accounts.md#sign-in-through-an-identity-provider) shows a complete
example and what happens at sign-in. Each provider is a `[auth.providers.<name>]` table in the
TOML file, or `EXACTDOCS_AUTH__PROVIDERS__<NAME>__<FIELD>` in the environment, where lists are
JSON (`EXACTDOCS_AUTH__PROVIDERS__CORP__ALLOWED_GROUPS='["docs-readers"]'`). The name is
lower-case letters, digits and hyphens, and it appears in the callback URL. A provider that is
not valid stops the server at start, with a message naming the field.

| Field | Default | What it does |
|---|---|---|
| `kind` | required | `oidc`, `oauth2`, or `github`, using authorization code + PKCE S256.<br/>ADFS 2016+ is `oidc`.<br/>`discord`, `google` and `microsoft` are presets: see [Discord, Google and Microsoft](providers.md#discord-google-and-microsoft) |
| `display_name` | the name | What the button says: **Sign in with** *display_name*.<br/>A preset's default is `Discord`, `Google` or `Microsoft` |
| `auto_create_users` | `true`; `false` for the presets | Create an account at an identity's first sign-in.<br/>When `false`, only identities people linked to their account in Account settings sign in; anyone else is refused with `not_linked`.<br/>With it `false` and no `allowed_groups`, everyone the provider vouches for may link |
| `icon` | the preset's; `github` for `github` | A built-in icon for the provider's buttons: `discord`, `github`, `google` or `microsoft` |
| `icon_file` | unset | An icon of your own: a PNG, WebP or SVG file of at most 64 KiB and 512x512 pixels, read at start and served by ExactDocs itself (`/api/v1/auth/<name>/icon`), never from the provider.<br/>Its type is told by its content; an SVG is rebuilt from an allowlist (shapes, gradients, references to its own `#ids`; no scripts, event handlers, styles, external links or DOCTYPE).<br/>A file that does not pass stops the server at start.<br/>Not together with `icon` |
| `issuer` | required for `oidc` | OIDC discovery issuer; OAuth2 stable linking namespace (default: token URL origin).<br/>HTTPS; plain HTTP only to loopback for development |
| `client_id` | required | The client ID registered at the provider |
| `client_secret` | unset | The client secret, from the environment only (`EXACTDOCS_AUTH__PROVIDERS__<NAME>__CLIENT_SECRET`).<br/>Leave it and `client_secret_file` unset for a public client |
| `client_secret_file` | unset | A file holding the client secret, read at every use (Docker and Kubernetes secrets).<br/>Not together with `client_secret` |
| `scopes` | `["openid", "profile", "email", "offline_access"]` | OIDC requires `openid`; OAuth2 always adds `offline_access` for revalidation.<br/>GitHub uses `read:user read:org` |
| `allowed_groups` | `[]` | Groups, as the provider names them, whose members may sign in |
| `allow_any_user` | `false` | Admit everyone the provider vouches for.<br/>Either this, `allowed_groups`, or GitHub membership filters is required |
| `admin_groups` | `[]` | Members of these groups get the role `admin`, everyone else `user`, decided again at every sign-in and revalidation |
| `groups_claim` | `groups` | The claim holding the groups, a dotted path (Keycloak: `realm_access.roles`; ADFS: `group`).<br/>Read from userinfo when the ID token lacks it |
| `group_prefix` | empty | Put before each group name ExactDocs stores for the account (for example `corp:`).<br/>Matching against `allowed_groups` and `admin_groups` uses the provider's names |
| `username_claim` | `preferred_username` | The claim that names a new account (ADFS: `upn` or `unique_name`); without it, the local part of the email.<br/>Read only when the account is created |
| `email_claim` | `email` | The email claim |
| `revalidate_minutes` | `60` | How often the groups are checked again with the stored refresh token |
| `revalidate_grace_minutes` | `1440` | How long access lasts without a successful check (the provider is unreachable, or it gave no refresh token).<br/>After that, access ends until the next sign-in |

## OAuth2-only sign-in

For `kind = "oauth2"`, set `authorization_url`, `token_url`, and `userinfo_url` to the provider's
HTTPS endpoints (HTTP loopback is allowed for development). Set `client_id` and a secret as above.
`subject_claim` defaults to `sub`; `username_claim`, `email_claim` and `groups_claim` use the
same defaults as OIDC. Claim names can be literal keys or dotted nested paths. A literal key wins
when both exist. The subject must be a nonempty string; it, together with `issuer`, links the
account. Email and username changes never link another account.

`client_auth_method` is `client_secret_basic` by default; use `client_secret_post` if required by
the token endpoint. Configure `scopes` as needed; `offline_access` is always requested. The
provider must return a refresh token for continuing web revalidation; otherwise access ends after
the configured grace period. Refresh tokens are sealed, and a refreshed subject change is refused.

## Linking providers to an account

Every account has at most one identity per provider. The one it was created through (by a first
sign-in, or by Cloudflare Access) is its *origin*: an account without a password follows it, its
role, groups and access, and it can never be unlinked. Any other configured provider can be
linked from Account settings, and unlinked again (after a confirmation); a linked identity only
signs the account in, and its groups and role at the provider are not used. An identity that is
already linked to another account is refused. Linking needs a signed-in session: the
provider's callback must come back to the same browser session that started it. See
[REST API](../../rest-api/account.md#linked-sign-in-providers) (*Linked sign-in providers*).

Two settings apply to all providers:

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_AUTH__REVALIDATE_POLL_SECONDS` | `300` | How often the server looks for accounts whose groups are due a check |
| `EXACTDOCS_MCP_OAUTH_PROVIDER` | unset | The name of one provider that web MCP hosts (Claude, ChatGPT) sign in through with OAuth.<br/>It needs a client secret.<br/>See [MCP](../../mcp/connect.md#oauth-for-web-hosts) |

<figure class="xd-shot" markdown>

![The Sign-in tab of the account page, with the password section and the list of linked sign-in providers](../../assets/screenshots/account-sign-in-light.webp#only-light){ loading=lazy }
![The Sign-in tab of the account page, with the password section and the list of linked sign-in providers](../../assets/screenshots/account-sign-in-dark.webp#only-dark){ loading=lazy }

<figcaption>The <strong>Sign-in</strong> tab of the account page lists the linked providers.</figcaption>

</figure>

## Who may create libraries

By default every authenticated user may create a library and becomes its owner. Operators
can restrict creation in the configuration file:

```toml
[auth.library_creation]
users = ["stable-account-id"]
groups = ["corp:docs-admins"]
```

A user matching either list may create libraries. `users` contains exact stable account IDs,
not usernames (the users API exposes each account's `id`). For an unlinked verified MCP OAuth
identity, its stable ID is `<provider>:<subject>`. `groups` contains ExactDocs' exact mapped group
names, including the provider's `group_prefix`. Browser sessions and API tokens use the account's
current stored groups; verified MCP OAuth requests use their verified token's mapped groups and
role instead. Disabled accounts cannot create libraries.

The environment equivalents are `EXACTDOCS_AUTH__LIBRARY_CREATION__USERS='["stable-account-id"]'`
and `EXACTDOCS_AUTH__LIBRARY_CREATION__GROUPS='["corp:docs-admins"]'`. An omitted
`auth.library_creation` section preserves existing access. Supplying an empty section (or
`EXACTDOCS_AUTH__LIBRARY_CREATION='{}'`) permits only operators. Operators retain creation
permission regardless of these lists. Local internal commands, stdio MCP and scheduled jobs
retain their existing instance access. Read-only repository checks and previews remain available;
adding a library is checked before Git access, credential storage or import queueing, including
additions made by sources apply. Changing this configuration requires restarting the server.
