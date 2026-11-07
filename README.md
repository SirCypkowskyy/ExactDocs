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
  the git hosts, model endpoints and (opt-in) trace collector you configure.

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
for loopback. `serve`, `reindex`, `backup`, `restore` and `admin ...` stay local: they open the
database directly.

Manage libraries and tokens from the same login (every command takes `--url`/`--token` and, for
scripts, `--json`; progress of `--wait` goes to stderr):

```bash
uvx exactdocs add https://github.com/acme/docs --ref v1.4.0 --path docs/ --exclude docs/archive/ --wait
uvx exactdocs add https://github.com/acme/docs --id /acme/docs --tag-rule 'docs/api/**=api'
uvx exactdocs add https://github.com/acme/docs --ref v1.4.0 --path 'docs/**' --dry-run  # lists the files, stores nothing
uvx exactdocs libraries --json
uvx exactdocs version add /acme/docs v1.5.0 --wait
uvx exactdocs sync /acme/docs --wait             # re-syncs the branch versions, checks the tags
uvx exactdocs sync /acme/docs --confirm --wait   # also re-imports every tag that moved upstream
uvx exactdocs sync /acme/docs --confirm-tag v1.4.0  # ... or only the moved tags named
uvx exactdocs remove /acme/docs/v1.4.0           # asks first; --yes skips the question
uvx exactdocs remove /acme/docs --yes
uvx exactdocs add git@github.com:acme/private.git --ssh-key ./deploy_key
uvx exactdocs token create ci --expires-in 30    # asks for your password
uvx exactdocs token list
uvx exactdocs token revoke 0198f2c1
```

See what an agent would get, with the commands and flags of `ctx7` (`library <name> [query]`,
`docs <libraryId> <query> [--language L] [--json]`):

```bash
uvx exactdocs library acme "retry policy"
uvx exactdocs docs /acme/docs "retry policy"
uvx exactdocs docs /acme/docs@v1.4.0 "retry policy" --language go --json
```

Differences from `ctx7`: the output starts with the untrusted-content notice (with `--json` of
`library` the notice goes to stderr so stdout stays the plain list); control characters are
stripped; failures go to stderr with the exit codes below (ctx7: stdout, always 1); the query may
be given as several words; a library lists its default version, articles and chunks (no stars or
trust score); there is no `ctx7 search` yet (it needs a search-all REST route).

Exit codes: 0 done, 1 other failure, 2 usage or rejected input (also: `remove` without a terminal
and without `--yes`), 3 not found, 4 conflict (an import is running, the ID is taken), 5 not signed
in or refused, 6 an import or a sync failed (or `--wait` lost track of it), 130 interrupted.
A sync that fails says why with a stable code, and every version keeps serving what it had:
`repo_unreachable` (deleted, private or down), `auth_failed` (the token or key was refused),
`ref_deleted` (the branch or tag is gone) or `tag_moved` (the tag points elsewhere now; a sync
never re-imports it: `--confirm` (every moved tag) or `--confirm-tag REF` does, at the new commit,
and prints each tag's old and new commit). The same codes are on the jobs
(`error_code`).

`--wait` only watches: it follows an import for `--wait-timeout` seconds (default 600) and retries
a poll that hiccups. When it times out, loses track or you press Ctrl-C (exit 130), it says so and
the job keeps running on the server.

`add --dry-run` sends the URL, `--ref`, `--path` and `--exclude` (and a credential) to
`POST /repositories/preview` instead and prints the files the import would take, how many there
are and, past 1000, `truncated`; nothing is stored. `--id` and `--wait` have no effect, and
`--tag-rule` is only checked, so a malformed rule fails the dry run as it would fail `add`. There are no file sizes: knowing them would mean downloading every file. A server running
as many previews as it allows answers "try again" (exit 1).

In the web UI, **Preview** on the add-library form does the same: it shows the matching files as a
folder tree with counts, what the repository's `context7.json` says (its paths fill the empty path
boxes, still editable) and its `previousVersions` as checkboxes; the ticked tags are imported
after the library is added.

For a private repository, tick **This repository is private** on the same form and give an access
token (https address; optionally the user name the host expects, `x-token-auth` for Bitbucket) or a
deploy key without a passphrase (ssh address; paste it or choose the key file). The check, the
branch and tag list (`POST /repositories/refs`), the preview and the add all send it in the request
body; the form keeps it in memory only and drops it once the library is added. For an ssh address
the check shows the server's host-key fingerprint: compare it with the one your git host publishes
before you add the library. On a library's settings page, **Add a version** of a private library
takes a replacement token or key, which is what to do when the stored one can't be read any more
(`credentials_required`, after the secret key changed) or was refused.

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
uvx exactdocs skill                             # prints the agent usage skill; redirect it to a SKILL.md
                                                # (also the MCP resource skill://exactdocs/SKILL.md)
```

`config` prints a snippet to paste into the client's config file. It never contains your token:
it refers to `EXACTDOCS_TOKEN` (or, for VS Code, asks for it) unless you pass `--show-token`.
Claude Desktop reaches HTTP servers through `mcp-remote` (pinned to `0.16.0`); replace the
`<your-exactdocs-token>` placeholder there with your token. Desktop apps often lack `~/.local/bin`
on their PATH: put the absolute paths from `which uvx` / `which npx` in `command`. With
`--show-token` the snippet holds your real token, so never commit the file it goes into (the
command warns on stderr). Prefer `--new-token`: it creates a token just for this client (asks for
your password, like `token create`), so revoking it breaks nothing else. It is named
`mcp-<client>` (`--name` changes that) and expires after 90 days (`--expires-in`); the command
prints its id on stderr, for `exactdocs token revoke <id>`.

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
Passwords are stored as argon2id hashes, and at most 4 are checked at once.

Failed sign-ins are throttled, on the web UI's sign-in and `exactdocs login` alike. Every
attempt counts against its client address (IPv6: its /64) and its username at once, before the
password is checked, so a burst of concurrent guesses gets no more tries than guesses sent one
by one. After 5 attempts that did not succeed, each further one must wait (5 seconds, doubling up
to 15 minutes) and is answered 429 `rate_limited` with a `Retry-After` header meanwhile. A right
password takes its own attempt back (without restarting the address's wait) and clears its
username's count. An address that has signed
into a username in the last 30 days is held to its own count only, not to the username's, so
others failing for the admin's username cannot lock the admin out of a machine they already
use; a new address still waits. Behind a reverse proxy, list it in
`EXACTDOCS_FORWARDED_ALLOW_IPS`, so the throttle counts the client's address rather than the
proxy's. The counts are kept in the server's memory: restarting the server clears them, and
nothing else does (`admin reset-password` runs in another process and cannot).

The web UI signs the admin in with `POST /api/v1/session`: an HttpOnly, SameSite=Lax cookie that
ends after 7 days without use or 30 days at most, and that only works on `/api` (never on `/mcp`).
Lost the password? Run `exactdocs admin reset-password` on the machine (same options as
`admin create`): it sets a new password, signs the admin out everywhere and revokes
the API tokens. If sign-ins are throttled meanwhile (429), restart the server to clear the
throttle.

Then add your first library in the UI (**Add library**: URL, ref, paths) or over REST, as in the
walkthrough above. The import runs as a background job whose progress, skipped files and problems
the UI shows. ExactDocs splits every article by its headings; a branch version is re-synced on
demand and re-chunks only the files that changed. The command line does the same (see
[Use the CLI against an instance](#use-the-cli-against-an-instance)). A repository's root
`context7.json` pre-fills the library: added without paths, it takes its folders and exclusions,
its title and description win over the README's, and its rules come first in every `query-docs`
answer (details in [docs/rest-api.md](docs/rest-api.md)). Also planned: auto-import of new tags.
See the [Roadmap](#roadmap).

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
| `query-docs(libraryId, query, language?)` | context7-compatible: documentation for `/owner/repo` (default version) or `/owner/repo/<ref>` (exactly that version, never another). Returns whole chunks, best first, within a size budget; `language` moves chunks with code in it first (it does not filter). The library's `context7.json` rules, if any, come first |
| `list_libraries(limit?, cursor?)` | Libraries and imported versions (`refs`: ref, kind, commit SHA, default flag) |
| `list_articles(library, ref?, path_prefix?, tags?, tags_match?, limit?, cursor?)` | The article tree of a version |
| `read_article(library, ref?, path)` | A full article, verbatim; an unknown path lists close matches |
| `search_docs(library, query, ref?, tags?, tags_match?, limit?, mode?)` | Search one version; results carry location, neighbors (`prev_chunk_id` / `next_chunk_id`), `coverage`, the retrieval mode that answered (`retrieval_mode`, `reranked`) and, when a cheaper mode answered, `fallback_reason`. Without `mode` the library's mode is used, else the instance's, else the best one configured; asking for a mode that is not available is an error (`mode_unavailable`) naming the missing model role and listing the available modes (see [Retrieval](#retrieval)) |
| `search_all_docs(query, library?, tags?, tags_match?, limit?)` | Search the default version of every library at once; each result names its library and version, `libraries` counts matches per library; at most 500 libraries are searched and `libraries_omitted` says how many were left out (REST: `GET /api/v1/search`) |
| `read_chunk(chunk_id)` | One chunk verbatim, e.g. a neighbor of a search result; a chunk ID from before a re-sync answers `stale_chunk` |
| `article_outline(library, path, ref?)` | An article's heading tree with the chunk ID of each heading (a heading merged into another's chunk points to that chunk) and no body text, to see what it covers before reading it (REST: `GET /api/v1/libraries/{owner}/{repo}/outline?path=&ref=`); a path the version lacks is `not_found` |

Library IDs are `/owner/repo`; without a ref, a library's **default version** is used (the highest imported stable semver tag, else the default branch, else the most recently imported version, unless pinned), and every response
says which version answered. Every tool's output starts with a notice that the content is
external data, never instructions. Planned: hosts that support MCP Apps (Claude, ChatGPT) will
render articles and results as UI.
All tools are read-only, and everything returned is marked as external content.

### MCP resources

Clients that browse resources read articles from the resource template
`exactdocs://{owner}/{repo}/{path*}{?ref}` (no `ref`: the default version). Percent-encode `ref`:
`/` is `%2F` and `+` is `%2B` (a bare `+` means a space and is refused, e.g. `?ref=v1.0.0%2Bbuild`).
`{path*}` is FastMCP's multi-segment match, not RFC 6570; `guide/a.md` and `guide%2Fa.md` read the
same article. Other aliases of one article: a mixed-case owner or repo (lowercased like library IDs),
percent-encoded letters and `./` segments; `../` never leaves the version's article tree. A repeated
`ref` is refused, and a missing library, version or article is JSON-RPC error `-32002`.

A read returns two items: the untrusted-content notice as `text/plain`, then the article as
`text/markdown`, byte for byte what `read_article` gives, with its ref, commit SHA and source link
in `_meta`. MCP does not say how clients present several items, so the leading notice is best
effort; the template description and the server instructions carry the notice too.

`resources/list` is a **truncated sample**: at most 200 articles of the libraries' default
versions, shared fairly across libraries, always with an explicit `?ref=`, sorted by URI and
paged (currently 50 per page; clients must not assume a page size) with a stable cursor. Every
page's `_meta` has `truncated` and `max_resources`. The list is rebuilt at most every 30 seconds.
Use the template or `list_articles` for the rest. Resources sit behind the same bearer token as
the tools and are served read-only over stdio.

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

Which mode answers a search: the call's `mode`, else the **library's** mode
(`PUT /api/v1/libraries/{owner}/{repo}/retrieval`), else the **instance's**
(`EXACTDOCS_AI__MODE`), else the best mode the configured models allow. The modes are
`bm25`, `hybrid` (needs an embedding model), `hybrid_hyde` (embedding model and LLM) and
`agentic` (LLM, never a default); reranking is a flag on top of any mode when a reranker is
configured. A call that asks for a mode that cannot run fails with `mode_unavailable`, naming the
missing model role; a library or instance mode that cannot run (its model was removed) never fails
a search: the next one answers, with `fallback_reason: mode_unavailable` (or
`vector_store_unavailable` when the hybrid modes cannot run because sqlite-vec cannot be loaded by
this Python; BM25 keeps answering). Setting a library's mode
is refused the same way when its model is not configured. Searching across libraries
(`search_all_docs`, `GET /api/v1/search`) and `resolve-library-id` stay BM25 whatever the library
and instance modes are: their scores must compare across libraries.

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
tagged from front matter and path rules, and by hand: the article page of the web UI shows each
tag under where it comes from and adds or removes manual tags, which hold for every version
(`PUT`/`DELETE /api/v1/libraries/{owner}/{repo}/tags?path=`). Listings and search filter by tag.
Each library chooses its split level (`h1`...`h6`) and chunk sizes (`max_chars` cuts long
sections again at deeper headings, `min_chars` merges tiny ones) with
`PUT /api/v1/libraries/{owner}/{repo}/settings` (left out, the stored chunking is kept); every
version is then re-chunked from the stored text, without fetching, and keeps serving its old
chunks until the new ones are in place.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `EXACTDOCS_DATA_DIR` | `/data` in the Docker image, else the platform user-data directory | Where ExactDocs keeps everything (the SQLite database, the generated secret key, `known_hosts`, fetch caches and `jobs.sqlite`, the durable steps of running imports; on PostgreSQL only `known_hosts` and fetch caches). Created if missing; the server refuses to start, naming the path, if it is not writable. `uvx` and stdio MCP use the same default path |
| `EXACTDOCS_DATABASE_URL` | `exactdocs.db` in the data directory | A SQLite file, e.g. `sqlite:////srv/exactdocs.db` (opened in WAL mode), or a PostgreSQL database, `postgresql://user:password@host:5432/exactdocs` (psycopg 3; see [PostgreSQL](#postgresql)). The schema is migrated on start and `/api/health` reports its revision (see [Upgrading](#upgrading)) |
| `EXACTDOCS_DBOS_SYSTEM_SCHEMA` | `dbos` | PostgreSQL only: the schema of the same database where DBOS keeps the durable steps of jobs (SQLite keeps them in `<data dir>/jobs.sqlite`) |
| `EXACTDOCS_SECRET_KEY` | generated into `<data dir>/secret.key` (mode 0600) on first run | Encrypts the stored tokens and deploy keys of private repositories (Fernet). It must be **random** and at least 32 characters: `openssl rand -base64 32` (it is stretched with HKDF, not a password hash, so a passphrase is not safe). Without it the credentials cannot be read: libraries keep serving their docs and ask for the token again (`credentials_required`) |
| `EXACTDOCS_SECRET_KEY_PREVIOUS` | – | Rotation: set the new key in `EXACTDOCS_SECRET_KEY` and the old one here. Credentials sealed with the old key still open and are sealed with the new one whenever they are sent again; remove this once they all were |
| `EXACTDOCS_ALLOWED_HOSTS` | – | Host names besides localhost the server answers to, comma-separated (e.g. `docs.example.com,*.corp.example`); needed behind a reverse proxy or on a LAN address |
| `EXACTDOCS_ALLOWED_ORIGINS` | – | Browser origins allowed to make state-changing requests, comma-separated |
| `EXACTDOCS_SECURE_COOKIES` | `false` | The session cookie is always `Secure` over HTTPS; set `true` when TLS ends at a proxy that does not forward `X-Forwarded-Proto` from a trusted address |
| `EXACTDOCS_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Proxies whose `X-Forwarded-*` headers are trusted (scheme, and the client address the sign-in throttle counts) |
| `EXACTDOCS_AI__MODE` | unset (`auto`) | The retrieval mode of searches that name none, for libraries without their own: `bm25`, `hybrid`, `hybrid_hyde` or `agentic`; unset or `auto`: the best mode the configured models allow (BM25 while none is). An unknown name stops the server at start; a mode whose model is not configured falls back with `fallback_reason: mode_unavailable` (see [Retrieval](#retrieval)) |
| `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET` | `10000` | Size of one whole `query-docs` answer, notice included, in tokens counted as characters / 4 (undercounts CJK text and dense code); at least `500`. Only whole chunks are returned: one too large for the budget is listed as a pointer to fetch with `read_chunk`, and a last line says how many matching chunks were left out |
| `EXACTDOCS_HOST`, `EXACTDOCS_PORT` | `127.0.0.1`, `3000` | Address `serve` binds (the Docker image binds `0.0.0.0`); `--host` / `--port` override them |
| `EXACTDOCS_MAX_ARTICLE_BYTES` | `2097152` (2 MiB) | An import skips a file above this size, unread, and reports it as `too_large` |
| `EXACTDOCS_MAX_IMPORT_BYTES` | `268435456` (256 MiB) | An import whose selected text adds up to more fails with `import_too_large` instead of exhausting memory |
| `EXACTDOCS_IMPORT_BATCH_FILES` | `100` | Files an import parses and chunks per durable step. An import that a crash, `kill -9` or a deploy interrupted resumes on the next start after its last completed step (DBOS keeps them in `<data dir>/jobs.sqlite`, or in the `dbos` schema on PostgreSQL: about 3x the version's text while the import runs, compacted once no job runs), so it loses at most this many files of work |
| `EXACTDOCS_JOB_POLL_SECONDS` | `1` | How often the job worker looks for a queued job to start (at most 60). An idle server polls no more often than this; lower it only if a second of delay before an import starts matters |
| `EXACTDOCS_TELEMETRY` | `off` | `otlp`: traces and metrics over OTLP/HTTP to your OpenTelemetry collector, named by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `..._METRICS_ENDPOINT`); a signal with no endpoint, or with `OTEL_TRACES_EXPORTER` / `OTEL_METRICS_EXPORTER` set to `none`, is not exported. See [Privacy and observability](#privacy-and-observability) |
| `EXACTDOCS_TELEMETRY_QUERY_TEXT` | `false` | Keep the text of search queries in the traces. Off, it is left out of every span and redacted from request URLs |
| `EXACTDOCS_METRICS` | `false` | `true`: Prometheus metrics at `/metrics` (requests, searches, imports, syncs; LLM usage once the AI retrieval modes exist), behind the Host allowlist; `serve` only, not `--stdio`. See [Privacy and observability](#privacy-and-observability) |
| `EXACTDOCS_METRICS_TOKEN` | – | A bearer token `/metrics` requires (`Authorization: Bearer <token>`, else 401). Unset, a scrape needs no credentials. Surrounding whitespace and newlines are trimmed, as Prometheus trims its `credentials_file`. Set it whenever the port is reachable beyond a network you trust |
| `EXACTDOCS_AUTO_SYNC_SCHEDULE` | `0 * * * * *` | When the scheduled check ticks (a DBOS cron expression, seconds first). Each tick checks the libraries whose own interval is up (`PUT /api/v1/libraries/{owner}/{repo}/auto-sync`): new matching tags imported, old automatic versions pruned, branches re-synced. Paused while no library has a schedule. An invalid expression stops startup |

### Upgrading

On PostgreSQL, stop every process first (see [PostgreSQL](#postgresql)). Start the new version on the same data directory (`docker pull` and recreate the container, or
`uvx --refresh exactdocs serve`): the database is migrated on start and every library keeps
serving; nothing is imported again. CI proves it for each change, from the previous release's data
directory. When a release changes how the search index is built, its notes have a **Requires
reindex** section, the server logs a warning and `/api/health` reports `"reindex_required": true`.
Search keeps answering as before until you run, where the server runs (it opens the data
directory):

```bash
docker exec exactdocs exactdocs reindex     # or: uvx exactdocs reindex
```

It rebuilds the index from the stored chunks beside the one that answers, then swaps them in one
step: the server keeps serving throughout. Running it when nothing changed is harmless.

### Backup and restore

On PostgreSQL, use `pg_dump` instead (see [PostgreSQL](#postgresql)); what follows is for the
SQLite database.

`exactdocs backup` writes one archive of the instance while the server keeps serving: a
consistent snapshot of the database (SQLite's online backup API, so writers are not stopped) with
the libraries, versions, articles, images, settings, accounts and API tokens; DBOS's durable job
steps (`jobs.sqlite`, so an import that was running resumes after a restore); and `known_hosts`.
Run it where the server runs:

```bash
docker exec exactdocs exactdocs backup - > exactdocs-$(date +%F).tar.gz   # or a path in the volume
uvx exactdocs backup ~/exactdocs-backup.tar.gz
```

`exactdocs restore` puts an archive into a data directory that holds no instance yet (it refuses
to overwrite one), with the server stopped, checks every file against the archive's checksums,
then migrates the schema: a backup from an older release is brought up to this version, one from
a newer release is refused before anything is written. Then start the server as usual:

```bash
docker run --rm -v exactdocs-data:/data -v "$PWD:/backup:ro" \
  ghcr.io/sircypkowskyy/exactdocs:latest restore /backup/exactdocs-2026-11-07.tar.gz
uvx exactdocs restore ~/exactdocs-backup.tar.gz      # into EXACTDOCS_DATA_DIR
```

**The secret key is not in the archive** unless you pass `--include-secret-key`. Without it, the
encrypted repository credentials in the archive cannot be read by whoever holds the archive, and
the restored instance needs the original key to read them: set the same `EXACTDOCS_SECRET_KEY`,
or copy the old `secret.key` into the new data directory (before or after the restore, before
`serve`). Without the key every library keeps serving its docs, and adding a version asks for its
credential again (`credentials_required`). With `--include-secret-key` the archive opens those
credentials by itself: store it like the key. Archives and restored files are created with mode
`0600`; they also hold the password and token hashes. (The files a running server creates itself,
such as `exactdocs.db`, are `0644` inside the `0700` data directory; a restored instance's are
`0600`. Both keep other users out.)

A backup stages its copies next to the archive (for `-`, in the data directory) before writing it,
so that filesystem needs room for about two copies of the database while it runs. A backup that was
killed leaves a `.exactdocs-backup-*` folder there; the next backup removes those older than a
day. A restore checks each file's size against its manifest and the free space (keeping 64 MiB to
spare) before it writes anything.

PostgreSQL is backed up with its own tools: `pg_dump -Fc` of the database (DBOS's job steps are in
it too), plus `EXACTDOCS_SECRET_KEY`; `exactdocs backup` refuses a non-SQLite
`EXACTDOCS_DATABASE_URL`.

**Planned, not read by this version:** the model endpoints and roles (`EXACTDOCS_AI__...` and a
TOML file, see [AI retrieval decisions](https://sircypkowskyy.github.io/ExactDocs/decisions/ai-retrieval/)). The optional
`exactdocs[ai]` extra (`uvx --from 'exactdocs[ai]' exactdocs serve`) already installs their
dependencies; nothing of it is imported while no model is configured.

### PostgreSQL

A team's instance can keep everything in PostgreSQL 14 or newer (a UTF8 database, in any locale)
instead of the SQLite file, and
then run several server processes on it: in one container (`WEB_CONCURRENCY`), in several, or on
several hosts behind a load balancer. Every process serves the web UI, the API and MCP, and runs
jobs; a job runs once, in whichever process takes it first, and at most one per library at a time.
A process that dies with running jobs leaves them to the next one that starts, or after about 30 s
to any running process, which resumes them at their last completed step. A database outage or
failover of up to about 15 s is waited out. A longer one, or another process taking over a
process's executor slot meanwhile, makes that process stop taking jobs and stop itself (as
`SIGTERM` does) within a few seconds, before anyone else can take its jobs over, so that no job runs
twice: run it with a restart policy (`restart: unless-stopped` in the example below, a Deployment
in Kubernetes). A process that starts after a crash waits 15 s before it resumes the jobs the
crashed one left (it logs why).

- `EXACTDOCS_DATABASE_URL=postgresql://user:password@host:5432/exactdocs` (`postgresql+psycopg://`
  means the same). The role needs to own the database, or at least to create tables and a schema
  in it; it does **not** need `CREATEDB`: DBOS keeps its tables in the schema `dbos` of the same
  database (`EXACTDOCS_DBOS_SYSTEM_SCHEMA`), never in a database of its own. Percent-encode
  special characters of the password.
- `EXACTDOCS_SECRET_KEY` is required, the same in every process: otherwise each process would
  generate its own key and could not open the credentials another one stored.
- Every process still has its own data directory for its git work folders and `known_hosts`;
  nothing in it has to be shared or backed up.
- Back up with PostgreSQL's own tools (`pg_dump -Fc exactdocs > exactdocs.dump`); `exactdocs
  backup` and `restore` copy a SQLite file only. Stop every ExactDocs process before a
  `pg_restore`, and start them once it is done.
- **Upgrade with every process stopped.** The new version migrates the schema when its first
  process starts, and older processes only check the schema when they start, so stop them all,
  then start the new version. This also matters when a release changes how jobs run (its notes
  say so): an older process would otherwise keep running jobs the new one cannot resume.
- Search uses PostgreSQL's full-text search (`tsvector`, the `simple` configuration, ranked with
  `ts_rank_cd` over the same column weights, words cut as SQLite's index cuts them). It is not
  BM25, but the shared ranking suite passes on it as on SQLite.
- Writes that must not interleave (storing and activating a version, indexing it) take turns
  across all processes, as on SQLite, so several processes serve more readers but do not import
  faster. A writer that waits more than 30 s for its turn gives up with an error, as SQLite does
  after its own wait.
- Sign-in throttling counts failures per process (#253).

Several processes on one PostgreSQL database, verified in CI (`deploy/compose.postgres.yaml`):

<!-- compose.postgres.yaml: start -->
```yaml
# ExactDocs on PostgreSQL: several server processes share one database (README, "PostgreSQL").
#   export POSTGRES_PASSWORD=$(openssl rand -hex 24) EXACTDOCS_SECRET_KEY=$(openssl rand -base64 32)
#   docker compose -f compose.postgres.yaml up -d
services:
  db:
    restart: unless-stopped
    # PostgreSQL 17 with pg_search and pgvector; any PostgreSQL 14 or newer works as well.
    image: paradedb/paradedb:0.26.3-pg17@sha256:950f68abebc78e28fd2ecfc8ed915aa29d07b5dd8cba25b2f513ca4e211dda70
    environment:
      POSTGRES_USER: exactdocs
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
      POSTGRES_DB: exactdocs
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U exactdocs -d exactdocs"]
      interval: 2s
      retries: 30
    volumes: ["exactdocs-db:/var/lib/postgresql/data"]
  exactdocs:
    # A process whose executor slot another one took stops itself; this brings it back.
    restart: unless-stopped
    image: ${EXACTDOCS_IMAGE:-ghcr.io/sircypkowskyy/exactdocs:latest}
    depends_on:
      db: { condition: service_healthy }
    environment:
      EXACTDOCS_DATABASE_URL: postgresql://exactdocs:${POSTGRES_PASSWORD}@db:5432/exactdocs
      EXACTDOCS_SECRET_KEY: ${EXACTDOCS_SECRET_KEY:?set EXACTDOCS_SECRET_KEY}
      WEB_CONCURRENCY: "2" # server processes; on PostgreSQL every one serves and runs jobs
    ports: ["127.0.0.1:3000:3000"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    volumes: ["exactdocs-data:/data"]
volumes:
  exactdocs-db:
  exactdocs-data:
```
<!-- compose.postgres.yaml: end -->

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
  holds both and defeats the encryption: use `exactdocs backup`, which leaves `secret.key` out
  unless asked (see [Backup and restore](#backup-and-restore)), or keep `EXACTDOCS_SECRET_KEY`
  outside the volume. A key file that was readable by others is made
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

MVP-1 has one admin account. An instance can already run on [PostgreSQL](#postgresql) with several
server processes; for teams, the plan is to sign in through OIDC/OAuth, and share libraries with users or
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

Behind a reverse proxy in another container, add that proxy's own address to
`EXACTDOCS_FORWARDED_ALLOW_IPS`. Otherwise every client looks like the proxy, and 5 failed
sign-ins from anyone throttle everyone. Whatever this setting lists can choose the client
address the server sees (through `X-Forwarded-For`), so list only the proxy: not a range such as
`172.16.0.0/12`, which covers every container on every Docker network of the host. To pin the
proxy's address, give it a fixed one on a network of its own:

```yaml
services:
  proxy:
    networks: { edge: { ipv4_address: 172.30.0.2 } }
  exactdocs:
    environment:
      EXACTDOCS_FORWARDED_ALLOW_IPS: "172.30.0.2"
    networks: [edge]
networks:
  edge:
    ipam: { config: [{ subnet: 172.30.0.0/24 }] }
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
    db[("SQLite in the data directory<br/>or PostgreSQL")]
    git[("Git hosts you configure<br/>GitHub, GitLab, Bitbucket, ...")]
    models[/"Optional model endpoints<br/>embeddings, reranker, LLM (planned)"/]
    agent -->|MCP| mcp
    browser --> ui
    browser -->|REST| api
    app --> db
    importer -->|git fetch of the pinned commit| git
    retrieval -.-> models
```

### Health checks

Two probes answer `GET` and `HEAD` without sign-in (also before the first account exists), for
Docker, Kubernetes or a load balancer:

| Path | Answers | Use it for |
|---|---|---|
| `/healthz` | `200` while the process runs, whatever the database does, within about 0.3 s: `status`, `version`, `database_reachable`, and (when the database answered in time) `schema_revision`, `search_index_format`, `reindex_required` (`null` when unknown) | liveness: restart the process when it stops answering |
| `/readyz` | `200 {"status": "ready"}` when the database file exists, answers within 2 s and is at this version's schema, else `503 {"status": "not_ready", "reason": ...}` | readiness: send traffic only while it is ready |

`/api/health` is an alias of `/healthz`, kept for existing clients. Neither probe creates a
missing database file (an existing empty one gets SQLite's header and WAL files on connect). To
wait for a starting instance, poll `/readyz`: liveness answers before the database does.

The probes answer whatever the `Host` header says, so a Kubernetes `httpGet` probe (which sends
the pod IP) needs no extra header. Only exact `GET`/`HEAD` requests on these three paths skip the
DNS-rebinding guard, and `/healthz` then answers just `{"status": "ok"}`: the version and the
database details go only to a `Host` the instance trusts (`localhost` or
`EXACTDOCS_ALLOWED_HOSTS`). Probe timeouts:

```yaml
livenessProbe:  {httpGet: {path: /healthz, port: 3000}, timeoutSeconds: 1, periodSeconds: 10}
readinessProbe: {httpGet: {path: /readyz, port: 3000}, timeoutSeconds: 3, periodSeconds: 10}
```

The Docker image's `HEALTHCHECK` asks `/readyz`, so `docker compose`'s
`depends_on: condition: service_healthy` waits for a usable database. Plain Docker only marks the
container unhealthy; Docker Swarm, or an autoheal sidecar, restarts an unhealthy container, so
there a database outage longer than a few checks turns into restarts. With SQLite on a local
volume that is what you want: a restart reopens the file.

## Privacy and observability

ExactDocs makes no outbound connections you did not configure: only your git hosts, your model
endpoints (planned) and, if you turn it on, your trace collector. No analytics, no update checks.
The Prometheus endpoint, if you turn it on, waits to be scraped and sends nothing.

**Traces and metrics (opt-in).** With `EXACTDOCS_TELEMETRY=otlp` and `OTEL_EXPORTER_OTLP_ENDPOINT`
pointing at your collector (e.g. `http://otel-collector:4318`), ExactDocs exports OpenTelemetry
traces and metrics over OTLP/HTTP, with the plain OpenTelemetry SDK; the other standard `OTEL_*`
variables (headers, service name, resource attributes, sampling) apply. Nothing is written to the
console (stdout belongs to stdio MCP). Off (the default), the SDK is not even imported, and setting
the `OTEL_*` variables alone exports nothing. The metrics are those listed under *Prometheus metrics* below,
under their OpenTelemetry names (`http.server.request.duration`, `exactdocs.search.duration`,
`exactdocs.job.duration`...). The spans:

| Span | Where from |
|---|---|
| `GET /api/v1/libraries/{owner}/{repo}/search`, ... | every request (FastAPI's built-in OpenTelemetry), except the health checks |
| `tools/call search_docs`, ... | every MCP request, named after the tool (FastMCP) |
| `retrieval.search_docs`, `retrieval.search_all_libraries`, `retrieval.query_docs`, `retrieval.resolve_library_id` | every search, with `exactdocs.retrieval.mode` (`bm25`), library and ref |
| `retrieval.<search>.version`, `.rank`, `.chunks` (`.versions` for the cross-library ones) | each stage of a search: finding the version, ranking, loading the chunks |
| `ingestion.import`, `ingestion.refresh` (a branch sync), `ingestion.reprocess`, `ingestion.rechunk`, `ingestion.retag`, `ingestion.collect` | every job, with its library and version |

**Query text stays out** unless you set `EXACTDOCS_TELEMETRY_QUERY_TEXT=true`: no span carries it;
the values of `q`, `query`, `libraryName` and `url` (a repository URL may hold a token) in request
URLs are replaced with `REDACTED`; and an error keeps its exception type but not its message or
stack trace, which can quote the input (a refused, over-long query is named in its validation
error). MCP spans also lose FastMCP's `enduser.id` and `enduser.scope` (the calling token's
client ID and scopes), which would tie the searches to a person. LLM calls will be traced without their prompts and answers (pydantic-ai's
`include_content=False`) once the AI retrieval modes exist.

**Access logs are not covered.** uvicorn's access log on stdout (`GET /api/v1/...?q=... 200`)
holds the full URL, query text included, whatever the telemetry settings, as it always did. If your
container logs are shipped somewhere, filter those lines (logger `uvicorn.access`) in your log
pipeline.

**Prometheus metrics (opt-in).** With `EXACTDOCS_METRICS=true`, `GET /metrics` serves the
Prometheus text format, from an OpenTelemetry metric reader that only answers scrapes. Off (the
default), there is no `/metrics` (404) and `prometheus_client` is not imported. With
`EXACTDOCS_TELEMETRY=otlp` as well, it is a second reader on the same meter provider: the
collector gets the same metrics. Point Prometheus at the address and Host name you serve, with
the token in a file if you set `EXACTDOCS_METRICS_TOKEN`:

```yaml
scrape_configs:
  - job_name: exactdocs
    static_configs: [{targets: ["exactdocs:3000"]}]   # the Host must be allowed (EXACTDOCS_ALLOWED_HOSTS)
    authorization:                                    # only with EXACTDOCS_METRICS_TOKEN
      credentials_file: /etc/prometheus/exactdocs-metrics-token
```

| Metric (Prometheus name) | Labels |
|---|---|
| `http_server_request_duration_seconds` (histogram), `http_server_active_requests` | `http_route` (the route template, e.g. `/api/v1/libraries/{owner}/{repo}/search`, or `/mcp`), `http_request_method`, `http_response_status_code`, `error_type` |
| `exactdocs_search_duration_seconds` (histogram) | `exactdocs_search` (`search_docs`, `search_all_libraries`, `query_docs`, `resolve_library_id`), `exactdocs_search_stage` (`total`, `version`/`versions`, `rank`, `chunks`), `exactdocs_retrieval_mode` (`bm25`), `error_type` |
| `exactdocs_job_duration_seconds` (histogram) | `exactdocs_job_kind`: `import`, `refresh` (a branch sync), `reprocess`, `rechunk`, `retag`, `collect`; `error_type` when it failed |
| `gen_ai_client_token_usage` and pydantic-ai's cost metrics | LLM usage, once the AI retrieval modes exist: anything recorded through OpenTelemetry's global meter appears here |
| `process_*`, `python_*`, `target_info` | the process (memory, CPU, open files), the Python runtime, and the service name and version |

**Who may scrape.** `/metrics` takes no account sign-in (Prometheus has none). The metrics carry
nothing a user typed or owns: no query text, library, version, user name or token client ID,
whatever `EXACTDOCS_TELEMETRY_QUERY_TEXT` says (requests are labelled with the route template,
never the path). They do tell how busy the instance is, its error types, the process's memory and
open files, and which Python and ExactDocs versions it runs. So set `EXACTDOCS_METRICS_TOKEN`
whenever the port is reachable beyond a network you trust: a scrape without
`Authorization: Bearer <token>` then gets 401 (compared in constant time). Without it, anyone who
reaches the port can scrape. The Host allowlist applies either way (an unknown `Host` gets 400),
but it is a DNS-rebinding guard, not access control; blocking `/metrics` at your reverse proxy also
works. Scrapes and the health probes are not counted as requests.

`/metrics` renders `prometheus_client`'s default registry, on purpose: besides ExactDocs' own
metrics it holds the process and Python runtime collectors. A dependency that registers its own
Prometheus collectors there would show up too; none does today.

This is tested, not just promised, in
[`test_no_outbound.py`](packages/exactdocs/tests/bootstrap/test_no_outbound.py): an import over
git/HTTP, REST search and both MCP search tools run with FastMCP's update check forced off and
no telemetry configured, then again with telemetry on and a collector on loopback, in a process
of its own. What that proves, exactly:

- **Observed:** every Python socket and name lookup goes through a guard that refuses anything
  but loopback. Where unprivileged user namespaces exist (`unshare -rn`), the same loop and a
  redirect to another host also run in a network namespace with only loopback, so the kernel
  itself blocks anything else, git included. Elsewhere that check is skipped.
- **Only pinned:** where it is skipped, git (a child process) is checked by what it was *told*:
  the only URL is the fixture server, the protocols are restricted, no ssh is started.
- git follows an HTTP redirect from your git host, and honours `HTTP(S)_PROXY`/`ALL_PROXY`
  when set (traffic then goes to that proxy). The test runs without proxy variables.
- Off, a fresh process started with the defaults (and a collector named in `OTEL_*`) sets up no
  OpenTelemetry SDK provider. With telemetry on, the spans reach the collector and nothing else is
  contacted; [`test_telemetry.py`](packages/exactdocs/tests/bootstrap/test_telemetry.py) checks
  that no exported byte holds the query text.

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

Stack: Python (FastAPI, FastMCP), React (TanStack Router and Query, shadcn/ui), SQLite or
PostgreSQL (pydantic-ai is planned). The production image serves the built frontend from the backend, so there
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
- [x] PostgreSQL with several server processes
- [ ] OIDC/OAuth, sharing with viewer / contributor / admin / creator roles
- [x] OpenTelemetry traces to your own collector
- [x] Prometheus metrics
- [ ] `exactdocs.sources.yaml`, webhooks

**Later**

- [ ] `llms.txt` and website crawling, package-registry and lockfile resolution
- [ ] Prebuilt index snapshots, more formats (reST, AsciiDoc, notebooks)

## Contributing

Contributions are welcome. Please open an issue (Feature or Bug template) before large changes.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. Imported documentation remains under the license of its original repository.
