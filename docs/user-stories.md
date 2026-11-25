# User stories

!!! abstract "TL;DR"
    - This page lists the product's user stories with their acceptance criteria, plus the terms,
      decisions and actors they rely on.
    - The main loop is: add a library → choose docs → import → browse and search → keep in sync.
    - A version is a library at one git ref, resolved to a commit SHA. Every response states the
      version it used, and a search in one version never returns text from another.
    - ExactDocs ships no models. With nothing configured it is a BM25 server, and AI retrieval is
      opt-in.
    - Stories are grouped by milestone: MVP-1, MVP-2, Next (AI retrieval, teams, operations) and
      Later.

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
| **Library ID** | Always exactly two segments, context7-style: `/owner/repo`. Defaults to the repository's owner (top-level group for nested GitLab groups) and name;<br/>must be unique, so a collision (e.g. the same `acme/payments` on GitHub and Bitbucket) asks the user to choose another ID. |
| **Version** | A library imported at one git ref (tag, branch or commit), resolved to a commit SHA.<br/>Addressed as the library ID followed by the ref: `/acme/payments/v1.4.0`, `/acme/payments/release/1.4` (everything after the two ID segments is the ref). |
| **Default version** | What `/owner/repo` without a ref means: automatically the highest imported **stable** semver tag (pre-releases such as `-rc`, `-beta` excluded), else the default-branch version if imported, else the most recently imported version;<br/>it moves when a higher stable tag is imported, unless the owner pinned a version (LIB-10). Every response states the version it used. |
| **Article** | One Markdown file of a library version, addressed by its path in the repo. |
| **Chunk** | A section of an article, by default one heading and its content. Chunk ID = hash(version ID, article path, heading path, occurrence index, content hash): scoped to one version, so `read_chunk` and neighbors are never ambiguous. On a branch re-sync, unchanged chunks keep their ID;<br/>changed or removed ones answer `stale_chunk`. |
| **Version in responses** | ExactDocs tools return it as a field;<br/>the context7-compatible tools state it in the external-content notice block (MCP-07), so their payload stays context7-shaped. |
| **Verbatim** | The original Markdown, except that invisible control characters (zero-width, bidi) are removed on import. |

**Naming:**

- The context7-compatible MCP tools keep context7's names and arguments (`resolve-library-id`,
  `query-docs`, `libraryId`).
- ExactDocs' own tools use snake_case, and their `library` argument is the library ID.

**Milestones:**

- **MVP-1**: the main loop working end to end for one admin user, with zero external services.
- **MVP-2**: convenience and polish on top of the loop. Stories (or parts of acceptance
  criteria) marked *MVP-2* below.
- **Next**: optional AI-powered retrieval, teams and roles, integrations.
- **Later**: other sources and extras.

## Decisions

| Topic | Decision |
|---|---|
| BM25 engine (diagram: [Retrieval modes](flows.md#retrieval-modes)) | SQLite **FTS5** locally, **ParadeDB** (`pg_search`) on PostgreSQL, behind one search port, with a shared ranking test suite and a custom tokenizer for identifiers (SRCH-01) |
| Version storage (diagram: [data model](architecture.md#data-model)) | A version is a **manifest** (article path, tags, blob SHA) pointing at shared content;<br/>chunks are **deduplicated by (git blob SHA, chunking-config hash)**;<br/>the commit SHA lives on the version. Many tags and re-syncs stay cheap |
| Library settings | Paths, tag rules and chunking are **per library**;<br/>editing them re-processes every version of the library (cheap thanks to dedup), so versions stay comparable |
| Identifier tokenizer | Done **in Python before indexing**: expanded tokens (`camelCase` → `camel case`, `snake_case`, `--flag`, `pkg.mod.fn`) go into an extra indexed column, identical on FTS5 and pg_search |
| Chunker | Behind a port;<br/>the default adapter is **markdown-it-py** (issue #27: Chonkie's Markdown recipe needs the Hugging Face Hub and network, which breaks RUN-02, so it was dropped);<br/>heading-path and never-split guarantees are tested on the fixture repo whatever chunker is used |
| Git | The **system `git` binary** (in the Docker image; documented requirement for `uvx`), for `--filter=blob:none`, shallow fetch and sparse checkout |
| REST API | `/api/v1`, described by OpenAPI; the **only** API the web UI and the CLI use |
| Data location | Docker: `/data`; `uvx`: the platform user-data directory; stdio MCP uses the same default path |
| Agent stack (see [AI retrieval decisions](decisions/ai-retrieval.md)) | `pydantic-ai-slim` 2.60.0 + [`pydantic-ai-harness`](https://pydantic.dev/docs/ai/harness/) 0.60.0 and `pydantic-monty` (Code Mode without the harness's `[codemode]` extra, which pulls an unused search client), pinned to matching versions, in an optional `exactdocs[ai]` extra;<br/>never imported when no LLM or embedding model is configured |
| Web UI auth (diagram: [Authentication](flows.md#authentication)) | Server **session cookie** (HttpOnly); API tokens are for MCP, REST and the CLI |
| MCP auth | API tokens verified by a FastMCP `TokenVerifier` (the token acts as its user);<br/>with ACL-01, FastMCP OAuth/OIDC (`OIDCProxy`) is combined with API tokens via `MultiAuth`, so web hosts (Claude, ChatGPT) can connect;<br/>OAuth discovery routes (`/.well-known/...`) are served at the root |
| MCP endpoint | **Stateless** Streamable HTTP (`stateless_http=True`) at `/mcp` (and `/mcp/` as an alias);<br/>every route of the MCP app (incl. OAuth `/.well-known/...`) is served as-is;<br/>errors are masked (`mask_error_details=True`) except `DomainError`s, which reach the agent as tool errors with their message;<br/>FastMCP's update check (`FASTMCP_CHECK_FOR_UPDATES=off`) and stdio banner are disabled |
| Host and origin checks | **One allowlist for the whole app** (REST, UI and MCP): localhost plus `EXACTDOCS_ALLOWED_HOSTS` (comma-separated, wildcards allowed), enforced by `TrustedHostMiddleware` and FastMCP's host/origin guard;<br/>state-changing browser requests with a foreign `Origin` get 403 (CSRF / DNS rebinding), unless the origin is listed in `EXACTDOCS_ALLOWED_ORIGINS` (comma-separated browser origins allowed to make state-changing requests);<br/>`EXACTDOCS_FORWARDED_ALLOW_IPS` tells uvicorn which proxies to trust |
| Telemetry | The plain **OpenTelemetry SDK** (Logfire was the first choice; dropped in #87, see *Telemetry* in docs/architecture.md);<br/>OTLP over HTTP/protobuf to the operator's collector;<br/>FastAPI's built-in OpenTelemetry for requests (not `instrument_fastapi`, which records request arguments);<br/>pydantic-ai instrumentation with `include_content=False`;<br/>Prometheus via an additional OpenTelemetry metric reader;<br/>the SDK is only set up when `EXACTDOCS_TELEMETRY=otlp`, never with a console exporter (stdout belongs to stdio MCP) |
| HTTP client | `httpx2` (the client FastMCP 4 and pydantic-ai use), in every adapter |
| Web UI serving | FastAPI's `app.frontend(...)` for the built SPA (falls back to `index.html` only for HTML GET requests) |
| Users and tenancy | MVP: a **single admin** account. Next: an operator (role `admin`) creates, disables and resets further **local accounts** (role `user` or `admin`, no self-signup, ACL-06);<br/>library roles (viewer, contributor, admin, creator; users and groups) came with E12-05. **One tenant** per instance;<br/>library IDs are globally unique, like context7's |
| Background jobs (see [Architecture](architecture.md#background-jobs) and the [import flow](flows.md#importing-a-version)) | MVP-1: an **in-process worker** with a job table in the database.<br/>MVP-2: jobs run as **DBOS** durable workflows (its own SQLite file in the data directory), so a killed import resumes at its last completed step (E3-11) |
| stdio MCP | A **standalone, in-process** server on the local database;<br/>opens it read-only (SQLite WAL), so it is safe next to a running HTTP server, except for the AI spend ledger, which it writes through a second, narrow connection (#274);<br/>works before any account exists |
| Refs containing `/` | Part of the path in MCP and context7 IDs (`/acme/payments/release/1.4`). REST routes are `/api/v1/libraries/{owner}/{repo}` and `.../versions/{ref:path}`, with the ref always last (servers decode `%2F` before routing, so encoded segments cannot work);<br/>routes that need a ref and an article path take both as query parameters (`?ref=` and `?path=`) |
| Persistence | **SQLAlchemy Core** (async, no ORM) with aiosqlite;<br/>**one Alembic history** owned by bootstrap, with `render_as_batch=True` (SQLite) and FTS5 tables created via `op.execute`;<br/>tables prefixed per domain (`catalog_`, `retrieval_`, ...);<br/>**no cross-domain foreign keys** (other domains' IDs are held by value) |
| Vector storage ([details](decisions/ai-retrieval.md#vector-store)) | One `VectorIndex` port;<br/>**sqlite-vec** on SQLite (float32 BLOBs, `vec_distance_cosine`), **pgvector** on PostgreSQL and Supabase;<br/>one table per embedding space (model, dimensions and input format recorded), exact search scoped to the active manifest;<br/>a model change builds a new space while BM25 answers. Replaces the earlier numpy brute force |
| AI providers ([details](decisions/ai-retrieval.md#provider-abstraction)) | Named provider profiles mapped to pydantic-ai providers, always built with explicit URLs and keys (never `OPENAI_API_KEY` and the like): custom OpenAI-compatible (base URL, optional key), OpenAI, OpenRouter, Anthropic (also Claude on Vertex AI and Azure AI Foundry), Azure OpenAI (key or Entra ID), Google Vertex AI and Gemini, Ollama, vLLM, LiteLLM and pydantic-ai's other OpenAI-SDK platforms;<br/>roles `embedding`, `reranker`, `llm`, `judge`;<br/>configured in env or a TOML file, or in the UI with keys sealed by the secret box (moving to bootstrap, #248);<br/>per-library overrides except the embedding model. Embeddings and rerankers sit behind our own ports (pydantic-ai `Embedder`, Cohere-compatible/TEI HTTP, fastembed) |
| Local models and images ([details](decisions/ai-retrieval.md#local-and-offline-models)) | Optional `exactdocs[local]` extra: **fastembed** on ONNX Runtime (CPU), default `BAAI/bge-small-en-v1.5` and `Xenova/ms-marco-MiniLM-L-6-v2`, loaded from `EXACTDOCS_MODELS_DIR` (default `<data dir>/models`), never downloaded at run time.<br/>Images: base (410 MB, BM25), `-ai` (560 MB), `-local` (950 MB, models included) |
| AI cost ([details](decisions/ai-retrieval.md#cost-and-budgets)) | Token and USD budgets per instance, library and user (daily, monthly) in one database table: harness `SpendLimits` over a `BatchSpendStore` for LLM agents, retrieval's own check before each embedding batch or rerank call;<br/>LLM searches per minute limited inside retrieval;<br/>a limit degrades to a cheaper mode with a `fallback_reason`, never an error |
| PostgreSQL and Supabase ([details](decisions/ai-retrieval.md#databases)) | psycopg 3 (already in the image through DBOS);<br/>DBOS's tables in the same database (`system_database_url` set to it, plus `dbos_system_schema`), never a separate system database;<br/>ParadeDB `pg_search` for BM25;<br/>on databases without it (Supabase), PostgreSQL full-text search behind the same search port;<br/>Supabase only as a database, session connections, pgvector in `extensions` |
| External sign-in (Teams; [details](decisions/ai-retrieval.md#sign-in-for-the-teams-milestone)) | Named providers next to local accounts: `oidc` (ADFS included), `oauth2`, `github` (github.com, a GHE Server host or `*.ghe.com`, with an optional `api_url`; organization and team membership checked via the GitHub API at sign-in and every hour, 403s for unapproved apps or SAML SSO reported as such);<br/>OIDC/OAuth2 revalidation needs a refresh token, without one a session ends after the grace period;<br/>Authlib for the web, FastMCP `OIDCProxy` / `OAuthProxy` + `MultiAuth` for MCP |

## Actors

| Actor | Who |
|---|---|
| **User** | A developer who adds libraries and reads them in the web UI, CLI, REST API or through their agent |
| **AI agent** | An MCP client (Claude Code, Cursor, ChatGPT, Claude, VS Code...) reading docs on a user's behalf |
| **Library owner** | The user who created a library (the *creator* role) |
| **Operator** | Whoever runs the instance: deployment, configuration, upgrades, observability |
| **ExactDocs** | The system itself: importer, sync scheduler, retrieval |

## Lightweight by default

- ExactDocs ships **no models**: no embedding model, no reranker and no LLM in the package or the
  default image.
- With nothing configured it is a small BM25 search server.
- Only the optional `exactdocs:<v>-local` image (and the `exactdocs[local]` extra after
  `exactdocs models pull`) carries a small local embedding model and reranker, for offline
  semantic search.
- Every AI capability is opt-in: you point it at an endpoint you choose.

The retrieval pipeline upgrades itself to what is available:

| Configured | Default retrieval |
|---|---|
| nothing | **BM25** |
| reranker | BM25 → rerank |
| LLM only | BM25 (HyDE needs embeddings); agentic mode can be switched on |
| embedding model | **hybrid**: BM25 + vector search, fused |
| embedding model + reranker | hybrid → rerank |
| embedding model + LLM (+ reranker) | **hybrid with HyDE**: the LLM writes a hypothetical answer, which is embedded for the vector half → rerank if configured.<br/>The default when everything is configured. |
| LLM + agentic mode | **agentic tree retrieval**: a pydantic-ai agent browses the library's tree until it finds the articles that answer the question, and explains why (RET-04) |

Which mode answers a call, first match wins:

1. the call's `mode` argument
2. the library's setting
3. the instance's setting
4. the best available pipeline from the table

---

## MVP: the main loop

- Stories without a marker are **MVP-1**.
- *(MVP-2)* marks whole stories.
- *MVP-2:* marks the part of an acceptance criterion that can wait.

!!! note "The CLI in MVP-1"
    In MVP-1 users manage tokens and libraries in the web UI (and over REST); stdio and HTTP MCP
    work. The CLI has only its local commands (`serve`, `admin create`, `admin reset-password`).
    Every `exactdocs` command that talks to the server (`login`, `token`, `add`, `libraries`,
    `version add`, `sync`, `remove`) is *MVP-2* (CLI-01).

### First run and access

- **[AUTH-01]** As a user starting ExactDocs for the first time, I want to create the first (admin) account in the web UI or with `exactdocs admin create`, because even a single-user instance on a network port must not be open to anyone.
    - Acceptance:
        - until an account exists, the UI shows only the setup page and the API refuses everything else
        - local accounts use hashed passwords
        - the UI has login and logout, sessions expire, and `exactdocs admin reset-password` (local command) recovers a lost password
        - the session cookie is HttpOnly and SameSite=Lax, state-changing requests are Origin-checked, and the cookie is never accepted on `/mcp`.
- **[AUTH-02]** As a user, I want to create, list and revoke API tokens in the UI and with `exactdocs token create|list|revoke`, because my agent (MCP over HTTP), the CLI and REST clients need credentials.
    - Acceptance:
        - a token is shown once, stored hashed, can have an expiry, and is accepted by MCP and REST
        - stdio MCP (`exactdocs serve --stdio`) needs no token.
    - *MVP-2:* the CLI: `exactdocs token create|list|revoke`, tokens accepted by the CLI, and `exactdocs login <url>` asks for username and password, calls a REST endpoint that issues a named API token, and stores it in the CLI config (`--token` accepts an existing token instead).
- **[CLI-01]** *(MVP-2)* As a user, I want the CLI to work as a client of the server's REST API (`/api/v1`, see Decisions) (server URL and token from flags, env, or a config file written by `exactdocs login`), because the CLI should behave exactly like the UI and work against a remote instance too.
    - Acceptance:
        - every command goes through the REST API except the local ones: `serve`, `admin create` and `admin reset-password` (plus `reindex`, `backup` and `restore` once RUN-04 and OPS-02 exist)
        - a CLI action and the same UI action produce identical results.

### Add a library

- **[LIB-01]** As a user, I want to add a library by pasting a git URL (GitHub, Bitbucket, GitLab, Gitea or any HTTPS/SSH git server), because my documentation lives in repositories, not on one hosting platform.
    - Acceptance:
        - `https://github.com/org/repo`, `https://bitbucket.org/org/repo`, `git@host:org/repo.git` and a self-hosted HTTPS URL are accepted
        - the URL is checked (reachable, a git repo) before anything is saved
        - the default library ID follows the Terms rules.
- **[LIB-02]** As a user, I want to choose which docs to import with a folder or glob patterns (`docs/`, `**/*.md`, `README.md`, exclusions like `docs/archive/**`), because a repo holds far more than documentation.
    - Acceptance:
        - matching `.md` / `.mdx` / `.rst` files are imported (`.txt` only when a path names `.txt`, #435)
        - exclusions win over inclusions
        - an empty selection means `**/*.{md,mdx}`.
    - *MVP-2:* images referenced by imported articles are imported too (size-capped) so they render without access to the git host.
- **[LIB-03]** *(MVP-2)* As a user, I want to preview the matching file tree (count and size) before importing, because I want to fix a wrong pattern before waiting for an import.
    - Acceptance: after entering URL, ref and patterns, the UI and `exactdocs add --dry-run` list the files that would be imported, without storing anything.
- **[LIB-04]** As a user, I want to pick the git ref to import (tag, branch or commit), because docs must match the version of the code I work with.
    - Acceptance:
        - without a ref, the repository's default branch is used
        - the ref is resolved to a commit SHA stored with the version and carried by every article, chunk and search response
        - the UI offers tags and branches
        - a commit version can also be addressed by its short SHA. A branch version keeps its ID while its commit moves forward on sync (see IMP-05).
- **[LIB-05]** As a user, I want to import from private repositories with a personal access token or SSH deploy key, because most internal docs are not public.
    - Acceptance:
        - credentials are encrypted with a key from `EXACTDOCS_SECRET_KEY` (generated and stored in the data volume on first run if unset), never shown after saving, never logged, and sent only to that library's host
        - losing the key means re-entering credentials, not losing docs.
- **[LIB-06]** *(MVP-2)* As a user, I want ExactDocs to honor a `context7.json` in the repository (`projectTitle`, `description`, `folders`, `excludeFolders`, `excludeFiles`, `rules`, `previousVersions`), because many projects already describe their docs for context7 and I shouldn't repeat that.
    - Acceptance:
        - when the file exists it pre-fills title, description and path selection (all still editable)
        - `previousVersions` are offered for import
        - `rules` are stored and returned by `query-docs`.
- **[LIB-07]** As a user, I want each library to have a title and description, because agents choose libraries by them in `resolve-library-id`.
    - Acceptance:
        - defaults come from the root README's H1 (its text, or its image's alt text; else the alt text of a logo the README opens with; never a lower heading) and the first paragraph after it (the root README is always fetched for this, even outside the selected paths), else the repo name
        - both are editable.
    - *MVP-2:* `context7.json` values take precedence.
    - Decisions:
        - the README of the library's *default version* wins (the one `/owner/repo` resolves to, so a README of an older tag never overwrites it)
        - its text is refreshed whenever that version is imported. Removing the default version, or pinning or unpinning it (LIB-10), does not re-derive the text: it stays until the new default is imported again. `README.md` is preferred over `README.mdx`. Title = first heading, description = first paragraph after it (plain text, invisible characters stripped, cut at 120 / 500 characters; tables and link-only lines are skipped, HTML headings such as `<h1>` are ignored)
        - README text is untrusted. Text typed by a user is sanitized the same way (single-line title, no invisible characters). A field the user edited (`PATCH /api/v1/libraries/{owner}/{repo}`) is never overwritten again, per field
        - a missing heading or paragraph falls back to the repo name and an empty description.
- **[LIB-08]** *(MVP-2)* As a user, I want the same from the CLI (`exactdocs add <git-url> --id /acme/payments --ref v1.4.0 --path docs/`), because I script my setup.
    - Acceptance: `exactdocs libraries` lists what the UI shows (CLI-01).
- **[LIB-09]** *(MVP-2)* As a user, I want to edit a library's paths and path tag rules (TAG-02), because my first selection is rarely perfect.
    - Acceptance:
        - settings apply to the whole library: saving re-processes every version in the background
        - the previous state is served until the atomic swap (IMP-05). Versions are added with LIB-11 and removed with SYNC-03. Editing chunking settings (IMP-03) only re-chunks, without re-fetching. (In MVP-1, paths and tag rules are set when the library is added.)
- **[LIB-10]** *(MVP-2)* As a library owner, I want to pin the default version, because the newest tag is not always the one my team uses.
    - Acceptance:
        - a pinned default stays until unpinned
        - unpinned, it follows the *Default version* rule
        - the UI and `list_libraries` show whether it is pinned.
    - Decisions:
        - only an imported version can be pinned (its exact ref, or a unique short SHA of a commit version)
        - removing the pinned version unpins the library. Changing the pin does not re-derive the title and description (LIB-07): re-import the new default to refresh them.
- **[LIB-11]** As a user, I want to add another version (ref) to an existing library, because I need `v1.3.0` next to `v1.4.0`.
    - Acceptance:
        - in the UI and with `exactdocs version add /acme/payments v1.3.0`
        - same validation as LIB-04
        - uses the library's paths, path tag rules (TAG-02) and chunking.

### Import and chunking

- **[IMP-01]** As ExactDocs, I want to fetch only what is needed (shallow clone of the chosen ref, sparse checkout of the selected paths and the root README; *MVP-2:* referenced images), because large monorepos must not take minutes or gigabytes to import.
    - Acceptance:
        - importing `docs/` from a large repo transfers only that ref's objects
        - no full history is cloned.
- **[IMP-02]** As ExactDocs, I want to chunk each article by its Markdown headings (document-structure chunking), keeping each chunk's heading path, because header-based chunks are almost always the best retrieval unit for documentation.
    - Acceptance:
        - by default one chunk = one heading and its content, split with markdown-it-py (Chonkie was dropped in #27: it needs the network)
        - code blocks and tables are never split
        - every chunk stores article path, heading path (`Guide > Install > Docker`) and position
        - chunk IDs follow the Terms rule.
- **[IMP-03]** *(MVP-2)* As a user, I want to customize chunking per library (split level such as `h2` or `h3`, minimum/maximum chunk size with merging of tiny sections, or another chunker), because some docs have huge sections and others one-line headings.
    - Acceptance:
        - chunking settings are part of the library's configuration
        - changing them re-chunks without re-cloning
        - defaults apply when nothing is set.
- **[IMP-04]** As ExactDocs, I want to read front matter and MDX safely, because many doc sites use both.
    - Acceptance:
        - an article's title is front-matter `title`, else its first H1, else the file name
        - front matter is parsed (title, tags, description), hidden in the rendered view and returned as metadata by `read_article`
        - MDX is treated as Markdown, and JSX components are shown as inert code, never executed.
- **[IMP-06]** As a user, I want a Sphinx documentation set in reStructuredText (SQLAlchemy's `doc/build`, behave's `docs/`) imported like Markdown, because much of the Python ecosystem documents itself that way (#435).
    - Acceptance:
        - `.rst` files are parsed with docutils (no Sphinx build, no network) and written as the Markdown the chunker takes, so headings (any adornment style), paragraphs, lists, tables, code blocks with their language, chunks, heading paths, anchors, search, the outline and `read_article` work as for Markdown. `code-block` / `sourcecode` / `literalinclude` keep their language
        - `include` and `literalinclude` read files of the fetched paths (relative to the article, `/x` from the folder of `conf.py`), at most 8 levels and 64 files deep, and count toward the import's byte budget
        - admonitions (`note`, `warning`, `seealso`, `versionadded`, `deprecated`...) become GitHub alerts
        - `toctree` and `index` are not indexed
        - `:class:` / `:func:` / `:meth:`... are code, `:ref:` links to a section of the same file (else its title or label as text), `:doc:` links to the `.rst` file
        - substitutions are replaced. An unknown directive keeps its argument and content as text, an unknown role its text as code, and the file gets a `markup` problem
        - nothing about a file's markup fails the import. Markdown and reStructuredText under the selected paths are imported into the same version.
- **[IMP-05]** As ExactDocs, I want an import to be all-or-nothing per version and resumable after a restart, because readers must never see half a version, and a crash must not restart a large import from zero.
    - Acceptance:
        - while (re)importing, the previous state keeps being served and is swapped atomically when done
        - an interrupted import restarts cleanly.
    - *MVP-2:* a killed worker resumes where it stopped (durable jobs with DBOS) and finishes with no duplicates.
- **[IMP-06]** As a user, I want to see import progress and per-file problems, because I need to know whether everything I selected made it in.
    - Acceptance:
        - the UI shows files done / total and lists skipped files with the reason (too large, binary, undecodable: non-UTF-8 files are decoded by detected encoding or skipped)
        - one bad file does not fail the import.

### Tags

- **[TAG-01]** As a user, I want articles to be tagged, from their front matter (`tags: [api, auth]`) automatically and by hand in the UI, because I want to slice documentation by topic across folders.
    - Acceptance: front-matter tags are imported and shown on the article and in the tree.
    - *MVP-2:*
        - manual tags in the UI
        - they belong to the library (all versions) and are keyed by article path, following renames detected by git.
- **[TAG-02]** As a user, I want to assign tags by path rules in the library configuration (`docs/api/** → api`), because most repos have no front matter but a meaningful folder layout.
    - Acceptance:
        - rules apply on every import
        - tags from front matter and rules combine.
    - *MVP-2:* manual tags (TAG-01) combine with them.
- **[TAG-03]** As a user or AI agent, I want to filter browsing and search by tags (any of / all of), because "only the API reference" or "only ADRs" is a common need.
    - Acceptance: the UI tree, UI search and the MCP tools `list_articles` and `search_docs` accept tag filters, applied before ranking.

### Browse

- **[BRW-01]** As a user, I want to browse a library as a file tree and read each article rendered (code highlighting, tables, admonitions, images), because reading the docs is the point.
    - Acceptance:
        - the tree mirrors the repo paths and shows article titles
        - both admonition syntaxes render (MkDocs `!!! note` and GitHub `> [!NOTE]`)
        - in MVP-1 images load from the git host's raw URL (alt text for private repos)
        - *MVP-2:* from the imported copies.
- **[BRW-02]** *(MVP-2)* As a user, I want relative links and images between articles to work inside ExactDocs, because docs written for GitHub link to each other with relative paths.
    - Acceptance:
        - `[setup](../setup.md#docker)` opens the imported article at that heading, also after git saw `setup.md` moved in that version (one hop)
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

### Search

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

### Use it from an AI agent (MCP)

- **[MCP-01]** As an AI agent, I want to list libraries with their ID, title, description, versions (default marked) and tags, because I must know what documentation exists before reading it.
    - Acceptance: `list_libraries` returns those fields and the commit SHA per version.
- **[MCP-02]** As an AI agent, I want to list a version's articles as a tree (optionally filtered by path prefix or tags), because I navigate docs like a human: overview first, then the relevant article.
    - Acceptance:
        - `list_articles(library, ref?, path_prefix?, tags?, tags_match?)` returns paths, titles, tags and sizes, paginated with `limit` and `cursor` (MCP's list pagination does not apply to tool results)
        - no `ref` means the default version.
- **[MCP-03]** As an AI agent, I want to read a full article by its exact library, version and path, because once I know where the answer is, I want the whole article.
    - Acceptance:
        - `read_article(library, ref?, path)` returns the verbatim Markdown as a plain text block (not escaped inside JSON) plus front-matter metadata, commit SHA and source link as structured content (`read_chunk` likewise)
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

### context7 parity

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

### Keep it in sync

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

### Run it

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

## Next: AI-powered retrieval (all optional)

- **[RET-01]** As an operator, I want to configure an embedding model endpoint (OpenAI-compatible API, Ollama, TEI, a local server) with key, base URL, dimensions and batch size, because I want semantic search with the model of my choice.
    - Acceptance:
        - search becomes hybrid (BM25 + vectors, fused with RRF)
        - existing versions are embedded in the background while BM25 keeps answering
        - changing the model re-embeds instead of mixing vectors.
    - Implementation:
        - [`pydantic_ai.Embedder`](https://pydantic.dev/docs/ai/guides/embeddings/) (OpenAI-compatible, OpenAI, OpenRouter, Azure OpenAI, Vertex AI, Ollama, vLLM) behind our own `Embeddings` port
        - local models run in-process only through fastembed (ONNX, no torch) in the optional `exactdocs[local]` extra and `-local` image
        - sentence-transformers stays unsupported, to keep installs light.
- **[RET-02]** As an operator, I want to configure a reranker, either a cross-encoder endpoint (Cohere-compatible, Jina, TEI, local) or a **judge model** (any pydantic-ai model, ideally a fast decision model via the System One API or Ollama, otherwise a small LLM) that rates each candidate chunk's relevance to the query, because reranking the top results improves precision.
    - Acceptance:
        - the top N candidates (configurable, default 32) are reranked
        - judge calls count against the RET-07 budgets
        - a reranker error or timeout falls back to the unreranked order (`reranked: false`) and is logged, never failing the search. The judge returns a bounded relevance score (pydantic-ai decision models do this natively)
        - each judge call has a timeout. Inspired by harness [Smart Search](https://pydantic.dev/docs/ai/harness/smart-search/)'s judge step, but on our header-based chunks, with no shell, workspace or files on disk.
- **[RET-03]** As an operator, I want to configure an LLM (endpoint, API key, model, optional HTTP proxy, timeouts, extra headers and parameters), because HyDE and agentic retrieval need one, and companies route LLM traffic through their own gateways.
    - Acceptance:
        - any OpenAI-compatible endpoint works
        - the key is stored as a secret
        - with embeddings also configured, hybrid search uses HyDE by default
        - HyDE outputs are cached per query and version.
    - Implementation:
        - `OpenAIProvider(base_url=…, api_key=…)` with `OpenAIChatModel` for custom OpenAI-compatible endpoints, and pydantic-ai's own providers for OpenAI, OpenRouter, Anthropic, Azure OpenAI and Vertex AI (see [AI retrieval decisions](decisions/ai-retrieval.md#provider-abstraction))
        - the proxy is set on the transport (`httpx2.AsyncHTTPTransport(proxy=…)`), because a retrying transport stops httpx reading `HTTPS_PROXY`
        - exactly one layer retries (transport or `max_retries`)
        - `request_timeout` is the overall deadline. HyDE is a plain `Agent(output_type=str)` whose output is embedded. For RET-01, the adapter batches inputs itself (`Embedder` has no batch size), sets `EmbeddingSettings(dimensions=…)` and stores model and dimensions with each vector. For RET-02, an LLM judge rates all candidates in one call (`list[...]` output) with an output validator that rejects chunk IDs it was not given.
- **[RET-04]** As a user or AI agent, I want an optional agentic retrieval mode where a pydantic-ai agent browses the library tree (list articles, read headings, open articles) until it finds the articles that answer the question, and returns them with a justification, because some questions need reasoning over structure, not keyword or vector similarity.
    - Acceptance:
        - selected by `mode="agentic"` or the library/instance setting
        - returns the MCP-05 result shape
        - step and token limits are enforced
        - the agent reads article outlines (headings only) through an `article_outline` tool that is also exposed over MCP
        - it uses the same read tools as MCP, so it only sees what the caller may see (the caller's access scope is passed as pydantic-ai `deps`, never as tool arguments the model can see or change)
        - tools are offered only inside Code Mode's sandboxed `run_code` (never IPython Code Mode), each with a typed return model
        - a run is bounded by `max_tool_calls`, Monty resource limits and `UsageLimits`
        - [loop detection](https://pydantic.dev/docs/ai/harness/detect-loops/), a usage or spend limit ends the run and falls back to BM25, with the reason in the response
        - an [output guardrail](https://pydantic.dev/docs/ai/harness/guardrails/) rejects article IDs that are not in the pinned version or not visible to the caller.
    - Implementation: the agent uses pydantic-ai harness [Code Mode](https://pydantic.dev/docs/ai/harness/code-mode/): our read tools (`list_articles`, `article_outline`, `read_article`, `read_chunk`, `search_docs`) are exposed as functions inside one sandboxed `run_code` (Monty), so the model can walk the tree, open many outlines in parallel and filter results in code within one or two model turns. [Repo Context](https://pydantic.dev/docs/ai/harness/repo-context/) can feed the library's own `AGENTS.md` / `CLAUDE.md` files to the agent as guidance about how the docs are organized.
- **[RET-05]** As ExactDocs, I want to cache agentic retrieval results and reuse them for similar later questions, because agentic retrieval is slow and expensive and questions repeat.
    - Acceptance:
        - a question similar enough to a cached one (threshold configurable) for the same version returns the cached result with `cache_hit: true`
        - similarity uses hybrid search over past questions, or BM25 when no embedding model is configured
        - entries are invalidated when the version is re-synced.
- **[RET-06]** As a library contributor (per library) or operator (instance default), I want to set the retrieval mode (e.g. BM25 for a tiny library, agentic for a complex one), because one size does not fit every documentation set.
    - Acceptance:
        - the effective pipeline per library is shown in the UI
        - settings are validated against what is configured
        - precedence is call > library > instance.
- **[RET-07]** As an operator, I want limits on LLM usage (requests per minute, daily token budget, per-call step limit), because HyDE and agentic retrieval cost money.
    - Acceptance:
        - token or USD budgets per instance, library and user, enforced in one `retrieval_` table that works on SQLite and PostgreSQL: LLM agents (HyDE, judge, agentic) through harness [`SpendLimits`](https://pydantic.dev/docs/ai/harness/spend/) over our `BatchSpendStore`, embedding and rerank calls (which run through no agent) by retrieval's own check against the same table before each batch or call
        - LLM searches per minute per caller are limited inside retrieval (REST, HTTP MCP and stdio), not by FastMCP middleware
        - LLM token and cost metrics come from pydantic-ai's built-in `gen_ai.client.token.usage` and cost metrics
        - when a limit is reached, calls fall back to the non-LLM pipeline and say so in `retrieval_mode`
        - usage is visible in the UI and metrics.
- **[RET-08]** As a library owner, I want the repository's `AGENTS.md` / `CLAUDE.md` files to guide agentic retrieval, because they often describe how the docs are organized.
    - Acceptance:
        - the importer keeps each version's instruction files even outside the selected paths
        - they reach the agent through harness [Repo Context](https://pydantic.dev/docs/ai/harness/repo-context/) over a read-only, database-backed [workspace](https://pydantic.dev/docs/ai/core-concepts/workspace/)
        - off by default
        - delivered as user-channel notes when the agent opens a directory (nested traversal), and as system instructions only when the owner marks the library as trusted, because repo content is untrusted.
- **[RET-09]** As a maintainer, I want a retrieval eval suite built with [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) that reports recall@k, wrong-version rate, cost and latency per retrieval mode, because modes must be compared before one becomes a default.
    - Acceptance:
        - runs on the fixture libraries in CI for BM25 and, when model endpoints are provided, for the other modes
        - trace checks prove agentic runs stayed within the requested version.

## Next: richer agent experience

- **[MCP-08]** As a user chatting in Claude or ChatGPT, I want the MCP server to return rendered UI ([FastMCP Apps](https://gofastmcp.com/apps/overview) with Prefab components), e.g. an article with its headings and code, or a result list with links, because reading docs inside the chat is better than reading raw Markdown.
    - Acceptance:
        - separate app tools (`view_article`, `view_search`, `@mcp.tool(app=True)`, `fastmcp[apps]` with a pinned `prefab-ui`) render in hosts that support MCP Apps
        - the existing tools are unchanged, so other hosts keep plain results
        - app tools return an explicit text fallback
        - depends on ACL-01, because web hosts connect with OAuth.

## Next: teams, sharing and roles

- **[ACL-01]** As an operator, I want sign-in through OIDC, OAuth2, ADFS or GitHub / GitHub Enterprise (next to local accounts), with groups taken from the identity provider or from GitHub organization and team membership, because access should follow our existing identity setup.
    - Acceptance:
        - users sign in via OIDC (ADFS included), generic OAuth2 or GitHub / GitHub Enterprise (Server or `*.ghe.com`)
        - IdP group claims, or GitHub organization and team memberships (`github:<org>/<team>`), map to ExactDocs groups on every sign-in and are re-checked at least hourly (OIDC/OAuth2 through a refresh token; without one the session ends after a grace period), so a removed member loses access without anyone touching ExactDocs
        - a GitHub organization that has not approved the app, or needs SAML SSO authorization, is reported as such
        - MCP accepts both OAuth (FastMCP `OIDCProxy`) and API tokens through `MultiAuth`.
- **[ACL-02]** As a library owner, I want to share a library with users and groups in a role, because docs belong to teams, not to whoever imported them:
    - **viewer**: sees the library in the UI and in MCP (search, browse, read);
    - **contributor**: viewer + edits it (tags, paths, chunking, re-sync, versions);
    - **admin**: contributor + deletes it and manages access (except the owner);
    - **creator**: the single owner (whoever created it); admin + removes admins and transfers ownership.
    - Acceptance:
        - viewer, contributor and admin can be granted to users and groups
        - the effective role is the highest granted
        - every UI action, REST call and MCP tool checks it.
- **[ACL-03]** As an operator, I want to control who may create libraries (users or IdP groups), because not everyone on a shared instance should import repositories.
    - Acceptance:
        - an instance-level "can create libraries" permission is mapped from users or groups
        - the creator of a library becomes its owner.
- **[ACL-04]** As a user, I want my tokens to see exactly the libraries I may view, because my agent should have my access, not more.
    - Acceptance:
        - tokens act as their user (optionally narrowed to chosen libraries)
        - a library without view access is invisible, not even its name appears in listings or errors (MCP masks unexpected errors; only domain errors pass, and "not found" and "no access" look the same).
- **[ACL-05]** As a library owner or operator, I want a log of access changes and deletions, because we need to know who shared or deleted what.
    - Acceptance: grants, revocations, deletions and ownership transfers are recorded with actor and time and visible to library admins and operators.
- **[ACL-06]** As an operator, I want to create, disable and reset local user accounts in the UI and with `exactdocs user create|disable|reset-password`, because not every team member signs in through OIDC; no self-signup.
    - Acceptance:
        - only an operator creates local accounts (there is no sign-up page)
        - a disabled user's sessions and tokens are refused
        - a password reset ends the user's sessions.
- **[TEAM-01]** As an operator, I want a shared instance on PostgreSQL, because the whole team should work on the same libraries.
    - Acceptance:
        - `EXACTDOCS_DATABASE_URL=postgresql+psycopg://…` (PostgreSQL with ParadeDB `pg_search`, e.g. the `paradedb/paradedb` image, or Supabase, where search falls back to PostgreSQL full-text search) works with all MVP features, and the search ranking suite passes on it as on SQLite
        - several server processes can run against one database.
- **[TEAM-02]** As an operator, I want to declare libraries in an `exactdocs.sources.yaml` kept in our own repo (URL, ID, ref or tag pattern, paths, tags, chunking) and apply it with a dry-run diff, because the set of imported docs should go through code review.
    - Acceptance:
        - `exactdocs sources plan` prints the diff and changes nothing
        - `apply` makes the instance match
        - a second `apply` reports no changes.
- **[TEAM-03]** As a user, I want a push to the docs repository (webhook from GitHub/Bitbucket/GitLab) to trigger a sync, because teammates should read merged docs, not last night's.
    - Acceptance:
        - a signed webhook for the library's repo and branch starts a sync within 30 seconds
        - unsigned or unknown webhooks are rejected.

## Next: operations

- **[OPS-01]** As an operator, I want an optional OpenTelemetry export (OTLP to a collector) and a Prometheus scrape endpoint for metrics, because I monitor ExactDocs with the same stack as everything else.
    - Acceptance:
        - off by default
        - when on, it exports request, search (per retrieval mode and stage), import, sync and LLM-usage metrics and traces
        - query text is excluded unless explicitly enabled
        - implemented as in the Telemetry decision (OpenTelemetry SDK, FastAPI built-in OpenTelemetry, pydantic-ai [instrumentation](https://pydantic.dev/docs/ai/capabilities/instrumentation/) with `include_content=False`, one span per tool call nested in `run_code`)
        - health checks are excluded from request traces.
- **[OPS-02]** As an operator, I want health and readiness endpoints and a backup/restore command, because the instance becomes something the team depends on.
    - Acceptance:
        - `/healthz` reports the process is up and `/readyz` that the database is reachable
        - `exactdocs backup` / `restore` round-trips libraries, versions, settings, accounts and tokens.

## Later: beyond Markdown in git

These are good ideas that do not belong to the main loop yet.

| Idea | Why later |
|---|---|
| Import from `llms.txt` / `llms-full.txt` | A second source type; the git importer comes first |
| Crawl documentation websites | Needs a crawler, rate limiting and HTML-to-Markdown conversion |
| Resolve library docs from package registries (PyPI, npm) and lockfiles | Requires a curated registry that maps packages to repos and paths |
| Prebuilt, signed index snapshots and a public registry of popular libraries | Depends on the registry and a stable index format |
| Backup LLM ([model fallback](https://pydantic.dev/docs/ai/capabilities/model-fallback/)) and a remote Monty sandbox worker for multi-process setups | Only matters once agentic mode runs in production at scale |
| Pattern-based prompt-injection flags on imported docs ([defender](https://pydantic.dev/docs/ai/harness/prompt-injection-defender/), no ML model) | Report-only nice-to-have |
| Other formats: AsciiDoc, Jupyter notebooks (reStructuredText: IMP-06) | Markdown and reStructuredText cover most repositories |
