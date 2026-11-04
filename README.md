# ExactDocs

**Self-hosted, version-accurate documentation for AI coding agents.**
Point ExactDocs at a git repository, pick the Markdown docs you care about, and browse and search
them in a web UI and from your AI agent over MCP, pinned to the exact tag, branch or commit you
imported. A drop-in, self-hosted alternative to context7.

> **Status: MVP-1 is released (v0.2.0).** The main loop works end to end for one admin user with
> no external services: add a library from a git URL, import it, browse and search it in the web
> UI, over REST and over MCP. Everything marked *planned* below is not built yet; see the
> [Roadmap](#roadmap) and the [user stories](https://sircypkowskyy.github.io/ExactDocs/user-stories/).

---

## Why ExactDocs

- **Your docs, from your repos.** GitHub, Bitbucket, GitLab, Gitea or any git server, public or
  private. You choose the folders and files; ExactDocs imports only those.
- **Version is a hard filter.** Every library version is a git ref resolved to a commit SHA. Ask
  about `v1.3` and you get `v1.3` or an explicit "no result", never a plausible answer from `v1.4`.
- **Verbatim, with sources.** Results are the original Markdown with path, heading, commit SHA and
  a link to the file on your git host. Nothing is paraphrased.
- **Lightweight by default.** No bundled models. It is a fast BM25 server (SQLite FTS5); optional
  embedding, reranker and LLM endpoints are planned.
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

`uvx exactdocs serve` needs `git` on your `PATH` and refuses to start without it (the import runs
`git`). Python 3.14 is fetched by `uv` when it is missing; SQLite 3.35 or newer is required (uv's
Python and the Docker image have it, otherwise ExactDocs refuses to start). Then open <http://localhost:3000>. For an
agent that only reads an existing database, `uvx exactdocs serve --stdio` needs no `git` and no port.

A fresh instance offers nothing but its setup: until the first admin account exists, every
`/api/v1` request is refused with `403 setup_required`. Open <http://localhost:3000> and create the
admin on the setup page, or from the command line, or over the API:

```bash
docker exec -it exactdocs exactdocs admin create   # prompts for username and password
# or, without Docker
uvx exactdocs admin create
# or, over the API (the password must be 12 to 1024 characters)
curl -X POST http://localhost:3000/api/v1/setup -H 'content-type: application/json' \
  -d '{"username": "ada", "password": "a long passphrase"}'
```

### Use the CLI against an instance

The other commands are clients of the REST API, so they work against any instance you can reach:

```bash
uvx exactdocs login https://docs.example.com    # asks for username and password
echo "$TOKEN" | uvx exactdocs login https://docs.example.com --token-stdin   # reuse an API token
EXACTDOCS_TOKEN=exd_... uvx exactdocs login https://docs.example.com         # same, from the env
uvx exactdocs logout                            # forget the stored credentials
```

`login` creates an API token named after your machine and stores the server URL and token in
`config.json` in your user config directory (mode 0600; the token is never printed). The new token
**expires after 90 days**; change that with `--expires-in DAYS`, or use `--no-expiry` for a token
that lives until you revoke it in the web UI. Prefer `--token-stdin` or `EXACTDOCS_TOKEN` over
`--token`, which ends up in your shell history and in `ps`. `logout` only forgets the credentials
locally: the token stays valid on the server until you revoke it in the web UI (Tokens).

Resolution order: flags, then `EXACTDOCS_URL` / `EXACTDOCS_TOKEN`, then that file. A stored token is
only used for the server it came from. Plain `http://` is accepted for loopback (`localhost`,
`127.0.0.1`, `::1`) only; anything else needs `https://`. Proxy variables (`HTTPS_PROXY`, ...) are
honoured for remote servers (the proxy sees where you connect, not your https traffic) and ignored
for loopback. `serve` and `admin ...` stay local: they open the database directly.

Manage libraries and tokens from the same login (every command takes `--url`/`--token` and, for
scripts, `--json`; progress of `--wait` goes to stderr):

```bash
uvx exactdocs add https://github.com/acme/docs --ref v1.4.0 --path docs/ --exclude docs/archive/ --wait
uvx exactdocs add https://github.com/acme/docs --id /acme/docs --tag-rule 'docs/api/**=api'
uvx exactdocs libraries --json
uvx exactdocs version add /acme/docs v1.5.0 --wait
uvx exactdocs sync /acme/docs --wait             # re-syncs the branch versions
uvx exactdocs remove /acme/docs/v1.4.0           # asks first; --yes skips the question
uvx exactdocs remove /acme/docs --yes
uvx exactdocs add git@github.com:acme/private.git --ssh-key ./deploy_key
uvx exactdocs token create ci --expires-in 30    # asks for your password
uvx exactdocs token list
uvx exactdocs token revoke 0198f2c1
```

Exit codes: 0 done, 1 other failure, 2 usage or rejected input (also: `remove` without a terminal
and without `--yes`), 3 not found, 4 conflict (an import is running, the ID is taken), 5 not signed
in or refused, 6 an import or a sync failed (or `--wait` lost track of it), 130 interrupted.

`--wait` only watches: it follows an import for `--wait-timeout` seconds (default 600) and retries
a poll that hiccups. When it times out, loses track or you press Ctrl-C (exit 130), it says so and
the job keeps running on the server.

Setting a private repository's credential (`--git-token-file`, `--ssh-key`; a token or key is read
from a file of at most 64 KB, never from the command line; group- or world-readable files get a
warning) and all `token` commands need **your password**, not an
API token. REST only lets a signed-in session do that, so that a leaked token cannot mint itself a
successor or replace a repository credential; the CLI signs in for the one command and signs out
(`--username`, `--password-stdin`); `--token` is ignored for such a command. The CLI's own `--token` is the API token, which is why the
repository token is `--git-token-file`.

### Connect an MCP client

```bash
uvx exactdocs config --client claude            # claude, claude-desktop, cursor, vscode, codex
uvx exactdocs config --client codex --stdio     # local, read-only, no token
uvx exactdocs skill > SKILL.md                  # the agent usage skill (also the MCP resource skill://exactdocs/SKILL.md)
```

`config` prints a snippet to paste into the client's config file. It never contains your token:
it refers to `EXACTDOCS_TOKEN` (or, for VS Code, asks for it) unless you pass `--show-token`.
Claude Desktop reaches HTTP servers through `mcp-remote` (pinned to `0.16.0`); replace the
`<your-exactdocs-token>` placeholder there with your token. Desktop apps often lack `~/.local/bin`
on their PATH: put the absolute paths from `which uvx` / `which npx` in `command`. With
`--show-token` the snippet holds your real token, so never commit the file it goes into (the
command warns on stderr). Prefer `--new-token`: it creates a token just for this client (asks for
your password, like `token create`), so revoking it breaks nothing else.

### From `docker run` to a searchable library

The same flow CI runs on every change ([`deploy/smoke.sh`](deploy/smoke.sh), `sh` and `curl`
only, against a fixture repository instead of a URL), in well under five minutes, with no model
and no API key. It imports [encode/httpx](https://github.com/encode/httpx) at tag `0.28.1`, so the
machine needs outbound access to GitHub (CI does not). Create the admin as above, or over the API
(step 1):

```bash
docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data ghcr.io/sircypkowskyy/exactdocs:latest
H='content-type: application/json'; U=http://localhost:3000
curl -X POST $U/api/v1/setup -H "$H" -d '{"username":"ada","password":"a long passphrase"}'    # 1. admin
curl -c jar.txt $U/api/v1/session -H "$H" -d '{"username":"ada","password":"a long passphrase"}' # 2. sign in
curl -b jar.txt $U/api/v1/tokens -H "$H" -d '{"name":"laptop"}'                                  # 3. token (shown once)
curl -b jar.txt $U/api/v1/libraries -H "$H" \
  -d '{"url":"https://github.com/encode/httpx","ref":"0.28.1","include_paths":["docs/"]}'         # 4. add; returns job_id
curl -b jar.txt $U/api/v1/jobs/<job_id>                                                          # 5. until "succeeded"
TOKEN=<token from step 3>; A="authorization: Bearer $TOKEN"   # reads below use the token, as an agent would
curl -H "$A" "$U/api/v1/libraries/encode/httpx/articles?ref=0.28.1"                              # 6. list ...
curl -H "$A" -G "$U/api/v1/libraries/encode/httpx/article" -d ref=0.28.1 -d path=docs/index.md   # ... and read
curl -H "$A" -G "$U/api/v1/libraries/encode/httpx/search" -d ref=0.28.1 -d q=timeout             # 7. search
```

8. Point your agent at `http://localhost:3000/mcp` with the token ([Connect your agent](#connect-your-agent))
   and call `query-docs` with `libraryId` `/encode/httpx/0.28.1`.

`admin create` opens the database directly (so it works before the server is up, and against the
same data directory) and, for scripts, reads the password from stdin with `--password-stdin`.
Passwords are stored as argon2id hashes.

The web UI signs the admin in with `POST /api/v1/session`: an HttpOnly, SameSite=Lax cookie that
ends after 7 days without use or 30 days at most, and that only works on `/api` (never on `/mcp`).
Lost the password? Run `exactdocs admin reset-password` on the machine (same options as
`admin create`): it sets a new password, signs the admin out everywhere and revokes
the API tokens.

Then add your first library in the UI (**Add library**: URL, ref, paths) or over REST, as in the
walkthrough above. The import runs as a background job whose progress, skipped files and problems
the UI shows. ExactDocs splits every article by its headings; a branch version is re-synced on
demand and re-chunks only the files that changed. The command line does the same (see
[Use the CLI against an instance](#use-the-cli-against-an-instance)). Also planned: a preview of matching
files before importing, auto-import of new tags, and pre-selection from a repository's
`context7.json`. See the [Roadmap](#roadmap).

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
moment they are revoked. Create, list and revoke them on the **Account** page of the web UI, or
over the REST API with your signed-in session (the token routes do not accept a token, so a leaked
token cannot mint successors):

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

Planned (MVP-2): `exactdocs token create` and `exactdocs config --client claude|cursor|vscode`,
which will print a ready-to-paste snippet with a new token.

#### Without a network port: stdio

```json
{
  "mcpServers": {
    "exactdocs": { "command": "uvx", "args": ["exactdocs", "serve", "--stdio"] }
  }
}
```

stdio needs no token and no running server, but it needs an **existing database**: run
`exactdocs serve` (or `exactdocs admin create`) once first. Otherwise it exits with an error on
stderr naming the expected path. It uses the same data directory (`EXACTDOCS_DATA_DIR`), opens the
SQLite file read-only (`mode=ro` and `query_only`, safe next to a running server, which keeps
importing), runs no worker, no identity and no migration, and exposes the same read-only tools. If the server has since been upgraded and
migrated the database, upgrade the stdio command too. Manage libraries through the server. Run it as the same user as the server: with the server
stopped, SQLite creates `exactdocs.db-wal` and `-shm` next to the database (the directory must be
writable for that), and files owned by another user can stop the server from starting later.
`--host`, `--port` and `--reload` are HTTP-only and rejected with `--stdio`.

## MCP tools

| Tool | Purpose |
|---|---|
| `resolve-library-id(libraryName, query)` | context7-compatible: find a library ID such as `/acme/payments` |
| `query-docs(libraryId, query, language?)` | context7-compatible: documentation for `/owner/repo` (default version) or `/owner/repo/<ref>` (exactly that version, never another). Returns whole chunks, best first, within a size budget; `language` moves chunks with code in it first (it does not filter) |
| `list_libraries(limit?, cursor?)` | Libraries and imported versions (`refs`: ref, kind, commit SHA, default flag) |
| `list_articles(library, ref?, path_prefix?, tags?, tags_match?, limit?, cursor?)` | The article tree of a version |
| `read_article(library, ref?, path)` | A full article, verbatim; an unknown path lists close matches |
| `search_docs(library, query, ref?, tags?, tags_match?, limit?, mode?)` | Search one version; results carry location, neighbors (`prev_chunk_id` / `next_chunk_id`), `coverage` and the retrieval mode used (`bm25` is the only one; any other `mode` is an error listing the available ones) |
| `search_all_docs(query, library?, tags?, tags_match?, limit?)` | Search the default version of every library at once; each result names its library and version, `libraries` counts matches per library; at most 500 libraries are searched and `libraries_omitted` says how many were left out (REST: `GET /api/v1/search`) |
| `read_chunk(chunk_id)` | One chunk verbatim, e.g. a neighbor of a search result; a chunk ID from before a re-sync answers `stale_chunk` |

Library IDs are `/owner/repo`; without a ref, a library's **default version** is used (the highest imported stable semver tag, else the default branch, else the most recently imported version, unless pinned), and every response
says which version answered. Every tool's output starts with a notice that the content is
external data, never instructions. Planned: hosts that support MCP Apps (Claude, ChatGPT) will
render articles and results as UI.
All tools are read-only, and everything returned is marked as external content.

### context7 over REST

The same two operations for integrations that do not speak MCP, with context7's parameter
names and shapes (same use cases, budget and API tokens as the tools above). Only the paths
differ; there is no `/api/v2` alias:

| context7 | ExactDocs | Same as |
|---|---|---|
| `GET /api/v2/libs/search?libraryName=&query=` | `GET /api/v1/c7/search?libraryName=&query=` | `resolve-library-id` |
| `GET /api/v2/context?libraryId=&query=&language=&type=` | `GET /api/v1/c7/docs?libraryId=&query=&language=&type=` | `query-docs` |

```bash
curl -H "Authorization: Bearer $EXACTDOCS_TOKEN" \
  "http://localhost:3000/api/v1/c7/search?libraryName=react&query=hooks"
curl -H "Authorization: Bearer $EXACTDOCS_TOKEN" \
  "http://localhost:3000/api/v1/c7/docs?libraryId=/facebook/react&query=useEffect&type=json"
```

- Search returns JSON `{results: [{id, title, description, branch, versions, ...}],
  searchFilterApplied}`.
- Docs with `type=txt` (default) returns the notice, a blank line, then the tool's text byte for
  byte; `type=json` returns `infoSnippets` (one per chunk; `codeSnippets` is always empty).
- `libraryId` takes `/owner/repo`, `/owner/repo/<ref>` and context7's `/owner/repo@<ref>`.
- `language` moves chunks with code in it first (it does not filter). context7's `fast` is
  accepted and ignored: nothing here is reranked by an LLM.
- Both mark their content as untrusted: JSON carries `notice`, the text starts with it and also
  carries it in the `X-ExactDocs-Notice` header.
- Errors are `{error, detail, message}`: `message` repeats `detail` for context7 clients.

## Retrieval

Today every search is **BM25** on SQLite FTS5, pinned to one version, with identifiers indexed whole
and by their parts (`camelCase`, `snake_case`, `pkg.mod.fn`). The pipeline is built to upgrade
itself to whatever you configure; the rows below that need an endpoint are **planned**
([Roadmap](#roadmap)), and [Flows](https://sircypkowskyy.github.io/ExactDocs/flows/) draws how
the mode is chosen.

| Configured | Retrieval | Status |
|---|---|---|
| nothing | BM25 | **available** |
| reranker | BM25 → rerank | planned |
| embedding model | hybrid: BM25 + vector search | planned |
| embedding model + reranker | hybrid → rerank | planned |
| embedding model + LLM (+ reranker) | hybrid with HyDE → rerank (the default when everything is configured) | planned |
| LLM + agentic mode | a pydantic-ai agent browses the documentation tree and returns the articles that answer the question, with a justification; similar past questions are served from a cache | planned |

Articles are chunked by Markdown headings with [markdown-it-py](https://github.com/executablebooks/markdown-it-py),
never splitting code blocks or tables (Chonkie was dropped: its Markdown recipe needs the Hugging
Face Hub and the network, which a model-free, offline-capable image cannot have). Articles are
tagged from front matter and path rules, and listings and search filter by tag.
Per-library split level and chunk sizes, and manual tags, are planned (MVP-2).

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
| `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET` | `10000` | Size of one whole `query-docs` answer, notice included, in tokens counted as characters / 4 (undercounts CJK text and dense code); at least `500`. Only whole chunks are returned: one too large for the budget is listed as a pointer to fetch with `read_chunk`, and a last line says how many matching chunks were left out |
| `EXACTDOCS_HOST`, `EXACTDOCS_PORT` | `127.0.0.1`, `3000` | Address `serve` binds (the Docker image binds `0.0.0.0`); `--host` / `--port` override them |
| `EXACTDOCS_MAX_ARTICLE_BYTES` | `2097152` (2 MiB) | An import skips a file above this size, unread, and reports it as `too_large` |
| `EXACTDOCS_MAX_IMPORT_BYTES` | `268435456` (256 MiB) | An import whose selected text adds up to more fails with `import_too_large` instead of exhausting memory |

**Planned, not read by this version:** `EXACTDOCS_EMBEDDING_*`, `EXACTDOCS_RERANKER_*` and
`EXACTDOCS_LLM_*` (optional model endpoints), `EXACTDOCS_RETRIEVAL_MODE` (`auto`, `bm25`, `hybrid`,
`hybrid_hyde`, `agentic`), `EXACTDOCS_TELEMETRY` (`otlp`) and `EXACTDOCS_METRICS` (Prometheus at
`/metrics`). The two telemetry switches exist in the settings model but nothing consumes them yet.

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
on `PATH`; `exactdocs serve` refuses to start without it. Only where that check is skipped, such as
`--stdio` (which never imports), a missing git is a warning and repository checks answer
`git_not_installed`). URLs may be `https://`, `http://`, `ssh://`, `user@host:path` or `file://`;
credentials never go in the URL (they are refused, never echoed or logged), and
`POST /api/v1/repositories/check` runs git with prompts, user git config and ssh keys switched off
and a 15 s timeout. An import fetches only the pinned commit (no history, no unselected files) into
a temporary folder under the data directory (`work/`), with hooks, submodules and symlinks off; git
2.30 or newer is recommended, and a server without partial-clone support just sends more.

## Teams and access (planned)

MVP-1 has one admin account on SQLite. For teams, the plan is to run one instance on PostgreSQL, sign in through OIDC/OAuth, and share libraries with users or
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

A hardened single-container deployment that works today (the image runs as UID 10001 and needs
nothing but `/data` and `/tmp` to be writable; CI runs it this way):

```yaml
# docker-compose.yml
services:
  exactdocs:
    image: ghcr.io/sircypkowskyy/exactdocs:latest
    ports: ["3000:3000"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { cpus: "2", memory: 1g }
    volumes: ["exactdocs-data:/data"]
volumes:
  exactdocs-data:
```

## How it works

```mermaid
flowchart TD
    agent["AI agent<br/>Claude Code, Cursor, ChatGPT, ..."]
    browser[Browser]
    subgraph app ["ExactDocs (one image, one process)"]
        mcp["FastMCP<br/>/mcp (HTTP) or stdio"]
        api["FastAPI<br/>/api/v1"]
        ui["Web UI<br/>static build"]
        retrieval["Retrieval<br/>version filter → BM25"]
        catalog["Catalog<br/>libraries, versions, manifests"]
        importer["Importer and job worker<br/>fetch → parse → chunk → index → activate"]
        identity["Identity<br/>admin, sessions, API tokens"]
        mcp --> retrieval & catalog
        api --> retrieval & catalog & importer & identity
        importer --> catalog & retrieval
    end
    db[("SQLite in the data directory<br/>PostgreSQL planned")]
    git[("Git hosts you configure<br/>GitHub, GitLab, Bitbucket, ...")]
    models[/"Optional model endpoints<br/>embeddings, reranker, LLM (planned)"/]
    agent -->|MCP| mcp
    browser --> ui
    browser -->|REST| api
    app --> db
    importer -->|git fetch of the pinned commit| git
    retrieval -.-> models
```

## Privacy and observability

ExactDocs makes no outbound connections you did not configure: only your git hosts, your model
endpoints (planned). No analytics, no update checks. OpenTelemetry export and the Prometheus
endpoint are planned and off; nothing in this version sends or exposes telemetry.

This is tested, not just promised, in
[`test_no_outbound.py`](packages/exactdocs/tests/bootstrap/test_no_outbound.py): an import over
git/HTTP, REST search and both MCP search tools run with FastMCP's update check forced off and
no telemetry configured. What that proves, exactly:

- **Observed:** every Python socket and name lookup goes through a guard that refuses anything
  but loopback. Where unprivileged user namespaces exist (`unshare -rn`), the same loop and a
  redirect to another host also run in a network namespace with only loopback, so the kernel
  itself blocks anything else, git included. Elsewhere that check is skipped.
- **Only pinned:** where it is skipped, git (a child process) is checked by what it was *told*:
  the only URL is the fixture server, the protocols are restricted, no ssh is started.
- git follows an HTTP redirect from your git host, and honours `HTTP(S)_PROXY`/`ALL_PROXY`
  when set (traffic then goes to that proxy). The test runs without proxy variables.

The web UI bundles its fonts; `pnpm build` fails if the built HTML, CSS or any JS chunk names
another host ([`web/scripts/check-dist.mjs`](web/scripts/check-dist.mjs)).

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.14), Node 26 LTS, pnpm 12,
[just](https://just.systems).

```bash
git clone https://github.com/SirCypkowskyy/ExactDocs && cd ExactDocs
just setup        # Python workspace + web dependencies
just dev          # API + MCP on :3000, UI on :5173
just check        # everything CI runs
```

Stack: Python (FastAPI, FastMCP), React (TanStack Router and Query, shadcn/ui), SQLite
(PostgreSQL and pydantic-ai are planned). The production image serves the built frontend from the backend, so there
is a single service to run.

| Path | What |
|---|---|
| `packages/exactdocs/` | the app: one folder per domain plus `bootstrap` (composition root) |
| `packages/exactdocs-kernel/` | shared kernel used by every domain |
| `web/` | React UI (vertical slices) |
| `deploy/` | Dockerfile, smoke test, size budgets, self-hosted runner scripts |
| `docs/` | documentation site (Zensical) |
| `.agents/skills/` | how agents work on issues, test and release |

Read [docs/architecture.md](docs/architecture.md) (modular monolith, ports & adapters) and
[docs/releasing.md](docs/releasing.md) (branches, versions, tags) before contributing.

## Roadmap

**MVP-1: the main loop, one admin user, no external services** (released as v0.2.0)

- [x] First-run admin account, sessions, API tokens (CLI as a REST client moved to MVP-2)
- [x] Add a library from any git URL (public or private), choose ref and paths, import
- [x] Header-based chunking (markdown-it-py), front-matter and path-rule tags, BM25 search pinned to a version
- [x] Web UI: setup and sign-in, library list, article tree, rendered Markdown, version switcher, search, tokens
- [x] MCP tools, including context7-compatible `resolve-library-id` and `query-docs`
- [x] Re-sync, removal, graceful sync failures, one-command Docker / `uvx` start

**MVP-2: polish**

- [ ] Import preview, `context7.json`, custom chunking, manual tags, images, relative links
- [ ] Search across all libraries, auto-import of new tags, resumable imports, upgrades without re-import
- [ ] The CLI as a REST client (`login`, `add`, `sync`, `token`), `ctx7`-style commands, REST API equivalents, `exactdocs config --client ...`

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
