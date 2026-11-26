# Cloudflare Access

!!! abstract "TL;DR"
    - Off unless the `[auth.cloudflare_access]` table exists; `team_domain` and `audience` are
      required.
    - A token is accepted only with a valid RS256 signature, the right `iss` and `aud`, and valid
      times (60 seconds of clock skew); a failing token is treated as none.
    - People are linked by the Access `sub`, never by email; `admin_emails` get `admin`, and
      `auto_create_users` defaults to `true`.
    - A service token acts as the existing account mapped in `service_tokens`; an unlisted one signs
      nobody in.
    - A session cookie, API token or OAuth bearer still wins over Access.

When ExactDocs runs behind [Cloudflare Access](../../deployment/reverse-proxy.md#behind-cloudflare-access), it can
sign people and MCP clients in by the identity Access already checked, so nobody signs in twice
and MCP clients need only the Access service-token headers. It is off unless the
`[auth.cloudflare_access]` table exists (or `EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__<FIELD>` in the
environment, where lists and tables are JSON). An invalid value stops the server at start, with
a message naming the field.

```toml
[auth.cloudflare_access]
team_domain = "https://acme.cloudflareaccess.com"
audience = ["4714c1358e65fe4b408ad6d432a5f878f08194bdb4752441fd56faefa9b2b6f2"]
admin_emails = ["ada@acme.com"]
auto_create_users = true

[auth.cloudflare_access.service_tokens]
"88bf3b6d86161464f6509f7219099e57.access" = "ci-bot"
```

| Field | Environment | Default | What it does |
|---|---|---|---|
| `team_domain` | `EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__TEAM_DOMAIN` | required | `https://<team>.cloudflareaccess.com`.<br/>The tokens' issuer (`iss`); the signing keys are read from `<team_domain>/cdn-cgi/access/certs` |
| `audience` | `..._AUDIENCE='["<aud>"]'` | required | The Access application's **Application Audience (AUD) tag**, one or more. A token must name one of them |
| `admin_emails` | `..._ADMIN_EMAILS='["ada@acme.com"]'` | `[]` | People with these emails (compared case-insensitively) get the role `admin`; everyone else Access signs in is a `user`.<br/>Decided again at every visit |
| `auto_create_users` | `..._AUTO_CREATE_USERS` | `true` | Create an account at a person's first visit.<br/>When `false`, only people whose account was created earlier get in |
| `service_tokens` | `..._SERVICE_TOKENS='{"<client id>": "ci-bot"}'` | `{}` | Access service token client ID (`<id>.access`, the token's `common_name`) to the username of an **existing** account it acts as.<br/>An unlisted service token signs nobody in |

How a request is checked and linked:

- ExactDocs reads the token from the `Cf-Access-Jwt-Assertion` header, or else the
  `CF_Authorization` cookie. It is accepted only with a valid **RS256** signature by a key of the
  team's certs (cached, fetched again when a token names an unknown key, at most once a minute,
  with a 10-second timeout), an `iss` equal to `team_domain`, an `aud` among `audience`, and
  valid `exp`, `nbf` and `iat` (60 seconds of clock skew). A token that fails any check is
  logged with the reason, never the token, and the request is treated as if it had none.
- A **person** is linked to an account by the Access `sub` (stable for the person within your
  team), never by the email: the same `sub` always reaches the same account, even if the email
  changes. The first visit creates the account, named by the email (or its local part, or
  `<local part>@cloudflare-access` when those are taken); an existing account is never taken
  over by its name. It has no password and shows as provider `cloudflare-access` on the
  **Users** page. A disabled account is refused.
- A **service token** acts as the mapped account, with that account's role and library roles.
  The account must exist and not be disabled.
- A session cookie, an API token or an OAuth bearer the request carries still wins: Access
  signs in only a request that has none of them. A wrong API token is refused, never replaced by
  the Access identity.
- An account created by Access keeps its API tokens working for 30 days after its owner last
  came through Access (Access itself keeps a removed person away from the origin).
