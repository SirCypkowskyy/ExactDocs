# Configuration

ExactDocs runs with no configuration at all: SQLite in the data directory, a generated secret key
and BM25 search. Everything on this page is optional.

## Where settings come from

Settings are environment variables named `EXACTDOCS_<SETTING>`. Nested settings use a double
underscore, as in `EXACTDOCS_AI__MODE` or `EXACTDOCS_AI__PROVIDERS__CORP__KIND`. They can also come
from a `.env` file in the working directory, or from a TOML file named by `EXACTDOCS_CONFIG_FILE`
(for example the `[ai]` tables on [Search and AI models](search.md), or the `[auth]` tables
below).

When the same setting appears in several places, the environment wins over `.env`, and both win
over the TOML file, field by field.

!!! warning "No secrets in the TOML file"
    The TOML file may not hold API keys, client secrets or `secret_key`, and the server refuses to
    start if it does. Those come from the environment, or from the file that a model provider's
    `api_key_file` or a sign-in provider's `client_secret_file` names.

## Settings

### Storage

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_DATA_DIR` | `/data` in the Docker image, else the platform's user-data directory | Where ExactDocs keeps everything: the SQLite database, the generated secret key, `known_hosts`, fetch caches and `jobs.sqlite` (the durable steps of running imports). On PostgreSQL only `known_hosts` and fetch caches live here. Created if missing; the server refuses to start, naming the path, if it is not writable. `uvx` and stdio MCP use the same default path |
| `EXACTDOCS_DATABASE_URL` | `exactdocs.db` in the data directory | A SQLite file, such as `sqlite:////srv/exactdocs.db` (opened in WAL mode), a PostgreSQL database, `postgresql://user:password@host:5432/exactdocs` (psycopg 3; see [PostgreSQL](deployment.md#postgresql)), or a libSQL server, `libsql://host?authToken=...` (the `libsql-database` extra; see [ExactDocs' own database on libSQL](#exactdocs-own-database-on-libsql)). The schema is migrated on start, and `/api/health` reports its revision |
| `EXACTDOCS_DBOS_SYSTEM_SCHEMA` | `dbos` | PostgreSQL only: the schema of the same database where DBOS keeps the durable steps of jobs. SQLite keeps them in `<data dir>/jobs.sqlite` |
| `EXACTDOCS_MODELS_DIR` | `<data dir>/models` | Where local models live; see [Local models](search.md#local-models) |

### Security

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_SECRET_KEY` | generated into `<data dir>/secret.key` (mode 0600) on first run | Encrypts the stored tokens and deploy keys of private repositories (Fernet). See [The secret key](#the-secret-key) |
| `EXACTDOCS_SECRET_KEY_PREVIOUS` | unset | The old key during a rotation |
| `EXACTDOCS_ALLOWED_HOSTS` | unset | Host names besides localhost that the server answers to, comma-separated (for example `docs.example.com,*.corp.example`). Needed behind a reverse proxy or on a LAN address |
| `EXACTDOCS_ALLOWED_ORIGINS` | unset | Browser origins allowed to make state-changing requests, comma-separated |
| `EXACTDOCS_SECURE_COOKIES` | `false` | The session cookie is always `Secure` over HTTPS, and whenever `EXACTDOCS_PUBLIC_URL` is `https://`. Set `true` when TLS ends at a proxy that does not forward `X-Forwarded-Proto` from a trusted address and no public URL is set |
| `EXACTDOCS_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Proxies whose `X-Forwarded-*` headers are trusted, for the scheme and for the client address the sign-in throttle counts. See [Behind a reverse proxy](deployment.md#behind-a-reverse-proxy) |
| `EXACTDOCS_PUBLIC_URL` | unset | The URL people reach the server at, without a path (`https://docs.example.com`). Required once a sign-in provider is configured: the redirect URI to register at the provider is `<public_url>/api/v1/auth/<name>/callback`, never built from a request's `Host` |

### Sign-in providers

People can sign in through OpenID Connect providers as well as with a password;
[Getting started](getting-started.md#sign-in-through-an-identity-provider) shows a complete
example and what happens at sign-in. Each provider is a `[auth.providers.<name>]` table in the
TOML file, or `EXACTDOCS_AUTH__PROVIDERS__<NAME>__<FIELD>` in the environment, where lists are
JSON (`EXACTDOCS_AUTH__PROVIDERS__CORP__ALLOWED_GROUPS='["docs-readers"]'`). The name is
lower-case letters, digits and hyphens, and it appears in the callback URL. A provider that is
not valid stops the server at start, with a message naming the field.

| Field | Default | What it does |
|---|---|---|
| `kind` | required | `oidc`, `oauth2`, or `github`, using authorization code + PKCE S256. ADFS 2016+ is `oidc`. `discord`, `google` and `microsoft` are presets: see [Discord, Google and Microsoft](#discord-google-and-microsoft) |
| `display_name` | the name | What the button says: **Sign in with** *display_name*. A preset's default is `Discord`, `Google` or `Microsoft` |
| `auto_create_users` | `true`; `false` for the presets | Create an account at an identity's first sign-in. When `false`, only identities people linked to their account in Account settings sign in; anyone else is refused with `not_linked`. With it `false` and no `allowed_groups`, everyone the provider vouches for may link |
| `icon` | the preset's; `github` for `github` | A built-in icon for the provider's buttons: `discord`, `github`, `google` or `microsoft` |
| `icon_file` | unset | An icon of your own: a PNG, WebP or SVG file of at most 64 KiB and 512x512 pixels, read at start and served by ExactDocs itself (`/api/v1/auth/<name>/icon`), never from the provider. Its type is told by its content; an SVG is rebuilt from an allowlist (shapes, gradients, references to its own `#ids`; no scripts, event handlers, styles, external links or DOCTYPE). A file that does not pass stops the server at start. Not together with `icon` |
| `issuer` | required for `oidc` | OIDC discovery issuer; OAuth2 stable linking namespace (default: token URL origin). HTTPS; plain HTTP only to loopback for development |
| `client_id` | required | The client ID registered at the provider |
| `client_secret` | unset | The client secret, from the environment only (`EXACTDOCS_AUTH__PROVIDERS__<NAME>__CLIENT_SECRET`). Leave it and `client_secret_file` unset for a public client |
| `client_secret_file` | unset | A file holding the client secret, read at every use (Docker and Kubernetes secrets). Not together with `client_secret` |
| `scopes` | `["openid", "profile", "email", "offline_access"]` | OIDC requires `openid`; OAuth2 always adds `offline_access` for revalidation. GitHub uses `read:user read:org` |
| `allowed_groups` | `[]` | Groups, as the provider names them, whose members may sign in |
| `allow_any_user` | `false` | Admit everyone the provider vouches for. Either this, `allowed_groups`, or GitHub membership filters is required |
| `admin_groups` | `[]` | Members of these groups get the role `admin`, everyone else `user`, decided again at every sign-in and revalidation |
| `groups_claim` | `groups` | The claim holding the groups, a dotted path (Keycloak: `realm_access.roles`; ADFS: `group`). Read from userinfo when the ID token lacks it |
| `group_prefix` | empty | Put before each group name ExactDocs stores for the account (for example `corp:`). Matching against `allowed_groups` and `admin_groups` uses the provider's names |
| `username_claim` | `preferred_username` | The claim that names a new account (ADFS: `upn` or `unique_name`); without it, the local part of the email. Read only when the account is created |
| `email_claim` | `email` | The email claim |
| `revalidate_minutes` | `60` | How often the groups are checked again with the stored refresh token |
| `revalidate_grace_minutes` | `1440` | How long access lasts without a successful check (the provider is unreachable, or it gave no refresh token). After that, access ends until the next sign-in |

### OAuth2-only sign-in

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

### GitHub and GitHub Enterprise sign-in

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

### Discord, Google and Microsoft

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

### Linking providers to an account

Every account has at most one identity per provider. The one it was created through (by a first
sign-in, or by Cloudflare Access) is its *origin*: an account without a password follows it, its
role, groups and access, and it can never be unlinked. Any other configured provider can be
linked from Account settings, and unlinked again (after a confirmation); a linked identity only
signs the account in, and its groups and role at the provider are not used. An identity that is
already linked to another account is refused. Linking needs a signed-in session: the
provider's callback must come back to the same browser session that started it. See
[REST API](rest-api.md) (*Linked sign-in providers*).

Two settings apply to all providers:

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_AUTH__REVALIDATE_POLL_SECONDS` | `300` | How often the server looks for accounts whose groups are due a check |
| `EXACTDOCS_MCP_OAUTH_PROVIDER` | unset | The name of one provider that web MCP hosts (Claude, ChatGPT) sign in through with OAuth. It needs a client secret. See [MCP](mcp.md#oauth-for-web-hosts) |

### Cloudflare Access

When ExactDocs runs behind [Cloudflare Access](deployment.md#behind-cloudflare-access), it can
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
| `team_domain` | `EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__TEAM_DOMAIN` | required | `https://<team>.cloudflareaccess.com`. The tokens' issuer (`iss`); the signing keys are read from `<team_domain>/cdn-cgi/access/certs` |
| `audience` | `..._AUDIENCE='["<aud>"]'` | required | The Access application's **Application Audience (AUD) tag**, one or more. A token must name one of them |
| `admin_emails` | `..._ADMIN_EMAILS='["ada@acme.com"]'` | `[]` | People with these emails (compared case-insensitively) get the role `admin`; everyone else Access signs in is a `user`. Decided again at every visit |
| `auto_create_users` | `..._AUTO_CREATE_USERS` | `true` | Create an account at a person's first visit. When `false`, only people whose account was created earlier get in |
| `service_tokens` | `..._SERVICE_TOKENS='{"<client id>": "ci-bot"}'` | `{}` | Access service token client ID (`<id>.access`, the token's `common_name`) to the username of an **existing** account it acts as. An unlisted service token signs nobody in |

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

### Server and imports

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_HOST`, `EXACTDOCS_PORT` | `127.0.0.1`, `3000` | The address `serve` binds; the Docker image binds `0.0.0.0`. `--host` and `--port` override them |
| `EXACTDOCS_MAX_ARTICLE_BYTES` | `2097152` (2 MiB) | An import skips a file above this size, unread, and reports it as `too_large` |
| `EXACTDOCS_MAX_IMPORT_BYTES` | `268435456` (256 MiB) | An import whose selected text adds up to more fails with `import_too_large` instead of exhausting memory |
| `EXACTDOCS_MAX_IMAGE_BYTES` | `2097152` (2 MiB) | An image an article references above this size is skipped, unread |
| `EXACTDOCS_MAX_IMAGES_BYTES` | `33554432` (32 MiB) | A version keeps images until they add up to this many bytes; later ones are skipped and listed as problems. Images are held in memory and in the database, about 8 times over at the peak |
| `EXACTDOCS_IMPORT_BATCH_FILES` | `100` | Files an import parses and chunks per durable step. An import interrupted by a crash, `kill -9` or a deploy resumes on the next start after its last completed step, so it loses at most this many files of work[^dbos] |
| `EXACTDOCS_JOB_POLL_SECONDS` | `1` | How often the job worker looks for a queued job to start (at most 60). An idle server polls no more often than this; lower it only if a second of delay before an import starts matters |
| `EXACTDOCS_AUTO_SYNC_SCHEDULE` | `0 * * * * *` | When the scheduled check ticks (a DBOS cron expression, seconds first). Each tick checks the libraries whose own interval is up (`PUT /api/v1/libraries/{owner}/{repo}/auto-sync`): new matching tags are imported, old automatic versions pruned and branches re-synced. Paused while no library has a schedule. An invalid expression stops startup |
| `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET` | `10000` | Size of one whole `query-docs` answer in tokens, counted as characters / 4; at least `500`. See [MCP](mcp.md#the-query-docs-budget) |

[^dbos]: DBOS keeps the steps in `<data dir>/jobs.sqlite`, or in the `dbos` schema on PostgreSQL.
    They take about three times the version's text while the import runs and are compacted once no
    job runs.

### Search and AI

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_CONFIG_FILE` | unset | A TOML file with the same settings (the `[ai]` and `[auth]` sections among them); the environment wins over it |
| `EXACTDOCS_AI__MODE` | unset (`auto`) | The retrieval mode of searches that name none, for libraries without their own: `bm25`, `hybrid`, `hybrid_hyde` or `agentic`. Unset or `auto` means the best default mode the configured models allow, which is BM25 until the eval suite makes another mode a default. An unknown name stops the server at start; a mode whose model is not configured falls back with `fallback_reason: mode_unavailable` |
| `EXACTDOCS_AI__RERANK_WITH` | `cross_encoder` | What reranks searches when both a cross-encoder and a judge could: `cross_encoder` or `judge`. See [LLM judge](search.md#llm-judge) |
| `EXACTDOCS_AI__PROVIDERS__<NAME>__<FIELD>`, `EXACTDOCS_AI__<ROLE>__MODEL` | unset | Provider profiles and model roles. See [AI providers and model roles](search.md#ai-providers-and-model-roles) |
| `EXACTDOCS_AI__LLM__THINKING`, `EXACTDOCS_AI__JUDGE__THINKING` | unset | How much the `llm` and `judge` models think before they answer: `minimal`, `low`, `medium`, `high` or `xhigh` (any letter case), sent as each provider's own control. Unset: the provider's default (a judge that is the LLM thinks as the LLM). Set here, the level cannot be changed over the REST API or in the UI. See [Thinking level](search.md#thinking-level) |
| `EXACTDOCS_AI__HYDE__CACHE_TTL` | `P30D` (30 days) | How long a HyDE hypothetical answer stays cached, in seconds or as an ISO 8601 duration. Once a day (just after UTC midnight, and at start; one process on PostgreSQL), and after every collection, the server deletes older answers and those of an `llm` model that is no longer configured. Answers are also deleted when their version's manifest is collected |
| `EXACTDOCS_AI__AGENTIC_CACHE__ENABLED`, `__THRESHOLD`, `__SCOPE`, `__TTL` | `false`, unset, `library`, `P7D` | The agentic answer cache. See [Re-asked questions](search.md#re-asked-questions) |
| `EXACTDOCS_AI__BUDGETS__...`, `EXACTDOCS_AI__AGENTIC__...` | unset | Spend limits and agent limits (prices only in the TOML file). See [Search and AI models](search.md) |
| `EXACTDOCS_SEARCH_BACKEND` | `database` | Where full-text search runs: `database` (SQLite FTS5, or PostgreSQL full-text search / pg_search) or a registered external backend. The database keeps every chunk; the backend holds a copy of each version that imports, removals and re-tags keep in step and `exactdocs index rebuild` writes again. A backend that does not answer at start stops the server, naming it; an unknown name or a missing extra too. See [External index backends](architecture/index-backends.md) |
| `EXACTDOCS_VECTOR_BACKEND` | `database` | Where vector searches run: `database` (sqlite-vec or pgvector) or a registered external backend. The database's store still keeps every vector, so an embedding is paid once and the backend can be rebuilt from it; the store's extension is still needed |
| `EXACTDOCS_INDEX_BACKENDS__<NAME>__<OPTION>` | unset | An external backend's options (`[index_backends.<name>]` in the TOML file): its URL, index or collection names. Keys, tokens and passwords come from the environment or an option ending in `_file`; the TOML file refuses them |

### Observability

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_TELEMETRY` | `off` | `otlp` exports traces and metrics over OTLP/HTTP to your OpenTelemetry collector, named by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `..._METRICS_ENDPOINT`). A signal with no endpoint, or with `OTEL_TRACES_EXPORTER` / `OTEL_METRICS_EXPORTER` set to `none`, is not exported |
| `EXACTDOCS_TELEMETRY_QUERY_TEXT` | `false` | Keep the text of search queries in the traces. When off, it is left out of every span and redacted from request URLs |
| `EXACTDOCS_METRICS` | `false` | `true` serves Prometheus metrics at `/metrics` (requests, searches, imports, syncs, AI usage), behind the Host allowlist. `serve` only, not `--stdio` |
| `EXACTDOCS_METRICS_TOKEN` | unset | A bearer token that `/metrics` requires (`Authorization: Bearer <token>`, else 401). Unset, a scrape needs no credentials. Surrounding whitespace and newlines are trimmed, as Prometheus trims its `credentials_file`. Set it whenever the port is reachable beyond a network you trust |

[Observability](deployment.md#observability) explains what each of these exports.

### Outbound connections

ExactDocs reads the standard proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`,
`NO_PROXY`, in upper or lower case, lower case winning) and the standard CA bundle variables
(`SSL_CERT_FILE`, then `REQUESTS_CA_BUNDLE`, then `CURL_CA_BUNDLE`) once, and every outbound
client takes them from there: git, model downloads, AI providers, index backends, sign-in
providers, the OpenTelemetry exporter and the command-line client. Each `EXACTDOCS_` variable
below replaces its standard one, so ExactDocs can use another proxy than the rest of the machine.
[Behind a corporate proxy](deployment.md#behind-a-corporate-proxy) shows complete setups.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_HTTPS_PROXY` | `https_proxy`, `HTTPS_PROXY`, then `ALL_PROXY` | The forward proxy of `https://` connections, as `http://host:port`; credentials go in the URL (`http://user:password@host:port`, percent-encoded) and are never logged or shown |
| `EXACTDOCS_HTTP_PROXY` | `http_proxy`, `HTTP_PROXY`, then `ALL_PROXY` | The forward proxy of plain `http://` connections |
| `EXACTDOCS_NO_PROXY` | `no_proxy`, `NO_PROXY` | Hosts reached without the proxy, separated by commas or spaces: a host name (and every name under it: `example.com`, `.example.com` and `*.example.com` all match `docs.example.com`), an IP address, a CIDR range (`10.0.0.0/8`, `fd00::/8`, matched against URLs that name an address; a host name is never resolved for it), `host:port` for one port only, or `*` for every host. Set but empty, it lists no host. Loopback (`localhost`, `127.0.0.0/8`, `::1`), link-local addresses (`169.254.0.0/16`, the cloud metadata endpoints) and `metadata.google.internal` are never proxied, whatever it says |
| `EXACTDOCS_CA_BUNDLE` | `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, then `CURL_CA_BUNDLE` | A PEM file of the CA certificates every outbound TLS connection trusts, git included (as its `http.sslCAInfo`), instead of the system's: the company CA of a proxy that re-signs TLS. It replaces the system's certificates, so include the public ones too when some hosts are reached without the re-signing proxy. A file that cannot be read stops the server at start. Verification is never turned off |
| `EXACTDOCS_AI__USE_INSTANCE_PROXY` | `false` | AI provider profiles without a `proxy` of their own call their provider (and Entra ID) through the proxy above, unless `NO_PROXY` lists the endpoint. Off, they connect directly, as before #538; a profile's own `proxy` always wins. The CA bundle applies to them either way. See [Behind a corporate proxy](deployment.md#behind-a-corporate-proxy) |

The proxy can be `socks5://` (or `socks5h://`) where the client supports it: git does, the Python
clients need the `socksio` package. Redis and MongoDB backends speak their own protocols, which no
HTTP proxy carries: they connect directly, and use the CA bundle for TLS when their options name
no CA file.

### Usage counts and leaderboards

ExactDocs counts reads, searches and agent answers per UTC day, account, API token, library and
operation (#510): counts only, never a query, a path or any text. Operators read them at
`GET /api/v1/stats/usage`, everyone their own at `GET /api/v1/account/usage`, and the leaderboards
at `GET /api/v1/stats/leaderboard` (see [REST API](rest-api.md)). Per-person usage is monitoring
data under the GDPR, hence the opt-in for people and the bounded retention. The `[usage]` table
of the TOML file takes the same settings.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_USAGE__PEOPLE_LEADERBOARD` | `false` | Turn the people leaderboard on. Even then it ranks, and operators' usage reports name, only people who opted in (the `leaderboard_opt_in` interface preference, off by default); everyone else counts in totals only. Off, nobody is shown by name to anyone, operators included. The libraries leaderboard is always on |
| `EXACTDOCS_USAGE__RETENTION_MONTHS` | `13` | How many months of daily counts are kept (1 to 120). Every night the days before it are deleted: 13 keeps a year and the month before it |

### Command-line client

These are read by the CLI commands that talk to a server (`login`, `add`, `sync` and the rest), not
by the server.

| Variable | What it does |
|---|---|
| `EXACTDOCS_URL` | The server, when `--url` is not given |
| `EXACTDOCS_TOKEN` | The API token, when `--token` is not given; also what `exactdocs config` snippets refer to |
| `EXACTDOCS_CLIENT_CONFIG` | Another file instead of `config.json` in your user config directory |

The client follows the [outbound connections](#outbound-connections) settings too (the standard
variables and their `EXACTDOCS_` overrides, from its own environment): a remote server is reached
through the proxy unless `NO_PROXY` lists it, a server on `localhost` or a loopback address never
is, and the CA bundle is trusted.

## External index backends

`EXACTDOCS_SEARCH_BACKEND` and `EXACTDOCS_VECTOR_BACKEND` move an index out of the database (see
[External index backends](architecture/index-backends.md)). Each backend is configured
under `[index_backends.<name>]` in the TOML file, or `EXACTDOCS_INDEX_BACKENDS__<NAME>__<OPTION>`;
keys and tokens only from the environment or a `*_file` option. After switching, or after the
backend lost data, run `exactdocs index rebuild` ([Deployment](deployment.md#external-index-backends)).

### Azure AI Search

Azure AI Search can hold the **search index**, the **vector index**, or both
(`EXACTDOCS_SEARCH_BACKEND=azure_search`, `EXACTDOCS_VECTOR_BACKEND=azure_search`, #353). Its
client is an optional extra, not in the images: `pip install 'exactdocs[azure-search]'` or
`uvx --from 'exactdocs[azure-search]' exactdocs serve` (with `ai` for hosted embedding models:
`exactdocs[ai,azure-search]`). It uses `azure-search-documents` 12.0.0 (the `2026-04-01` REST
API) over azure-core's requests transport, and `azure-identity` for Entra ID.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "azure_search"
vector_backend = "azure_search"

[index_backends.azure_search]
endpoint = "https://contoso-docs.search.windows.net"
index = "exactdocs"
```

```bash
# An admin key, from the environment (or api_key_file in the TOML file, a mounted secret):
export EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__API_KEY=...
# Or Entra ID: no key, and auth = "default" (DefaultAzureCredential) or "managed_identity".
```

| Option | Default | Meaning |
|---|---|---|
| `endpoint` | required | The service's URL, `https://<service>.search.windows.net` (HTTPS only, no path) |
| `index` | `exactdocs` | The search index's name; each embedding space's index is `<index>-space<id>`. Lower-case letters, digits and single dashes, 2 to 100 characters. Give every ExactDocs instance that shares a service its own |
| `auth` | `api_key` with a key, else `default` | `api_key`: an admin key. `default`: Entra ID through `DefaultAzureCredential` (the `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_CLIENT_SECRET` or workload identity variables, a managed identity, the Azure CLI's sign-in). `managed_identity`: the system-assigned managed identity, or the user-assigned one `client_id` names |
| `api_key` | unset | An admin key. From the environment only (`EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__API_KEY`); the TOML file refuses it |
| `api_key_file` | unset | A file holding the admin key (a mounted secret), instead of `api_key` |
| `client_id` | unset | The client ID of a user-assigned managed identity (`auth = "managed_identity"` or `"default"`) |
| `audience` | unset | The Entra ID audience of a sovereign cloud (e.g. `https://search.azure.us`); unset: the public cloud |
| `timeout` | `10` | Seconds to connect, and to read each answer. Requests the service throttles or fails are retried twice by the SDK, then by the job |
| `index_timeout` | `60` | Seconds a write waits for the index to return what it wrote (below); past it the write fails and its job is retried |
| `hybrid` | `true` | Native hybrid search (below). The vector index only; `false` keeps the words out of the spaces' indexes |
| `vector_search` | `approximate` | `approximate` (HNSW) or `exact` (every vector of the asked versions: exhaustive k-nearest-neighbours, exact and slower on large versions) |
| `semantic_configuration` | unset | The name of a semantic configuration: Azure's **semantic ranker** reranks the hybrid searches that ask for reranking (below). Letters, digits, `_` and `-`, up to 128 characters; needs `hybrid = true`. Unset: the semantic ranker is never used |

Both backends read the same table, so with both indexes in Azure AI Search they share the
service.

**What ExactDocs creates.** Each chunk of each version is one document, keyed by its manifest
and chunk IDs: in `<index>` for the search index, in `<index>-space<id>` for an embedding space.
Each carries `manifest_id`, `library`, `version_id`, `chunk_id` (filterable; `manifest_id` and
`library` facetable, for the drift check), `article_path`, `tags` (a filterable collection), and
the words in three searchable fields (`heading`, `path`, `body`: the section's heading, the
headings above it, its text, as every word whole and by its identifier parts, lower case, so
`retryPolicy` is `retrypolicy`, `retry` and `policy`). They use the `whitespace` analyzer, so
`retry_policy` and `--dry-run` stay whole tokens (a language analyzer would split them and stem
the rest), and the index ranks with BM25 and a scoring profile, `exactdocs`, that weighs them as
the database's own indexes do (heading 20, the headings above 4, text 1). A space's documents
also carry `vector` (`Collection(Edm.Single)`, the embedding model's dimensions, an HNSW profile
comparing by cosine; not retrievable or stored, to save room). The search index is created when
the server starts and it is missing; a space's index on the space's first write. An index of
that name that exists with another schema (a field of another type, another analyzer, vectors of
other dimensions, no `exactdocs` scoring profile) is never written to: the start, or the write,
fails naming the index and what differs; delete it or set another `index`, then run
`exactdocs index rebuild`. A new embedding model makes a new space, so a new index; the retired
space's index is deleted. An index deleted behind ExactDocs' back is created again on the next
write (`exactdocs index rebuild` fills it).

Every query filters on the asked versions' `manifest_id` (and the tags) with an OData filter
inside Azure AI Search, before ranking (vector queries are pre-filtered), so another version's
chunks are never returned. A query's words are its terms, each escaped for the full Lucene
syntax, so a query is never parsed as syntax, and BM25 statistics are global, so the same chunk
in two versions scores the same.

**Writes wait for the index.** Azure AI Search indexes in near real time: a document is
searchable about a second after the service took it. Every write marks its documents
(`write_id`) and returns only once the index counts all of them (a delete: none of them), so a
version is complete in the index when its import or embedding job says so.

**Authentication.** With a key, use an admin key (a query key cannot write); keep it in the
environment or a mounted file. With Entra ID, enable role-based access on the service (API access
control *Role-based access control* or *Both*) and give ExactDocs' identity two roles on it:
**Search Service Contributor** (it creates and deletes its indexes) and **Search Index Data
Contributor** (it writes and queries documents). Tokens come from the sync `azure-identity`
credentials, run in a thread, about once an hour. A refused key or identity stops the start with
`authentication failed` and the backend's name; no error or log line carries the key (azure-core
redacts the `api-key` header in its own logs).

**Native hybrid search.** With `hybrid` on (the default), each space's documents also carry the
words (the same three fields), and a hybrid search of one version is one Azure hybrid query: the
words (BM25, weighted) and the vector query (at least the 50 nearest), both filtered
to the version and the tags, fused by Azure with reciprocal rank fusion. With `hybrid = false`,
ExactDocs fuses its own search index (Azure AI Search's or the database's) with the nearest
vectors itself. Turning it on later needs `exactdocs index rebuild` to write the words of the
documents already there. The search across libraries (`search_all_docs`) always fuses in
ExactDocs.

**Semantic ranker.** Azure's semantic ranker (#473) can rerank hybrid searches instead of
ExactDocs' own reranker. Name a semantic configuration:

```toml
[index_backends.azure_search]
endpoint = "https://contoso-docs.search.windows.net"
semantic_configuration = "exactdocs-semantic"   # any name; ExactDocs makes it
```

and keep a reranker configured (`EXACTDOCS_AI__RERANKER__MODEL`, or a library's own): reranking
is asked for as it always is, by the reranker role ([Reranker](search.md#reranker)). A hybrid
search (`hybrid`, and `hybrid_hyde`'s native query) of a library that reranks is then one Azure
request: the same hybrid query (the words, the vector, the filters to the version and the tags,
before ranking), with `semanticConfiguration` and the query's own text as `semanticQuery`. Azure
reranks its best 50 results; the result says `reranked: true`, its scores are the ranker's (0 to
4), and ExactDocs' reranker is not called for that search (no cross-encoder or judge call, nothing
recorded against ExactDocs' budgets; a budget that already turned the search's reranking off,
`llm_budget_reached`, turns Azure's off too). Searches the semantic ranker does not answer are reranked
as before by ExactDocs' reranker: `bm25` and `vector` searches, the search across libraries, and
any hybrid search Azure could not rerank (the ranker over capacity: Azure answers in the hybrid
order, `semanticErrorHandling = partial`; or the request refused, such as the Free plan's
monthly requests used up: ExactDocs logs a warning and asks the hybrid query alone). Without a
reranker configured nothing reranks, as today; without `semantic_configuration` the semantic
ranker is never used.

With the option, each space's documents also carry two plain-text fields the ranker reads,
`title` (the section's headings, `Guide / Retries`) and `content` (its text, as written),
searchable and retrievable as a semantic configuration needs but never searched by BM25 nor
returned; the configuration ranks by them (`title` as its title field, `content` as its content
field). A new space's index is made with them. An existing space's index without them gets them
added in place (Azure adds fields and semantic configurations without a rebuild, and ExactDocs
logs a warning): run `exactdocs index rebuild` once, so the documents written before carry the
text. A configuration of that name over other fields, or a `title` / `content` field of another
kind, is a schema mismatch: the write fails naming the index and what differs.

**Setting it up.** The semantic ranker needs a region that offers it. Every service starts on
its **Free** plan (any tier), which allows a monthly number of semantic requests (1,000 at the
time of writing); once they are used up, semantic queries are refused until the next month.
The **Standard** plan (the Basic tier or higher) bills each semantic request beyond the free
ones, per 1,000 requests: see [Azure AI Search pricing](https://azure.microsoft.com/pricing/details/search/).
Choose the plan in the portal (**Settings** > **Premium features** > **Semantic ranker**) or with
the management API's `semanticSearch` property (`free` or `standard`). **What it costs:** every
reranked hybrid search is one semantic request (a search that does not ask for reranking, or is
not a native hybrid search, makes none), and the `content` field stores each chunk's text once
more in every space's index (about what the chunks' text takes; see *Sizing*). The semantic
ranker reads each document's first 2,000 or so tokens across `title` and `content`, more than
ExactDocs' chunks hold.

**Sizing.** One document per chunk of each version (the same section in two versions is two
documents), so count the chunks of every indexed version. A vector takes 4 bytes per dimension
in the vector index (1,536 dimensions, `text-embedding-3-small`: about 6 GB per million chunks,
plus the HNSW graph's links), which counts against the tier's vector index quota per partition;
the words and fields take about what the chunks' text does. Each embedding space is an index of
its own and, while a new model is embedding, the old space's index is still there: with the
search index that makes three indexes, the Free tier's limit. Check the tier's storage, vector
index and index count limits before indexing many versions, and leave room for a rebuild.

**Testing against a real service.** There is no emulator: CI runs the contract suites against an
in-process fake of the REST API, plugged in as the SDK's transport. The manual workflow
**Azure AI Search (real service)** (`.github/workflows/azure-search.yml`, *Run workflow*) runs
the same suites against a real service. It needs a GitHub environment `azure-search`, the
repository variable `AZURE_SEARCH_ENDPOINT` and, for `auth: api_key`, the environment secret
`AZURE_SEARCH_API_KEY` (an admin key); for `auth: entra`, the repository variables
`AZURE_CLIENT_ID` and `AZURE_TENANT_ID` of an app registration (or user-assigned identity) with a
federated credential for `repo:<owner>/<repo>:environment:azure-search` and both roles above.
Each test writes to indexes of its own (`exactdocs-test-<random>`) and deletes them, so a Free
tier service will do. The `azure_search_semantic` cases run with a semantic configuration, so the
service's region must offer the semantic ranker (its Free plan's requests are plenty). Locally:

```bash
EXACTDOCS_TEST_AZURE_SEARCH_URL=https://<service>.search.windows.net \
EXACTDOCS_TEST_AZURE_SEARCH_KEY=<admin key> \
  uv run pytest --integration packages/exactdocs/tests/retrieval -k "azure_search and not fake"
```

(Without `EXACTDOCS_TEST_AZURE_SEARCH_KEY`, the tests sign in with `DefaultAzureCredential`,
e.g. after `az login`. The real service's cases are integration tests: `--integration` turns them
on, see [Fast and integration tests](releasing/tests.md).)

### Chroma

[Chroma](https://www.trychroma.com), as a server, as Chroma Cloud or embedded in a local
directory, can hold the **vector index** (`EXACTDOCS_VECTOR_BACKEND=chroma`, #361). Its client is
an optional extra, not in the images, in two flavours that install the same `chromadb` module
(pick one):

- `exactdocs[chroma]`: the HTTP-only client (`chromadb-client`), for a Chroma server or Chroma
  Cloud (`url`). No ONNX runtime, no tokenizer, no model.
- `exactdocs[chroma-local]`: the full `chromadb` package, which adds the embedded persistent
  client (`path`); it also speaks HTTP. It pulls more (Chroma's server parts, `onnxruntime`,
  `tokenizers`), none of which ExactDocs uses.

`pip install 'exactdocs[chroma]'` or `uvx --from 'exactdocs[chroma]' exactdocs serve` (combine it
with `ai` for hosted embedding models: `exactdocs[ai,chroma]`). It is tested against
`chromadb/chroma:1.5.9` (the clients are 1.5.9); use a server of the same minor version.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE): a server, or Chroma Cloud
vector_backend = "chroma"

[index_backends.chroma]
url = "https://api.trychroma.com"   # or http://chroma.internal:8000
tenant = "3f8c..."                  # Chroma Cloud: your tenant and database
database = "exactdocs"
collection = "exactdocs"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__CHROMA__TOKEN=ck-...   # or token_file in the TOML file
```

```toml
# embedded: one directory, read and written by this ExactDocs process only
vector_backend = "chroma"

[index_backends.chroma]
path = "/var/lib/exactdocs/chroma"
```

| Option | Default | Meaning |
|---|---|---|
| `url` | one of `url` / `path` | A Chroma server or Chroma Cloud, `http(s)://host[:port]` (port 8000, or 443 with `https`, when none is given; no path) |
| `path` | one of `url` / `path` | The embedded persistent client's directory (created when missing); needs `exactdocs[chroma-local]` |
| `collection` | `exactdocs` | The collections' prefix: each embedding space is the collection `<collection>_space<id>`. Give every ExactDocs instance that shares a Chroma database its own |
| `tenant` | `default_tenant` | The Chroma tenant (Chroma Cloud: yours) |
| `database` | `default_database` | The Chroma database in that tenant (Chroma Cloud: one you created) |
| `token` | unset | A Chroma Cloud API key, or the token a proxy in front of a server checks. From the environment only (`EXACTDOCS_INDEX_BACKENDS__CHROMA__TOKEN`); the TOML file refuses it |
| `token_file` | unset | A file holding the token (a mounted secret), instead of `token` |
| `token_header` | `x-chroma-token` | Where the token is sent: `x-chroma-token` (Chroma Cloud's header) or `authorization` (`Authorization: Bearer <token>`, for a proxy) |
| `timeout` | `30` | Seconds one call to Chroma may take |

**What ExactDocs creates.** On the first write to an embedding space, the collection
`<collection>_space<id>`, with cosine distance and **no embedding function**: ExactDocs sends the
vectors its own embedding model made and never any text to embed, so Chroma runs no model and
downloads none. The collection's metadata records the space's dimensions
(`exactdocs_dimensions`) and model; a collection of that name without it (not made by ExactDocs)
or with other dimensions (another instance's) is never written to, and the write fails naming
it. A collection dropped behind ExactDocs' back is created again on the next write. Each record
is one chunk of one version, with the metadata `manifest_id`, `library`, `version_id`,
`chunk_id`, `article_path`, `headings` and one `tag:<tag>` key (`true`) per tag of its article;
every search filters on the asked versions' `manifest_id` (and tags) in Chroma, before ranking,
so another version's chunks are never returned. The metadata holds no lists on purpose: in
Chroma 1.5.9 a record's list metadata can read back, and over HTTP be filtered by, another
record's lists. A new embedding model makes a new space, so a new collection; the retired
space's collection is dropped. Hybrid search fuses ExactDocs' BM25 index with Chroma's nearest
vectors in ExactDocs, as with the database.

**Authentication.** Chroma Cloud takes its API key as `token` (sent as `x-chroma-token`), with
your `tenant` and `database`. A self-hosted Chroma server does not check a token itself: keep it
on a private network, or put it behind a reverse proxy that does (`token_header =
"authorization"`). Use `https` for anything but loopback or a private network. A token that is
missing or refused stops the start with the backend's name and what the server answered; no
error or log line carries the token.

**Embedded mode.** The directory belongs to one process: the server. `exactdocs index check` and
`exactdocs index rebuild` open it too, so run them while the server is stopped (or use a Chroma
server). Several ExactDocs server processes (PostgreSQL with replicas) need a
Chroma server (`url`).

**Sizing.** Chroma holds one record per chunk of each version (the same section in two versions
is two records), so count the chunks of every indexed version. A collection's HNSW index is kept
in memory: 4 bytes per dimension per record (1536 dimensions: about 6 KB; 100,000 chunks: about
600 MB), plus the graph (roughly 10 to 20 % more); the metadata, a few hundred bytes per record,
is on disk. The drift check (at start and every 5 minutes) reads the records' metadata a
thousand at a time: 100 requests per 100,000 records.

### DuckDB

`duckdb` keeps the search index, the vector index or both in one embedded DuckDB database file
(#357): no server, and a file you can query yourself for analytics or your own retrieval.
Install the extra (`pip install 'exactdocs[duckdb]'`, or `uvx --from 'exactdocs[duckdb]'
exactdocs serve`); the published Docker images do not include it.

```toml
search_backend = "duckdb"
vector_backend = "duckdb"

[index_backends.duckdb]
path = "/data/index.duckdb"
```

| Option | Default | What it does |
|---|---|---|
| `path` | required | The database file. Its folder must exist; the file is made at the first start. Both indexes may share it (one process opens it once) |
| `threads` | every CPU | Threads DuckDB uses for a query or an index build |
| `memory_limit` | DuckDB's (80% of RAM) | DuckDB's memory limit, e.g. `2GB` |

- **No credentials.** The file holds the text of every imported version, private libraries'
  included: protect it as the database (file permissions, the same volume and backups). It
  holds derived data only, so a lost file is written again by `exactdocs index rebuild`.
- **Offline.** The full-text search extension (`fts`) is installed with the extra, from the
  `duckdb-extension-fts` wheel (DuckDB's signed binary, pinned to the same DuckDB release as
  `duckdb`), and loaded from that file; DuckDB checks its signature, and extension auto-install
  and auto-load are off. ExactDocs makes no outbound request for DuckDB, at start or later.
- **One process.** DuckDB lets one process write a file, and no other process may open it,
  even to read, while ExactDocs has it open. A second process is refused at start, naming the
  process holding it: run one server process on the file (`WEB_CONCURRENCY=1` on PostgreSQL;
  SQLite always runs one), and stop the server before `exactdocs index check` or
  `exactdocs index rebuild`. To query the file yourself, stop ExactDocs or query a copy made
  while it was stopped.
- **Tables.** `exactdocs_search` has one row per chunk of each version: `library`,
  `version_id` (`/owner/repo/<ref>`), `manifest_id`, `chunk_id`, `article_path`,
  `heading_path`, `content`, `tags`, and the tokens the full-text index reads (`fts_*`). Each
  embedding space has `exactdocs_vectors_<space id>` with the same columns but the text, and
  `vector FLOAT[<dimensions>]`. `fts_main_exactdocs_search` is the `fts` extension's index.
- **Search.** BM25 from the `fts` extension, with the heading, ancestor headings, text and
  identifier columns weighted as the database's own index weighs them. The `fts` index does not
  follow writes: a write marks it stale and the first search after it rebuilds it whole, which
  takes about 7 s per 100,000 chunks on 2 threads (0.7 s per 10,000); searches then take tens of
  milliseconds. After an import, the first search waits for that rebuild.
- **Vectors.** An exact scan with DuckDB's `array_cosine_distance`, limited to the searched
  versions: about 0.15 s for 20,000 chunks of 1,536 dimensions on 2 threads, growing with the
  chunks of the searched versions; a vector takes 4 bytes per dimension. The `vss` extension's
  HNSW index is not used: in DuckDB 2.0 keeping it in a database file is still experimental
  (`hnsw_enable_experimental_persistence`; DuckDB warns that a crash can lose or corrupt it). Hybrid search
  fuses BM25 and the vectors in ExactDocs (reciprocal rank fusion), as with the database.

### Elasticsearch and OpenSearch

`EXACTDOCS_SEARCH_BACKEND=elasticsearch` (or `opensearch`) puts the full-text index in that
cluster, `EXACTDOCS_VECTOR_BACKEND=elasticsearch` (or `opensearch`) the vector index; either or
both. Install the client with the extra: `pip install 'exactdocs[elasticsearch]'` or
`'exactdocs[opensearch]'` (`uvx --from 'exactdocs[elasticsearch]' exactdocs serve`); the Docker
images do not include them. Elasticsearch 8.x and 9.x and OpenSearch 2.x and 3.x (Amazon
OpenSearch Service included) are supported; CI runs Elasticsearch 9.5 and OpenSearch 3.8. A
release without the native hybrid query gets hybrid search fused by ExactDocs (see below).

```toml
[index_backends.elasticsearch]   # or [index_backends.opensearch]
url = "https://search.internal:9200"   # several nodes: comma-separated
index_prefix = "exactdocs"
username = "exactdocs"
ca_certs = "/etc/exactdocs/search-ca.pem"
# the password comes from EXACTDOCS_INDEX_BACKENDS__ELASTICSEARCH__PASSWORD or password_file
```

| Option | Default | What it does |
|---|---|---|
| `url` | required | The cluster's URL (`http://` or `https://`); several nodes separated by commas |
| `index_prefix` | `exactdocs` | ExactDocs creates `<prefix>-search` and one `<prefix>-vectors-<space>` index per embedding space (and, on OpenSearch, the search pipeline `<prefix>-hybrid`). Lower case, digits, `_` and `-`. Instances sharing a cluster need different prefixes |
| `api_key` / `api_key_file` | unset | Elasticsearch only: an API key (the encoded value, or `id:key`) |
| `username`, `password` / `password_file` | unset | Basic auth (OpenSearch's internal users and Amazon OpenSearch Service's fine-grained access control too) |
| `token` / `token_file` | unset | A bearer token (an Elasticsearch service token, an OpenSearch JWT) |
| `ca_certs` | system CAs | A PEM file of the certificate authorities the cluster's TLS certificate is checked against |
| `verify_certs` | `true` | `false` skips the certificate check (never in production) |
| `request_timeout` | `30` | Seconds before a request gives up |
| `number_of_shards`, `number_of_replicas` | `1`, the cluster's | Of each index ExactDocs creates |
| `num_candidates` | `100` | The fewest HNSW candidates a kNN search considers (at least the `k` asked); more is slower and closer to an exact search. At most 10,000 |
| `refresh` | `wait_for` | A write returns once it is searchable; `true` refreshes at once (more segments; for tests and small instances) |

Sign in one way: an API key, a token, or a user and password. Secrets come from the environment
or a `*_file` option (Docker and Kubernetes secrets); the TOML file refuses them. The user needs
the index privileges `create_index`, `write`, `read`, `delete` and `view_index_metadata` on
`<prefix>-*` (Elasticsearch's `manage` on those indexes covers them), and, on OpenSearch, the
cluster permission to put the search pipeline (`cluster:admin/search/pipeline/put`); without it
hybrid search is fused by ExactDocs instead, as said below.

**Mappings and analysis.** ExactDocs creates its indexes when they are missing, with strict
mappings: `manifest_id`, `library`, `version_id`, `chunk_id` and `tags` are `keyword` fields, and
every search filters by version inside the cluster, so another version's chunk never comes back.
The heading, path and text fields use an analyzer that keeps identifiers whole (`retry_policy`,
`v1.4.0`, `client.retry.timeout`, `--dry-run`), lower-cased and ASCII-folded; an `identifiers`
field holds their parts too (`retryPolicy` is also `retry` and `policy`), so `snake_case`,
`camelCase` and dotted names are found whole and by their parts, with the same field weights as
the database's own indexes; each word of a query counts once, in the field it scores best in, so
a section ranks as it does on the database. Vectors are `dense_vector` (Elasticsearch) or `knn_vector` with the
Lucene engine (OpenSearch) fields, cosine similarity, HNSW without quantisation.

**Native hybrid search.** With the vector index in the cluster, hybrid search asks the cluster
once: Elasticsearch fuses BM25 and kNN with its RRF retriever, OpenSearch with a `hybrid` query
and a normalisation search pipeline (min-max, arithmetic mean, equal weights). Elasticsearch's
RRF needs an Enterprise (or trial) licence and OpenSearch's hybrid query the neural-search plugin
(in the default distribution); a cluster that refuses it gets the two halves asked separately and
fused by ExactDocs (reciprocal rank fusion, as with the database), and the server logs that once.

**Sizing.** Each version is held apart (one document per chunk and version), so the indexes grow
with the versions you keep, not only with distinct content. A vector index needs about
`4 × dimensions` bytes per chunk for the vectors plus the HNSW graph (roughly another 10%), and
searches are fast while that fits in the nodes' memory outside the JVM heap (the page cache):
50,000 chunks of 1,024 dimensions are about 220 MB. One primary shard suffices for most
instances; give the JVM half the node's memory at most, as both engines advise (CI runs each
engine as a single node with a 512 MB heap).

### LanceDB

[LanceDB](https://lancedb.com) is an embedded vector database: it keeps Lance files in a local
directory or in object storage (S3, GCS, Azure Blob), with no server to run. It can hold the
**search index**, the **vector index**, or both (`EXACTDOCS_SEARCH_BACKEND=lancedb`,
`EXACTDOCS_VECTOR_BACKEND=lancedb`, #356), and serves hybrid search natively. Its client is an
optional extra, not in the images (with `pyarrow` it takes about 350 MB installed):
`pip install 'exactdocs[lancedb]'` or `uvx --from 'exactdocs[lancedb]' exactdocs serve` (with
`ai` for hosted embedding models: `exactdocs[ai,lancedb]`). It is pinned to `lancedb` 0.41.0,
which has wheels for x86_64 and ARM64 Linux and for macOS on Apple silicon. It suits a
single-node ExactDocs that wants its vectors outside SQLite, or kept in object storage.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "lancedb"
vector_backend = "lancedb"

[index_backends.lancedb]
uri = "/var/lib/exactdocs/lancedb"
```

| Option | Default | Meaning |
|---|---|---|
| `uri` | required | An absolute directory (`/var/lib/exactdocs/lancedb`, `file:///...`), created if missing, or an object-store URI LanceDB takes: `s3://bucket/path`, `gs://bucket/path`, `az://container/path` (without user info or a `?` query: credentials never go in the URI) |
| `table_prefix` | `exactdocs` | The tables' prefix (lower-case letters, digits, `_`): the search index is `<prefix>_chunks`, each embedding space `<prefix>_space_<id>`. Give every ExactDocs instance that shares a URI its own |
| `storage_options` | none | A table of LanceDB storage options for an object store, such as `region`, `endpoint` (S3-compatible stores like MinIO) or `allow_http`. Credentials are refused here (below) |
| `single_writer` | `false` | Required (`true`) for an object-store URI: you state that exactly one ExactDocs process writes it (below) |
| `lock_timeout_seconds` | `30` | How long a write waits while another process writes the same directory; then the write fails and its job retries it |
| `read_consistency_seconds` | `0` | How stale a read may be. `0` looks for other processes' writes (such as `exactdocs index rebuild`) on every search; on an object store a few seconds saves a request per search |

**Object storage and credentials.** LanceDB reads an object store's credentials from that store's
standard environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
`AWS_SESSION_TOKEN` (or an instance role), `GOOGLE_APPLICATION_CREDENTIALS` (or workload
identity), `AZURE_STORAGE_ACCOUNT_NAME` and `AZURE_STORAGE_ACCOUNT_KEY`. Set them for the server
process; a `storage_options` entry whose name holds `key`, `secret`, `token`, `password`,
`credential` or `sas` is refused at start, so no credential sits in the TOML file. Errors name the
error type only.

```toml
[index_backends.lancedb]
uri = "s3://docs-bucket/exactdocs"
single_writer = true

[index_backends.lancedb.storage_options]
region = "eu-central-1"
```

**Several processes writing.** Two processes upserting into one LanceDB table at the same time
leave duplicate rows (each commit is atomic, but neither sees the rows the other is adding).
ExactDocs therefore never lets them write at once:

- **A local directory is safe with several writers.** Every write takes an exclusive lock on
  `.exactdocs-write.lock` in the directory (`flock`), so the server, its jobs and an
  `exactdocs index rebuild` run alongside it take turns; searches never wait. The lock holds
  between processes of one machine (or containers sharing the volume on one host); do not
  share the directory between machines over NFS or SMB, where the lock is not reliable.
- **An object store is refused unless you declare one writer.** It has no lock ExactDocs can
  take, so a URI like `s3://...` stops the start with a message saying why, until you set
  `single_writer = true`. That states that exactly one ExactDocs process writes the URI: no
  replicas (one server, SQLite or PostgreSQL), and `exactdocs index rebuild` only while that
  server is stopped. Several replicas need a server backend instead.

**What ExactDocs creates.** The search table on the first import, and a space's table on the
first vector written to it, each with a bitmap index on `manifest_id` and full-text indexes on
three word columns: the section's heading, its ancestors' headings and its text, split as every
ExactDocs index splits identifiers (`retryPolicy` is `retrypolicy`, `retry` and `policy`). A row
is one chunk of one version: `manifest_id`, `library`, `version_id`, `chunk_id`, `article_path`,
`tags`, the word columns and, in a space's table, the vector (float32, the space's dimensions).
Every search filters on the asked versions' `manifest_id` (and tags) inside LanceDB, before
ranking, so another version's chunks are never returned. A new embedding model makes a new space,
so a new table; the retired space's table is dropped. A space table of other dimensions under
the same prefix (another instance's) is never written to, and the write fails naming it.

**Search and native hybrid search.** Keyword search is LanceDB's BM25 over the three columns,
weighted as the database's own index weighs them (heading 20, ancestors 4, text 1). Vector search
is exact: cosine distance over every vector of the asked version, so results do not depend on an
approximate index. A hybrid search asks LanceDB for both halves, the best 50 of each, filtered to
the version, and fuses them with LanceDB's reciprocal rank fusion reranker (`k` 60). The search
across libraries (`search_all_docs`) fuses in ExactDocs. Rows written are searched at once; a
process adds them to the full-text indexes and compacts the table two seconds after its last
write (or every 10,000 rows, and when it stops).

**Sizing.** LanceDB holds one row per chunk of each version (the same section in two versions is
two rows), on disk; memory is the operating system's page cache. A vector takes 4 bytes per
dimension (1,536 dimensions: about 6 KB; 100,000 chunks: about 600 MB), and the text columns and
their full-text indexes about twice the chunks' text. Measured on 4 CPU cores with a version of
20,000 chunks at 1,536 dimensions: a vector search about 55 ms (it reads that version's vectors,
about 120 MB, so its time grows with the version's size), a keyword search about 5 ms, a hybrid
search about 60 ms. LanceDB keeps the files of replaced table versions for 7 days before it
deletes them, so right after an import or a rebuild the directory can hold two to three times the
live data (382 MB for that version, both indexes). For versions of several hundred thousand
chunks, or several ExactDocs replicas, prefer a server backend with an approximate index.

### libSQL

[libSQL](https://github.com/tursodatabase/libsql), the open-source fork of SQLite behind Turso, can
hold the **search index**, the **vector index**, or both (`EXACTDOCS_SEARCH_BACKEND=libsql`,
`EXACTDOCS_VECTOR_BACKEND=libsql`, #358): full-text search with FTS5, as on SQLite, and vectors
in libSQL's native vector type and index (`F32_BLOB`, `libsql_vector_idx`, `vector_top_k`), with
no extension to load. It runs in one of two places, named by `url`:

- **A libSQL server** (`sqld`, self-hosted, or a Turso database): `libsql://`, `https://` or
  `http://`. ExactDocs talks to its HTTP API with its own HTTP client, so nothing more is
  installed: the images can use it as they are. Tested against
  `ghcr.io/tursodatabase/libsql-server:v0.24.33`.
- **A local file**: `file:<path>` (or a path). libSQL then runs inside ExactDocs, through the
  `libsql` package: `pip install 'exactdocs[libsql]'` or
  `uvx --from 'exactdocs[libsql]' exactdocs serve`. It is not in the images. Its latest release
  (0.1.11) has a Python 3.14 wheel for Linux x86_64 only; elsewhere pip builds it from source,
  which needs a Rust toolchain.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "libsql"
vector_backend = "libsql"

[index_backends.libsql]
url = "libsql://exactdocs-acme.turso.io"   # or "http://sqld:8080", or "file:/data/index.db"
prefix = "exactdocs"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__LIBSQL__AUTH_TOKEN=...   # or auth_token_file in the TOML file
```

| Option | Default | Meaning |
|---|---|---|
| `url` | required | `libsql://host[:port]` (HTTPS; add `?tls=0` for plain HTTP), `https://host[:port]`, `http://host[:port]`, or a local file: `file:<path>`, `file://<path>` or a path. A server URL names the server only: no path, user or password |
| `auth_token` | unset | The server's token (a JWT: a Turso database token, or one signed with the key given to `sqld --auth-jwt-key-file` / `SQLD_AUTH_JWT_KEY`), sent as `Authorization: Bearer`. From the environment only (`EXACTDOCS_INDEX_BACKENDS__LIBSQL__AUTH_TOKEN`); the TOML file refuses it. Not for a local file |
| `auth_token_file` | unset | A file holding the token (a mounted secret), instead of `auth_token` |
| `prefix` | `exactdocs` | What every table ExactDocs creates starts with (letters, digits and `_`, at most 40). Give every ExactDocs instance that shares a libSQL database its own |
| `timeout` | `10` | Seconds one request to a server may take |
| `compress_neighbors` | `float1bit` | How the vector index stores the vectors of a node's neighbours: `float1bit`, `float8`, `float16`, `floatb16` or `float32` (sizing below). Set when a space's table is created: changing it later needs the space dropped (a new embedding model) or the tables dropped and `exactdocs index rebuild` |
| `max_neighbors` | libSQL's | The most neighbours of a node in the vector index (libSQL's default grows with the square root of the dimensions). Fewer: a smaller, faster to write, less exact index |

**What ExactDocs creates.** For the search index, `<prefix>_search_entries` (one row per chunk of
each version: manifest ID, chunk ID, library, tags) and `<prefix>_search`, its FTS5 table with
the columns, tokenizer (`unicode61 tokenchars '-_.'`) and `bm25()` column weights of ExactDocs'
SQLite index. For the vector index, `<prefix>_spaces` (the embedding spaces and their
dimensions) and, on the first write to a space, `<prefix>_space_<id>`: the chunks of each
version with their vectors in an `F32_BLOB(<dimensions>)` column, and the vector index
`<prefix>_space_<id>_ann` (cosine). A new embedding model makes a new space, so a new table; the
retired space's table is dropped. A space of the same ID with other dimensions (another instance
with the same `prefix`) is never written to: the write fails naming it.

**Searches.** Every search names the versions it may look at, in SQL: never a chunk of another
version. Full-text search ranks with FTS5's `bm25()`, as ExactDocs' SQLite index does; its
statistics are over libSQL's entries (one per chunk of each version, where the database holds
one per distinct section), so two hits whose scores are close may come in the other order. A
vector search asks the vector index (`vector_top_k`) for enough neighbours that the asked
versions' share of the space fills the limit (twice that many, at most 2,000), keeps theirs and
orders them by their exact cosine distance; when the versions are too small a share of the space
for that (or a tag filter keeps too few of them), it compares every vector of those versions
instead, which is exact and cheap for a version's few thousand chunks. Hybrid search fuses
libSQL's two halves in ExactDocs (reciprocal rank fusion), as with the database.

**Several processes.** A libSQL server is what several ExactDocs processes or hosts share (with
PostgreSQL, or this same libSQL server, as their database): each write is one transaction, which the server runs one after
the other. A local file is for one host: processes there may share it (WAL, and a writer
waits up to 5 seconds for another's lock), but never put it on a network filesystem. Embedded
replicas (a local copy synced from a server) are not used.

**Authentication.** Use `https` (or `libsql://`) for anything but a server on loopback or a
private network: the token goes with every request. A missing or refused token stops the start
with `HTTP 401` and the backend's name; no error or log line carries the token.

**Sizing.** libSQL holds one row per chunk of each version (the same section in two versions is
two rows), so count the chunks of every indexed version. The search index keeps a copy of each
chunk's text and its FTS5 index, as ExactDocs' SQLite index does. A vector takes 4 bytes per dimension,
but the vector index takes much more: each node keeps its neighbours' vectors, compressed by
`compress_neighbors`. The index only proposes candidates (their exact distances rank them), so
the default, one bit per dimension, costs no recall we could measure and is several times smaller
and faster to write. Measured on a local file (x86_64, libSQL's default `max_neighbors`):

| Dimensions | `compress_neighbors` | Disk per chunk | Write per chunk |
|---|---|---|---|
| 384 | `float1bit` (default) | about 7 KiB | about 2 ms |
| 384 | `float8` | about 28 KiB | about 4 ms |
| 1536 | `float1bit` (default) | about 40 KiB | about 5 ms |
| 1536 | `float8` | about 200 KiB | about 40 ms |
| 1536 | `float32` | about 320 KiB | about 50 ms |

Recall@10 of the index's 20 candidates, ranked by exact distance, was 0.99 to 1.00 with
`float1bit` and `float8` (384 dimensions, 3,000 clustered test vectors; `float1bit` with 1536 too). So 100,000 chunks of a 1536-dimension model take about
4 GB and a rebuild writes them in roughly ten minutes (one writer); with `float8`, five times
that. `max_neighbors` lower than libSQL's default makes the index smaller again (384 dimensions,
`float8`, 32 neighbours: about 18 KiB a chunk). One bit per dimension needs many dimensions to
tell vectors apart: for a model of fewer than about 256, use `float8`.

### ExactDocs' own database on libSQL

ExactDocs' own database can live on a **libSQL server** (`sqld`, self-hosted, or a Turso
database) instead of a SQLite file (#474), so several ExactDocs processes and hosts share one
SQLite-style database:

```bash
pip install 'exactdocs[libsql-database]'     # or: uvx --from 'exactdocs[libsql-database]' exactdocs serve
export EXACTDOCS_DATABASE_URL='libsql://exactdocs-acme.turso.io?authToken=...'
# a sqld on loopback or a private network, without TLS:
export EXACTDOCS_DATABASE_URL='libsql://sqld:8080?tls=0&authToken=...'
```

The URL names the server only (no path): `libsql://host[:port]`, over HTTPS unless `tls=0`, with
its token (a JWT: a Turso database token, or one signed with the key given to `sqld
--auth-jwt-key-file`) as `authToken`, as Turso writes it; a server without authentication takes
none. Log lines and errors never show the token. The extra installs Turso's `turso-serverless`
driver (pure Python, no dependency, so every platform); it is not in the images. ExactDocs runs
SQLite's own SQLAlchemy dialect over it (`sqlite+libsql`, in `bootstrap/libsql_database.py`),
each connection on a thread of its own as aiosqlite does, so every table, revision and query is
SQLite's: the schema is migrated on start, and the search index is SQLite's FTS5. Tested against
`ghcr.io/tursodatabase/libsql-server:v0.24.33`; CI runs the persistence contract tests' SQLite
cases on it, and a scenario with two server processes.

**Several processes.** Each process (and host) has a data directory of its own and uses the
server for everything in the database. Writes take turns on the server: a transaction that asks
for `BEGIN IMMEDIATE` (the first admin, activations, the search index) waits for the one before
it, as on a file. Processes starting together migrate one after the other.

**What differs from a SQLite file:**

- **Vectors use libSQL's own functions.** The vector store keeps the same tables and BLOBs as on
  SQLite and searches them exactly, with libSQL's `vector_distance_cos` instead of `sqlite-vec`,
  which a server cannot load (`/api/health` names its requirement `libSQL vectors`). For an
  approximate index on libSQL, add the [libSQL backend](#libsql) on the same server.
- **No read-only access.** A libSQL server refuses `PRAGMA query_only` and has no authorizer, so
  `serve --stdio` (and the commands that open the database read-only) refuse it: run `exactdocs
  serve` and connect over HTTP (`/mcp`).
- **`exactdocs backup` refuses it**: use the server's backups (a Turso database's point-in-time
  restore, or copies of `sqld`'s data directory).
- **Jobs stay with their process.** DBOS keeps each process's running jobs in `jobs.sqlite` in its
  data directory, as on a file: a job runs on the process that took it, and every process sees
  its state in the database. One server process per data directory, as on a file.
- **The server keeps its own settings.** It refuses `journal_mode`, `busy_timeout`,
  `synchronous`, `ANALYZE` and other PRAGMAs that set something; ExactDocs only switches
  `foreign_keys` on for each connection (the server's default too). Without `ANALYZE` the query
  planner has no statistics, so it may pick another of a table's indexes than on a file (the
  answers are the same).
- **Streams expire.** The server drops a connection's stream after a few seconds idle (`sqld`:
  10 s). A statement outside a transaction is then sent again; a transaction left idle that long
  is rolled back by the server and fails.
- **Every statement is a round trip.** One HTTP request each (about 2 ms on loopback): a first
  migration takes about a second, and an import is slower than on a local file, more so the
  farther the server.
- `REGEXP` is not available (ExactDocs does not use it), and an infinite float cannot be sent.
- A **local libSQL file** is not a database option: it is the same format as SQLite, so use
  `sqlite:///path` (libSQL's local file is for the [search and vector backend](#libsql)).

### Milvus

[Milvus](https://milvus.io), as a server, as Zilliz Cloud (its managed service) or as Milvus Lite
in a local directory, can hold the **vector index** (`EXACTDOCS_VECTOR_BACKEND=milvus`, #360), and
answer hybrid searches itself. Its client is an optional extra, not in the images:

- `exactdocs[milvus]`: `pymilvus`, for a Milvus server or Zilliz Cloud (`uri = "http(s)://..."`).
- `exactdocs[milvus-lite]`: `pymilvus` and `milvus-lite`, which adds Milvus Lite, the embedded
  engine, on a local `.db` directory (`uri = "/path/name.db"`). It is pure Python on `faiss-cpu`
  and `pyarrow`, with wheels for Linux x86_64 and ARM64 and macOS.

`pip install 'exactdocs[milvus]'` or `uvx --from 'exactdocs[milvus]' exactdocs serve` (combine it
with `ai` for hosted embedding models: `exactdocs[ai,milvus]`). It is tested against the
`milvusdb/milvus:v3.0.5` standalone server (pymilvus 3.0.2) and Milvus Lite 3.2.2; use a Milvus
3.0 server.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE): a server, or Zilliz Cloud
vector_backend = "milvus"

[index_backends.milvus]
uri = "http://milvus.internal:19530"   # or https://in03-....zillizcloud.com
collection = "exactdocs"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__MILVUS__TOKEN=root:Milvus   # or token_file in the TOML file
```

```toml
# Milvus Lite: one directory, read and written by this ExactDocs process only
vector_backend = "milvus"

[index_backends.milvus]
uri = "/var/lib/exactdocs/milvus.db"
```

| Option | Default | Meaning |
|---|---|---|
| `uri` | required | A Milvus server or Zilliz Cloud (`http://host:19530`, `https://...`), or a Milvus Lite directory: a path ending in `.db` (made absolute; its parent is created when missing; needs `exactdocs[milvus-lite]`) |
| `collection` | `exactdocs` | The collections' prefix: each embedding space is the collection `<collection>_space<id>`. Give every ExactDocs instance that shares a Milvus database its own |
| `db_name` | the default database | The Milvus database the collections are in |
| `token` | unset | A server's `user:password` or a Zilliz Cloud API key. From the environment only (`EXACTDOCS_INDEX_BACKENDS__MILVUS__TOKEN`); the TOML file refuses it. Milvus Lite takes none |
| `token_file` | unset | A file holding the token (a mounted secret), instead of `token` |
| `hybrid` | `true` | Native hybrid search: Milvus keeps each chunk's words for BM25 and fuses BM25 and the vectors itself (RRF). `false` keeps vectors only, and ExactDocs fuses its own BM25 index with Milvus' nearest vectors |
| `consistency_level` | `Strong` | The consistency new collections get: `Strong` (a search sees every earlier write), `Bounded`, `Session` or `Eventually` (faster searches; a version just written may be missed for a moment) |
| `timeout` | `30` | Seconds one call to Milvus may take |

**What ExactDocs creates.** On the first write to an embedding space, the collection
`<collection>_space<id>`, with the space's dimensions and cosine similarity (`AUTOINDEX`: Milvus
picks the index). Each row is one chunk of one version, keyed by a hash of the manifest and chunk
IDs, with the fields `manifest_id`, `library`, `version_id` (each with a scalar `INVERTED`
index), `chunk_id`, `article_path` and `tags` (an `INVERTED` index too on a server; Milvus Lite
has no array index); every search filters on the asked versions' `manifest_id` (and tags) in
Milvus, before ranking, so another version's chunks are never returned. With `hybrid`, a row also
keeps its headings and text as words in an analyzed `text` field (standard tokenizer, lower case;
cut at a word past 64 KB), which a BM25 function turns into the sparse vector `sparse`; a hybrid
search is one request, a BM25 half and a dense half, both filtered to the version, fused by
Milvus' RRF ranker (k = 60, as ExactDocs' own fusion). Collections are made once: with
`hybrid` switched on for collections made without it, hybrid searches answer with BM25 alone
(`vector_store_unavailable`); drop the collections and run `exactdocs index rebuild`. A new embedding model makes a new space,
so a new collection; the retired space's collection is dropped.

**Authentication.** A Milvus server with authentication on takes `user:password` as `token`
(`root:Milvus` until you change it), Zilliz Cloud its API key. Use `https` for anything but
loopback or a private network. A server that cannot be reached, or refuses the token, stops the
start with the backend's name and Milvus' error code; no error or log line carries the token.

**Milvus Lite.** The engine runs inside the ExactDocs process, which locks the directory: another
process cannot open it ("Open local milvus failed"). `exactdocs index check` and
`exactdocs index rebuild` open it too, so run them while the server is stopped (or use a Milvus
server). Several ExactDocs server processes (PostgreSQL with replicas) need a Milvus server.

**Sizing.** Milvus holds one row per chunk of each version (the same section in two versions is
two rows), so count the chunks of every indexed version. A loaded collection keeps its vectors in
memory: 4 bytes per dimension per row (1536 dimensions: about 6 KB; 100,000 chunks: about 600 MB),
plus the index (roughly 10 to 20 % more for HNSW). `hybrid` adds the chunk's words (about the
size of its text) and the BM25 sparse index (a few hundred bytes per chunk); `hybrid = false`
saves both. The drift check (at start and every 5 minutes) is one grouped count per collection on
a server; Milvus Lite reads the rows' version keys a thousand at a time.

### MongoDB

MongoDB with Atlas Search and Atlas Vector Search (an Atlas cluster, or MongoDB Community or
Enterprise 8.2+ with `mongot`, the search process) can hold the **search index**, the **vector
index**, or both (`EXACTDOCS_SEARCH_BACKEND=mongodb`, `EXACTDOCS_VECTOR_BACKEND=mongodb`, #363).
Its client is an optional extra, not in the images: `pip install 'exactdocs[mongodb]'` or
`uvx --from 'exactdocs[mongodb]' exactdocs serve` (with `ai` for hosted embedding models:
`exactdocs[ai,mongodb]`). It is tested against the `mongodb/mongodb-atlas-local:9.0.8` image
(MongoDB 9.0.8 with `mongot`; the client is `pymongo` 4.20.0, its async API). Native hybrid
search with one `$rankFusion` stage needs MongoDB 8.1 or later; on an older server ExactDocs
fuses the two searches itself.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "mongodb"
vector_backend = "mongodb"

[index_backends.mongodb]
url = "mongodb+srv://cluster0.example.mongodb.net/?retryWrites=true&w=majority"
username = "exactdocs"
database = "exactdocs"
collection = "chunks"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__MONGODB__PASSWORD=...   # or password_file in the TOML file
# or the whole connection string, password included, in a mounted secret:
#   url_file = "/run/secrets/mongodb-url"   (instead of url, username and password)
```

| Option | Default | Meaning |
|---|---|---|
| `url` | `url` or `url_file` required | The connection string, `mongodb://host[:port][,host...]/?options` or `mongodb+srv://host` (TLS on by default with `+srv`; add `tls=true` otherwise). It may not hold a password, nor a parameter whose name says password, secret or token |
| `url_file` | unset | A file holding the whole connection string, credentials included (a mounted secret), instead of `url` |
| `username` | unset | The database user, unless the connection string names one |
| `password` | unset | The user's password. From the environment only (`EXACTDOCS_INDEX_BACKENDS__MONGODB__PASSWORD`); the TOML file refuses it |
| `password_file` | unset | A file holding the password (a mounted secret), instead of `password` |
| `database` | `exactdocs` | The database ExactDocs writes to (letters, digits, `_` and `-`) |
| `collection` | `chunks` | The search index's collection; each embedding space's is `<collection>.space<id>`. Letters, digits, `_` and `-`. Give every ExactDocs instance that shares a database its own |
| `timeout` | `10` | Seconds one operation may take (server selection, connecting, and each command: the client's `timeoutMS`) |
| `index_timeout` | `120` | Seconds a write waits for a new search index to be queryable, and for the search indexes to return what it wrote (below); past it the write fails and its job is retried |
| `hybrid` | `true` | Native hybrid search (below). The vector index only; `false` keeps the words out of the spaces' collections |
| `vector_search` | `approximate` | `approximate` (HNSW, `numCandidates` 20 times the hits asked, at least 100) or `exact` (a full scan of the version's vectors: exact, slower on large versions) |

Both backends read the same table, so with both indexes in MongoDB they share the database.

**What ExactDocs creates.** Each chunk of each version is one document (`_id` is its manifest
and chunk ID): in `<collection>` for the search index, in `<collection>.space<id>` for an
embedding space. Each carries `manifest_id`, `library`, `version_id`, `chunk_id`, `article_path`
and `tags`, and the words in three fields (`heading`, `path`, `body`: the section's heading, the
headings above it, its text, as every word whole and by its identifier parts, lower case, so
`retryPolicy` is `retrypolicy`, `retry` and `policy`). A space's documents carry the vector as
BSON float32. The first write to a collection creates it, with lookup indexes on `manifest_id`,
and its search indexes when they are missing, then waits until they are queryable:

- `exactdocs_text`, an Atlas Search index: the three word fields (`lucene.whitespace`, no
  stemming, no stop words), ranked with BM25 and weighted in each query as the database's own
  indexes weigh them (heading 20, the headings above 4, text 1), and the five ID fields as
  `token` fields;
- `exactdocs_vectors`, an Atlas Vector Search index on each space's collection: `vector`
  (cosine, the embedding model's dimensions) and the five ID fields as `filter` fields.

Every query filters on the asked versions' `manifest_id` (and the tags) inside MongoDB, before
ranking (`$search`'s `compound.filter`, `$vectorSearch`'s pre-filter), so another version's
chunks are never returned. A new embedding model makes a new space, so a new collection; the
retired space's collection is dropped with its indexes. A collection whose vector index has other
dimensions (another instance's) is never written to: the write fails naming it. A collection or
index dropped behind ExactDocs' back is created again on the next write (`exactdocs index
rebuild` fills it).

**Writes wait for the indexes.** `mongot` follows each collection's change stream, so a write is
searchable a moment after MongoDB took it (about 0.3 s on the test image). Every write marks its
documents (`write_id`) and returns only once the search indexes return all of them (a delete:
once they return none), so a version is complete in the indexes when its import or embedding job
says so. On the test image, writing 10,000 chunks into both indexes took about a minute.

**Authentication and TLS.** Give ExactDocs its own database user with the `readWrite` role on
its database: it creates its collections and their search indexes, and needs nothing else (the
tests sign in as such a user). Keep the password in the environment or a mounted file, or put
the whole connection string in `url_file`. A password that is refused stops
the start with `authentication failed` and the backend's name; no error or log line carries the
password. `mongodb+srv://` connection strings use TLS; for a `mongodb://` one outside a private
network, add `tls=true` (and `tlsCAFile=...` for a private CA).

**Native hybrid search.** With `hybrid` on (the default), each space's documents also carry the
words (the same three fields, and an `exactdocs_text` index on that collection), and a hybrid
search of one version is a single `$rankFusion` stage: a `$search` and a `$vectorSearch`, both
filtered to the version and the tags, 50 deep (or the limit when higher), fused by MongoDB with
reciprocal rank fusion (`k` 60). The start asks the server whether it has `$rankFusion`; on one
without it, the backend runs the two searches itself and fuses them with ExactDocs' own
reciprocal rank fusion (the same weights). With `hybrid = false`, ExactDocs fuses its own search
index (MongoDB's or the database's) with MongoDB's nearest vectors. Turning it on later needs
`exactdocs index rebuild` to write the words of the documents already there (until then they are
found by their vector only). The search across libraries (`search_all_docs`) always fuses in
ExactDocs.

**Sizing.** One document per chunk of each version (the same section in two versions is two
documents), so count the chunks of every indexed version. Measured on
`mongodb-atlas-local:9.0.8` (10,000 chunks of about 1,000 characters each, 768-dimension vectors,
`hybrid` on), per million chunks:

| What | Per million chunks |
|---|---|
| Search collection on disk (`collStats` `storageSize`; 2.4 GB uncompressed) | 0.9 GB |
| A space's collection on disk, 768 dimensions, with the words | 4.6 GB |
| `mongot`'s indexes on disk (both word indexes and the HNSW graph) | 5.9 GB |

A vector is 4 bytes per dimension in its document and again in the HNSW graph, which `mongot`
keeps in memory to search fast: give the search nodes (Atlas) or the `mongot` process about
4 bytes per dimension per chunk of memory, plus room for the word indexes (1,536-dimension
vectors, `text-embedding-3-small`: about 6 GB per million chunks for the graph alone). Leave room
for a rebuild, which writes a version's documents again.

### Pinecone

Vectors only (`EXACTDOCS_VECTOR_BACKEND=pinecone`), extra `pinecone` (#362). Full-text search
stays in the database, or in another backend.

```toml
[index_backends.pinecone]
host = "https://docs-abc1234.svc.aped-4627-b74a.pinecone.io"  # or: index = "docs"
namespace = "exactdocs-prod"
hybrid = true
```

```bash
EXACTDOCS_VECTOR_BACKEND=pinecone
EXACTDOCS_INDEX_BACKENDS__PINECONE__API_KEY=pcsk_...   # or ..._API_KEY_FILE=/run/secrets/pinecone
```

| Option | Default | What it does |
|---|---|---|
| `host` | | The index's host, as the Pinecone console shows it. Set it or `index` |
| `index` | | The index's name instead; the host is looked up once at start |
| `api_key` / `api_key_file` | | The API key, from the environment or a file (Docker or Kubernetes secrets); the TOML file refuses `api_key`. It is sent to Pinecone only, never logged |
| `namespace` | `exactdocs` | The namespace this instance keeps its vectors in. Give each instance its own and they can share one index without mixing data |
| `hybrid` | `false` | Also store a sparse vector of each chunk's words, so `hybrid` searches are one sparse-dense query in Pinecone instead of ExactDocs fusing BM25 and the vectors. Needs a `dotproduct` index |
| `hybrid_alpha` | `0.5` | The vector half's weight in a hybrid query, 0 to 1 (the words get the rest) |
| `timeout` | `30` | Seconds one request may take |

**The index.** Create a serverless dense index (Pinecone's `list` and delete-by-ID are what the
adapter uses; pod indexes cannot list IDs) with the `cosine` or `dotproduct` metric
(`dotproduct` for `hybrid`), and a dimension at least the embedding model's. A model with fewer
dimensions is padded with zeros, which leaves cosine unchanged, so a model change to a smaller
one needs no new index; a larger one does (the embedding job fails, naming the dimensions). The
start fails, naming the backend, when the index cannot be reached, the key is refused, or its
metric does not fit.

**What is stored.** One vector per chunk of each version and embedding space, with the
version's manifest ID, its library, the space and the article's tags as metadata (no text). A
vector's ID is `<manifest>#<space>#<chunk>`: a version is deleted by listing its ID prefix,
since serverless indexes do not delete by metadata filter. Every query filters on the space and
the versions searched, so nothing of another version is returned.

**Sizing and cost.** Storage is one vector per chunk per version (a blob shared by two versions
is two vectors), at the index's dimension, plus a few dozen bytes of metadata; with `hybrid`, a
sparse vector of up to 1000 terms too. A query reads the namespace, filtered: Pinecone bills it
by the namespace's size. The drift check (at start and every 5 minutes, and
`exactdocs index check`) lists the namespace's IDs, 100 per request, so it costs about one read
request per 100 vectors each time; for millions of vectors, prefer an instance that does not
serve (`exactdocs index check` from a job) or accept the reads. Writes go 100 vectors per
request and are retried by the job that made them.

**Trying it locally.** Pinecone Local's single-index image emulates an index (amd64 only, kept
in memory, sparse values ignored, so `hybrid` cannot be tried on it):

```bash
docker run -d --name pinecone -p 5081:5081 -e PORT=5081 -e INDEX_TYPE=serverless \
  -e VECTOR_TYPE=dense -e DIMENSION=1536 -e METRIC=dotproduct \
  ghcr.io/pinecone-io/pinecone-index:v1.0.0.rc0@sha256:d60708292452e1e1d0740da86f653706a73b3682f302e1f0c18908f59e7ec7e0
EXACTDOCS_VECTOR_BACKEND=pinecone EXACTDOCS_INDEX_BACKENDS__PINECONE__HOST=http://localhost:5081 \
  EXACTDOCS_INDEX_BACKENDS__PINECONE__API_KEY=pclocal exactdocs serve
```

The contract tests run on it with `EXACTDOCS_TEST_PINECONE_URL=http://localhost:5081` (an index of
at least 256 dimensions) and `--integration` (they are integration tests). CI's integration job runs them on Pinecone Local (the image above, 256 dimensions,
`dotproduct`), which ignores sparse values; the manual **Pinecone** workflow runs them, hybrid
included, against a real index (repository secret `PINECONE_API_KEY`, its host as the workflow's
input). CI never calls Pinecone itself.

### Qdrant

[Qdrant](https://qdrant.tech), self-hosted or Qdrant Cloud, can hold the **vector index**
(`EXACTDOCS_VECTOR_BACKEND=qdrant`, #355). Its client is an optional extra, not in the images:
`pip install 'exactdocs[qdrant]'` or `uvx --from 'exactdocs[qdrant]' exactdocs serve` (combine it
with `ai` for hosted embedding models: `exactdocs[ai,qdrant]`). It is tested against
`qdrant/qdrant:v1.20.0` (the client is `qdrant-client` 1.20.0); use a server of the same minor
version or the one next to it.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
vector_backend = "qdrant"

[index_backends.qdrant]
url = "https://xyz-example.eu-central.aws.cloud.qdrant.io:6333"
collection = "exactdocs"
hybrid = true
```

```bash
export EXACTDOCS_INDEX_BACKENDS__QDRANT__API_KEY=...   # or api_key_file in the TOML file
```

| Option | Default | Meaning |
|---|---|---|
| `url` | required | The server's REST endpoint, `http(s)://host[:port]` (port 6333 when none is given) |
| `collection` | `exactdocs` | The collections' prefix: each embedding space is the collection `<collection>_space<id>`. Give every ExactDocs instance that shares a server its own |
| `api_key` | unset | The API key (a Qdrant Cloud database key, or a self-hosted server's `service.api_key`), sent as the `api-key` header. From the environment only (`EXACTDOCS_INDEX_BACKENDS__QDRANT__API_KEY`); the TOML file refuses it |
| `api_key_file` | unset | A file holding the API key (a mounted secret), instead of `api_key` |
| `timeout` | `10` | Seconds one request may take |
| `hybrid` | `false` | Native hybrid search: Qdrant ranks the words and the vector in one query (below) |
| `on_disk` | `false` | Keep the vectors memory-mapped from disk instead of in RAM |
| `quantization` | `none` | `scalar`: also keep an int8 copy of each vector in RAM, 4 times smaller, which searches use first |

**What ExactDocs creates.** On the first write to an embedding space, the collection
`<collection>_space<id>`: a dense vector `dense` with the embedding model's dimensions and cosine
distance, a sparse vector `words` (with Qdrant's IDF modifier), and keyword payload indexes on
`manifest_id` (as the tenant key), `library` and `tags`. A collection dropped behind ExactDocs'
back is created again on the next write, and missing payload indexes on the first write after a
start; a collection of the same name with vectors of other dimensions (another
instance's) is never written to, and the write fails naming it. Each point is one chunk of one
version, with the payload `manifest_id`, `library`, `version_id`, `chunk_id`, `article_path`,
`heading_path` and `tags`; every search filters on the asked versions' `manifest_id` (and tags) in
Qdrant, before ranking, so another version's chunks are never returned. A new embedding model
makes a new space, so a new collection; the retired space's collection is dropped.

**Authentication.** Use `https` for anything but a server on loopback: the key is sent with every
request (the client warns about a key over `http`). A key that is missing or refused stops the
start with `HTTP 401` or `403` and the backend's name; no error or log line carries the key.

**Native hybrid search.** With `hybrid = true`, each point also carries its words as a sparse
vector: BM25 term weights (`k1` 1.2, `b` 0.75, headings counting 3 times), split as every ExactDocs
index splits identifiers (`retryPolicy` is `retrypolicy`, `retry` and `policy`), with the IDF that
Qdrant computes over the collection. A hybrid search of one version is then a single Qdrant query
whose two prefetches (words and vector, both filtered to the version) are fused with reciprocal
rank fusion (`k` 60). Off, ExactDocs fuses its own BM25 index with Qdrant's nearest vectors, as
with the database. Turning it on later needs `exactdocs index rebuild` to write the words of the
points already there (until then they are found by their vector only). The search across
libraries (`search_all_docs`) always fuses in ExactDocs.

**Sizing.** Qdrant holds one point per chunk of each version (the same section in two versions is
two points), so count the chunks of every indexed version. In RAM, each point's vector takes
4 bytes per dimension (1536 dimensions: about 6 KB; 100,000 chunks: about 600 MB), plus the HNSW
graph (roughly 10 to 20 % more) and a few hundred bytes of payload. `quantization = "scalar"`
adds a quarter of that in RAM and, with `on_disk = true`, leaves the full vectors on disk. With
`hybrid`, the sparse vectors add about 8 bytes per distinct word of a chunk.

### Redis

[Redis](https://redis.io) 8 or later, whose Query Engine (formerly RediSearch) indexes text and
vectors in memory, can hold the **search index**, the **vector index**, or both
(`EXACTDOCS_SEARCH_BACKEND=redis`, `EXACTDOCS_VECTOR_BACKEND=redis`, #364). Its client is an
optional extra, not in the images: `pip install 'exactdocs[redis]'` or
`uvx --from 'exactdocs[redis]' exactdocs serve` (with `ai` for hosted embedding models:
`exactdocs[ai,redis]`). It is tested against the official `redis:8.10.3` image (the client is
`redis` 8.1.0, redis-py). Redis Stack 7.4 and managed Redis with the Query Engine work the same
way; native hybrid search needs Redis 8.4 or later. One Redis server (or a primary with
replicas): the community Query Engine does not search across the shards of a Redis Cluster.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "redis"
vector_backend = "redis"

[index_backends.redis]
url = "rediss://redis.internal:6380"
prefix = "exactdocs"
username = "exactdocs"
tls_ca_file = "/run/secrets/redis-ca.pem"
hybrid = true
```

```bash
export EXACTDOCS_INDEX_BACKENDS__REDIS__PASSWORD=...   # or password_file in the TOML file
```

| Option | Default | Meaning |
|---|---|---|
| `url` | required | The server, `redis://host[:port]`, or `rediss://` for TLS (port 6379 when none is given). It may not hold a user or password, nor a database other than 0 (the Query Engine indexes database 0 only) |
| `prefix` | `exactdocs` | Names the indexes and keys: the search index is `<prefix>:search`, each embedding space's `<prefix>:space<id>`, each over the hashes whose keys start with its name. Letters, digits, `_` and `-`. Give every ExactDocs instance that shares a server its own |
| `username` | unset | The ACL user (Redis 6 or later); unset, the `default` user |
| `password` | unset | The user's password, sent with `AUTH`. From the environment only (`EXACTDOCS_INDEX_BACKENDS__REDIS__PASSWORD`); the TOML file refuses it |
| `password_file` | unset | A file holding the password (a mounted secret), instead of `password` |
| `tls_ca_file` | unset | With `rediss://`: the CA certificate the server's certificate is checked against (unset: the system's trusted CAs). The certificate and the host name are always checked |
| `tls_cert_file`, `tls_key_file` | unset | With `rediss://`: a client certificate and its key, for a server that asks for one (`tls-auth-clients yes`) |
| `timeout` | `10` | Seconds one command may take, also each query's `TIMEOUT` (a query that runs out fails instead of answering with part of its results) |
| `hybrid` | `false` | Native hybrid search: Redis ranks the words and the vector in one `FT.HYBRID` query (below). The vector index only |
| `vector_algorithm` | `hnsw` | `hnsw` (approximate, fast on large versions) or `flat` (exact, brute force) |

Both backends read the same table, so with both indexes in Redis they share the server and the
prefix.

**What ExactDocs creates.** Each chunk of each version is one hash: `<prefix>:search:<manifest>:<chunk>`
in the search index, `<prefix>:space<id>:<manifest>:<chunk>` in a space's. The first write
creates the index with `FT.CREATE` when it is missing: `manifest_id`, `library`, `version_id`,
`chunk_id` and `tags` as `TAG` fields (case-sensitive), the words in three `TEXT` fields weighted
as the database's own indexes weigh them (the section's heading 20, the headings above it 4, its
text 1; no stemming, no stop words, every word whole and by its identifier parts, so
`retryPolicy` is `retrypolicy`, `retry` and `policy`), ranked with BM25 (`BM25STD`). A space's
index adds a `VECTOR` field (`FLOAT32`, cosine) whose dimensions are the embedding model's; a new
model makes a new space, so a new index, and the retired space's index is dropped with its
hashes (`FT.DROPINDEX ... DD`). Every query filters on the asked versions' `manifest_id` (and the
tags) inside Redis, before ranking, so another version's chunks are never returned. An index
dropped behind ExactDocs' back is created again on the next write (`exactdocs index rebuild`
fills it); an index of the same name whose vectors have other dimensions (another instance's) is
never written to, and the write fails naming it. Deleting a chunk or a version leaves its terms
in the index's statistics until the Query Engine's garbage collector cleans them (after
`search-fork-gc-clean-threshold` deletions, 100 by default), so BM25 scores can shift a little
after a rebuild; the order of the hits holds.

**Authentication and TLS.** Give ExactDocs its own ACL user, limited to its keys (the rights
below are what it needs, and what the tests sign in with):

```text
ACL SETUSER exactdocs on >PASSWORD ~exactdocs:* +@read +@write +@search +@transaction +ping +info
```

Keep the password in the environment or a mounted file. A password that is refused stops the start with
`authentication failed` and the backend's name; no error or log line carries the password. Use
`rediss://` for anything but a server on loopback or a private network you trust: the password
and every chunk travel in the clear otherwise.

**Native hybrid search.** With `hybrid = true`, each hash of a space also carries the chunk's
words (the same three `TEXT` fields), and a hybrid search of one version is a single `FT.HYBRID`
query: a BM25 search and a KNN search (`K` 50), both filtered to the version and the tags,
fused by Redis with reciprocal rank fusion (`k` 60). The start checks the server has `FT.HYBRID`
(Redis 8.4 or later). Off, ExactDocs fuses its own search index (Redis' or the database's) with
Redis' nearest vectors itself. Turning it on later needs `exactdocs index rebuild` to write the
words of the hashes already there (until then they are found by their vector only). The search
across libraries (`search_all_docs`) always fuses in ExactDocs.

**Sizing.** Redis holds everything in memory: one hash per chunk of each version (the same
section in two versions is two hashes), so count the chunks of every indexed version. Measured
on `redis:8.10.3` (`used_memory`, 20,000 chunks of about 1,000 characters of text each),
per million chunks:

| Index | Memory per million chunks |
|---|---|
| Search (`<prefix>:search`) | 5.6 GB |
| Vectors, 384 dimensions | 5.0 GB |
| Vectors, 768 dimensions | 8.6 GB |
| Vectors, 1,536 dimensions (`text-embedding-3-small`) | 15.9 GB |
| Vectors with `hybrid = true` | add 5 GB (the words) |

A vector takes 4 bytes per dimension twice (in its hash and in the index), plus about 2 KB for
the HNSW graph, the tags and the key; the words take about 5 times the chunk's text (the hash
holds the tokens, the index their postings, without positions), so longer chunks cost more. Both
indexes in Redis with 1,536-dimension vectors and `hybrid = true`: about 27 GB per million chunks. Leave room for Redis' own overhead and for a rebuild,
which writes a version's hashes again before the old ones are collected; set `maxmemory` with
the `noeviction` policy, so a full server refuses writes (the job fails and is retried) instead
of evicting entries without saying so.

## The secret key

`EXACTDOCS_SECRET_KEY` encrypts the stored tokens and deploy keys of private repositories and the
refresh tokens of identity providers, and keys the HMACs of the agentic answer cache. Unset, ExactDocs generates one into `<data dir>/secret.key`
(mode 0600) on first run.

It must be random and at least 32 characters:

```bash
openssl rand -base64 32
```

It is stretched with HKDF, not with a password hash, so a passphrase is not safe. Without the key
the stored credentials cannot be read: libraries keep serving their docs and ask for the token
again (`credentials_required`), and accounts of an identity provider lose access at their next
check until they sign in again.

On PostgreSQL, set it explicitly and use the same value in every process. Otherwise each process
generates its own key and cannot open the credentials another one stored.

### Rotating it

1. Put the new key in `EXACTDOCS_SECRET_KEY` and the old one in `EXACTDOCS_SECRET_KEY_PREVIOUS`.
2. Credentials sealed with the old key still open, and each one is sealed with the new key
   whenever it is sent again.
3. Remove `EXACTDOCS_SECRET_KEY_PREVIOUS` once they all have been.

HyDE's and the agentic cache's answers are keyed with the current key only, so after a rotation
every cached answer is a miss (the LLM is asked again) until the TTL prunes the old rows.

Backups and the secret key are covered in [Backup and restore](deployment.md#backup-and-restore).

### Who may create libraries

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
