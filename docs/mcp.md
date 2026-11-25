# MCP

ExactDocs speaks the [Model Context Protocol](https://modelcontextprotocol.io) at `/mcp`
(Streamable HTTP) and over stdio. Agents get context7-compatible tools, so a client set up for
context7 only needs a new URL, plus tools for browsing, reading and searching one version of a
library.

## Connect a client

The quickest way is to let ExactDocs print the configuration:

```bash
uvx exactdocs config --client claude            # claude, claude-desktop, cursor, vscode, codex
uvx exactdocs config --client codex --stdio     # local, read-only, no token
uvx exactdocs skill                             # prints the agent usage skill; redirect it to a SKILL.md
                                                # (also the MCP resource skill://exactdocs/SKILL.md)
```

`config` prints a snippet to paste into the client's configuration file. The snippet never holds
your token: it refers to `EXACTDOCS_TOKEN` (VS Code asks for it instead) unless you pass
`--show-token`.

- Claude Desktop reaches HTTP servers through `mcp-remote`, pinned to `0.16.0`. Replace the
  `<your-exactdocs-token>` placeholder there with your token.
- Desktop apps often lack `~/.local/bin` on their `PATH`. Put the absolute paths from `which uvx`
  or `which npx` in `command`.
- With `--show-token` the snippet holds your real token, so never commit the file it goes into;
  the command warns about this on stderr.

`--new-token` is the better option. It creates a token just for this client (asking for your
password, like `token create`), so revoking it breaks nothing else. The token is named
`mcp-<client>` (`--name` changes that) and expires after 90 days (`--expires-in` changes that).
The command prints its id on stderr, for `exactdocs token revoke <id>`.

### Over HTTP

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

MCP over HTTP needs an API token (or [OAuth](#oauth-for-web-hosts), for hosts that cannot paste
one), and the token acts as the account that created it. Tokens start with `exd_`. They are shown
once when created, stored only as a hash, may expire, and stop working the moment they are
revoked. Create, list and revoke them on the **Account** page of the web UI, with
`exactdocs token`, or over the REST API with a signed-in session. The token routes do not accept a
token, so a leaked token cannot mint successors.

<figure class="xd-shot" markdown>

![The Account page on its API tokens tab: one token for every library the account can read, with the start of the token; below it, the MCP client config to paste, with the server's /mcp URL and a placeholder where the token goes.](assets/screenshots/connect-light.webp#only-light){ loading=lazy }
![The Account page on its API tokens tab: one token for every library the account can read, with the start of the token; below it, the MCP client config to paste, with the server's /mcp URL and a placeholder where the token goes.](assets/screenshots/connect-dark.webp#only-dark){ loading=lazy }

<figcaption>The <strong>Account</strong> page: the tokens, and the config for this server with a
placeholder for the token.</figcaption>

</figure>

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

### OAuth for web hosts

Web hosts such as Claude and ChatGPT cannot paste an API token; they connect with OAuth. Choose
one of your [sign-in providers](getting-started.md#sign-in-through-an-identity-provider) for them
(an MCP client discovers a single authorization server):

```bash
EXACTDOCS_MCP_OAUTH_PROVIDER=corp
```

The host then finds the OAuth metadata at `/.well-known/oauth-authorization-server` and
`/.well-known/oauth-protected-resource/mcp` on the server's root, registers itself, shows the
person a consent page on your server, and sends them to the provider. API tokens keep working next
to it, so the CLI and coding agents are unaffected.

- **Register a second redirect URI.** At the provider, add `<EXACTDOCS_PUBLIC_URL>/auth/callback`
  to the client's redirect URIs, next to the one for the web sign-in. The provider needs a client
  secret (the proxy derives its token signing key from it).
- **Same membership checks.** The provider's `allowed_groups`, `allow_any_user` and `admin_groups`
  apply, and a disabled account is refused. The check runs at every call, not only at sign-in, but
  for OIDC it reads the ID token the server holds for the host, so what it sees depends on the change:
    - A person who signs in to the web UI as well acts as that account; **disabling the account
      gives a `401` at the next call**, with the same token.
    - A person who **leaves a group at the provider** keeps access until the ID token expires
      (usually about an hour), because the token itself does not change. Then the host gets a
      `401`, renews with its refresh token, and the provider's current groups apply: a person
      outside the allowed groups gets no working token.
  Anyone who never signed in to the web UI acts as `<provider>:<subject>`, and no account is
  created. Library group grants use the verified provider groups with the provider's
  `group_prefix`, including for these OAuth-only callers; members of `admin_groups` can manage
  every library. A linked caller can also use grants to their account. The request's verified
  groups and role are used without changing stored web-account memberships or refresh tokens.
- **What the host sees when the ID token expires.** A `401` with the usual `WWW-Authenticate`
  header. A host that keeps its refresh token trades it for a new token and carries on; one that
  does not sends the person through the sign-in again.
- **OIDC groups must be in the ID token.** The check reads the provider's ID token (always a JWT),
  not userinfo. Make sure the `groups_claim` is in it (ADFS: an issuance transform rule for
  `group`; Entra ID: the groups optional claim).
- **OAuth2 and GitHub use opaque access tokens.** `oauth2` reads current userinfo at each MCP
  request; `github` reads the current user and applies the same organization/team checks and
  app-approval/SSO refusals as browser sign-in. Lost membership is refused at the next MCP request.
  Both use FastMCP `OAuthProxy` with the configured endpoints; OIDC/ADFS uses `OIDCProxy`.
  The presets follow their protocol: `discord` is OAuth2, `google` and `microsoft` are OIDC (a
  multi-tenant Microsoft provider checks each token against its own tenant's issuer). A provider
  that creates no accounts (`auto_create_users = false`, the presets' default) refuses a person
  whose identity no account has linked; a linked identity acts as its account, with the
  account's own role and groups.
  GitHub `base_url`/`api_url` support GitHub.com, Enterprise Server and `*.ghe.com`, as in
  [GitHub setup](configuration/sign-in.md#github-and-github-enterprise-sign-in). GitHub OAuth Apps accept
  one callback URL: use a separate OAuth App/provider for MCP with `/auth/callback` as its
  callback, and choose that provider with `EXACTDOCS_MCP_OAUTH_PROVIDER`.
- The `Host` and `Origin` allowlist (`EXACTDOCS_ALLOWED_HOSTS`, `EXACTDOCS_ALLOWED_ORIGINS`)
  applies to the OAuth routes too. The proxy keeps its registrations and tokens, encrypted, in
  `<data dir>/mcp-oauth`; changing the client secret makes hosts sign in again, and the state kept
  under the old secret is deleted at the next start.

### Behind Cloudflare Access

When ExactDocs runs [behind Cloudflare Access](deployment/reverse-proxy.md#behind-cloudflare-access) with
[`[auth.cloudflare_access]`](configuration/sign-in.md#cloudflare-access) configured, an MCP client needs
no ExactDocs token: it sends only the Access service-token headers. Access checks them, adds its
signed token to the request, and ExactDocs runs the call as the account the service token's client
ID is mapped to in `service_tokens`, with that account's library roles.

```json
{
  "mcpServers": {
    "exactdocs": {
      "url": "https://docs.acme.com/mcp",
      "headers": {
        "CF-Access-Client-Id": "<client id>.access",
        "CF-Access-Client-Secret": "<client secret>"
      }
    }
  }
}
```

A client that also sends `Authorization: Bearer exd_...` acts as that token's account instead
(a wrong token is refused, never replaced by the Access identity). A service token that is not
mapped, or whose account is missing or disabled, gets a `401`.

### Without a network port: stdio

```json
{
  "mcpServers": {
    "exactdocs": { "command": "uvx", "args": ["exactdocs", "serve", "--stdio"] }
  }
}
```

stdio needs no token and no running server, but it does need an existing database. Run
`exactdocs serve` (or `exactdocs admin create`) once first; otherwise it exits with an error on
stderr naming the path it expected.

It uses the same data directory (`EXACTDOCS_DATA_DIR`) and opens the SQLite file read-only
(`mode=ro` and `query_only`), which is safe next to a running server that keeps importing. It runs
no worker, no identity and no migration, and it exposes the same read-only tools. Manage libraries
through the server. `--host`, `--port` and `--reload` only apply to HTTP and are rejected with
`--stdio`.

!!! note "One write: AI spend"
    When an LLM step or a paid reranker runs in a stdio process, its spend is added to the shared
    `retrieval_ai_spend` ledger (with its replay tokens), so the server's budgets and
    `GET /api/v1/ai/usage` count it. That write goes through a second connection of its own.

    - On SQLite it opens the existing file with `mode=rw` under an authorizer that refuses every
      write to any other table, every schema change and every `PRAGMA` but a few reads.
    - On PostgreSQL it is the same role without `default_transaction_read_only`, used by the spend
      ledger alone.

    If that write fails (a read-only file system, a lock held too long), the process logs a warning
    and keeps the spend in memory until it exits; the AI call never fails because of it. While the
    server holds the SQLite write lock, a stdio call that spent can wait up to 5 s for it before
    falling back to memory.

Keep stdio and the server on the same release: if the server has been upgraded and has migrated
the database, upgrade the stdio command too.

Run stdio as the same user as the server. With the server stopped, SQLite creates
`exactdocs.db-wal` and `-shm` next to the database (the directory must be writable for that), and
files owned by another user can stop the server from starting later. The same goes for every other
command, since all of them except `serve --stdio` migrate: the first one creates
`exactdocs.db-migration.lock` next to the database (mode 0600), processes that start together take
turns on that lock to migrate, and a server that cannot open it stops with an error naming it.

## Tools

All tools are read-only, and every tool's output starts with a notice that the content is external
data, never instructions.

| Tool | What it does |
|---|---|
| `resolve-library-id(libraryName, query)` | context7-compatible: finds a library ID such as `/acme/payments` |
| `query-docs(libraryId, query, language?)` | context7-compatible: documentation for `/owner/repo` (the default version) or `/owner/repo/<ref>` (exactly that version, never another). Returns whole chunks, best first, within a size budget. `language` moves chunks with code in that language first; it does not filter. The library's `context7.json` rules, if any, come first |
| `list_libraries(limit?, cursor?)` | libraries and their imported versions (`refs`: ref, kind, commit SHA, default flag) |
| `list_articles(library, ref?, path_prefix?, tags?, tags_match?, limit?, cursor?)` | the article tree of a version |
| `read_article(library, ref?, path)` | a whole article, verbatim; an unknown path lists close matches |
| `search_docs(library, query, ref?, tags?, tags_match?, limit?, mode?)` | searches one version (see below) |
| `search_all_docs(query, library?, tags?, tags_match?, limit?)` | searches the default version of every library at once (REST: `GET /api/v1/search`) |
| `read_chunk(chunk_id)` | one chunk verbatim, for example a neighbour of a search result; a chunk ID from before a re-sync answers `stale_chunk` |
| `article_outline(library, path, ref?)` | an article's heading tree with each heading's chunk ID and no body text, to see what it covers before reading it (REST: `GET /api/v1/libraries/{owner}/{repo}/outline?path=&ref=`) |
| `view_article(library, path, ref?)` | MCP App: shows an article to the user as UI, with a text fallback (see [MCP Apps](#mcp-apps)) |
| `view_search(library, query, ref?, tags?, tags_match?, limit?)` | MCP App: shows the results of a search of one version to the user as UI, with a text fallback |

Library IDs are `/owner/repo`. Without a ref, a library's default version answers: the highest
imported stable semver tag, else the default branch, else the most recently imported version,
unless a version is pinned as the default. Every response says which version answered.

`search_docs` results carry their location, their neighbours (`prev_chunk_id`, `next_chunk_id`),
`coverage`, the retrieval mode that answered (`retrieval_mode`, `reranked`) and, when a cheaper
mode answered, `fallback_reason`. `agentic` results also carry `justification` and
`explored_path`. Without `mode`, the library's mode is used, else the instance's, else the best one
configured. Asking for a mode that is not available is an error, `mode_unavailable`, which names
the missing model role and lists the modes that are available (see
[Search and AI models](search/index.md)).

`search_all_docs` results each name their library and version, and `libraries` counts the matches
per library. At most 500 libraries are searched; `libraries_omitted` says how many were left out.

In `article_outline`, a heading merged into another heading's chunk points to that chunk, and a
path the version lacks is `not_found`.

### MCP Apps

Hosts that support [MCP Apps](https://gofastmcp.com/apps/overview), such as Claude and ChatGPT,
render `view_article` and `view_search` as UI ([Prefab](https://prefab.prefect.io) components):

- `view_article`: the article's title, version, commit, tags and source link, then the article
  rendered from its Markdown, headings and code blocks included.
- `view_search`: a card per result, best first, with its heading path, article, tags, source link
  and verbatim text. It searches like `search_docs` in the default retrieval mode, and never falls
  back to another version.

Both tools are read-only, take the same token scopes and library roles as `read_article` and
`search_docs`, and show the untrusted-content notice at the top of the UI. They do not replace
`read_article` and `search_docs`, which are unchanged: an agent reading docs for itself should keep
using those.

Hosts without MCP Apps get text instead. `view_article` returns the notice, a block naming the
article's library, version, commit, path, tags and source, then the article verbatim, as
`read_article` gives it. `view_search` returns the notice, then the results as text, each with its
article, source link, chunk ID and text. The structured content of both is the UI, not data: use
`read_article` and `search_docs` for that.

The UI is drawn by one resource, `ui://exactdocs/renderer.html` (`text/html;profile=mcp-app`):
Prefab's renderer with every script and style inlined (about 7 MB), so the host loads nothing from
a third party. Repository text reaches the renderer only as data in the UI's state, never as part
of the component tree, so text that looks like a Prefab template (`{{ ... }}`) is shown as it is.

## Resources

Clients that browse resources read articles from the resource template
`exactdocs://{owner}/{repo}/{path*}{?ref}`. Without `ref`, the default version answers.

- Percent-encode `ref`: `/` is `%2F` and `+` is `%2B`. A bare `+` means a space and is refused, so
  write `?ref=v1.0.0%2Bbuild`. A repeated `ref` is refused.
- `{path*}` is FastMCP's multi-segment match, not RFC 6570, so `guide/a.md` and `guide%2Fa.md`
  read the same article. A mixed-case owner or repo (lowercased like library IDs), percent-encoded
  letters and `./` segments are other aliases of the same article; `../` never leaves the version's
  article tree.
- A missing library, version or article is JSON-RPC error `-32002`.

A read returns two items: the untrusted-content notice as `text/plain`, then the article as
`text/markdown`, byte for byte what `read_article` gives, with its ref, commit SHA and source link
in `_meta`. MCP does not say how clients present several items, so the leading notice is best
effort; the template description and the server instructions carry the notice too.

`resources/list` is a truncated sample: at most 200 articles of the libraries' default versions,
shared fairly across libraries, always with an explicit `?ref=`, sorted by URI and paged with a
stable cursor. Pages hold 50 entries today, but clients must not assume a page size. Every page's
`_meta` has `truncated` and `max_resources`, and the list is rebuilt at most every 30 seconds. Use
the template or `list_articles` for everything else.

Resources sit behind the same bearer token as the tools and are served read-only over stdio.

## context7 over REST

Integrations that do not speak MCP get the same two operations with context7's parameter names and
shapes, the same use cases, budget and API tokens. Only the paths differ; there is no `/api/v2`
alias.

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

- Search returns JSON `{results: [{id, title, description, branch, versions, ...}], searchFilterApplied}`.
- Docs with `type=txt` (the default) returns the notice, a blank line, then the tool's text byte
  for byte. `type=json` returns `infoSnippets`, one per chunk; `codeSnippets` is always empty.
- `libraryId` takes `/owner/repo`, `/owner/repo/<ref>` and context7's `/owner/repo@<ref>`.
- `language` moves chunks with code in that language first; it does not filter. context7's `fast`
  is accepted and ignored.
- Both mark their content as untrusted: JSON carries `notice`, and the text starts with it and also
  carries it in the `X-ExactDocs-Notice` header.
- Errors are `{error, detail, message}`, where `message` repeats `detail` for context7 clients.

## The query-docs budget

`query-docs` answers within `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET` tokens (10,000 by default, notice
included, counted as characters / 4).[^tokens] It only returns whole chunks. A chunk too large for
the budget is listed as a pointer to fetch with `read_chunk`, and a last line says how many
matching chunks were left out.

[^tokens]: Characters divided by four undercounts CJK text and dense code. The budget must be at
    least 500.
