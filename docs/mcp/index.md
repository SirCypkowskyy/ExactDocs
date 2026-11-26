# MCP

!!! abstract "TL;DR"
    - ExactDocs serves MCP at `/mcp` (Streamable HTTP, with an API token or OAuth) and over stdio
      (local, read-only, no token).
    - `uvx exactdocs config --client <client>` prints the config to paste; `--new-token` gives the
      client its own token.
    - The reading tools: context7's `resolve-library-id` and `query-docs`, plus tools to list,
      browse, read and search one version. Callers who may create libraries also get `add_docs`
      and `import_status` to add libraries and versions; nothing over MCP removes anything.
    - Every answer names the version it came from and starts with a notice that the content is
      external data, never instructions.
    - Integrations without MCP get the context7 operations over REST under `/api/v1/c7`.

ExactDocs speaks the [Model Context Protocol](https://modelcontextprotocol.io) at `/mcp`
(Streamable HTTP) and over stdio. Agents get:

- context7-compatible tools, so a client set up for context7 only needs a new URL;
- tools for browsing, reading and searching one version of a library;
- for those who may create libraries, tools that add a library or a version and follow its import.

## Pages

| Page | What it covers |
|---|---|
| [Connect a client](connect.md) | client snippets, HTTP with API tokens, OAuth for web hosts, Cloudflare Access, stdio |
| [Tools](tools.md) | every reading tool and its arguments, refs and default versions, arguments agents get wrong, MCP Apps |
| [Adding libraries from an agent](adding.md) | `add_docs` and `import_status`: who sees them, what they take, which sources are refused, `EXACTDOCS_MCP_IMPORT_HOSTS` |

## Resources

Clients that browse resources read articles from the resource template
`exactdocs://{owner}/{repo}/{path*}{?ref}`. Without `ref`, the default version answers.

- Percent-encode `ref`: `/` is `%2F` and `+` is `%2B`. A bare `+` means a space and is refused, so
  write `?ref=v1.0.0%2Bbuild`. A repeated `ref` is refused.
- `{path*}` is FastMCP's multi-segment match, not RFC 6570, so `guide/a.md` and `guide%2Fa.md`
  read the same article. Other aliases of the same article:
    - a mixed-case owner or repo (lowercased like library IDs);
    - percent-encoded letters;
    - `./` segments.

    `../` never leaves the version's article tree.
- A missing library, version or article is JSON-RPC error `-32002`.

A read returns two items:

1. the untrusted-content notice as `text/plain`;
2. the article as `text/markdown`, byte for byte what `read_article` gives, with its ref, commit
   SHA and source link in `_meta`.

MCP does not say how clients present several items, so the leading notice is best effort; the
template description and the server instructions carry the notice too.

`resources/list` is a truncated sample:

- at most 200 articles of the libraries' default versions, shared fairly across libraries;
- always with an explicit `?ref=`, sorted by URI and paged with a stable cursor;
- pages hold 50 entries today, but clients must not assume a page size;
- every page's `_meta` has `truncated` and `max_resources`;
- the list is rebuilt at most every 30 seconds.

Use the template or `list_articles` for everything else. Resources sit behind the same bearer token
as the tools and are served read-only over stdio.

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
- Docs:
    - `type=txt` (the default) returns the notice, a blank line, then the tool's text byte for
      byte;
    - `type=json` returns `infoSnippets`, one per chunk; `codeSnippets` is always empty.
- `libraryId` takes `/owner/repo`, `/owner/repo/<ref>` and context7's `/owner/repo@<ref>`.
- `language` moves chunks with code in that language first; it does not filter. context7's `fast`
  is accepted and ignored.
- Both mark their content as untrusted: JSON carries `notice`, and the text starts with it and also
  carries it in the `X-ExactDocs-Notice` header.
- Errors are `{error, detail, message}`, where `message` repeats `detail` for context7 clients.

## The query-docs budget

`query-docs` answers within `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET` tokens (10,000 by default, notice
included, counted as characters / 4).[^tokens]

- It only returns whole chunks.
- A chunk too large for the budget is listed as a pointer to fetch with `read_chunk`.
- A last line says how many matching chunks were left out.

[^tokens]: ../Characters divided by four undercounts CJK text and dense code. The budget must be at
    least 500.
