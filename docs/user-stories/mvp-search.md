# MVP: browsing, search, sync and running

!!! abstract "TL;DR"
    - BRW-01 to BRW-05: a file tree with rendered articles, source links, a version picker and a
      library home page.
    - SRCH-01 to SRCH-03: BM25 search that works with nothing configured, never leaves the selected
      version, and (MVP-2) spans all libraries.
    - MCP-01 to MCP-07: agent tools to list libraries and articles, read articles and chunks, and
      search with one result shape for every mode; doc text is treated as untrusted.
    - C7-01 to C7-04: context7's tools, arguments and IDs, so ExactDocs can replace it by changing
      only the server URL.
    - SYNC-01 to SYNC-04: re-sync, automatic tag imports, removal with garbage collection, and
      failures that keep the last good version served.
    - RUN-01 to RUN-05: a one-command start with a library browsable within five minutes, no
      bundled models, no unexpected outbound connections, automatic migrations and a fixture repo.

## Browse

- **[BRW-01]** As a user, I want to browse a library as a file tree and read each article rendered (code highlighting, tables, admonitions, images), because reading the docs is the point.
    - Acceptance:
        - the tree mirrors the repo paths and shows article titles
        - both admonition syntaxes render (MkDocs `!!! note` and GitHub `> [!NOTE]`)
        - in MVP-1 images load from the git host's raw URL (alt text for private repos)
        - *MVP-2:* from the imported copies.
- **[BRW-02]** *(MVP-2)* As a user, I want relative links and images between articles to work inside ExactDocs, because docs written for GitHub link to each other with relative paths.
    - Acceptance:
        - `[setup](../../setup.md#docker)` opens the imported article at that heading, also after git saw `setup.md` moved in that version (one hop)
        - links to files outside the selection open on the git host.
- **[BRW-03]** As a user, I want a "view on GitHub/Bitbucket/..." link on every article with the exact commit, because I sometimes need the surrounding code or history.
    - Acceptance: the link points at the file at the imported commit SHA, not at the branch head.
- **[BRW-04]** As a user, I want to switch between imported versions of a library (e.g. `v1.3` and `v1.4`), because I work on projects pinned to different versions.
    - Acceptance:
        - a version picker lists imported refs and marks the default version
        - switching keeps the same article path when it exists, else falls back to the version's root.
    - *MVP-2:* follows renames detected by git, also across versions the switch skips (v1.2.0 to v1.4.0 when v1.4.0 renamed the article; one lookup per target version, #201).
- **[BRW-05]** As a user, I want a home page listing my libraries with title, versions, article count, tags, last sync time and sync errors, because I need to see what is available and how fresh it is.
    - Acceptance: each library shows URL, refs, commit SHAs, article count and last sync status with the error if it failed.

## Search

- **[SRCH-01]** As a user, I want full-text BM25 search within a library version, with results showing article, heading and a highlighted snippet, because I often know a term but not where it is documented.
    - Acceptance:
        - works with nothing configured
        - identifiers such as `snake_case`, `camelCase`, `--flag` and `pkg.mod.fn` are indexed both whole and split into parts (see Decisions)
        - the ranking test suite is written against the search port and runs on SQLite (PostgreSQL parity comes with TEAM-01)
        - on the acceptance fixture repo, exact identifiers return their defining section first
        - results link to the section anchor.
- **[SRCH-02]** As a user, I want search to stay within the version I selected, because an answer from another version is worse than none.
    - Acceptance:
        - searching `v1.3` never returns text that exists only in `v1.4`
        - "no results in v1.3" is shown even when other versions match.
- **[SRCH-03]** *(MVP-2)* As a user, I want one search box across all my libraries (each at its default version) with a library facet, because I don't always know which library documents something.
    - Acceptance:
        - results are grouped or filterable by library
        - selecting a library narrows the search to it.

## Use it from an AI agent (MCP)

- **[MCP-01]** As an AI agent, I want to list libraries with their ID, title, description, versions (default marked) and tags, because I must know what documentation exists before reading it.
    - Acceptance: `list_libraries` returns those fields and the commit SHA per version.
- **[MCP-02]** As an AI agent, I want to list a version's articles as a tree (optionally filtered by path prefix or tags), because I navigate docs like a human: overview first, then the relevant article.
    - Acceptance:
        - `list_articles(library, ref?, path_prefix?, tags?, tags_match?)` returns paths, titles, tags and sizes, paginated with `limit` and `cursor` (MCP's list pagination does not apply to tool results)
        - no `ref` means the default version.
- **[MCP-03]** As an AI agent, I want to read a full article by its exact library, version and path, because once I know where the answer is, I want the whole article.
    - Acceptance:
        - `read_article(library, ref?, path)` returns the verbatim Markdown as a plain text block (not escaped inside JSON) plus the same text, front-matter metadata, commit SHA and source link as structured content, so a client that reads only `structuredContent` gets the article too (`read_chunk` likewise)
        - an unknown path returns an error listing close matches.
    - *MVP-2:* articles are also exposed as MCP resources (`exactdocs://{owner}/{repo}/{path*}{?ref}`) for clients that browse resources.
- **[MCP-04]** As an AI agent, I want every search result to carry its location and its neighbors, and to fetch a neighbor chunk or the whole parent article, because a matching section often needs the one before or after it.
    - Acceptance:
        - results include `chunk_id`, `article_path`, `heading_path`, `position`/`total`, `prev_chunk_id`, `next_chunk_id`, commit SHA and link
        - `read_chunk(chunk_id)` returns a chunk verbatim
        - a `chunk_id` from before a re-sync returns an explicit `stale_chunk` error.
    - *MVP-2:* the error includes the new location when one exists.
- **[MCP-05]** As an AI agent, I want `search_docs(library, query, ref?, tags?, mode?)` to use the best available pipeline (or the mode I ask for) and say how results were found, because I should get the best results the instance can give, and know how.
    - Acceptance:
        - one result shape for every mode: chunks as in MCP-04, plus `retrieval_mode` (`bm25`, `hybrid`, `hybrid_hyde`, `agentic`), `reranked: true|false` and a `coverage` block (candidates considered, candidates reranked, whether the search was complete or cut short by a limit), an optional `fallback_reason` (e.g. LLM budget reached, reranker timeout), so the agent can tell "nothing exists" from "not everything was checked"
        - agentic results also carry `justification` and `explored_path`
        - asking for a `mode` that is not configured returns a tool error listing the available modes
        - a version with no match returns an explicit empty result, never another version.
- **[MCP-06]** *(MVP-2)* As a user, I want a ready-to-paste MCP config for my agent, because hand-written JSON is where setups break.
    - Acceptance:
        - `exactdocs config --client claude|cursor|vscode` prints a working snippet with the URL and a newly created token (AUTH-02)
        - the server also offers a short "how to use ExactDocs" skill over MCP for clients that load skills.
- **[MCP-07]** As a user, I want agent-facing text treated as untrusted, because a doc file can contain instructions aimed at my agent.
    - Acceptance:
        - ExactDocs tools carry the notice in a `notice` field of their structured result (clients that read only `structuredContent` still see it)
        - the context7-compatible tools return a `ToolResult` with two text blocks (notice, then the context7-shaped payload) and no output schema
        - invisible control characters are removed on import (see *Verbatim*).

## context7 parity

ExactDocs offers **at least the same MCP tools, arguments and IDs as context7**, so it can
replace it by changing only the server URL. The ExactDocs tools above come on top.

- **[C7-01]** As an AI agent, I want `resolve-library-id(libraryName, query)` to turn a library name into a library ID, ranked by relevance to my task, because that is the first call every context7-style prompt makes.
    - Acceptance:
        - same tool name and arguments as context7
        - returns matching libraries with ID, title, description, versions, article and chunk counts
        - `query` influences ranking
        - a CI contract test checks that the tool name and argument schema are a superset of a vendored copy of context7's schema, pinned to a context7 version and updated deliberately.
- **[C7-02]** As an AI agent, I want `query-docs(libraryId, query, language?)` to return the relevant documentation for a library ID, because that is the second call every context7-style prompt makes.
    - Acceptance:
        - same tool name and arguments as context7
        - `/owner/repo` uses the default version and `/owner/repo/<ref>` exactly that version (never another one)
        - `language` ranks code examples in that language first
        - uses the instance's retrieval mode (*Next:* the library's, RET-06)
        - *MVP-2:* includes the library's `rules` (from `context7.json`)
        - the response stays within a configurable size budget (default ~10k tokens, estimated as characters / 4, no tokenizer dependency), enforced in the use case and never by a response-limiting middleware (which would merge content blocks)
        - a recorded context7 session (both tools, real arguments) replays without errors.
- **[C7-03]** *(MVP-2)* As a user, I want CLI commands mirroring `ctx7` (`exactdocs library <name> <query>`, `exactdocs docs <libraryId> <query>`), because I want to check from the terminal what my agent would get.
    - Acceptance: output matches the corresponding MCP tool results.
- **[C7-04]** *(MVP-2)* As a user integrating ExactDocs into other tools, I want a REST API equivalent to context7's (search libraries, get docs for a library ID and query), because not every integration speaks MCP.
    - Acceptance: documented endpoints under `/api/v1` return the same data as the two MCP tools and accept the same tokens as MCP (AUTH-02).

## Keep it in sync

- **[SYNC-01]** As a user, I want to re-sync a library with one click (or `exactdocs sync <library>`), because docs change and I want the latest state of a branch.
    - Acceptance:
        - a branch version re-imports only when its head moved
        - unchanged articles are not re-chunked or re-embedded.
- **[SYNC-02]** *(MVP-2)* As a user, I want new tags matching a pattern (e.g. `v*`) imported automatically as new versions, optionally keeping only the last N, because I don't want to add every release by hand.
    - Acceptance:
        - a scheduled check imports new matching tags
        - branch versions are re-synced on a configurable interval
        - with a retention of N, older auto-imported versions are removed (manually imported ones are kept).
- **[SYNC-03]** As a user, I want to remove a version or a whole library, because I don't want stale docs found by me or my agent.
    - Acceptance:
        - after removal nothing from it appears in browse, search or MCP results
        - content no longer referenced by any version is garbage-collected.
- **[SYNC-04]** As a user, I want sync failures handled gracefully (repository deleted or private, credential expired, branch deleted, tag moved), because an upstream problem must not take my docs away.
    - Acceptance:
        - the last good version keeps being served
        - the error is shown on the library (BRW-05).
    - *MVP-2:*
        - each failure has its own error code (repository unreachable, credential expired, branch deleted, tag moved)
        - `exactdocs sync` exits non-zero with the reason
        - a moved tag is detected and reported as an error, and can be re-imported after confirmation.

## Run it

- **[RUN-05]** As a maintainer, I want a versioned acceptance fixture repository, because search, chunking and version-isolation criteria need stable, known content to test against.
    - Acceptance:
        - `tests/fixtures/docs-repo` is built into a git repository during tests, with two tags (`v1.3.0`, `v1.4.0`) and one branch
        - it contains code blocks, tables, front matter, MDX, both admonition syntaxes and identifiers (`snake_case`, `camelCase`, `--flag`, `pkg.mod.fn`), with a table of queries and their expected top sections
        - SRCH-01, SRCH-02, IMP-02, the chunker decision and RET-09 test against it.

- **[RUN-01]** As a user, I want to start ExactDocs with one command (`uvx exactdocs serve` or one `docker run`) and browse my first library within five minutes, because I won't adopt a tool that takes an afternoon to set up.
    - Acceptance:
        - from a clean machine with no models and no API keys, a documentation repository added by its git URL is browsable and searchable within five minutes on SQLite (the CI smoke demo mounts the fixture repository and adds it via `file://`, E10-03a)
        - data lives in `/data` (Docker) or the platform user-data directory (`uvx`), see Decisions.
- **[RUN-02]** As a user, I want the package and image to stay small, with no bundled ML models or LLMs, because many machines will only ever use BM25.
    - Acceptance:
        - no model weights in the wheel or image
        - ML client libraries load only when a provider is configured.
- **[RUN-03]** As a user, I want everything to stay on my machine or server, because my docs and queries are private.
    - Acceptance:
        - no outbound connections except to the git hosts, the model endpoints and (if enabled) the telemetry collector I configured
        - FastMCP's update check is off (see Decisions)
        - an integration test runs import, search and MCP calls with outbound traffic blocked except to a local git server.
- **[RUN-04]** *(MVP-2)* As an operator, I want upgrades to migrate the database and index automatically, because updating must not mean re-importing everything.
    - Acceptance:
        - a new release migrates on start
        - when a change truly requires re-indexing, the release notes say so and `exactdocs reindex` does it in one command while the old index keeps serving.

---
