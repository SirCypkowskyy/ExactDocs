# ExactDocs

**Self-hosted, version-accurate documentation for AI coding agents.**
Point ExactDocs at a git repository, pick the Markdown docs you care about, and browse and search
them in a web UI and from your AI agent over MCP, pinned to the exact tag, branch or commit you
imported. A drop-in, self-hosted alternative to context7.

> **Status: early development.** This README describes the target design. See the
> [user stories](https://sircypkowskyy.github.io/ExactDocs/user-stories/) for the full scope and
> the [Roadmap](#roadmap) for what ships when.

---

## Why ExactDocs

- **Your docs, from your repos.** GitHub, Bitbucket, GitLab, Gitea or any git server, public or
  private. You choose the folders and files; ExactDocs imports only those.
- **Version is a hard filter.** Every library version is a git ref resolved to a commit SHA. Ask
  about `v1.3` and you get `v1.3` or an explicit "no result", never a plausible answer from `v1.4`.
- **Verbatim, with sources.** Results are the original Markdown with path, heading, commit SHA and
  a link to the file on your git host. Nothing is paraphrased.
- **Lightweight by default.** No bundled models. With nothing configured it is a fast BM25 server;
  plug in an embedding model, a reranker or an LLM when you want more.
- **context7-compatible.** Same MCP tools and library IDs, so switching is a URL change.
- **Self-hosted and private.** No telemetry, no phone-home. The only outbound connections are to
  the git hosts and model endpoints you configure.

## Quick start

```bash
docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data \
  ghcr.io/sircypkowskyy/exactdocs:latest
# or, without Docker
uvx exactdocs serve
```

A fresh instance offers nothing but its setup: until the first admin account exists, every
`/api/v1` request is refused with `403 setup_required`. The setup page in the web UI is coming
(E8-01); until then create the admin from the command line or over the API:

```bash
docker exec -it exactdocs exactdocs admin create   # prompts for username and password
# or, without Docker
uvx exactdocs admin create
# or, over the API (the password must be 12 to 1024 characters)
curl -X POST http://localhost:3000/api/v1/setup -H 'content-type: application/json' \
  -d '{"username": "ada", "password": "a long passphrase"}'
```

`admin create` opens the database directly (so it works before the server is up, and against the
same data directory) and, for scripts, reads the password from stdin with `--password-stdin`.
Passwords are stored as argon2id hashes.

The web UI signs the admin in with `POST /api/v1/session`: an HttpOnly, SameSite=Lax cookie that
ends after 7 days without use or 30 days at most, and that only works on `/api` (never on `/mcp`).
Lost the password? Run `exactdocs admin reset-password` on the machine (same options as
`admin create`): it sets a new password, signs the admin out everywhere and revokes
the API tokens.

Then add your first library in the UI or from the CLI, which talks to the server's REST API:

```bash
exactdocs login http://localhost:3000       # stores the server URL and a new API token
exactdocs add https://github.com/acme/payments --ref v1.4.0 --path docs/ --path README.md
exactdocs add https://bitbucket.org/acme/platform --ref main --path "docs/**/*.md"
```

ExactDocs splits every article by its headings and keeps the library in sync (re-sync a branch
on demand). Planned next: a preview of matching files before importing, auto-import of new tags,
and pre-selection from a repository's `context7.json`. See the [Roadmap](#roadmap).

### Connect your agent

```json
{
  "mcpServers": {
    "exactdocs": {
      "url": "http://localhost:3000/mcp",
      "headers": { "Authorization": "Bearer <your-token>" }
    }
  }
}
```

MCP over HTTP needs an API token; it acts as the account that created it. Tokens start with
`exd_`, are shown once when created and stored only as a hash, may expire, and stop working the
moment they are revoked. Until the UI has a token page, use the REST API with your signed-in
session (the token routes do not accept a token, so a leaked token cannot mint successors):

```bash
curl -c jar.txt -H 'content-type: application/json' http://localhost:3000/api/v1/session \
  -d '{"username": "ada", "password": "a long passphrase"}'
curl -b jar.txt -H 'content-type: application/json' http://localhost:3000/api/v1/tokens \
  -d '{"name": "laptop", "expires_at": "2027-01-01T00:00:00Z"}'    # `expires_at` is optional
curl -b jar.txt http://localhost:3000/api/v1/tokens                  # list (never the secrets)
curl -b jar.txt -X DELETE http://localhost:3000/api/v1/tokens/<id>   # revoke
```

REST clients and scripts send the same token as `Authorization: Bearer exd_...` to any `/api/v1`
route except the token routes themselves.

Planned: tokens in the UI (**Settings → Tokens**) and `exactdocs token create`;
`exactdocs config --client claude|cursor|vscode` (planned) will print a ready-to-paste snippet with a new token.
For a local setup without a network port: `uvx exactdocs serve --stdio` (no token needed).

## MCP tools

| Tool | Purpose |
|---|---|
| `resolve-library-id(libraryName, query)` | context7-compatible: find a library ID such as `/acme/payments` |
| `query-docs(libraryId, query, language?)` | context7-compatible: documentation for `/owner/repo` (default version) or `/owner/repo/<ref>` (exactly that version, never another). Returns whole chunks, best first, within a size budget; chunks with code in `language` come first |
| `list_libraries()` | Libraries and imported versions you can access |
| `list_articles(library, version?, path_prefix?, tags?)` | The article tree of a version |
| `read_article(library, version?, path)` | A full article, verbatim |
| `search_docs(library, ref?, query, tags?, tags_match?, limit?)` | Search one version; results carry neighbors (`prev`/`next` chunk) and the retrieval mode used |
| `read_chunk(chunk_id)` | Fetch a neighboring section of a search result (planned: E7-03; until then follow `source_url`) |

Library IDs are `/owner/repo`; without a version, a library's **default version** is used (the highest imported stable semver tag, else the default branch, else the most recently imported version, unless pinned), and every response
says which version answered. Planned: hosts that support MCP Apps (Claude, ChatGPT) will
render articles and results as UI.
All tools are read-only, and everything returned is marked as external content.

## Retrieval

The pipeline upgrades itself to whatever you configure:

| Configured | Retrieval |
|---|---|
| nothing | BM25 |
| reranker | BM25 → rerank |
| embedding model | hybrid: BM25 + vector search |
| embedding model + reranker | hybrid → rerank |
| embedding model + LLM (+ reranker) | hybrid with HyDE → rerank (the default when everything is configured) |
| LLM + agentic mode | a pydantic-ai agent browses the documentation tree and returns the articles that answer the question, with a justification; similar past questions are served from a cache |

Articles are chunked by Markdown headings ([Chonkie](https://github.com/chonkie-inc/chonkie)),
never splitting code blocks or tables. Split level and chunk sizes are configurable per library.
Articles can be tagged (front matter, path rules or by hand) and filtered by tag everywhere.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `EXACTDOCS_DATA_DIR` | `/data` in the Docker image, else the platform user-data directory | Where ExactDocs keeps everything (database, the generated secret key, `known_hosts` and fetch caches). Created if missing; the server refuses to start, naming the path, if it is not writable. `uvx` and stdio MCP use the same default path |
| `EXACTDOCS_DATABASE_URL` | `exactdocs.db` in the data directory | SQLite file, e.g. `sqlite:////srv/exactdocs.db` (PostgreSQL arrives with TEAM-01). Opened in WAL mode; the schema is migrated on start and `/api/health` reports its revision |
| `EXACTDOCS_SECRET_KEY` | generated into `<data dir>/secret.key` (mode 0600) on first run | Encrypts the stored tokens and deploy keys of private repositories (Fernet). It must be **random** and at least 32 characters: `openssl rand -base64 32` (it is stretched with HKDF, not a password hash, so a passphrase is not safe). Without it the credentials cannot be read: libraries keep serving their docs and ask for the token again (`credentials_required`) |
| `EXACTDOCS_SECRET_KEY_PREVIOUS` | – | Rotation: set the new key in `EXACTDOCS_SECRET_KEY` and the old one here. Credentials sealed with the old key still open and are sealed with the new one whenever they are sent again; remove this once they all were |
| `EXACTDOCS_ALLOWED_HOSTS` | – | Host names besides localhost the server answers to, comma-separated (e.g. `docs.example.com,*.corp.example`); needed behind a reverse proxy or on a LAN address |
| `EXACTDOCS_ALLOWED_ORIGINS` | – | Browser origins allowed to make state-changing requests, comma-separated |
| `EXACTDOCS_SECURE_COOKIES` | `false` | The session cookie is always `Secure` over HTTPS; set `true` when TLS ends at a proxy that does not forward `X-Forwarded-Proto` from a trusted address |
| `EXACTDOCS_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Proxies whose `X-Forwarded-*` headers are trusted |
| `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET` | `10000` | Size budget of one `query-docs` answer, in tokens counted as characters / 4. Only whole chunks are returned; a chunk that does not fit is left out, never cut |
| `EXACTDOCS_EMBEDDING_URL`, `_MODEL`, `_API_KEY` | – | Optional OpenAI-compatible / Ollama / TEI embeddings endpoint; enables hybrid search |
| `EXACTDOCS_RERANKER_URL`, `_MODEL`, `_API_KEY` | – | Optional reranker endpoint (Cohere-compatible, Jina, TEI) |
| `EXACTDOCS_LLM_URL`, `_MODEL`, `_API_KEY`, `_PROXY` | – | Optional OpenAI-compatible LLM; enables HyDE and agentic retrieval |
| `EXACTDOCS_RETRIEVAL_MODE` | `auto` | `auto` (best available pipeline), `bm25`, `hybrid`, `hybrid_hyde` or `agentic` |
| `EXACTDOCS_TELEMETRY` | `off` | `off` or `otlp` (OpenTelemetry export to your collector; never to any cloud) |
| `EXACTDOCS_METRICS` | `off` | `on` exposes a Prometheus endpoint at `/metrics` |

### Private repositories

Send a credential next to the URL in `POST /api/v1/repositories/check`, `POST /api/v1/libraries`
or `POST /api/v1/libraries/{owner}/{repo}/versions`:

```json
{"url": "https://github.com/acme/docs", "credential": {"kind": "token", "token": "ghp_..."}}
{"url": "git@github.com:acme/docs.git", "credential": {"kind": "ssh_key", "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n..."}}
```

- A **token** goes with an `https://` URL (`http://` only for localhost); `username` defaults to
  `x-access-token` (GitHub, GitLab; Bitbucket repository tokens use `x-token-auth`). A **deploy
  key** (private key without a passphrase) goes with an SSH URL.
- Credentials are stored encrypted with `EXACTDOCS_SECRET_KEY`, never returned by the API and
  never written to logs or error messages. They reach git through `GIT_ASKPASS` (token) or a
  temporary key file named in `GIT_SSH_COMMAND` (deleted after each git call), never in the URL or
  the command line, and only for the repository's own host: a redirect to another host fails.
- **SSH host keys** live in `<data dir>/known_hosts`. GitHub, GitLab and Bitbucket are pinned with
  their published keys; any other host is trusted on first use and remembered. A host whose key
  changed is refused with `host_key_changed` until you remove its line from that file.
  `POST /api/v1/repositories/check` returns the `host_key_fingerprint` to compare with the host's
  published one.
- A credential is stored for the library **and the host it was given for**: it is never offered to
  another host, a library added again never inherits an earlier one, and removing a library
  deletes it. Sending a `credential` needs a signed-in session; an API token (for example an MCP
  client's) is refused with 401 for those requests.
- The generated key file and the database live in the same data volume, so a backup of the volume
  holds both and defeats the encryption: back up the database without `secret.key`, or keep
  `EXACTDOCS_SECRET_KEY` outside the volume. A key file that was readable by others is made
  private again but logged as exposed: rotate it. A symlink or a file of another user is refused.
- If the secret key is lost or changed, the library's docs stay available and adding a version
  answers `credentials_required`; send the credential again with the new version request.

ExactDocs reads repositories with the system `git` binary (in the Docker image; on `uvx` it must be
on `PATH`; without it the server still starts, logs a warning and repository checks answer
`git_not_installed`). URLs may be `https://`, `http://`, `ssh://`, `user@host:path` or `file://`;
credentials never go in the URL (they are refused, never echoed or logged), and
`POST /api/v1/repositories/check` runs git with prompts, user git config and ssh keys switched off
and a 15 s timeout. An import fetches only the pinned commit (no history, no unselected files) into
a temporary folder under the data directory (`work/`), with hooks, submodules and symlinks off; git
2.30 or newer is recommended, and a server without partial-clone support just sends more.

## Teams and access

Run one instance on PostgreSQL, sign in through OIDC/OAuth, and share libraries with users or
identity-provider groups:

| Role | Can |
|---|---|
| **viewer** | see the library in the UI and in MCP |
| **contributor** | also edit it: tags, paths, chunking, versions, re-sync |
| **admin** | also delete it and manage access |
| **creator** | the single owner (whoever created it): also remove admins and transfer ownership |

Who may create libraries is an instance-level permission mapped from users or IdP groups.
MCP tokens act as their user, so an agent sees exactly the libraries its user may view.
Libraries can also be declared in an `exactdocs.sources.yaml` in your own repo, and docs repos can
trigger a sync with a webhook on push.

```yaml
# docker-compose.yml
services:
  exactdocs:
    image: ghcr.io/sircypkowskyy/exactdocs:latest
    ports: ["3000:3000"]
    # The image runs as UID 10001 and needs nothing but /data and /tmp to be writable.
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { cpus: "2", memory: 1g }
    volumes: ["exactdocs-data:/data"]
    environment:
      EXACTDOCS_DATABASE_URL: postgresql://exactdocs:${DB_PASSWORD}@db:5432/exactdocs
    depends_on: [db]
  db:
    image: paradedb/paradedb:latest   # PostgreSQL with pg_search (BM25) and pgvector
    environment:
      POSTGRES_USER: exactdocs
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: exactdocs
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes:
  exactdocs-data:
  pgdata:
```

## How it works

```
 Agent (Claude Code, Cursor, ChatGPT, ...)        Browser
        │  MCP (HTTP / stdio)                         │
        ▼                                             ▼
┌───────────────────────────────────────────────────────────┐
│ ExactDocs (one image)                                     │
│  FastAPI ── FastMCP ── Web UI (static build)              │
│        │                                                  │
│  Retrieval: version filter → BM25 [+ vectors/HyDE]        │
│             [→ rerank]  or  agentic tree search           │
│        │                                                  │
│  Import: git fetch (ref, paths) → parse → chunk by        │
│          headings → index [→ embed]                       │
└───────────────┬───────────────────────────┬───────────────┘
                ▼                           ▼
     SQLite or PostgreSQL          optional model endpoints
                                   (embeddings, reranker, LLM)
```

## Privacy and observability

ExactDocs makes no outbound connections you did not configure: only your git hosts, your model
endpoints and, if enabled, your OpenTelemetry collector. No analytics, no update checks.
Telemetry and the Prometheus endpoint are **off by default**; query text is never exported
unless you opt in.

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.14), Node 26 LTS, pnpm 12,
[just](https://just.systems).

```bash
git clone https://github.com/SirCypkowskyy/ExactDocs && cd ExactDocs
just setup        # Python workspace + web dependencies
just dev          # API + MCP on :3000, UI on :5173
just check        # everything CI runs
```

Stack: Python (FastAPI, FastMCP, pydantic-ai), React (TanStack Router and Query, shadcn/ui),
SQLite or PostgreSQL. The production image serves the built frontend from the backend, so there
is a single service to run.

```
exactdocs/
├── packages/
│   ├── exactdocs/          # the app: one folder per domain + bootstrap (composition root)
│   └── exactdocs-kernel/   # shared kernel used by every domain
├── web/                    # React UI (vertical slices)
├── deploy/                 # Dockerfile, self-hosted runner scripts
├── docs/                   # documentation site (Zensical)
└── .agents/skills/         # how agents work on issues, test and release
```

Read [docs/architecture.md](docs/architecture.md) (modular monolith, ports & adapters) and
[docs/releasing.md](docs/releasing.md) (branches, versions, tags) before contributing.

## Roadmap

**MVP-1: the main loop, one admin user, no external services**

- [ ] First-run admin account, API tokens, CLI as a REST client
- [ ] Add a library from any git URL (public or private), choose ref and paths, import
- [ ] Header-based chunking (Chonkie), front-matter and path-rule tags, BM25 search pinned to a version
- [ ] Web UI: library list, article tree, rendered Markdown, version switcher, search
- [ ] MCP tools, including context7-compatible `resolve-library-id` and `query-docs`
- [ ] Re-sync, removal, graceful sync failures, one-command Docker / `uvx` start

**MVP-2: polish**

- [ ] Import preview, `context7.json`, custom chunking, manual tags, images, relative links
- [ ] Search across all libraries, auto-import of new tags, resumable imports, upgrades without re-import
- [ ] `ctx7`-style CLI commands, REST API equivalents, `exactdocs config --client ...`

**Next**

- [ ] Optional embeddings (hybrid search), reranker, LLM with HyDE
- [ ] Agentic tree retrieval with a pydantic-ai agent and a query cache
- [ ] Retrieval eval suite (Pydantic Evals) comparing modes
- [ ] MCP Apps (rendered articles in Claude / ChatGPT)
- [ ] PostgreSQL, OIDC/OAuth, sharing with viewer / contributor / admin / creator roles
- [ ] `exactdocs.sources.yaml`, webhooks, OpenTelemetry and Prometheus metrics

**Later**

- [ ] `llms.txt` and website crawling, package-registry and lockfile resolution
- [ ] Prebuilt index snapshots, more formats (reST, AsciiDoc, notebooks)

## Contributing

Contributions are welcome. Please open an issue (Feature or Bug template) before large changes.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. Imported documentation remains under the license of its original repository.
