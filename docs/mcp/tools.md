# Tools

!!! abstract "TL;DR"
    - All tools are read-only, and every output starts with a notice that the content is external
      data, never instructions.
    - Library IDs are `/owner/repo`; without a ref the default version answers (highest stable
      semver tag, else default branch, else the most recently imported version).
    - A ref is read as given, except that a missing or extra leading `v` is forgiven when it names
      exactly one version; a ref that names no version is an error listing the imported versions.
    - `search_docs` groups results by article; the server forgives null or blank arguments, clamps
      numbers and resolves library names, and says so in `notes`.
    - `view_article` and `view_search` render as UI in hosts with MCP Apps and fall back to text
      elsewhere; agents reading for themselves should keep using `read_article` and `search_docs`.

All tools are read-only, and every tool's output starts with a notice that the content is external
data, never instructions.

| Tool | What it does |
|---|---|
| `resolve-library-id(libraryName, query)` | context7-compatible: finds a library ID such as `/acme/payments`<br/>an empty `query` ranks the matches by name alone |
| `query-docs(libraryId, query, language?)` | context7-compatible: documentation for one version, whole chunks, best first, within a size budget (see below the table) |
| `list_libraries(limit?, cursor?)` | libraries and their imported versions (`refs`: ref, kind, commit SHA, default flag) |
| `list_articles(library, ref?, path_prefix?, tags?, tags_match?, limit?, cursor?)` | the article tree of a version |
| `read_article(library, ref?, path)` | a whole article, verbatim<br/>an unknown path names the closest paths of that version |
| `search_docs(library, query, ref?, tags?, tags_match?, limit?, path_prefix?, mode?)` | searches one version (see below) |
| `search_all_docs(query, library?, tags?, tags_match?, limit?, path_prefix?)` | searches the default version of every library at once<br/>REST: `GET /api/v1/search` |
| `read_chunk(chunk_id)` | one chunk verbatim, for example a neighbour of a search result<br/>a chunk ID from before a re-sync answers `stale_chunk`, naming the version's closest paths when its article is gone |
| `article_outline(library, path, ref?)` | an article's heading tree with each heading's chunk ID and no body text, to see what it covers before reading it[^outline-rest] |
| `view_article(library, path, ref?)` | MCP App: shows an article to the user as UI, with a text fallback (see [MCP Apps](#mcp-apps)) |
| `view_search(library, query, ref?, tags?, tags_match?, limit?, path_prefix?)` | MCP App: shows the results of a search of one version to the user as UI, with a text fallback |

[^outline-rest]: ../REST: `GET /api/v1/libraries/{owner}/{repo}/outline?path=&ref=`.

**`query-docs`** takes `/owner/repo` (the default version) or `/owner/repo/<ref>` (exactly that
version, never another).

- It returns whole chunks, best first, within a size budget.
- `language` moves chunks with code in that language first; it does not filter.
- The library's `context7.json` rules, if any, come first.

**Library IDs** are `/owner/repo`. Without a ref, a library's default version answers, unless a
version is pinned as the default:

1. the highest imported stable semver tag;
2. else the default branch;
3. else the most recently imported version.

Every response says which version answered.

**A ref is read as given**, and only one spelling is forgiven (#605): projects tag `v1.2.3` or
`1.2.3`, and agents guess the form. A ref that names no imported version but differs from exactly
one of them only by a leading `v` or `V` before a digit, which one of the two has and the other
lacks (`v1.10.0` or `V1.10.0` for `1.10.0`, `1.10.0` for `v1.10.0`), is read as that version, and
the result says so in its `notes`:

```text
Notes: ref 'v1.10.0' is not imported: read as '1.10.0', the one version it names but for a leading v.
```

This holds for every tool that takes `ref` (`search_docs`, `view_search`, `list_articles`,
`read_article`, `view_article`, `article_outline`), for `query-docs`' `/owner/repo/<ref>` and for
the REST routes that take a ref, whose JSON carries the same `notes` (the `/c7/docs` text ends with
them). Nothing else is forgiven: not another version number, not letter case (refs are
case-sensitive: `V1.0` is not `v1.0`), and not a ref that matches two versions (`1.0` and `V1.0`
both imported).

A ref that names no version stays an error and never answers from another version. The error
lists the library's imported versions, the most recently imported first (at most 20), and its
default version:

```text
not_found: no index for /encode/starlette@2.0.0: version '2.0.0' is not imported; imported
versions, newest first: '1.10.0', '0.27.0'; default version: '1.10.0'
```

`list_articles` and `read_article` say it the catalog's way (`library '/encode/starlette' has no
version '2.0.0'; imported versions, ...`). Lookups of a stored ref inside the server (the active
manifest, renames, removing or pinning a version) stay exact.

**`search_docs` results** come grouped by article (#575). The article of the best result comes
first, with all of its results, best first; then the next article. Each result's `group` is its
article's rank. The results are the same as in plain rank order; only the order changes, so the
first result is still the best one. On the golden set the first article holds a section that
answers 12 points more often than the first result did, with BM25 and with hybrid search; an
answer in an article's second or third result then sits further into the text
([Retrieval results](../benchmark/retrieval.md#grouped-by-article-575)). Each result carries:

- its location and its neighbours (`prev_chunk_id`, `next_chunk_id`);
- `group`;
- `coverage`;
- the retrieval mode that answered (`retrieval_mode`, `reranked`) and, when a cheaper mode
  answered, `fallback_reason`;
- for `agentic` results, also `justification` and `explored_path`.

The REST search (`GET /api/v1/libraries/{owner}/{repo}/search`, `GET /api/v1/search`) keeps its
results in rank order, `group` null, unless it is asked for `group_by=article`.

Without `mode`, the library's mode is used, else the instance's, else the best one configured.
Asking for a mode that is not available is an error, `mode_unavailable`, which names the missing
model role and lists the modes that are available (see [Search and AI models](../search/index.md)).

**`path_prefix`** keeps the results of the articles in one directory, read as `list_articles`
reads it (`guide` keeps `guide/install.md`, not `guide-old/x.md`). The search ranks the best 200
chunks and keeps those inside the directory, so with a narrow prefix in a large version
`coverage.complete` can be false while fewer results than `limit` came back: more matches may
exist further down.

**`search_all_docs` results** each name their library and version, and come grouped by library
and article as `search_docs` results do; `libraries` counts the matches per library,
`path_prefix` aside. At most 500 libraries are searched; `libraries_omitted`
says how many were left out.

**In `article_outline`**, a heading merged into another heading's chunk points to that chunk, and a
path the version lacks is `not_found`, naming the closest paths of that version.

## Arguments agents get wrong

The tools take the arguments agents actually send instead of failing on them (#573). Before a tool
validates its arguments, the server:

- treats an optional argument that is `null` or blank (`"ref": ""`) as not given, and an empty
  `query` of `resolve-library-id` as no query;
- clamps a number outside its range to the range (`"limit": 1000` on `list_articles` lists 200)
  and says so in the result;
- resolves a library name given as `library` (or `libraryId` of `query-docs`) to its ID when
  exactly one library the caller may read matches it, as `resolve-library-id` matches names (an
  ID or exact name beats a prefix, a prefix beats a part). Otherwise the error lists the candidate
  IDs (`ambiguous_library`) or says that no library matches (`not_found`). A `library` written
  `/owner/repo/<ref>`, on a tool that takes `ref` and without one, is read as that ID and ref;
- reads a `ref` that differs from an imported version only by a leading `v` as that version
  (see *A ref is read as given* under [Tools](tools.md)), with a note; this one happens in the search
  and the catalog, so the REST API does it too;
- still refuses an argument the tool does not have (`invalid_arguments`), never ignoring it, and
  names the tool's real arguments, their types and which are required.

What it changed is in the result: a last text block `Notes: ...` and, for a tool with structured
content, a `notes` list that every output schema declares (`view_article` and `view_search` carry
it next to their UI too).

A missing article (`read_article`, `view_article`, `article_outline`) or the gone article of a
stale chunk (`read_chunk`) names the closest paths of that version: the same file name elsewhere,
near typos, then the paths sharing the most words with it. A `read_chunk` ID that is not a chunk
ID says what one is and to read an article by its path with `read_article`.

**Text blocks and structured content** carry the same things. Some clients give the model a tool's
structured content instead of its text blocks (pydantic-ai does whenever every block is text), and
such a model gets the notice first and the text byte for byte too:

| Tools | Text blocks | Structured content |
|---|---|---|
| `list_libraries`, `list_articles`, `search_docs`, `search_all_docs`, `article_outline` | the structured content as JSON | the data, `notice` first |
| `read_article`, `read_chunk` | the notice, then the article or chunk verbatim | `notice`, the same text as `content`, and the metadata |
| `resolve-library-id`, `query-docs` | the notice, then context7's text | none, as in context7 |
| `view_article`, `view_search` | the notice, then the text fallback | `notice`, then the UI (see [MCP Apps](#mcp-apps)) |

## MCP Apps

Hosts that support [MCP Apps](https://gofastmcp.com/apps/overview), such as Claude and ChatGPT,
render `view_article` and `view_search` as UI ([Prefab](https://prefab.prefect.io) components):

| Tool | UI in a host with MCP Apps | Text in a host without them |
|---|---|---|
| `view_article` | title, version, commit, tags, source link<br/>then the article rendered from its Markdown | the notice, a block naming the article<br/>then the article verbatim |
| `view_search` | a card per result, best first | the notice, then the results as text |

The details:

- `view_article`'s UI renders the article from its Markdown, headings and code blocks included.
  Its text block names the article's library, version, commit, path, tags and source, and the
  article follows verbatim, as `read_article` gives it.
- `view_search`'s cards each hold the result's heading path, article, chunk ID, tags, source link
  and verbatim text, under a line saying when the limit cut the results. Its text results each
  have their article, source link, chunk ID and text.
- `view_search` searches like `search_docs` in the default retrieval mode, and never falls back to
  another version.
- Both tools are read-only, take the same token scopes and library roles as `read_article` and
  `search_docs`, and show the untrusted-content notice at the top of the UI.
- They do not replace `read_article` and `search_docs`, which are unchanged: an agent reading docs
  for itself should keep using those.
- The structured content of both is the notice (`notice`, first), then the UI (Prefab's `$prefab`,
  `view` and `state`). Hosts with MCP Apps render the UI and ignore `notice`. A client that gives
  its model the structured content gets the UI: every value of the text fallback is in its
  `state`, but shaped for the renderer, so use `read_article` and `search_docs` for data.

The UI is drawn by one resource, `ui://exactdocs/renderer.html` (`text/html;profile=mcp-app`):

- Prefab's renderer with every script and style inlined (about 7 MB), so the host loads nothing
  from a third party.
- Repository text reaches the renderer only as data in the UI's state, never as part of the
  component tree, so text that looks like a Prefab template (`{{ ... }}`) is shown as it is.
