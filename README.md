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

The image comes in three variants, built from one Dockerfile; all three start as a BM25 server
until a model role is configured:

| Tag | Holds | For |
|---|---|---|
| `:<version>`, `:latest` | BM25 on SQLite or PostgreSQL; no model, no ML library | most installs |
| `:<version>-ai`, `:latest-ai` | `exactdocs[ai]`: the hosted and self-hosted model providers, sqlite-vec, pgvector | [AI providers](#ai-providers-and-model-roles) over the network |
| `:<version>-local`, `:latest-local` | `exactdocs[ai,local]` and the two default [local models](#local-models), read-only in `/opt/exactdocs/models` (their licenses, MIT and Apache-2.0, in its `NOTICE`) | air-gapped instances: hybrid search and reranking with no network |

The `uvx` equivalents are `uvx --from 'exactdocs[ai]' exactdocs serve` and
`uvx --from 'exactdocs[ai,local]' exactdocs serve` (then `exactdocs models pull`). Dev builds
carry the same suffixes (`:dev-ai`, `:0.4.0.dev1-local`).

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
`config.json` in your user config directory (mode 0600; the token is never printed;
`EXACTDOCS_CLIENT_CONFIG` names another file). The new token
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
use; a new address still waits. `admin reset-password` forgets every address remembered for
the username, so one that signed in with the old password is held to the username's count
again. Behind a reverse proxy, list it in
`EXACTDOCS_FORWARDED_ALLOW_IPS`, so the throttle counts the client's address rather than the
proxy's. On SQLite the counts and remembered addresses are kept in the server's memory:
restarting the server clears them, and nothing else does (`admin reset-password` runs in another
process and cannot). On PostgreSQL they are kept in the database, so every server process counts
the same failures and a restart keeps them (`admin reset-password` drops the username's count
and its remembered addresses on every process); each count is dropped
once an hour has passed without a failure. If the database is too busy to count an attempt
within 5 seconds, the attempt is refused (429).

The web UI signs the admin in with `POST /api/v1/session`: an HttpOnly, SameSite=Lax cookie that
ends after 7 days without use or 30 days at most, and that only works on `/api` (never on `/mcp`).
Lost the password? Run `exactdocs admin reset-password` on the machine (same options as
`admin create`): it sets a new password, signs the admin out everywhere and revokes
the API tokens. If sign-ins are throttled meanwhile (429), or the old password may have leaked:
on SQLite, restart the server, which clears the throttle and the addresses it remembers (an
address that signed in with the old password is otherwise not held to the username's count). On
PostgreSQL the command also clears the username's count and forgets every address remembered
for it, so the new password works straight away on every server process and every address is
held to the username's count again (the client addresses' counts and other usernames' stay),
unless it warns that the sign-in throttle was busy or failed: the password has changed all the
same, so run the command again (that is safe) or wait out the `Retry-After`.

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
importing), runs no worker, no identity and no migration, and exposes the same read-only tools.
The one exception is AI spend: when an LLM step or a paid reranker runs in a stdio process, its
spend is added to the shared `retrieval_ai_spend` ledger (and its replay tokens), so the server's
budgets and `GET /api/v1/ai/usage` count it. That write goes through a second connection of its
own: on SQLite it opens the existing file with `mode=rw` under an authorizer that refuses every
write to any other table, every schema change and every `PRAGMA` but a few reads; on PostgreSQL it is
the same role without `default_transaction_read_only`, used by the spend ledger alone. If that
write fails (a read-only file system, a lock held too long), the process logs a warning and keeps
the spend in memory until it exits; the AI call never fails for it. While the server holds the
SQLite write lock, a stdio call that spent can wait up to 5 s for it before falling back to memory. If the server has since been upgraded and
migrated the database, upgrade the stdio command too. Manage libraries through the server. Run it as the same user as the server: with the server
stopped, SQLite creates `exactdocs.db-wal` and `-shm` next to the database (the directory must be
writable for that), and files owned by another user can stop the server from starting later.
The same goes for every other command (all but `serve --stdio` migrate): the first one creates
`exactdocs.db-migration.lock` next to the database (mode 0600), the lock processes starting
together take turns on to migrate, and a server that cannot open it stops with an error naming it.
`--host`, `--port` and `--reload` are HTTP-only and rejected with `--stdio`.

## MCP tools

| Tool | Purpose |
|---|---|
| `resolve-library-id(libraryName, query)` | context7-compatible: find a library ID such as `/acme/payments` |
| `query-docs(libraryId, query, language?)` | context7-compatible: documentation for `/owner/repo` (default version) or `/owner/repo/<ref>` (exactly that version, never another). Returns whole chunks, best first, within a size budget; `language` moves chunks with code in it first (it does not filter). The library's `context7.json` rules, if any, come first |
| `list_libraries(limit?, cursor?)` | Libraries and imported versions (`refs`: ref, kind, commit SHA, default flag) |
| `list_articles(library, ref?, path_prefix?, tags?, tags_match?, limit?, cursor?)` | The article tree of a version |
| `read_article(library, ref?, path)` | A full article, verbatim; an unknown path lists close matches |
| `search_docs(library, query, ref?, tags?, tags_match?, limit?, mode?)` | Search one version; results carry location, neighbors (`prev_chunk_id` / `next_chunk_id`), `coverage`, the retrieval mode that answered (`retrieval_mode`, `reranked`) and, when a cheaper mode answered, `fallback_reason`; `agentic` results also carry `justification` and `explored_path`. Without `mode` the library's mode is used, else the instance's, else the best one configured; asking for a mode that is not available is an error (`mode_unavailable`) naming the missing model role and listing the available modes (see [Retrieval](#retrieval)) |
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

By default every search is **BM25** on SQLite FTS5, pinned to one version, with identifiers indexed
whole and by their parts (`camelCase`, `snake_case`, `pkg.mod.fn`); with an embedding model it can
be **hybrid** (BM25 fused with vector search, still pinned to the version). The pipeline is built to upgrade
itself to whatever you configure; the rows below that need an endpoint are **planned**
([Roadmap](#roadmap)), and [Flows](https://sircypkowskyy.github.io/ExactDocs/flows/) draws how
the mode is chosen.

Which mode answers a search: the call's `mode`, else the **library's** mode
(`PUT /api/v1/libraries/{owner}/{repo}/retrieval`), else the **instance's**
(`EXACTDOCS_AI__MODE`), else the best default the configured models allow. The modes are
`bm25`, `hybrid` (needs an embedding model), `hybrid_hyde` (embedding model and LLM) and
`agentic` (LLM, never a default). A mode becomes a default only once the [eval
suite](https://sircypkowskyy.github.io/ExactDocs/evals/) shows it beats BM25, and none has yet, so
BM25 is the default: set `EXACTDOCS_AI__MODE=hybrid` (or a library's mode) to use hybrid search.
Reranking is a flag on top of any mode when a reranker is configured. A call that asks for a mode that cannot run fails with `mode_unavailable`, naming the
missing model role; a library or instance mode that cannot run (its model was removed) never fails
a search: the next one answers, with `fallback_reason: mode_unavailable` (or
`vector_store_unavailable` when the hybrid modes cannot run because the vector store's extension
cannot be loaded: sqlite-vec on SQLite, pgvector's `vector` on PostgreSQL; `/healthz` names it in
`vector_store_missing`; BM25 keeps answering). Setting a library's mode
is refused the same way when its model is not configured. Searching across libraries
(`search_all_docs`, `GET /api/v1/search`) and `resolve-library-id` stay BM25 whatever the library
and instance modes are: their scores must compare across libraries.

| Configured | Retrieval | Status |
|---|---|---|
| nothing | BM25 | **available** |
| reranker | BM25 → rerank | planned |
| LLM or judge model, judge chosen | any mode → the LLM judge rates the top candidates in one call and reorders them; unreranked with `fallback_reason` when it fails, times out, rates a chunk it was not given, or a budget is used up | **available** (opt-in: `EXACTDOCS_AI__RERANK_WITH=judge` or a library's `rerank_with`) |
| embedding model | hybrid: BM25 and vector search fused with reciprocal rank fusion (`k` = 60, the top 50 of each), within the version; BM25 with `fallback_reason` while a version is not embedded yet (`embedding_in_progress`) or when the model fails on the query (`embedding_unavailable`) | **available** (opt-in: `EXACTDOCS_AI__MODE=hybrid`) |
| embedding model + reranker | hybrid → rerank | planned |
| embedding model + LLM (+ reranker) | HyDE (`hybrid_hyde`): the LLM writes a short hypothetical answer, whose embedding searches the vector half while BM25 keeps the query; cached per query, version and model; within the budgets, else hybrid with `fallback_reason` `llm_budget_reached`, `llm_rate_limited` or `llm_unavailable` (an LLM error or timeout) | **available** (opt-in: `EXACTDOCS_AI__MODE=hybrid_hyde`; a default only once the eval suite shows it beats BM25) |
| LLM + agentic mode | a pydantic-ai agent browses the version's tree (outlines, articles, chunks, BM25) in a sandbox and returns the chunks that answer the question, each with a `justification` and its `explored_path`; past a limit, a budget or a loop it answers with the best non-LLM mode (`fallback_reason: agent_limit_reached`, `llm_budget_reached`, `agent_loop_detected`, `agent_failed`) | **available** (opt-in: `mode=agentic`, never a default; see [Agentic search](#agentic-search)) |
| LLM + agentic mode, repeated questions | similar past questions are served from a cache | planned |

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
chunks until the new ones are in place. Whatever the settings, a section longer than 8,000
characters (about 2,000 tokens) is split between its top-level blocks, never inside a code block,
table or MDX component, into parts that keep its heading path; a `max_chars` or `min_chars` above
8,000 is refused (422). The bundled local embedding model (bge-small, 512 tokens) embeds only
about the first 1,800 characters of a chunk; full-text search, reranking and the agent see all
of it.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `EXACTDOCS_DATA_DIR` | `/data` in the Docker image, else the platform user-data directory | Where ExactDocs keeps everything (the SQLite database, the generated secret key, `known_hosts`, fetch caches and `jobs.sqlite`, the durable steps of running imports; on PostgreSQL only `known_hosts` and fetch caches). Created if missing; the server refuses to start, naming the path, if it is not writable. `uvx` and stdio MCP use the same default path |
| `EXACTDOCS_DATABASE_URL` | `exactdocs.db` in the data directory | A SQLite file, e.g. `sqlite:////srv/exactdocs.db` (opened in WAL mode), or a PostgreSQL database, `postgresql://user:password@host:5432/exactdocs` (psycopg 3; see [PostgreSQL](#postgresql) and [Supabase](#supabase)). The schema is migrated on start and `/api/health` reports its revision (see [Upgrading](#upgrading)) |
| `EXACTDOCS_DBOS_SYSTEM_SCHEMA` | `dbos` | PostgreSQL only: the schema of the same database where DBOS keeps the durable steps of jobs (SQLite keeps them in `<data dir>/jobs.sqlite`) |
| `EXACTDOCS_SECRET_KEY` | generated into `<data dir>/secret.key` (mode 0600) on first run | Encrypts the stored tokens and deploy keys of private repositories (Fernet). It must be **random** and at least 32 characters: `openssl rand -base64 32` (it is stretched with HKDF, not a password hash, so a passphrase is not safe). Without it the credentials cannot be read: libraries keep serving their docs and ask for the token again (`credentials_required`) |
| `EXACTDOCS_SECRET_KEY_PREVIOUS` | – | Rotation: set the new key in `EXACTDOCS_SECRET_KEY` and the old one here. Credentials sealed with the old key still open and are sealed with the new one whenever they are sent again; remove this once they all were. HyDE's and the agentic cache's answers are keyed with the current key only, so after a rotation every cached answer is a miss (the LLM is asked again) until the TTL prunes the old rows |
| `EXACTDOCS_ALLOWED_HOSTS` | – | Host names besides localhost the server answers to, comma-separated (e.g. `docs.example.com,*.corp.example`); needed behind a reverse proxy or on a LAN address |
| `EXACTDOCS_ALLOWED_ORIGINS` | – | Browser origins allowed to make state-changing requests, comma-separated |
| `EXACTDOCS_SECURE_COOKIES` | `false` | The session cookie is always `Secure` over HTTPS; set `true` when TLS ends at a proxy that does not forward `X-Forwarded-Proto` from a trusted address |
| `EXACTDOCS_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Proxies whose `X-Forwarded-*` headers are trusted (scheme, and the client address the sign-in throttle counts) |
| `EXACTDOCS_CONFIG_FILE` | unset | A TOML file with the same settings (the `[ai]` section above); the environment wins over it. It may not hold keys or `secret_key`: those come from the environment or `api_key_file` |
| `EXACTDOCS_AI__PROVIDERS__<NAME>__<FIELD>`, `EXACTDOCS_AI__<ROLE>__MODEL` | unset | AI provider profiles and model roles, see [AI providers and model roles](#ai-providers-and-model-roles) |
| `EXACTDOCS_AI__MODE` | unset (`auto`) | The retrieval mode of searches that name none, for libraries without their own: `bm25`, `hybrid`, `hybrid_hyde` or `agentic`; unset or `auto`: the best default mode the configured models allow, which is BM25 until the eval suite makes another mode a default. An unknown name stops the server at start; a mode whose model is not configured falls back with `fallback_reason: mode_unavailable` (see [Retrieval](#retrieval)) |
| `EXACTDOCS_AI__HYDE__CACHE_TTL` | `P30D` (30 days) | How long a HyDE hypothetical answer stays cached (seconds or an ISO 8601 duration). Once a day (just after UTC midnight, and at start; one process on PostgreSQL), and after every collection, the server deletes older answers and those of an `llm` model no longer configured; answers are also deleted when their version's manifest is collected |
| `EXACTDOCS_AI__AGENTIC_CACHE__ENABLED`, `__THRESHOLD`, `__SCOPE`, `__TTL` | `false`, unset, `library`, `P7D` | The agentic answer cache (see [Agentic search](#agentic-search)): a question that asks again what one answered agentically before asked (the same content words in the same order, numbers and negations; with an embedding model, its cosine must also reach `THRESHOLD`, 0 to 1, as a confirmation), for the same version, tag filter and `llm` model is answered from that answer (`cache_hit: true`). `ENABLED`: the cache is opt-in, with an embedding model too (it trades exactness for cost and serves only near-verbatim re-asks); while it is off, the nightly upkeep deletes every cached answer. `THRESHOLD` unset: `0.8` with an embedding model, `0.9` with words alone. `SCOPE`: `library` (callers of a version share answers, justifications included) or `caller`. Answers older than `TTL` are deleted by the nightly upkeep |
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

### AI providers and model roles

Model endpoints are **provider profiles**, named once and used by every role as
`<profile>:<model>`. Configure them in the environment or in a TOML file named by
`EXACTDOCS_CONFIG_FILE` (the environment wins, field by field); they need the `exactdocs[ai]` extra
(`uvx --from 'exactdocs[ai]' exactdocs serve`). Nothing of it is imported, and nothing is sent
anywhere, while no profile is configured.

```toml
# EXACTDOCS_CONFIG_FILE=/etc/exactdocs/exactdocs.toml
[ai.providers.corp]                     # a company gateway speaking the OpenAI API
kind = "openai-compatible"
base_url = "https://llm.example.com/v1"
api_key_file = "/run/secrets/corp_llm_key"   # never api_key in the file
headers = { "X-Team" = "docs" }     # no credentials here: Authorization, *-key, *-token are refused
proxy = "http://proxy.example.com:3128"
request_timeout = 30

[ai.llm]
model = "corp:gpt-4.1-mini"

[ai.embedding]
model = "corp:text-embedding-3-small"   # instance-wide only
dimensions = 1024                       # optional: ask the model for shorter vectors
batch_size = 64                         # chunks per call and per durable step
```

The same in the environment: `EXACTDOCS_AI__PROVIDERS__CORP__KIND=openai-compatible`,
`EXACTDOCS_AI__PROVIDERS__CORP__API_KEY=...`, `EXACTDOCS_AI__LLM__MODEL=corp:gpt-4.1-mini`.

- **Kinds:** `openai-compatible` (any gateway: a base URL, an optional key), `openai`,
  `openrouter`, `anthropic` (`platform = "api"`, `"vertex"`, `"foundry"`, or `"bedrock"` with
  boto3, not in the images), `azure` (Azure OpenAI: `base_url` or `resource`, `api_version`, a
  key or `auth = "entra"`), `google-vertex` (`project`, `location` and `credentials_file`, or
  `credentials = "adc"`, or an Express-mode key), `google` (Gemini API), `ollama`, `vllm`,
  `litellm`, pydantic-ai's OpenAI-API providers (`deepseek`, `together`, `fireworks`, `cerebras`,
  `github`, `vercel`, `moonshotai`, `heroku`, `nebius`, `ovhcloud`, `sambanova`, `alibaba`),
  `tei` (Text Embeddings Inference serving a reranker: the `reranker` role only), and `local`
  (models in this process, see *Local models*). Groq, Mistral, Cohere, xAI and Bedrock are reached through their OpenAI-compatible
  endpoint or LiteLLM.
- **Roles:** `embedding`, `reranker`, `llm`, `judge` (defaults to `llm`).
- **Explicit values only.** Every SDK client gets its endpoint, key (`unused` for a profile
  without one), project, region and API version from the profile; `OPENAI_API_KEY`,
  `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_*`, `GOOGLE_*` and the like are never read,
  and each profile's HTTP client refuses any scheme, host or port but its endpoint's.
  `OPENAI_CUSTOM_HEADERS` and `ANTHROPIC_CUSTOM_HEADERS` are removed from the process before any
  SDK client is built (the SDKs would let them replace a profile's key).
- **The server's own cloud identity** (`credentials = "adc"`, `credentials_file`,
  `auth = "entra"`, and Claude on Bedrock, which signs with the AWS identity) is used only by
  profiles of the environment or the TOML file, never by ones created over REST, and such a
  profile takes no `base_url`: its endpoint is derived from `location` or `resource` (Google's,
  Azure's or AWS's own), so the token never reaches another host. `resource`, `location` and
  `project` must each be a single DNS label (letters, digits, inner hyphens), and a derived
  endpoint is built with a URL constructor and checked against the provider's exact host form
  (`<resource>.openai.azure.com`, `<resource>.services.ai.azure.com`,
  `bedrock-runtime.<region>.amazonaws.com`, Vertex AI's `aiplatform` hosts). GCP's legacy
  domain-scoped project IDs (`example.com:project`) are therefore refused. An Entra ID credential
  chain (client secret or certificate, workload identity, managed identity, user-assigned through
  `AZURE_CLIENT_ID`) is built once per profile; the profile's `proxy` carries the calls to
  `login.microsoftonline.com`, never managed identity's local endpoint. Entra ID never uses the
  Azure CLI, PowerShell, VS Code or any developer sign-in: for local development, use a client
  secret (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`). Google's token refresh uses the environment's proxy
  variables, as google-auth reads them itself.
- **Extra headers carry no credentials:** `Authorization`, `Cookie`, `x-api-key`, `api-key`
  and names ending in `-key`, `-token`, `-secret` or `-password` are refused ("use the key
  field"), so no credential sits unsealed in the database or the file.
- **Over REST** (`/api/v1/ai/providers`, admins): profiles can be created, changed, deleted and
  checked; their keys are sealed with the secret key (`EXACTDOCS_SECRET_KEY` or `secret.key`,
  under their own key derivation) and never returned. Profiles of the environment or the file are
  read-only there. A stored key is dropped, not reused, when the profile's endpoint changes.
- **Per library** (`PUT /api/v1/libraries/{owner}/{repo}/retrieval`): AI on or off (off: nothing
  of the library is ever sent to a provider, searches are BM25), its own `llm`, `judge` and
  `reranker`, its own `rerank_top_n`, what reranks it (`rerank_with`: `cross_encoder` or `judge`),
  its own spend limits per day and month (`budgets`), no higher than the instance's, and its
  `repo_guidance` (see [Agentic search](#agentic-search)). The embedding model is instance-wide only. The library's settings
  page (*Retrieval and AI*) shows the pipeline its searches run now and edits all of these.
- **Check:** `exactdocs ai check` (where the server runs) makes one minimal call per role and
  prints the latency, the model that answered and an embedding's dimensions, never a key;
  `POST /api/v1/ai/providers/{name}/check` does the same for one profile.
- **Background embedding:** with an embedding model set, every version is embedded in the
  background, one `embed` job per version (a durable step per `batch_size` chunks, resumed after
  a restart), queued on start, after each import and whenever the model changes. Each chunk is
  sent once, as its article title, heading path and text, even when many versions hold it; a
  library with AI off is never sent. Changing the model, its `dimensions` or the input format
  starts a new embedding space: every version is embedded again, and until a version is covered
  by the new model its searches answer BM25 with `fallback_reason: embedding_in_progress` (two
  models' vectors are never mixed). The old space is dropped once the new one covers every
  version. The tokens each call used (from the provider's answer) are recorded per UTC day and
  month, for the instance, the library and embedding runs, in the `retrieval_ai_spend` table,
  which the budgets below read. Saving the embedding role's profile over REST re-queues what it changes; a
  batch the provider does not answer for now (a timeout, a 429) is tried again a few times.
  On PostgreSQL the vectors go to pgvector (see *PostgreSQL*); without its `vector` extension
  each embed job is skipped with `vector_store_unavailable`.
- **Estimate first:** `exactdocs ai estimate` (where the server runs) prints the chunks still to
  embed, an estimate of their tokens (4 characters per token, never a tokenizer) and of the US
  dollars from the bundled price list, without calling any model;
  `GET /api/v1/ai/embedding/estimate` is the same over REST.
- **Budgets and rate limits:** `[ai.budgets]` (or `EXACTDOCS_AI__BUDGETS__...`) caps spend in
  US dollars and tokens per UTC day and month, for the instance (`daily_usd`, `monthly_usd`,
  `daily_tokens`, `monthly_tokens`), for each library (`per_library_...`), for each account
  (`per_user_...`: the API token's or the session's; stdio MCP counts to instance and library
  only) and for embedding runs (`daily_embedding_...`, `monthly_embedding_...`).
  `llm_searches_per_minute` limits each caller's LLM searches, over REST, HTTP MCP and stdio
  alike (counted per server process). Every model call is counted from the provider's reported
  usage, in one `retrieval_ai_spend` table shared by every server process and by stdio MCP
  processes, which open the database read-only but add their spend to this table over a
  connection that may write it alone (see [stdio](#without-a-network-port-stdio); #274). LLM agents are held by the
  harness `SpendLimits`, embedding and rerank calls by retrieval's own check before each batch or
  call, so a burst can overshoot by the calls already in flight. Reaching a limit degrades search,
  never breaks it: the LLM step is skipped and the result names the cheaper mode with
  `fallback_reason: llm_budget_reached` (or `llm_rate_limited`); a paid rerank is skipped
  (`reranked: false`; a rerank that ran counts one request and its tokens, estimated at 4
  characters per token since rerank endpoints report none); an `embed` job of a paid model stops
  before its next batch with `ai_budget_reached` and is queued again after the window resets
  (each UTC midnight, by one server process, a few minutes after at random), while BM25 keeps
  answering.
- **Prices:** from the `genai-prices` data bundled with pydantic-ai (never fetched); a model it
  does not know gets `[ai.prices."<profile>:<model>"]` `input_usd_per_mtok` and
  `output_usd_per_mtok`. `local` models cost nothing: their tokens are recorded (`local_tokens`
  in the usage) but count toward no token budget, so local search traffic never uses up a
  budget, and no budget stops a local embedding job or a search's local query embedding or
  rerank (#284). Tokens recorded before this release (local ones included, since older rows do
  not say which model spent them) stay counted until their day or month window resets.
  Self-hosted endpoints (`ollama`, `vllm`, a TEI reranker) count as paid and are never priced
  from another provider's list: with a US dollar budget, give them a price of 0
  (`input_usd_per_mtok = 0`) if they cost nothing. A US dollar budget with a configured model
  that has no price is refused at start. Spans never carry prompts or completions, even with
  `EXACTDOCS_TELEMETRY_QUERY_TEXT` on.
- **Usage:** `GET /api/v1/ai/usage` (admins) shows what the instance, embedding runs, each
  library and each account spent today and this month, and what is left of each budget (a
  library's own budget where it is tighter);
  `/metrics` has pydantic-ai's `gen_ai.client.token.usage` and `operation.cost` and
  `exactdocs_ai_fallbacks_total` by mode and reason, and `exactdocs_ai_cache_hits_total` (searches
  whose LLM step a cache answered) by cache (`agentic_answer`, `hyde_answer`) and mode (never a
  library, user or query).
- **In the UI:** the *AI* page (admins) lists the providers and roles (never a key) with a
  check per profile, the embedding progress of each space (`GET /api/v1/ai/embedding`) and the
  usage and budgets above.

```toml
[ai.budgets]
daily_usd = 10
monthly_embedding_usd = 50
per_library_daily_usd = 2
per_user_daily_usd = 1
llm_searches_per_minute = 30

[ai.prices."corp:gpt-4.1-mini"]   # only for models genai-prices does not know
input_usd_per_mtok = 0.40
output_usd_per_mtok = 1.60
```

#### Reranker

A cross-encoder reranker reorders the best candidates of every search (`search_docs`,
`query_docs`, the REST search) for precision. It speaks one of two HTTP dialects:

```toml
[ai.providers.cohere]                   # Cohere-compatible POST <base_url>/rerank
kind = "openai-compatible"
base_url = "https://api.cohere.com/v2"  # Jina: https://api.jina.ai/v1, Voyage: https://api.voyageai.com/v1
api_key_file = "/run/secrets/cohere_key"

[ai.providers.tei]                      # Text Embeddings Inference: POST <base_url>/rerank
kind = "tei"
base_url = "http://tei:8080"

[ai.reranker]
model = "cohere:rerank-v3.5"            # or "tei:BAAI/bge-reranker-base" (TEI serves one model)
top_n = 32                              # candidates reranked per search (1 to 200)
timeout = 2.0                           # seconds for building the reranker and its call
```

A `tei` profile still needs the `exactdocs[ai]` extra, like every profile, although it only uses
`httpx2`. vLLM and LiteLLM (`kind = "vllm"` / `"litellm"`, base URL ending in `/v1` or `/v2`) and Azure AI
Foundry's Cohere deployments (`openai-compatible`) speak the Cohere-compatible dialect too. Only
the query and the candidates' chunk text are sent (cut to 8000 characters each, in batches of 100,
or 32 for TEI), never a library name, a version or a user. A reranker that times out, fails or
answers something unusable never fails a search: results keep their order with `reranked: false`
and `fallback_reason` `reranker_timeout` or `reranker_failed`, and the failure is logged without
the query. With a `limit` above `top_n`, the reranked results come first and the rest follow in the
mode's order, with the mode's scores (not comparable with the reranker's). With any
provider profile other than `local` configured, the provider SDKs are loaded in a worker thread at
start, so the first search never waits for them; a load that fails is a warning, never a stop. Whatever the reranker raises (an HTTP client closed under the
call because its profile was edited, a partly installed SDK) counts as `reranker_failed`. Traces show it as the `rerank` stage, without the query or any text. A hybrid search is
reranked the same way, after the fusion.

#### LLM judge

Without a cross-encoder endpoint, or for better judgments than one gives, a small, fast LLM can
rerank instead: the `judge` role (any chat profile; it defaults to the `llm` role) rates every
candidate in **one** call, a whole score from 0 to 10 per candidate. It reranks only where it is
chosen, since it costs an LLM call per search:

```toml
[ai.judge]
model = "corp:gpt-4.1-mini"             # optional: the [ai.llm] model when unset
timeout = 10.0                          # seconds for building the model and its one call

[ai]
rerank_with = "judge"                   # EXACTDOCS_AI__RERANK_WITH; default "cross_encoder"
```

A library chooses for itself with `rerank_with` (`cross_encoder` or `judge`) in its retrieval
settings or the UI; unset, the instance's choice applies. When both a cross-encoder and a judge
are configured, the cross-encoder (cheaper) reranks unless the judge is chosen; a library that
chooses the judge without one configured is reranked by the cross-encoder, if there is one. The
judge gets the best of the same top N as the cross-encoder that fit one bounded call: at most 64,
and at most about 18,500 input tokens, estimated at 4 characters per token for ASCII text, 1.5 for
long ASCII runs without whitespace (base64, hashes), 4 tokens for a character above U+FFFF (CJK
Extension B, emoji) and a token for any other (CJK, Cyrillic, control characters...).
That keeps the call under the 60,000 tokens one LLM step may use, even for code full of escaped
`<`, `>` and `&`, base64 broken by spaces or rare scripts at 3 tokens a character, so a call is never stopped after it was paid for. With 2000 characters per
candidate that is about 32 English or code candidates, or 9 CJK; the candidates beyond them keep the mode's order
after the judged ones, and `coverage.reranked` counts only the judged. It gets the query and each
candidate's chunk text (cut to 2000 characters), named by position (`c1`, `c2`...), never by
chunk ID, and never a library name, a version or a user; the prompt and the instructions mark
them as untrusted, delimited text, and every `<`, `>` and `&` in them is escaped, so a candidate
cannot close its delimiter. Its answer may only reorder the candidates it was given: ratings that
name an ID it was not given (anything but exactly `c1` to `cN`), rate one twice, leave one
out or go outside 0 to 10 are refused at once (no retry), and the search keeps its order with `fallback_reason` `reranker_failed`. A
judge that does not answer within its timeout keeps the order with `reranker_timeout`. It is an
LLM step: it counts against the budgets and the LLM search rate limit (above) (once
per search, with HyDE's step), and once a budget is used up the search keeps its order with
`fallback_reason` `llm_budget_reached`, without calling it. Traces show it as the `judge` stage,
without the query, the candidates or the ratings.

#### Agentic search

With an `llm` role configured, `mode=agentic` (a call's, a library's or `EXACTDOCS_AI__MODE`; it
is never chosen by default) hands the question to a pydantic-ai agent on that model. The agent
works in [Code Mode](https://pydantic.dev/docs/ai/harness/code-mode/): its only tool is
`run_code`, a sandbox ([Monty](https://github.com/pydantic/monty), never IPython) in which it can
call `list_articles`, `article_outline`, `read_article`, `read_chunk` and `search_docs` (BM25),
each with a typed result, all bound to what the caller may see: the one version searched and the
call's tags. That scope is the agent's `deps`, never a tool argument, so no argument can name a
library, a version or a tag. It answers with chunk IDs and one sentence each; an output guardrail
(the harness `OutputGuardrail`) removes every ID that is not in the version's manifest or that
the call's tags exclude before the answer leaves the agent, and the IDs are checked once more
after it, so a result of another version (or a made-up ID) is dropped, never returned; only the
number of rejected picks is logged. The call's tags apply to every read too, so the agent never sees an
article they exclude. Each result carries its `justification` and `explored_path` (the read
calls up to the one that reached its article, such as `search_docs(retry)`,
`article_outline(docs/guide/resilience.md)`). Both are model output, marked so in the schema and
the MCP notice: control characters are removed, a justification is cut at 600 characters, a
path keeps at most 50 calls with each argument cut at 120.

Only the question and what the agent reads are sent to the model, never a library name or a user.
A run is bounded per search by `[ai.agentic]` (or `EXACTDOCS_AI__AGENTIC__...`) and by the
budgets above (the harness `SpendLimits`, counted to the instance, the library and the caller;
a library's own budgets apply where they are tighter than the instance's):

```toml
[ai.agentic]
max_tool_calls = 20          # read calls per search, run_code included (1 to 200)
max_requests = 8             # model requests per search (1 to 50)
max_tokens = 60000           # input and output tokens per search
sandbox_seconds = 5.0        # each run_code snippet's execution time (time awaiting a tool does not count)
sandbox_memory = 67108864    # each snippet's heap, in bytes
sandbox_suspensions = 500    # the sandbox's host calls per search
timeout = 120.0              # seconds per search, model calls included (more than sandbox_seconds)
max_repeated_calls = 3       # the same call (tool and arguments) this often is a loop (2 to 50)
```

A snippet running when `timeout` passes stops at its own `sandbox_seconds`, so a search can last
up to `timeout` plus `sandbox_seconds`; `sandbox_seconds` must be less than `timeout`.

Passing any of them ends the run, and the search answers with the best mode without an LLM step
(BM25, or hybrid when an embedding model is set) and `fallback_reason: agent_limit_reached`; a
budget reached during the run gives `llm_budget_reached`; an agent that makes the same call (the
same tool with the same arguments, `run_code` or a read inside it) `max_repeated_calls` times,
`agent_loop_detected` (the repeated read never runs; a loop whose arguments change each time
is not detected as one, and ends at `max_tool_calls` with `agent_limit_reached`); a model that fails or keeps answering
something unusable, `agent_failed`, as does a read that fails on the server (the database, the
catalog): its error is never shown to the model, only a fixed text, and the run ends. Failures
are logged by kind, never with the question or the error's text. Traces
show the run as the `agent` stage, with one span per model request and per tool call (the read
calls nested in `run_code`, each with an `exactdocs.agent.read` event naming the version it was
bound to and the versions of what it returned), never with prompts, answers or tool arguments;
`/metrics` shows its tokens (`gen_ai.client.token.usage`).

**Re-asked questions are answered from a cache.** Teams ask the same thing again; an agentic
answer is kept, and a later question that asks it again is answered from it at once,
with `cache_hit: true` and the same results, justifications and explored paths, costing no LLM
call, no budget and no rate limit (counted in `exactdocs.ai.cache_hits`). An answer is reused only
for the same version as it is now (a re-sync to a new commit, a new manifest, never reuses it),
the same tag filter, the same `llm` model and the same `[ai.agentic]` limits; each of its chunks
is looked up again in the version, under the call's tags, before it is returned, and an answer
none of whose chunks are left runs the agent. **Only a question asked again hits: the same
content words in the same order.** Filler such as "how", "do", "I", "I want" or "behaviour" is
dropped, and only plurals fold ("retries"/"retry", "rows"/"row"), so "how do I configure
retries", "how to configure retry behaviour" and "I want to configure retries" are one
question. Nothing else folds: "connecting" is not "connect", "meaning" is not "mean",
"migration" is not "migrate" and "format" is never "form", because a wrong fold serves a wrong
answer and a missing one only costs a miss. Question words ("when" is not "why"), prepositions and conjunctions ("build for
arm" is not "build on arm") stay. Order is part of the question, so every swap misses: "replace requests
with httpx" is not "replace httpx with requests", "from v1 to v2" is not "to v1 from v2". That
also makes an order-flipped re-ask ("retry configuration" for "configure retries") a miss,
which is accepted. Symbols are terms in their places ("latency > threshold" is not "latency <
threshold", `c++` is not `c`; `≥`, `≤`, `≠`, `≈` and `→` read as `>=`, `<=`, `!=`, `~=` and `->`);
only sentence punctuation is dropped. Single letters are terms too, but "a" and "I" only as
names, next to a symbol or a direction word ("move it to a from b"). Numbers and versions (with
their sign, a comparison or range operator right before them and a `+` right after: `-1` is not
`1`, `>= 3.8` is not `< 3.8`, `~1.2` is not `^1.2`, `3.8+` is not `3.8`), words with digits
(`python3`, `oauth2`, `E42`) and negations ("not", "never", "without", "can't", "dont"...) must
match exactly. A question with a word the other lacks never hits, a paraphrase in other words
included: neither words nor embeddings tell "enable" from "disable" or "client" from "server"
(the default local model scores those 0.85 to 0.96, as high as real paraphrases), and a wrong
answer costs more than a miss. With an embedding model, the cosine of the two questions' embeddings must also clear the
threshold, as a confirmation (it never makes two different questions match). **The cache is
opt-in** (`enabled = true`), with an embedding model too: it trades exactness for cost, and it
serves only near-verbatim re-asks; the threshold is 0.8 with an embedding model and 0.9 with
words alone by default.
Saving a library's retrieval settings or removing it forgets its answers; the nightly upkeep
deletes answers past `ttl`, of an `llm` model no longer configured, or compared with another
embedding model than the configured one, and every answer while the cache is off.

```toml
[ai.agentic_cache]
enabled = true       # off by default: while off, stored answers are deleted
# threshold = 0.8    # 0 to 1; unset: 0.8 with an embedding model, 0.9 with words alone
scope = "library"    # or "caller": each caller is answered from their own questions only
ttl = "P7D"          # seconds or an ISO 8601 duration
```

With `scope = "library"` (the default) every caller of a library's version shares the cache: one
caller's cached answer, **the model's justifications included** (which may paraphrase their
question), can be served to another caller of the same library and version. Use `scope =
"caller"` where callers must not see the gist of each other's questions.

The cache (`retrieval_agentic_answers`) never stores the question's text: it keeps an HMAC of
the normalized question and of each of its terms, keyed from the instance's secret key, and,
with an embedding model, the question's embedding (an embedding can be partly inverted into the
words it came from, so treat the table as holding what the question meant). It also keeps the
answer as returned: chunk IDs, justifications and explored paths, which are model output and may
quote words of the question. The embedding of the question is a query embedding like a hybrid
search's: it is sent to the embedding model and counted to the same budgets.

**Repo guidance** (`AGENTS.md` / `CLAUDE.md`, off by default). Many repositories describe how
their docs are organized in these files; a library can let the agent use them with
`repo_guidance` in its retrieval settings (`PUT /api/v1/libraries/{owner}/{repo}/retrieval`):

| `repo_guidance` | What imports keep | What the agent gets |
|---|---|---|
| `off` (default) | nothing | nothing |
| `notes` | each version's root `AGENTS.md` / `CLAUDE.md` and those of every folder holding a selected file, also outside the selected paths (at most 32 folders; a file over 32 KiB, not text, or a link that does not lead in one hop to a file inside the repository is left out and listed on the job, the others are kept; a link that does is kept as its target's text) | a folder's file, once it opens that folder (lists it, or reads an article or a chunk in it), as an untrusted **user-channel** note in a `<context-file>` block, never as system instructions |
| `trusted` | the same | as `notes`, and the root's file is also part of its **system instructions**: only for a repository you trust as much as your own instructions |

The files are repository content, so untrusted: they reach the agent through harness [Repo
Context](https://pydantic.dev/docs/ai/harness/repo-context/) over a read-only workspace that holds
only the searched version's files (read from the database, never a checkout). The text is
NFKC-normalized, control and invisible (default-ignorable) characters are dropped, and every `<` /
`>` and lookalike (fullwidth, small form, angle brackets) is written `&lt;` / `&gt;`, so a file can
neither close its block nor open one; at most 16 files / 24,000 characters per search.
They cannot add a tool, reach another library or version, or lift a limit: the read tools, the
pinned version and `[ai.agentic]` are fixed before the run, and every pick is still checked
against the version. Their text counts toward the run's `max_tokens` and budgets like everything
else sent to the model (a streamed response whose server reports no usage is counted with the
judge's estimate above), and is never logged or put on a span. Turning guidance on (`off` to
`notes` or `trusted`) queues a `reprocess` of the library: every version is re-imported at its
commit and keeps its files, without a new upstream commit. Switching between `notes` and `trusted`,
or back to `off`, takes effect at the next search (`off`: nothing is sent; the kept files go with
the next import). Anyone who can edit the library's AI settings can mark it `trusted` until
library roles exist (E12-05), which will make it admin-only.

#### Local models

An air-gapped instance, or one whose docs may not leave it, runs a small embedding model and a
cross-encoder inside ExactDocs, on the CPU (fastembed on ONNX Runtime, no torch, no GPU). They
come with the `exactdocs[local]` extra (`uvx --from 'exactdocs[ai,local]' exactdocs serve`) and
are fetched **once**, by the one command that contacts the Hugging Face Hub:

```bash
exactdocs models pull        # BAAI/bge-small-en-v1.5 (67 MB) and Xenova/ms-marco-MiniLM-L-6-v2 (92 MB)
exactdocs models pull BAAI/bge-base-en-v1.5   # or any fastembed embedding model or cross-encoder
```

```toml
[ai.providers.local]                    # EXACTDOCS_AI__PROVIDERS__LOCAL__KIND=local: required,
kind = "local"                          # a `local:` role without it is warned about at start

[ai.embedding]
model = "local:BAAI/bge-small-en-v1.5"  # <profile>:<model>, 384 dimensions

[ai.reranker]
model = "local:Xenova/ms-marco-MiniLM-L-6-v2"
# timeout: unset means 5 s for a reranker on a `local` profile, the instance's or a library's
# own (2 s otherwise): a CPU reranks 32 long candidates in about 0.2 to 2 s, more with fewer cores
```

bge-small reads at most 512 tokens, so a chunk longer than about 1,800 characters (chunks go up
to 8,000) is embedded from its title, heading path and first 1,800 characters or so; full-text
search, reranking and the agent still see all of it.

The `-local` image has both default models already, so the same settings in its environment are
all it needs, even with no network at all (CI runs it with `--network none`):

```bash
docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data \
  -e EXACTDOCS_AI__PROVIDERS__LOCAL__KIND=local \
  -e EXACTDOCS_AI__EMBEDDING__MODEL=local:BAAI/bge-small-en-v1.5 \
  -e EXACTDOCS_AI__RERANKER__MODEL=local:Xenova/ms-marco-MiniLM-L-6-v2 \
  -e EXACTDOCS_AI__MODE=hybrid \
  ghcr.io/sircypkowskyy/exactdocs:latest-local
```

- **Where models live:** `EXACTDOCS_MODELS_DIR` (default `<data dir>/models`; the `-local` image
  sets its read-only `/opt/exactdocs/models`, where the two defaults were pulled when the image
  was built, so it needs no `models pull` and no network), one folder per model (`BAAI/bge-small-en-v1.5/`)
  with its ONNX file, its tokenizer and a marker `models pull` writes last. A model already there
  is skipped, so a cached directory makes the command offline.
- **Pinned revisions:** the two defaults are pulled at a fixed Hub commit (bge-small's
  `aa8f8b06`, MiniLM's `a0914435`), so a pull, and the `-local` image, are reproducible; the
  marker records the commit of every model. A default model pulled at another commit is refused
  at start (pull it again); other models are pulled at the commit `main` points to then.
- **Never downloaded at run time.** Models load from that folder only (fastembed's
  `specific_model_path` and `local_files_only`), which never reaches Hub code, so
  `HF_HUB_OFFLINE` is not needed; a test with sockets blocked proves no connection is made.
  A role whose model is not there is **turned off at start** with an error naming the command
  (`AI role embedding (local:BAAI/bge-small-en-v1.5) is off: model ... is not in ...: run
  `exactdocs models pull BAAI/bge-small-en-v1.5``); the server starts and answers BM25.
- **In process, bounded:** each model is loaded once per process (at start for the instance's
  roles), never on the event loop. The embedding jobs' batches run on a pool of their own (one
  at a time); what a search waits on (its query embedding, the rerank) runs on another (two at
  a time), so a search never queues behind ingestion. Each call gives ONNX Runtime half the
  cores, and its memory arena is off. A local model embeds at most 16 texts per call (padding
  to the longest text costs memory). On a 4-core x86_64 machine, embedding the fixture library
  (3 versions, 61 distinct chunks) with bge-small took 2.4 to 3.3 s (4.7 to 5.7 s of CPU), and
  the whole process grew from 398 MB (app and model loaded) to about 495 MB, peaking near
  530 MB; with all cores per call, one arena and batches of 64 it was 4.3 to 5.9 s and 636 MB.
- A local model cannot shorten its vectors: leave `[ai.embedding] dimensions` unset (or set to
  the model's). A `local` profile runs no chat model; use `ollama` (or any `openai-compatible`
  server) for a local LLM.
- **Budgets (#95):** a local model is priced at 0, so a US dollar budget is accepted at start
  and never stops it; its tokens are recorded as for any model, so a token budget can stop the
  embedding job (queued again when the window resets). A search's query embedding and rerank on
  a local model are never refused by a budget: only paid calls are checked.

The hybrid (#92), HyDE (#94) and agentic (#98) pipelines are built.

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
- **Connect with a session**: directly to PostgreSQL, or through a pooler in session mode
  (PgBouncer's `pool_mode = session`). A pooler in **transaction mode** is unsupported: it hands
  each transaction to any server connection, and ExactDocs' jobs (DBOS's `LISTEN`, the executor
  slots' advisory locks) and psycopg's prepared statements need the same session from one
  statement to the next, so jobs would fail at random. Supabase's is refused at start from its URL
  (see [Supabase](#supabase)). Any other (a self-hosted PgBouncer on 6432, another provider's, or
  Supabase's named by its IP address) cannot be recognised from the URL: after migrating, each
  process sets a session value in one transaction and reads it back in the next, and logs a
  WARNING naming the session or direct connection to use when it was lost. That probe can only
  warn, never prove a session: a transaction-mode pooler with one idle server connection keeps
  the value, so no warning is no guarantee. The process starts either way.
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
- Search is chosen when a process starts, from what the database offers. With ParadeDB's
  `pg_search` extension installed in the database (the ParadeDB image below installs it), search
  is BM25, as on SQLite: the first start builds its index (`retrieval_search_bm25`, a while on a
  large instance; `CONCURRENTLY`, so the instance keeps serving and importing meanwhile; if it
  fails, the process logs a WARNING, uses full-text search and tries again at its next start),
  later ones find it. Without it, search uses PostgreSQL's full-text search (`tsvector`, the `simple`
  configuration, ranked with `ts_rank_cd`, words cut as SQLite's index cuts them), and the log
  says why: at INFO on a server without `pg_search` (managed PostgreSQL such as Supabase), as a
  WARNING when the server has it but the database does not (`CREATE EXTENSION pg_search CASCADE`
  adds it). Both pass the shared ranking suite as SQLite does, and both read the same rows: adding
  the extension needs only a restart, no `exactdocs reindex`; removing it needs
  `DROP EXTENSION pg_search CASCADE` (the BM25 index depends on it), then a restart. `/healthz`
  names the engine in use (`search_engine`: `fts5`, `pg_search` or `postgres_fts`).
- Writes that must not interleave (storing and activating a version, indexing it) take turns
  across all processes, as on SQLite, so several processes serve more readers but do not import
  faster. A writer that waits more than 30 s for its turn gives up with an error, as SQLite does
  after its own wait.
- The sign-in throttle's counts live in the database (`identity_failed_sign_ins`,
  `identity_known_sign_ins`), so failed sign-ins count the same on every process; they survive a
  restart, and old ones are deleted whenever a new one is written.
- Hybrid search keeps its vectors in the same database with **pgvector** (#243): one table per
  embedding model, with a `vector(<dimensions>)` column, searched exactly (cosine distance, no
  index), so any dimensions up to pgvector's 16,000 work, including those above the 2,000 an
  index would allow. ExactDocs looks for the `vector` extension once per process, when an
  embedding model is configured, and creates it if it is not in the database yet. Creating it
  needs a superuser (pgvector is not a trusted extension): the ParadeDB image of the example
  already has it in every new database; elsewhere run `CREATE EXTENSION vector;` as a superuser
  in the ExactDocs database (managed services offer it as well: on Supabase, see
  [Supabase](#supabase); it goes to schema `extensions` there, which ExactDocs finds), then
  restart ExactDocs. Without it hybrid search answers with BM25 (`fallback_reason:
  vector_store_unavailable`), the server logs why, and `/healthz` names the missing extension in
  `vector_store_missing`.

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
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U exactdocs -d exactdocs"]
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

### Supabase

ExactDocs runs on a [Supabase](https://supabase.com) project's database, as PostgreSQL without
`pg_search` (only the database: no Supabase SDK, Auth or Storage). Everything in
[PostgreSQL](#postgresql) applies; search is PostgreSQL's full-text search (`search_engine:
postgres_fts`), which passes the same ranking suite as SQLite, and hybrid search keeps its vectors
in pgvector from the `extensions` schema. CI runs the scenarios below and the ranking suite on the
`supabase/postgres` image, over SSL, with the role this setup creates.

1. **Set up a role and schemas** once, in the SQL editor (as `postgres`). ExactDocs gets a login
   role without `CREATEDB`, its tables in schema `exactdocs` and DBOS's
   in schema `dbos` (neither is exposed by the Data API unless you add it there), and pgvector's
   `vector` in `extensions` (the role cannot create it: Supabase lets only `postgres` do that):

<!-- supabase.sql: start -->
```sql
-- ExactDocs on Supabase (README, "Supabase"): run once in the SQL editor, as `postgres`.
-- A login role of its own, without CREATEDB, owning one schema for ExactDocs' tables and one
-- for DBOS's. Neither schema is exposed by Supabase's Data API unless you add it there.
-- Then give the role a password of your own, in a statement of its own (README, step 2).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE ROLE exactdocs LOGIN NOCREATEDB NOCREATEROLE; -- no password yet: it cannot sign in
GRANT exactdocs TO postgres; -- lets `postgres` hand the schemas to it (PostgreSQL 16 and newer)
CREATE SCHEMA exactdocs AUTHORIZATION exactdocs;
CREATE SCHEMA dbos AUTHORIZATION exactdocs;
GRANT USAGE ON SCHEMA extensions TO exactdocs; -- pgvector's type and operators
ALTER ROLE exactdocs SET search_path = exactdocs, extensions;
```
<!-- supabase.sql: end -->

2. **Give the role a password**, in a statement of its own: the script sets none, so the role
   cannot sign in until you do, and a pasted script never leaves a known password behind.
   Generate one (`openssl rand -hex 24`) and run, with it in place of the placeholder,
   `ALTER ROLE exactdocs PASSWORD '<the generated password>';`. From `psql`, keep it out of your
   shell history with `\set password <the generated password>` and then
   `ALTER ROLE exactdocs PASSWORD :'password';`.
3. **Connect with a session**, never the pooler's transaction mode: ExactDocs' jobs (DBOS's
   `LISTEN`, the executor slots' advisory locks) and psycopg's prepared statements need the same
   session from one statement to the next. A URL on port 6543 of a Supabase host (Supavisor's or
   the dedicated pooler's transaction mode) is refused at start, saying so; the pooler named by its
   IP address cannot be recognised from the URL, and gets only the start-up probe's WARNING (see
   [PostgreSQL](#postgresql)), which cannot catch every case. Use either
   - the **direct connection**, `postgresql://exactdocs:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require`.
     It is **IPv6 only** unless the project has the IPv4 add-on: from a host or a Docker network
     without IPv6, it cannot connect; or
   - the **session pooler** (Supavisor in session mode, IPv4 and IPv6), the same host as the
     transaction pooler on **port 5432**, with the project in the user name:
     `postgresql://exactdocs.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require`.
     Each ExactDocs process keeps a few connections open (a pool, its executor slot and DBOS's):
     size the pooler's session limit for every process.
4. **Keep `sslmode=require`** (or `verify-full` with Supabase's CA certificate), in the URL or in
   `PGSSLMODE`: without either on a Supabase host, the server logs a WARNING that the connection
   may not be encrypted.
5. Set `EXACTDOCS_SECRET_KEY` as for any PostgreSQL instance, and start ExactDocs. `/api/health`
   reports `search_engine: postgres_fts`; with an embedding model configured, `vector_store_missing`
   stays empty. Without `GRANT USAGE ON SCHEMA extensions`, the log says that pgvector is in a
   schema the role may not use (and which `GRANT` fixes), `/api/health` names `vector` in
   `vector_store_missing`, and hybrid search answers with BM25.

Back up with Supabase's backups or `pg_dump -n exactdocs -n dbos`.

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
| `/healthz` | `200` while the process runs, whatever the database does, within about 0.3 s: `status`, `version`, `database_reachable`, and (when the database answered in time) `schema_revision`, `search_index_format`, `reindex_required`, `search_engine` (`null` when unknown), `vector_store_missing` (the extension hybrid search needs and cannot load, once an embedding model is configured: `sqlite-vec` or `vector`; `null` otherwise) | liveness: restart the process when it stops answering |
| `/readyz` | `200 {"status": "ready"}` when the database file exists, answers within 2 s and is at this version's schema, else `503 {"status": "not_ready", "reason": ...}` | readiness: send traffic only while it is ready |

`/api/health` is an alias of `/healthz`, kept for existing clients. Neither probe creates a
missing database file (an existing empty one gets SQLite's header and WAL files on connect). To
wait for a starting instance, poll `/readyz`: liveness answers before the database does.
A probe stops waiting for the database when its budget is up, even while a statement still
runs; that check ends in the background, and later probes wait for it instead of starting
another: however often they are called, a stuck database holds at most one connection for each.
So a probe may get the result of a check an earlier probe started. A stopping instance waits up
to 2 s for such a check, then cancels it and waits up to 2 s more, before it closes its database
connections. A statement stuck in the driver's thread cannot be interrupted: if the check still
runs after those 4 s, the instance logs a warning and stops without it, and that connection may
be finalized, unclosed, later.

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
