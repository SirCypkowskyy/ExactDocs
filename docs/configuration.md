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
| `EXACTDOCS_DATABASE_URL` | `exactdocs.db` in the data directory | A SQLite file, such as `sqlite:////srv/exactdocs.db` (opened in WAL mode), or a PostgreSQL database, `postgresql://user:password@host:5432/exactdocs` (psycopg 3; see [PostgreSQL](deployment.md#postgresql)). The schema is migrated on start, and `/api/health` reports its revision |
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
| `kind` | required | `oidc`, `oauth2`, or `github`, using authorization code + PKCE S256. ADFS 2016+ is `oidc` |
| `display_name` | the name | What the button says: **Sign in with** *display_name* |
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
| `EXACTDOCS_SEARCH_BACKEND` | `database` | Where full-text search runs: `database` (SQLite FTS5, or PostgreSQL full-text search / pg_search) or a registered external backend. The database keeps every chunk; the backend holds a copy of each version that imports, removals and re-tags keep in step and `exactdocs index rebuild` writes again. A backend that does not answer at start stops the server, naming it; an unknown name or a missing extra too. See [External index backends](architecture.md#external-index-backends) |
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

### Command-line client

These are read by the CLI commands that talk to a server (`login`, `add`, `sync` and the rest), not
by the server.

| Variable | What it does |
|---|---|
| `EXACTDOCS_URL` | The server, when `--url` is not given |
| `EXACTDOCS_TOKEN` | The API token, when `--token` is not given; also what `exactdocs config` snippets refer to |
| `EXACTDOCS_CLIENT_CONFIG` | Another file instead of `config.json` in your user config directory |

## External index backends

`EXACTDOCS_SEARCH_BACKEND` / `EXACTDOCS_VECTOR_BACKEND` name the backend; its options go in
`[index_backends.<name>]` of the TOML file or in `EXACTDOCS_INDEX_BACKENDS__<NAME>__<OPTION>`.
Keys come from the environment or an `*_file` option, never the TOML file. Each backend is an
optional extra: install it with `pip install 'exactdocs[<extra>]'` (or
`uvx --from 'exactdocs[<extra>]' exactdocs serve`). How the backends keep in step with the
database, and how to repair one, is in [Deployment](deployment.md#external-index-backends).

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
at least 256 dimensions). Pinecone Local has no ARM64 image, so CI does not run them; the manual
**Pinecone** workflow runs them, hybrid included, against a real index (repository secret
`PINECONE_API_KEY`, its host as the workflow's input). CI never calls Pinecone.

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
