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
| `kind` | required | `oidc`, the only kind so far: OpenID Connect with discovery and the authorization code flow with PKCE. ADFS 2016+ is an `oidc` provider |
| `display_name` | the name | What the button says: **Sign in with** *display_name* |
| `issuer` | required | The issuer URL, exactly as the discovery document's `issuer` says. HTTPS; plain HTTP only to a loopback host, for development |
| `client_id` | required | The client ID registered at the provider |
| `client_secret` | unset | The client secret, from the environment only (`EXACTDOCS_AUTH__PROVIDERS__<NAME>__CLIENT_SECRET`). Leave it and `client_secret_file` unset for a public client |
| `client_secret_file` | unset | A file holding the client secret, read at every use (Docker and Kubernetes secrets). Not together with `client_secret` |
| `scopes` | `["openid", "profile", "email", "offline_access"]` | The scopes asked for. `openid` is required; `offline_access` gets the refresh token that revalidation needs |
| `allowed_groups` | `[]` | Groups, as the provider names them, whose members may sign in |
| `allow_any_user` | `false` | Admit everyone the provider vouches for. Either this or `allowed_groups` is required |
| `admin_groups` | `[]` | Members of these groups get the role `admin`, everyone else `user`, decided again at every sign-in and revalidation |
| `groups_claim` | `groups` | The claim holding the groups, a dotted path (Keycloak: `realm_access.roles`; ADFS: `group`). Read from userinfo when the ID token lacks it |
| `group_prefix` | empty | Put before each group name ExactDocs stores for the account (for example `corp:`). Matching against `allowed_groups` and `admin_groups` uses the provider's names |
| `username_claim` | `preferred_username` | The claim that names a new account (ADFS: `upn` or `unique_name`); without it, the local part of the email. Read only when the account is created |
| `email_claim` | `email` | The email claim |
| `revalidate_minutes` | `60` | How often the groups are checked again with the stored refresh token |
| `revalidate_grace_minutes` | `1440` | How long access lasts without a successful check (the provider is unreachable, or it gave no refresh token). After that, access ends until the next sign-in |

Two settings apply to all providers:

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_AUTH__REVALIDATE_POLL_SECONDS` | `300` | How often the server looks for accounts whose groups are due a check |
| `EXACTDOCS_MCP_OAUTH_PROVIDER` | unset | The name of one provider that web MCP hosts (Claude, ChatGPT) sign in through with OAuth. It needs a client secret. See [MCP](mcp.md#oauth-for-web-hosts) |

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
| `EXACTDOCS_AI__HYDE__CACHE_TTL` | `P30D` (30 days) | How long a HyDE hypothetical answer stays cached, in seconds or as an ISO 8601 duration. Once a day (just after UTC midnight, and at start; one process on PostgreSQL), and after every collection, the server deletes older answers and those of an `llm` model that is no longer configured. Answers are also deleted when their version's manifest is collected |
| `EXACTDOCS_AI__AGENTIC_CACHE__ENABLED`, `__THRESHOLD`, `__SCOPE`, `__TTL` | `false`, unset, `library`, `P7D` | The agentic answer cache. See [Re-asked questions](search.md#re-asked-questions) |
| `EXACTDOCS_AI__BUDGETS__...`, `EXACTDOCS_AI__AGENTIC__...` | unset | Spend limits and agent limits (prices only in the TOML file). See [Search and AI models](search.md) |

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
