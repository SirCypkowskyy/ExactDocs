# User stories

Written as **"As _actor_, I want _capability_, because _reason_."** with short acceptance criteria.

!!! abstract "The main use case"
    **Point ExactDocs at a git repository, pick the folder or Markdown files you care about, and
    browse them** in the web UI and from your AI agent over MCP, pinned to the exact git ref
    (tag, branch or commit) you imported.

    Everything in the product serves this loop: **add a library → choose docs → import → browse
    and search → keep in sync**. Other ways of getting documentation in (`llms.txt`, website
    crawls, package registries, prebuilt snapshots) come later.

!!! tip "From story to issue"
    A story becomes a **Feature** issue: the story is the *Context*, the acceptance criteria become
    *Expected behavior* (a behave scenario) and *Criteria of success*. Put the story ID
    (e.g. `LIB-01`) in the issue.

## Terms

| Term | Meaning |
|---|---|
| **Library** | One imported documentation set: a git repository + the selected paths. Its ID is context7-style, `/owner/repo` by default (from the git URL), and can be renamed. |
| **Version** | A library imported at one git ref (tag, branch or commit), resolved to a commit SHA. Addressed as `/owner/repo/<ref>`, e.g. `/acme/payments/v1.4.0`. |
| **Article** | One Markdown file of a library version, addressed by its path in the repo. |
| **Chunk** | A section of an article, by default one heading and its content. |

**Milestones:** **MVP** completes the main loop for one user with zero external services;
**Next** adds optional AI-powered retrieval, team access and integrations; **Later** adds other
sources and extras.

## Actors

| Actor | Who |
|---|---|
| **User** | A developer who adds libraries and reads them in the web UI or CLI |
| **AI agent** | An MCP client (Claude Code, Cursor, ChatGPT, VS Code...) reading the same docs on a user's behalf |
| **Admin** | Whoever runs the instance (deployment, configuration, observability) |
| **ExactDocs** | The system itself: importer, sync scheduler, retrieval |

## Lightweight by default

ExactDocs ships **no models**: no embedding model, no reranker and no LLM in the package or
image. With nothing configured it is a small BM25 search server. Every AI capability is opt-in by
pointing it at an endpoint you choose, and the retrieval pipeline upgrades itself to what is available:

| Configured | Default retrieval |
|---|---|
| nothing | **BM25** |
| reranker | BM25 → rerank |
| embedding model | **hybrid**: BM25 + vector search, fused |
| embedding model + reranker | hybrid → rerank |
| embedding model + LLM (+ reranker) | **hybrid with HyDE**: the LLM writes a hypothetical answer, which is embedded for the vector half → rerank if configured. This is the default when everything is configured. |
| LLM, and agentic mode switched on | **agentic tree retrieval**: a pydantic-ai agent browses the library's tree until it finds the articles that answer the question, and explains why (RET-06) |

---

## MVP: the main loop

### 1. Add a library

- **[LIB-01]** As a user, I want to add a library by pasting a git URL (GitHub, Bitbucket, GitLab, Gitea or any HTTPS/SSH git server), because my documentation lives in repositories, not on one hosting platform.
    - Acceptance: `https://github.com/org/repo`, `https://bitbucket.org/org/repo`, `git@host:org/repo.git` and a self-hosted HTTPS URL are accepted; the URL is checked (reachable, a git repo) before anything is saved; the library ID defaults to `/org/repo` and must be unique.
- **[LIB-02]** As a user, I want to choose which docs to import with a folder or glob patterns (`docs/`, `**/*.md`, `README.md`, exclusions like `docs/archive/**`), because a repo holds far more than documentation.
    - Acceptance: only matching `.md` / `.mdx` files are imported; exclusions win over inclusions; an empty selection means `**/*.md`.
- **[LIB-03]** As a user, I want to preview the matching file tree (count and size) before importing, because I want to fix a wrong pattern before waiting for an import.
    - Acceptance: after entering URL, ref and patterns, the UI and `exactdocs add --dry-run` list the files that would be imported, without storing anything.
- **[LIB-04]** As a user, I want to pick the git ref to import (tag, branch or commit), because docs must match the version of the code I work with.
    - Acceptance: the ref is resolved to a commit SHA at import time and stored with every article; the UI offers the repo's tags and branches.
- **[LIB-05]** As a user, I want to import from private repositories with a personal access token or SSH deploy key, because most internal docs are not public.
    - Acceptance: credentials are stored encrypted, never shown again after saving, never logged, and sent only to that library's host.
- **[LIB-06]** As a user, I want ExactDocs to honor a `context7.json` in the repository (`folders`, `excludeFolders`, `excludeFiles`, `rules`, `previousVersions`) as the default selection, because many projects already describe their docs for context7 and I shouldn't repeat that.
    - Acceptance: when the file exists, its folders and exclusions pre-fill the path selection (still editable); `previousVersions` are offered as versions to import; `rules` are stored and returned by `query-docs`.
- **[LIB-07]** As a user, I want the same from the CLI (`exactdocs add <git-url> --id /acme/payments --ref v1.4.0 --path docs/`), because I script my setup and use ExactDocs without the UI.
    - Acceptance: the CLI and the UI create identical libraries; `exactdocs libraries` lists them.

### 2. Import and chunking

- **[IMP-01]** As ExactDocs, I want to fetch only what is needed (shallow clone of the chosen ref, sparse checkout of the selected paths), because large monorepos must not take minutes or gigabytes to import.
    - Acceptance: importing `docs/` from a large repo transfers only that ref's objects; no full history is cloned.
- **[IMP-02]** As ExactDocs, I want to chunk each article by its Markdown headings (document-structure chunking), keeping each chunk's heading path, because header-based chunks are almost always the best retrieval unit for documentation.
    - Acceptance: by default one chunk = one heading and its content, built with [Chonkie](https://github.com/chonkie-inc/chonkie)'s Markdown recipe; code blocks and tables are never split; every chunk stores article path, heading path (`Guide > Install > Docker`) and its position in the article.
- **[IMP-03]** As a user, I want to customize chunking per library (split level such as `h2` or `h3`, maximum/minimum chunk size with merging of tiny sections, or another Chonkie chunker), because some docs have huge sections and others one-line headings.
    - Acceptance: chunking settings are part of the library's configuration; changing them re-chunks the library without re-cloning; defaults apply when nothing is set.
- **[IMP-04]** As a user, I want to see import progress and per-file problems (unreadable files, broken front matter), because I need to know whether everything I selected made it in.
    - Acceptance: the UI shows files done / total and lists failed files with the reason; one bad file does not fail the whole import.
- **[IMP-05]** As ExactDocs, I want an import to be all-or-nothing per version and resumable after a restart, because readers must never see half a version, and a crash must not restart a large import from zero.
    - Acceptance: while importing, the previous version keeps being served; after a killed worker restarts, the import finishes with no duplicates.

### 3. Tags

- **[TAG-01]** As a user, I want articles to be tagged, from their front matter (`tags: [api, auth]`) automatically and by hand in the UI, because I want to slice documentation by topic across folders.
    - Acceptance: front-matter tags are imported; manual tags survive re-sync; tags are shown on the article and in the tree.
- **[TAG-02]** As a user, I want to assign tags by path rules in the library configuration (`docs/api/** → api`), because most repos have no front matter but a meaningful folder layout.
    - Acceptance: rules apply on every import; an article can have tags from front matter, rules and manual edits at the same time.
- **[TAG-03]** As a user or AI agent, I want to filter browsing and search by tags (any of / all of), because "only the API reference" or "only ADRs" is a common need.
    - Acceptance: the UI tree, search and the MCP tools `list_articles` and `search_docs` accept tag filters; the filter is applied before ranking, not after.

### 4. Browse

- **[BRW-01]** As a user, I want to browse a library as a file tree and read each article rendered (code highlighting, tables, admonitions, images), because reading the docs is the point.
    - Acceptance: the tree mirrors the repo paths; an article renders headings, code blocks with language, tables and images.
- **[BRW-02]** As a user, I want relative links and images between articles to work inside ExactDocs, because docs written for GitHub link to each other with relative paths.
    - Acceptance: `[setup](../setup.md#docker)` opens the imported article at that heading; links to files outside the selection open on the git host.
- **[BRW-03]** As a user, I want a "view on GitHub/Bitbucket/..." link on every article with the exact commit, because I sometimes need the surrounding code or history.
    - Acceptance: the link points at the file at the imported commit SHA, not at the branch head.
- **[BRW-04]** As a user, I want to switch between imported versions of a library (e.g. `v1.3` and `v1.4`), because I work on projects pinned to different versions.
    - Acceptance: a version picker lists imported refs; switching keeps the same article path when it exists in the other version.
- **[BRW-05]** As a user, I want a home page listing my libraries with versions, article count, tags and last sync time, because I need to see what is available and how fresh it is.
    - Acceptance: each library shows URL, refs, commit SHAs, article count and last sync status.

### 5. Search (BM25)

- **[RET-01]** As a user, I want full-text BM25 search across a library version, with results showing article, heading and a highlighted snippet, because I often know a term but not where it is documented.
    - Acceptance: works with nothing configured; exact identifiers (`useActionState`, `--no-verify`) rank the defining section first; results link to the section anchor.
- **[RET-02]** As a user, I want search to stay within the library version I selected, because an answer from another version is worse than none.
    - Acceptance: searching `v1.3` never returns text that exists only in `v1.4`; "no results in v1.3" is shown even when other versions match.

### 6. Use it from an AI agent (MCP)

- **[MCP-01]** As an AI agent, I want to list libraries and their imported versions (with tags in use), because I must know what documentation exists before reading it.
    - Acceptance: `list_libraries` returns name, git URL, refs, commit SHA per version and the library's tags.
- **[MCP-02]** As an AI agent, I want to list a library version's articles as a tree (optionally filtered by path prefix or tags), because I navigate docs like a human: overview first, then the relevant article.
    - Acceptance: `list_articles(library, version, path_prefix?, tags?)` returns paths, titles, tags and sizes.
- **[MCP-03]** As an AI agent, I want to read a full article by its exact library, version and path, because once I know where the answer is, I want the whole article, verbatim.
    - Acceptance: `read_article(library, version, path)` returns the original Markdown with commit SHA and source link; an unknown path returns an explicit error listing close matches.
- **[MCP-04]** As an AI agent, I want every search result to carry its location and its neighbors (previous and next chunk IDs, article path, chunk position and count), and to be able to fetch a neighbor chunk or the whole parent article, because a matching section often needs the one before or after it to make sense.
    - Acceptance: `search_docs` results include `chunk_id`, `article_path`, `heading_path`, `position`/`total`, `prev_chunk_id`, `next_chunk_id`, commit SHA and link; `read_chunk(chunk_id)` returns a neighbor verbatim; `read_article` works with the result's path.
- **[MCP-05]** As an AI agent, I want `search_docs(library, version, query, tags?)` to use the best retrieval mode available and say which one answered, because I should get the best results the instance can give, and know how they were found.
    - Acceptance: results include `retrieval_mode` (`bm25`, `hybrid`, `hybrid_hyde`, `agentic`); a version with no match returns an explicit empty result, never another version.
### 7. context7 parity

ExactDocs offers **at least the same MCP tools, arguments and IDs as context7**, so it can
replace it without changing agent prompts or rules. The ExactDocs-specific tools above
(`list_libraries`, `list_articles`, `read_article`, `read_chunk`) come on top.

- **[C7-01]** As an AI agent, I want a `resolve-library-id(libraryName, query)` tool that turns a library name into a context7-compatible ID, ranked by relevance to my task, because that is the first call every context7-style prompt makes.
    - Acceptance: same tool name and arguments as context7; returns matching libraries with ID (`/owner/repo`), title, description, available versions, article and chunk counts; `query` influences the ranking.
- **[C7-02]** As an AI agent, I want a `query-docs(libraryId, query, language?)` tool that returns the relevant documentation for a library ID, because that is the second call every context7-style prompt makes.
    - Acceptance: same tool name and arguments as context7; `libraryId` accepts `/owner/repo` (latest imported version) and `/owner/repo/<version>` (exact version, never another one); `language` ranks code examples in that language first; uses the same retrieval pipeline as `search_docs` and includes the library's `rules` when present.
- **[C7-03]** As a user, I want CLI commands mirroring `ctx7` (`exactdocs library <name> <query>`, `exactdocs docs <libraryId> <query>`), because I want to check from the terminal what my agent would get.
    - Acceptance: output matches the corresponding MCP tool results.
- **[C7-04]** As a developer integrating ExactDocs into other tools, I want a REST API equivalent to context7's (search libraries, get docs for a library ID and query), because not every integration speaks MCP.
    - Acceptance: documented endpoints under `/api/v1` return the same data as the two MCP tools; they use the same tokens and access rules.
- **[C7-05]** As a user switching from context7, I want ExactDocs to answer the same tool calls my agent already makes, because I only want to change the server URL in my MCP config.
    - Acceptance: a recorded context7 session (both tools, real arguments) replays against ExactDocs without errors; a CI contract test checks tool names and argument schemas against context7's.

### 8. Agent setup

- **[MCP-06]** As a user, I want a ready-to-paste MCP config for my agent, because hand-written JSON is where setups break.
    - Acceptance: `exactdocs config --client claude|cursor|vscode` prints a working snippet; stdio mode (`uvx exactdocs serve --stdio`) needs no token.
- **[MCP-07]** As a user, I want agent-facing text treated as untrusted (invisible Unicode stripped, results marked as external content), because a doc file can contain instructions aimed at my agent.
    - Acceptance: every MCP result is wrapped in an external-content marker; zero-width and bidi control characters are removed on import.

### 9. Keep it in sync

- **[SYNC-01]** As a user, I want to re-sync a library with one click (or `exactdocs sync <library>`), because docs change and I want the latest state of a branch.
    - Acceptance: a branch re-imports only when its head moved; unchanged articles are not re-chunked or re-embedded.
- **[SYNC-02]** As a user, I want new tags matching a pattern (e.g. `v*`) imported automatically as new versions, because I don't want to add every release by hand.
    - Acceptance: a scheduled check imports new matching tags; older versions stay until removed.
- **[SYNC-03]** As a user, I want to remove a version or a whole library, because I don't want stale docs found by me or my agent.
    - Acceptance: after removal nothing from it appears in browse, search or MCP results.

### 10. Run it

- **[RUN-01]** As a user, I want to start ExactDocs with one command (`uvx exactdocs serve` or one `docker run`) and browse my first library within five minutes, because I won't adopt a tool that takes an afternoon to set up.
    - Acceptance: from a clean machine with no models and no API keys, the first library is browsable and BM25-searchable within five minutes on SQLite.
- **[RUN-02]** As a user, I want the package and image to stay small, with no bundled ML models or LLMs, because many machines will only ever use BM25 and should not pay for gigabytes of weights.
    - Acceptance: no model weights in the wheel or image; importing ExactDocs does not import ML frameworks unless an embedding/reranker/LLM provider is configured.
- **[RUN-03]** As a user, I want everything to stay on my machine or server, because my docs and queries are private.
    - Acceptance: no outbound connections except to the git hosts and the model endpoints I configured.

---

## Next: AI-powered retrieval (all optional)

- **[RET-03]** As an admin, I want to configure an embedding model endpoint (OpenAI-compatible API, Ollama, TEI, a local server) with its key, base URL, dimensions and batch size, because I want semantic search with the model of my choice.
    - Acceptance: with an embedding model configured, search becomes hybrid (BM25 + vectors, fused with RRF) and existing versions are embedded in the background; until they are, BM25 keeps answering; changing the model triggers a re-embed instead of mixing vectors.
- **[RET-04]** As an admin, I want to configure a reranker (Cohere-compatible, Jina, TEI or a local cross-encoder endpoint), because reranking the top results noticeably improves precision.
    - Acceptance: when configured, the top N candidates of BM25 or hybrid are reranked; a reranker error or timeout falls back to the unreranked order and is logged, never fails the search.
- **[RET-05]** As an admin, I want to configure an LLM (endpoint, API key, model, optional HTTP proxy, timeouts, extra headers and parameters), because HyDE and agentic retrieval need one, and companies route LLM traffic through their own gateways.
    - Acceptance: any OpenAI-compatible endpoint works; the key is stored as a secret; with an embedding model also configured, hybrid search uses HyDE (the LLM's hypothetical answer is embedded for the vector half) by default.
- **[RET-06]** As a user or AI agent, I want an optional agentic retrieval mode where a pydantic-ai agent browses the library tree (list articles, read headings, open articles) until it finds the articles that answer the question, and returns them with a justification, because some questions need reasoning over the structure, not keyword or vector similarity.
    - Acceptance: enabled per instance or per call (`mode="agentic"`); returns articles/sections with a one-paragraph justification each and the path the agent explored; step and token limits are enforced; it uses the same read tools as MCP, so it can only see what the caller may see.
- **[RET-07]** As ExactDocs, I want to cache agentic retrieval results and reuse them for similar later questions (hybrid search over previous questions), because agentic retrieval is slow and expensive and the same questions repeat.
    - Acceptance: a question similar enough to a cached one (threshold configurable) for the same library version returns the cached articles with `cache_hit: true`; cache entries are invalidated when that version is re-synced.
- **[RET-08]** As an admin, I want to see and override the retrieval pipeline per library (e.g. force BM25 for a tiny library, agentic for a complex one), because one size does not fit every documentation set.
    - Acceptance: the effective pipeline per library is shown in the UI; overrides are validated against what is configured.

## Next: richer agent experience

- **[MCP-08]** As a user of Claude or ChatGPT, I want the MCP server to return rendered UI (FastMCP Apps / [Generative UI](https://gofastmcp.com/apps/generative)), e.g. an article rendered with its headings and code, or a result list with links, because reading docs inside the chat is better than reading raw Markdown.
    - Acceptance: hosts that support MCP Apps render articles and search results as UI; hosts that don't get the plain text result unchanged.

## Next: teams, sharing and roles

- **[ACL-01]** As an admin, I want user accounts with sign-in through OIDC/OAuth (or local accounts), and groups taken from the identity provider, because access should follow our existing identity setup.
    - Acceptance: users sign in via OIDC; IdP group claims map to ExactDocs groups on every sign-in.
- **[ACL-02]** As a library creator, I want to share a library with users and groups in one of four roles, because docs belong to teams, not to whoever imported them:
    - **viewer**: sees the library in the UI and in MCP (search, browse, read);
    - **contributor**: viewer + edits the library (tags, paths, chunking, re-sync, versions);
    - **admin**: contributor + deletes the library and manages who has access (except the creator);
    - **creator**: the owner; admin + can remove admins and transfer ownership.
    - Acceptance: roles can be granted to a user or a group; the effective role is the highest one granted; every MCP tool and UI action checks it.
- **[ACL-03]** As a user, I want my MCP token to see exactly the libraries I may view, because my agent should have my access, not more.
    - Acceptance: tokens act as their user (optionally narrowed to chosen libraries); a library without view access is invisible, not even its name appears in `list_libraries` or errors.
- **[ACL-04]** As an admin, I want an audit log of access changes and destructive actions, because we need to know who shared or deleted what.
    - Acceptance: grants, revocations, deletions and ownership transfers are recorded with actor and time.
- **[TEAM-01]** As an admin, I want a shared instance on PostgreSQL, because the whole team should work on the same libraries.
- **[TEAM-02]** As an admin, I want to declare libraries in `exactdocs.sources.yaml` kept in our own repo (URL, ref or tag pattern, paths, tags, chunking) and apply it with a dry-run diff, because the set of imported docs should go through code review.
- **[TEAM-03]** As a user, I want a push to the docs repository (webhook from GitHub/Bitbucket/GitLab) to trigger a sync, because teammates should read merged docs, not last night's.

## Next: operations

- **[OPS-01]** As an admin, I want an optional OpenTelemetry export (OTLP to a collector) and a Prometheus scrape endpoint for metrics, because I monitor ExactDocs with the same stack as everything else.
    - Acceptance: off by default; when on, it exports request, search (per retrieval mode and stage), import and sync metrics and traces; query text is excluded unless explicitly enabled.
- **[OPS-02]** As an admin, I want health/readiness endpoints, backups and upgrades that don't require re-importing, because the instance becomes something the team depends on.

## Later: beyond Markdown in git

These are good ideas that do not belong to the main loop yet.

| Idea | Why later |
|---|---|
| Import from `llms.txt` / `llms-full.txt` | A second source type; the git importer comes first |
| Crawl documentation websites | Needs a crawler, rate limiting and HTML-to-Markdown conversion |
| Resolve library docs from package registries (PyPI, npm) and lockfiles | Requires a curated registry that maps packages to repos and paths |
| Prebuilt, signed index snapshots and a public registry of popular libraries | Depends on the registry and a stable index format |
| Accuracy eval suite in CI (recall@k, wrong-version rate) per retrieval mode | Starts once retrieval modes exist and need comparing |
| Other formats: reStructuredText, AsciiDoc, Jupyter notebooks | Markdown covers most repositories |
