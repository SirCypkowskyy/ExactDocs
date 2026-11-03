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
| **Library** | One imported documentation set: a git repository + the selected paths. Has an ID, a title and a description. |
| **Library ID** | Always exactly two segments, context7-style: `/owner/repo`. Defaults to the repository's owner (top-level group for nested GitLab groups) and name; must be unique, so a collision (e.g. the same `acme/payments` on GitHub and Bitbucket) asks the user to choose another ID. |
| **Version** | A library imported at one git ref (tag, branch or commit), resolved to a commit SHA. Addressed as the library ID followed by the ref: `/acme/payments/v1.4.0`, `/acme/payments/release/1.4` (everything after the two ID segments is the ref). |
| **Default version** | What `/owner/repo` without a ref means. Set per library; initially the highest imported semver tag, or the default branch when there are no tags. Every response states the version it used. |
| **Article** | One Markdown file of a library version, addressed by its path in the repo. |
| **Chunk** | A section of an article, by default one heading and its content. |
| **Verbatim** | The original Markdown, except that invisible control characters (zero-width, bidi) are removed on import. |

Naming: the context7-compatible MCP tools keep context7's names and arguments
(`resolve-library-id`, `query-docs`, `libraryId`); ExactDocs' own tools use snake_case, and their
`library` argument is the library ID.

**Milestones:** **MVP** completes the main loop for one user with zero external services;
**Next** adds optional AI-powered retrieval, team access and integrations; **Later** adds other
sources and extras.

## Actors

| Actor | Who |
|---|---|
| **User** | A developer who adds libraries and reads them in the web UI, CLI, REST API or through their agent |
| **AI agent** | An MCP client (Claude Code, Cursor, ChatGPT, Claude, VS Code...) reading docs on a user's behalf |
| **Library owner** | The user who created a library (the *creator* role) |
| **Operator** | Whoever runs the instance: deployment, configuration, upgrades, observability |
| **ExactDocs** | The system itself: importer, sync scheduler, retrieval |

## Lightweight by default

ExactDocs ships **no models**: no embedding model, no reranker and no LLM in the package or
image. With nothing configured it is a small BM25 search server. Every AI capability is opt-in by
pointing it at an endpoint you choose, and the retrieval pipeline upgrades itself to what is available:

| Configured | Default retrieval |
|---|---|
| nothing | **BM25** |
| reranker | BM25 → rerank |
| LLM only | BM25 (HyDE needs embeddings); agentic mode can be switched on |
| embedding model | **hybrid**: BM25 + vector search, fused |
| embedding model + reranker | hybrid → rerank |
| embedding model + LLM (+ reranker) | **hybrid with HyDE**: the LLM writes a hypothetical answer, which is embedded for the vector half → rerank if configured. The default when everything is configured. |
| LLM + agentic mode | **agentic tree retrieval**: a pydantic-ai agent browses the library's tree until it finds the articles that answer the question, and explains why (RET-04) |

Which mode answers a call: the call's `mode` argument, else the library's setting, else the
instance's setting, else the best available pipeline from the table.

---

## MVP: the main loop

### First run and access

- **[AUTH-01]** As a user starting ExactDocs for the first time, I want to create the first (admin) account in the web UI or with `exactdocs admin create`, because even a single-user instance on a network port must not be open to anyone.
    - Acceptance: until an account exists, the UI shows only the setup page and the API refuses everything else; local accounts use hashed passwords.
- **[AUTH-02]** As a user, I want to create, list and revoke API tokens in the UI and with `exactdocs token create|list|revoke`, because my agent (MCP over HTTP), the CLI and REST clients need credentials.
    - Acceptance: a token is shown once, stored hashed, can have an expiry, and is accepted by MCP, REST and the CLI; stdio MCP (`exactdocs serve --stdio`) needs no token.
- **[CLI-01]** As a user, I want the CLI to work as a client of the server's REST API (server URL and token from flags, env or a config file), because the CLI should behave exactly like the UI and work against a remote instance too.
    - Acceptance: every CLI command except `serve` and `admin create` goes through the REST API; a CLI action and the same UI action produce identical results.

### Add a library

- **[LIB-01]** As a user, I want to add a library by pasting a git URL (GitHub, Bitbucket, GitLab, Gitea or any HTTPS/SSH git server), because my documentation lives in repositories, not on one hosting platform.
    - Acceptance: `https://github.com/org/repo`, `https://bitbucket.org/org/repo`, `git@host:org/repo.git` and a self-hosted HTTPS URL are accepted; the URL is checked (reachable, a git repo) before anything is saved; the default library ID follows the Terms rules.
- **[LIB-02]** As a user, I want to choose which docs to import with a folder or glob patterns (`docs/`, `**/*.md`, `README.md`, exclusions like `docs/archive/**`), because a repo holds far more than documentation.
    - Acceptance: matching `.md` / `.mdx` files are imported; exclusions win over inclusions; an empty selection means `**/*.md`; images referenced by imported articles are imported too (size-capped) so they render without access to the git host.
- **[LIB-03]** As a user, I want to preview the matching file tree (count and size) before importing, because I want to fix a wrong pattern before waiting for an import.
    - Acceptance: after entering URL, ref and patterns, the UI and `exactdocs add --dry-run` list the files that would be imported, without storing anything.
- **[LIB-04]** As a user, I want to pick the git ref to import (tag, branch or commit), because docs must match the version of the code I work with.
    - Acceptance: without a ref, the repository's default branch is used; the ref is resolved to a commit SHA stored with every article; the UI offers tags and branches; a commit version can also be addressed by its short SHA. A branch version keeps its ID while its commit moves forward on sync (see IMP-05).
- **[LIB-05]** As a user, I want to import from private repositories with a personal access token or SSH deploy key, because most internal docs are not public.
    - Acceptance: credentials are encrypted with a key from `EXACTDOCS_SECRET_KEY` (generated and stored in the data volume on first run if unset), never shown after saving, never logged, and sent only to that library's host; losing the key means re-entering credentials, not losing docs.
- **[LIB-06]** As a user, I want ExactDocs to honor a `context7.json` in the repository (`projectTitle`, `description`, `folders`, `excludeFolders`, `excludeFiles`, `rules`, `previousVersions`), because many projects already describe their docs for context7 and I shouldn't repeat that.
    - Acceptance: when the file exists it pre-fills title, description and path selection (all still editable); `previousVersions` are offered for import; `rules` are stored and returned by `query-docs`.
- **[LIB-07]** As a user, I want each library to have a title and description, because agents choose libraries by them in `resolve-library-id`.
    - Acceptance: defaults come from `context7.json`, else the README's first heading and paragraph, else the repo name; both are editable.
- **[LIB-08]** As a user, I want the same from the CLI (`exactdocs add <git-url> --id /acme/payments --ref v1.4.0 --path docs/`), because I script my setup.
    - Acceptance: `exactdocs libraries` lists what the UI shows (CLI-01).

### Import and chunking

- **[IMP-01]** As ExactDocs, I want to fetch only what is needed (shallow clone of the chosen ref, sparse checkout of the selected paths and referenced images), because large monorepos must not take minutes or gigabytes to import.
    - Acceptance: importing `docs/` from a large repo transfers only that ref's objects; no full history is cloned.
- **[IMP-02]** As ExactDocs, I want to chunk each article by its Markdown headings (document-structure chunking), keeping each chunk's heading path, because header-based chunks are almost always the best retrieval unit for documentation.
    - Acceptance: by default one chunk = one heading and its content, built with [Chonkie](https://github.com/chonkie-inc/chonkie)'s Markdown recipe; code blocks and tables are never split; every chunk stores article path, heading path (`Guide > Install > Docker`) and position; chunk IDs stay the same while their content is unchanged.
- **[IMP-03]** As a user, I want to customize chunking per library (split level such as `h2` or `h3`, minimum/maximum chunk size with merging of tiny sections, or another Chonkie chunker), because some docs have huge sections and others one-line headings.
    - Acceptance: chunking settings are part of the library's configuration; changing them re-chunks without re-cloning; defaults apply when nothing is set.
- **[IMP-04]** As ExactDocs, I want to read front matter and MDX safely, because many doc sites use both.
    - Acceptance: an article's title is front-matter `title`, else its first H1, else the file name; front matter is parsed (title, tags, description), hidden in the rendered view and returned as metadata by `read_article`; MDX is treated as Markdown, and JSX components are shown as inert code, never executed.
- **[IMP-05]** As ExactDocs, I want an import to be all-or-nothing per version and resumable after a restart, because readers must never see half a version, and a crash must not restart a large import from zero.
    - Acceptance: while (re)importing, the previous state keeps being served and is swapped atomically when done; a killed worker resumes and finishes with no duplicates.
- **[IMP-06]** As a user, I want to see import progress and per-file problems, because I need to know whether everything I selected made it in.
    - Acceptance: the UI shows files done / total and lists skipped files with the reason (too large, binary, undecodable: non-UTF-8 files are decoded by detected encoding or skipped); one bad file does not fail the import.

### Tags

- **[TAG-01]** As a user, I want articles to be tagged, from their front matter (`tags: [api, auth]`) automatically and by hand in the UI, because I want to slice documentation by topic across folders.
    - Acceptance: front-matter tags are imported; manual tags belong to the library (all versions) and are keyed by article path, following renames detected by git; tags are shown on the article and in the tree.
- **[TAG-02]** As a user, I want to assign tags by path rules in the library configuration (`docs/api/** → api`), because most repos have no front matter but a meaningful folder layout.
    - Acceptance: rules apply on every import; tags from front matter, rules and manual edits combine.
- **[TAG-03]** As a user or AI agent, I want to filter browsing and search by tags (any of / all of), because "only the API reference" or "only ADRs" is a common need.
    - Acceptance: the UI tree, UI search and the MCP tools `list_articles` and `search_docs` accept tag filters, applied before ranking.

### Browse

- **[BRW-01]** As a user, I want to browse a library as a file tree and read each article rendered (code highlighting, tables, admonitions, images), because reading the docs is the point.
    - Acceptance: the tree mirrors the repo paths and shows article titles; images come from the imported copies.
- **[BRW-02]** As a user, I want relative links and images between articles to work inside ExactDocs, because docs written for GitHub link to each other with relative paths.
    - Acceptance: `[setup](../setup.md#docker)` opens the imported article at that heading; links to files outside the selection open on the git host.
- **[BRW-03]** As a user, I want a "view on GitHub/Bitbucket/..." link on every article with the exact commit, because I sometimes need the surrounding code or history.
    - Acceptance: the link points at the file at the imported commit SHA, not at the branch head.
- **[BRW-04]** As a user, I want to switch between imported versions of a library (e.g. `v1.3` and `v1.4`), because I work on projects pinned to different versions.
    - Acceptance: a version picker lists imported refs and marks the default version; switching keeps the same article, following a git-detected rename, else falls back to the version's root.
- **[BRW-05]** As a user, I want a home page listing my libraries with title, versions, article count, tags, last sync time and sync errors, because I need to see what is available and how fresh it is.
    - Acceptance: each library shows URL, refs, commit SHAs, article count and last sync status with the error if it failed.

### Search

- **[SRCH-01]** As a user, I want full-text BM25 search within a library version, with results showing article, heading and a highlighted snippet, because I often know a term but not where it is documented.
    - Acceptance: works with nothing configured; on the acceptance fixture repo, exact identifiers (e.g. a function name, a CLI flag) return their defining section first; results link to the section anchor.
- **[SRCH-02]** As a user, I want search to stay within the version I selected, because an answer from another version is worse than none.
    - Acceptance: searching `v1.3` never returns text that exists only in `v1.4`; "no results in v1.3" is shown even when other versions match.
- **[SRCH-03]** As a user, I want one search box across all my libraries (each at its default version) with a library facet, because I don't always know which library documents something.
    - Acceptance: results are grouped or filterable by library; selecting a library narrows the search to it.

### Use it from an AI agent (MCP)

- **[MCP-01]** As an AI agent, I want to list libraries with their ID, title, description, versions (default marked) and tags, because I must know what documentation exists before reading it.
    - Acceptance: `list_libraries` returns those fields and the commit SHA per version.
- **[MCP-02]** As an AI agent, I want to list a version's articles as a tree (optionally filtered by path prefix or tags), because I navigate docs like a human: overview first, then the relevant article.
    - Acceptance: `list_articles(library, version?, path_prefix?, tags?)` returns paths, titles, tags and sizes; no version means the default version.
- **[MCP-03]** As an AI agent, I want to read a full article by its exact library, version and path, because once I know where the answer is, I want the whole article.
    - Acceptance: `read_article(library, version?, path)` returns the verbatim Markdown, front-matter metadata, commit SHA and source link; an unknown path returns an error listing close matches.
- **[MCP-04]** As an AI agent, I want every search result to carry its location and its neighbors, and to fetch a neighbor chunk or the whole parent article, because a matching section often needs the one before or after it.
    - Acceptance: results include `chunk_id`, `article_path`, `heading_path`, `position`/`total`, `prev_chunk_id`, `next_chunk_id`, commit SHA and link; `read_chunk(chunk_id)` returns a chunk verbatim; a `chunk_id` from before a re-sync returns an explicit `stale_chunk` error with the new location when one exists.
- **[MCP-05]** As an AI agent, I want `search_docs(library, version?, query, tags?, mode?)` to use the best available pipeline (or the mode I ask for) and say how results were found, because I should get the best results the instance can give, and know how.
    - Acceptance: one result shape for every mode: chunks as in MCP-04, plus `retrieval_mode` (`bm25`, `hybrid`, `hybrid_hyde`, `agentic`) and `reranked: true|false`; agentic results also carry `justification` and `explored_path`; a version with no match returns an explicit empty result, never another version.
- **[MCP-06]** As a user, I want a ready-to-paste MCP config for my agent, because hand-written JSON is where setups break.
    - Acceptance: `exactdocs config --client claude|cursor|vscode` prints a working snippet with the URL and a newly created token (AUTH-02).
- **[MCP-07]** As a user, I want agent-facing text treated as untrusted, because a doc file can contain instructions aimed at my agent.
    - Acceptance: every MCP result is wrapped in an external-content marker; invisible control characters are removed on import (see *Verbatim*).

### context7 parity

ExactDocs offers **at least the same MCP tools, arguments and IDs as context7**, so it can
replace it by changing only the server URL. The ExactDocs tools above come on top.

- **[C7-01]** As an AI agent, I want `resolve-library-id(libraryName, query)` to turn a library name into a library ID, ranked by relevance to my task, because that is the first call every context7-style prompt makes.
    - Acceptance: same tool name and arguments as context7; returns matching libraries with ID, title, description, versions, article and chunk counts; `query` influences ranking; a CI contract test checks the name and argument schema against context7's.
- **[C7-02]** As an AI agent, I want `query-docs(libraryId, query, language?)` to return the relevant documentation for a library ID, because that is the second call every context7-style prompt makes.
    - Acceptance: same tool name and arguments as context7; `/owner/repo` uses the default version and `/owner/repo/<ref>` exactly that version (never another one); `language` ranks code examples in that language first; uses the library's or instance's retrieval mode; includes the library's `rules`; the response stays within a configurable size budget (default ~10k tokens); a recorded context7 session (both tools, real arguments) replays without errors.
- **[C7-03]** As a user, I want CLI commands mirroring `ctx7` (`exactdocs library <name> <query>`, `exactdocs docs <libraryId> <query>`), because I want to check from the terminal what my agent would get.
    - Acceptance: output matches the corresponding MCP tool results.
- **[C7-04]** As a user integrating ExactDocs into other tools, I want a REST API equivalent to context7's (search libraries, get docs for a library ID and query), because not every integration speaks MCP.
    - Acceptance: documented endpoints under `/api/v1` return the same data as the two MCP tools and accept the same tokens as MCP (AUTH-02).

### Keep it in sync

- **[SYNC-01]** As a user, I want to re-sync a library with one click (or `exactdocs sync <library>`), because docs change and I want the latest state of a branch.
    - Acceptance: a branch version re-imports only when its head moved; unchanged articles are not re-chunked or re-embedded.
- **[SYNC-02]** As a user, I want new tags matching a pattern (e.g. `v*`) imported automatically as new versions, optionally keeping only the last N, because I don't want to add every release by hand.
    - Acceptance: a scheduled check imports new matching tags; with a retention of N, older auto-imported versions are removed (manually imported ones are kept).
- **[SYNC-03]** As a user, I want to remove a version or a whole library, because I don't want stale docs found by me or my agent.
    - Acceptance: after removal nothing from it appears in browse, search or MCP results.
- **[SYNC-04]** As a user, I want sync failures handled gracefully (repository deleted or private, credential expired, branch deleted, tag moved), because an upstream problem must not take my docs away.
    - Acceptance: the last good version keeps being served; the error is shown on the library (BRW-05); `exactdocs sync` exits non-zero with the reason; a moved tag is re-imported only after confirmation.

### Run it

- **[RUN-01]** As a user, I want to start ExactDocs with one command (`uvx exactdocs serve` or one `docker run`) and browse my first library within five minutes, because I won't adopt a tool that takes an afternoon to set up.
    - Acceptance: from a clean machine with no models and no API keys, the acceptance fixture repo (this repository's `docs/`) is browsable and searchable within five minutes on SQLite.
- **[RUN-02]** As a user, I want the package and image to stay small, with no bundled ML models or LLMs, because many machines will only ever use BM25.
    - Acceptance: no model weights in the wheel or image; ML client libraries load only when a provider is configured.
- **[RUN-03]** As a user, I want everything to stay on my machine or server, because my docs and queries are private.
    - Acceptance: no outbound connections except to the git hosts, the model endpoints and (if enabled) the telemetry collector I configured.
- **[RUN-04]** As an operator, I want upgrades to migrate the database and index automatically, because updating must not mean re-importing everything.
    - Acceptance: a new release migrates on start; when a change truly requires re-indexing, the release notes say so and `exactdocs reindex` does it in one command while the old index keeps serving.

---

## Next: AI-powered retrieval (all optional)

- **[RET-01]** As an operator, I want to configure an embedding model endpoint (OpenAI-compatible API, Ollama, TEI, a local server) with key, base URL, dimensions and batch size, because I want semantic search with the model of my choice.
    - Acceptance: search becomes hybrid (BM25 + vectors, fused with RRF); existing versions are embedded in the background while BM25 keeps answering; changing the model re-embeds instead of mixing vectors.
- **[RET-02]** As an operator, I want to configure a reranker (Cohere-compatible, Jina, TEI or a local cross-encoder endpoint), because reranking the top results improves precision.
    - Acceptance: the top N candidates are reranked; a reranker error or timeout falls back to the unreranked order (`reranked: false`) and is logged, never failing the search.
- **[RET-03]** As an operator, I want to configure an LLM (endpoint, API key, model, optional HTTP proxy, timeouts, extra headers and parameters), because HyDE and agentic retrieval need one, and companies route LLM traffic through their own gateways.
    - Acceptance: any OpenAI-compatible endpoint works; the key is stored as a secret; with embeddings also configured, hybrid search uses HyDE by default; HyDE outputs are cached per query and version.
- **[RET-04]** As a user or AI agent, I want an optional agentic retrieval mode where a pydantic-ai agent browses the library tree (list articles, read headings, open articles) until it finds the articles that answer the question, and returns them with a justification, because some questions need reasoning over structure, not keyword or vector similarity.
    - Acceptance: selected by `mode="agentic"` or the library/instance setting; returns the MCP-05 result shape; step and token limits are enforced; it uses the same read tools as MCP, so it only sees what the caller may see.
- **[RET-05]** As ExactDocs, I want to cache agentic retrieval results and reuse them for similar later questions, because agentic retrieval is slow and expensive and questions repeat.
    - Acceptance: a question similar enough to a cached one (threshold configurable) for the same version returns the cached result with `cache_hit: true`; similarity uses hybrid search over past questions, or BM25 when no embedding model is configured; entries are invalidated when the version is re-synced.
- **[RET-06]** As an operator, I want to set the retrieval mode per library (e.g. BM25 for a tiny library, agentic for a complex one), because one size does not fit every documentation set.
    - Acceptance: the effective pipeline per library is shown in the UI; settings are validated against what is configured; precedence is call > library > instance.
- **[RET-07]** As an operator, I want limits on LLM usage (requests per minute, daily token budget, per-call step limit), because HyDE and agentic retrieval cost money.
    - Acceptance: when a limit is reached, calls fall back to the non-LLM pipeline and say so in `retrieval_mode`; usage is visible in the UI and metrics.

## Next: richer agent experience

- **[MCP-08]** As a user chatting in Claude or ChatGPT, I want the MCP server to return rendered UI (FastMCP Apps / [Generative UI](https://gofastmcp.com/apps/generative)), e.g. an article with its headings and code, or a result list with links, because reading docs inside the chat is better than reading raw Markdown.
    - Acceptance: hosts that support MCP Apps render articles and search results as UI; other hosts get the plain text result unchanged.

## Next: teams, sharing and roles

- **[ACL-01]** As an operator, I want sign-in through OIDC/OAuth (next to local accounts), with groups taken from the identity provider, because access should follow our existing identity setup.
    - Acceptance: users sign in via OIDC; IdP group claims map to ExactDocs groups on every sign-in.
- **[ACL-02]** As a library owner, I want to share a library with users and groups in a role, because docs belong to teams, not to whoever imported them:
    - **viewer**: sees the library in the UI and in MCP (search, browse, read);
    - **contributor**: viewer + edits it (tags, paths, chunking, re-sync, versions);
    - **admin**: contributor + deletes it and manages access (except the owner);
    - **creator**: the single owner (whoever created it); admin + removes admins and transfers ownership.
    - Acceptance: viewer, contributor and admin can be granted to users and groups; the effective role is the highest granted; every UI action, REST call and MCP tool checks it.
- **[ACL-03]** As an operator, I want to control who may create libraries (users or IdP groups), because not everyone on a shared instance should import repositories.
    - Acceptance: an instance-level "can create libraries" permission is mapped from users or groups; the creator of a library becomes its owner.
- **[ACL-04]** As a user, I want my tokens to see exactly the libraries I may view, because my agent should have my access, not more.
    - Acceptance: tokens act as their user (optionally narrowed to chosen libraries); a library without view access is invisible, not even its name appears in listings or errors.
- **[ACL-05]** As a library owner or operator, I want a log of access changes and deletions, because we need to know who shared or deleted what.
    - Acceptance: grants, revocations, deletions and ownership transfers are recorded with actor and time and visible to library admins and operators.
- **[TEAM-01]** As an operator, I want a shared instance on PostgreSQL, because the whole team should work on the same libraries.
    - Acceptance: `EXACTDOCS_DATABASE_URL=postgresql://…` works with all MVP features; several server processes can run against one database.
- **[TEAM-02]** As an operator, I want to declare libraries in an `exactdocs.sources.yaml` kept in our own repo (URL, ID, ref or tag pattern, paths, tags, chunking) and apply it with a dry-run diff, because the set of imported docs should go through code review.
    - Acceptance: `exactdocs sources plan` prints the diff and changes nothing; `apply` makes the instance match; a second `apply` reports no changes.
- **[TEAM-03]** As a user, I want a push to the docs repository (webhook from GitHub/Bitbucket/GitLab) to trigger a sync, because teammates should read merged docs, not last night's.
    - Acceptance: a signed webhook for the library's repo and branch starts a sync within 30 seconds; unsigned or unknown webhooks are rejected.

## Next: operations

- **[OPS-01]** As an operator, I want an optional OpenTelemetry export (OTLP to a collector) and a Prometheus scrape endpoint for metrics, because I monitor ExactDocs with the same stack as everything else.
    - Acceptance: off by default; when on, it exports request, search (per retrieval mode and stage), import, sync and LLM-usage metrics and traces; query text is excluded unless explicitly enabled.
- **[OPS-02]** As an operator, I want health and readiness endpoints and a backup/restore command, because the instance becomes something the team depends on.
    - Acceptance: `/healthz` reports the process is up and `/readyz` that the database is reachable; `exactdocs backup` / `restore` round-trips libraries, versions, settings, accounts and tokens.

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
