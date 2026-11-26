# GitHub, Discord, Google and Microsoft

!!! abstract "TL;DR"
    - GitHub sign-in uses an OAuth App with `read:user read:org`, and a callback at
      `<EXACTDOCS_PUBLIC_URL>/api/v1/auth/<name>/callback`; `base_url` covers GitHub.com,
      Enterprise Server and `*.ghe.com`.
    - `allowed_orgs` and `allowed_teams` are checked, a verified team becomes group
      `github:<org>/<team>`, and with no filters you must set `allow_any_user = true`.
    - Losing membership or revoking the token ends web sessions and refuses API tokens on the next
      check.
    - The `discord`, `google` and `microsoft` presets need only the client ID and secret (and
      `tenant` for Microsoft), and create no accounts unless `auto_create_users = true`.

## GitHub and GitHub Enterprise sign-in

Create an **OAuth App** in GitHub's developer settings. Register
`<EXACTDOCS_PUBLIC_URL>/api/v1/auth/ghe/callback` as its authorization callback URL (`ghe` is the
provider name below). Configure the client secret through the environment or a mounted secret:

```toml
[auth.providers.ghe]
kind = "github"
display_name = "GitHub Enterprise"
base_url = "https://github.example.com"
client_id = "your-oauth-app-client-id"
client_secret_file = "/run/secrets/github-client-secret"
allowed_orgs = ["acme"]
allowed_teams = ["acme/docs-readers"]
admin_groups = ["github:acme/docs-admins"]
```

Use `base_url = "https://github.com"` for GitHub.com (API `https://api.github.com`). Enterprise
Server derives `<base_url>/api/v3`; data-residency Cloud `https://<sub>.ghe.com` derives
`https://api.<sub>.ghe.com`. An explicit `api_url` overrides this. Identity links use the API URL
and numeric user ID, so login renames keep the account. Changing the API URL changes that identity
namespace. GitHub Apps are outside this integration; use an OAuth App with `read:user read:org`.

Each configured organization, including organizations of `allowed_teams`, is checked first for
active membership. Teams are then read from paginated `/user/teams`, with an individual team
membership fallback. At least one configured team is required when `allowed_teams` is set. A
verified configured team becomes group `github:<org>/<team>`; include admin teams in
`allowed_teams` to make their groups available to `admin_groups`. If `allowed_groups` is also
set, it is an additional admission requirement. `group_prefix` applies as for OIDC. With no
membership filters, explicitly set `allow_any_user = true`; it never bypasses configured filters.

For an organization that restricts OAuth Apps, an organization owner must approve the ExactDocs
OAuth App under **Organization settings → Third-party access → OAuth app policy**. A refusal
names the organization and says it has not approved the app. For a SAML-enforced organization,
authorize the app using **Settings → Applications → Authorized OAuth Apps → Configure SSO**.
An SSO refusal asks the person to authorize SSO for that organization. These are separate from a
missing organization/team membership; provider messages and SSO URLs are never rendered directly.

The non-expiring OAuth App access token is sealed and used for periodic membership checks. Losing
membership or explicit token revocation ends web sessions and refuses API tokens on the next
check; transient provider outages retain access only within the existing bounded grace period.
The local password admin remains available for recovery.

## Discord, Google and Microsoft

These presets need only the client ID and secret (and, for Microsoft, the tenant); they set the
endpoints, scopes, claims, display name and icon themselves, and refuse an `issuer` or endpoint
set by hand. Register `<EXACTDOCS_PUBLIC_URL>/api/v1/auth/<name>/callback` as the redirect URI at
the provider.

```toml
[auth.providers.google]
kind = "google"
client_id = "1234.apps.googleusercontent.com"   # the secret from the environment, as above

[auth.providers.discord]
kind = "discord"
client_id = "112233445566778899"

[auth.providers.microsoft]
kind = "microsoft"
tenant = "organizations"
client_id = "00000000-0000-0000-0000-000000000000"
```

- `google` is OpenID Connect at `https://accounts.google.com` with `openid email profile`, and
  asks for offline access (Google sends a refresh token only at a person's first consent).
- `discord` is OAuth2: the subject is the Discord user ID, the username its `username`, with the
  `identify email` scopes. Discord has no groups.
- `microsoft` is OpenID Connect at Microsoft Entra ID. `tenant` is required: the directory
  (tenant) ID, a GUID, for one organization; `organizations` for any work or school account;
  `common` for those and personal accounts; `consumers` for personal accounts only. With
  `organizations` or `common`, each token's issuer names the person's own tenant (from its `tid`
  claim), so the same subject in two tenants is two identities. Groups come from the `groups`
  claim when the app registration emits it.

A preset creates no accounts (`auto_create_users = false`): anyone with a Google, Discord or
Microsoft account could otherwise get one. People sign in with another method (a password, or
your own identity provider) and link the provider under **Account settings → Sign-in**; from
then on it signs them in to that account, which keeps its own role and groups. To let a preset
create accounts, set `auto_create_users = true` together with `allowed_groups` or
`allow_any_user = true` (for Microsoft, usually with a single-tenant `tenant`).
