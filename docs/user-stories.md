# User stories

!!! abstract "TL;DR"
    - This section lists the product's user stories with their acceptance criteria, plus the terms,
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

## Pages

| Page | What it covers |
|---|---|
| [MVP: setup, libraries and imports](user-stories/mvp-libraries.md) | AUTH, CLI-01, LIB, IMP and TAG stories: first run, adding libraries, imports, tags |
| [MVP: browsing, search, sync and running](user-stories/mvp-search.md) | BRW, SRCH, MCP, C7, SYNC and RUN stories: browsing, search, the MCP tools, context7 parity, sync, running it |
| [Next: AI-powered retrieval (all optional)](user-stories/ai-retrieval.md) | RET stories: embeddings, reranker, HyDE, agentic search, budgets, the eval suite |
| [Next and later: agents, teams, operations, more sources](user-stories/next.md) | MCP Apps, ACL, TEAM and OPS stories, and the ideas for later |

## Terms

| Term | Meaning |
|---|---|
| **Library** | One imported documentation set: a git repository + the selected paths. Has an ID, a title and a description. |
| **Library ID** | Always exactly two segments, context7-style: `/owner/repo`. Defaults to the repository's owner (top-level group for nested GitLab groups) and name;<br/>must be unique, so a collision (e.g. the same `acme/payments` on GitHub and Bitbucket) asks the user to choose another ID. |
| **Version** | A library imported at one git ref (tag, branch or commit), resolved to a commit SHA.<br/>Addressed as the library ID followed by the ref: `/acme/payments/v1.4.0`, `/acme/payments/release/1.4` (everything after the two ID segments is the ref). |
| **Default version** | What `/owner/repo` without a ref means: automatically the highest imported **stable** semver tag (pre-releases such as `-rc`, `-beta` excluded), else the default-branch version if imported, else the most recently imported version;<br/>it moves when a higher stable tag is imported, unless the owner pinned a version (LIB-10). Every response states the version it used. |
| **Article** | One Markdown file of a library version, addressed by its path in the repo. |
| **Chunk** | A section of an article, by default one heading and its content.<br/>Chunk ID = hash(version ID, article path, heading path, occurrence index, content hash): scoped to one version, so `read_chunk` and neighbors are never ambiguous. On a branch re-sync, unchanged chunks keep their ID;<br/>changed or removed ones answer `stale_chunk`. |
| **Version in responses** | ExactDocs tools return it as a field;<br/>the context7-compatible tools state it in the external-content notice block (MCP-07), so their payload stays context7-shaped. |
| **Verbatim** | The original Markdown, except that invisible control characters (zero-width, bidi) are removed on import. |

**Naming:**

- The context7-compatible MCP tools keep context7's names and arguments (`resolve-library-id`,
  `query-docs`, `libraryId`).
- ExactDocs' own tools use snake_case, and their `library` argument is the library ID.

**Milestones:**

- **MVP-1**: the main loop working end to end for one admin user, with zero external services.
- **MVP-2**: convenience and polish on top of the loop. Stories (or parts of acceptance
  criteria) marked *MVP-2* on the story pages.
- **Next**: optional AI-powered retrieval, teams and roles, integrations.
- **Later**: other sources and extras.

## Decisions

| Topic | Decision |
|---|---|
| BM25 engine (diagram: [Retrieval modes](flows/retrieval-modes.md)) | SQLite **FTS5** locally, **ParadeDB** (`pg_search`) on PostgreSQL, behind one search port, with a shared ranking test suite and a custom tokenizer for identifiers (SRCH-01) |
| Version storage (diagram: [data model](architecture/data-model.md)) | A version is a **manifest** (article path, tags, blob SHA) pointing at shared content;<br/>chunks are **deduplicated by (git blob SHA, chunking-config hash)**;<br/>the commit SHA lives on the version. Many tags and re-syncs stay cheap |
| Library settings | Paths, tag rules and chunking are **per library**;<br/>editing them re-processes every version of the library (cheap thanks to dedup), so versions stay comparable |
| Identifier tokenizer | Done **in Python before indexing**: expanded tokens (`camelCase` → `camel case`, `snake_case`, `--flag`, `pkg.mod.fn`) go into an extra indexed column, identical on FTS5 and pg_search |
| Chunker | Behind a port;<br/>the default adapter is **markdown-it-py** (issue #27: Chonkie's Markdown recipe needs the Hugging Face Hub and network, which breaks RUN-02, so it was dropped);<br/>heading-path and never-split guarantees are tested on the fixture repo whatever chunker is used |
| Git | The **system `git` binary** (in the Docker image; documented requirement for `uvx`), for `--filter=blob:none`, shallow fetch and sparse checkout |
| REST API | `/api/v1`, described by OpenAPI; the **only** API the web UI and the CLI use |
| Data location | Docker: `/data`; `uvx`: the platform user-data directory; stdio MCP uses the same default path |
| Agent stack (see [AI retrieval decisions](decisions/ai-retrieval.md)) | `pydantic-ai-slim` 2.60.0 + [`pydantic-ai-harness`](https://pydantic.dev/docs/ai/harness/) 0.60.0 and `pydantic-monty` (Code Mode without the harness's `[codemode]` extra, which pulls an unused search client), pinned to matching versions, in an optional `exactdocs[ai]` extra;<br/>never imported when no LLM or embedding model is configured |
| Web UI auth (diagram: [Authentication](flows/authentication.md)) | Server **session cookie** (HttpOnly); API tokens are for MCP, REST and the CLI |
| MCP auth | API tokens verified by a FastMCP `TokenVerifier` (the token acts as its user);<br/>with ACL-01, FastMCP OAuth/OIDC (`OIDCProxy`) is combined with API tokens via `MultiAuth`, so web hosts (Claude, ChatGPT) can connect;<br/>OAuth discovery routes (`/.well-known/...`) are served at the root |
| MCP endpoint | **Stateless** Streamable HTTP (`stateless_http=True`) at `/mcp` (and `/mcp/` as an alias);<br/>every route of the MCP app (incl. OAuth `/.well-known/...`) is served as-is;<br/>errors are masked (`mask_error_details=True`) except `DomainError`s, which reach the agent as tool errors with their message;<br/>FastMCP's update check (`FASTMCP_CHECK_FOR_UPDATES=off`) and stdio banner are disabled |
| Host and origin checks | **One allowlist for the whole app** (REST, UI and MCP): localhost plus `EXACTDOCS_ALLOWED_HOSTS` (comma-separated, wildcards allowed), enforced by `TrustedHostMiddleware` and FastMCP's host/origin guard;<br/>state-changing browser requests with a foreign `Origin` get 403 (CSRF / DNS rebinding), unless the origin is listed in `EXACTDOCS_ALLOWED_ORIGINS` (comma-separated browser origins allowed to make state-changing requests);<br/>`EXACTDOCS_FORWARDED_ALLOW_IPS` tells uvicorn which proxies to trust |
| Telemetry | The plain **OpenTelemetry SDK** (Logfire was the first choice; dropped in #87, see *Telemetry* in docs/architecture/telemetry.md);<br/>OTLP over HTTP/protobuf to the operator's collector;<br/>FastAPI's built-in OpenTelemetry for requests (not `instrument_fastapi`, which records request arguments);<br/>pydantic-ai instrumentation with `include_content=False`;<br/>Prometheus via an additional OpenTelemetry metric reader;<br/>the SDK is only set up when `EXACTDOCS_TELEMETRY=otlp`, never with a console exporter (stdout belongs to stdio MCP) |
| HTTP client | `httpx2` (the client FastMCP 4 and pydantic-ai use), in every adapter |
| Web UI serving | FastAPI's `app.frontend(...)` for the built SPA (falls back to `index.html` only for HTML GET requests) |
| Users and tenancy | MVP: a **single admin** account. Next: an operator (role `admin`) creates, disables and resets further **local accounts** (role `user` or `admin`, no self-signup, ACL-06);<br/>library roles (viewer, contributor, admin, creator; users and groups) came with E12-05. **One tenant** per instance;<br/>library IDs are globally unique, like context7's |
| Background jobs (see [Architecture](architecture/jobs/index.md) and the [import flow](flows/import.md)) | MVP-1: an **in-process worker** with a job table in the database.<br/>MVP-2: jobs run as **DBOS** durable workflows (its own SQLite file in the data directory), so a killed import resumes at its last completed step (E3-11) |
| stdio MCP | A **standalone, in-process** server on the local database;<br/>opens it read-only (SQLite WAL), so it is safe next to a running HTTP server, except for the AI spend ledger, which it writes through a second, narrow connection (#274);<br/>works before any account exists |
| Refs containing `/` | Part of the path in MCP and context7 IDs (`/acme/payments/release/1.4`). REST routes are `/api/v1/libraries/{owner}/{repo}` and `.../versions/{ref:path}`, with the ref always last (servers decode `%2F` before routing, so encoded segments cannot work);<br/>routes that need a ref and an article path take both as query parameters (`?ref=` and `?path=`) |
| Persistence | **SQLAlchemy Core** (async, no ORM) with aiosqlite;<br/>**one Alembic history** owned by bootstrap, with `render_as_batch=True` (SQLite) and FTS5 tables created via `op.execute`;<br/>tables prefixed per domain (`catalog_`, `retrieval_`, ...);<br/>**no cross-domain foreign keys** (other domains' IDs are held by value) |
| Vector storage ([details](decisions/ai-retrieval/local-models.md#vector-store)) | One `VectorIndex` port;<br/>**sqlite-vec** on SQLite (float32 BLOBs, `vec_distance_cosine`), **pgvector** on PostgreSQL and Supabase;<br/>one table per embedding space (model, dimensions and input format recorded), exact search scoped to the active manifest;<br/>a model change builds a new space while BM25 answers. Replaces the earlier numpy brute force |
| AI providers ([details](decisions/ai-retrieval/providers.md#provider-abstraction)) | Named provider profiles mapped to pydantic-ai providers, always built with explicit URLs and keys (never `OPENAI_API_KEY` and the like):<br/>custom OpenAI-compatible (base URL, optional key), OpenAI, OpenRouter, Anthropic (also Claude on Vertex AI and Azure AI Foundry), Azure OpenAI (key or Entra ID), Google Vertex AI and Gemini, Ollama, vLLM, LiteLLM and pydantic-ai's other OpenAI-SDK platforms;<br/>roles `embedding`, `reranker`, `llm`, `judge`;<br/>configured in env or a TOML file, or in the UI with keys sealed by the secret box (moving to bootstrap, #248);<br/>per-library overrides except the embedding model. Embeddings and rerankers sit behind our own ports (pydantic-ai `Embedder`, Cohere-compatible/TEI HTTP, fastembed) |
| Local models and images ([details](decisions/ai-retrieval/local-models.md#local-and-offline-models)) | Optional `exactdocs[local]` extra: **fastembed** on ONNX Runtime (CPU), default `BAAI/bge-small-en-v1.5` and `Xenova/ms-marco-MiniLM-L-6-v2`, loaded from `EXACTDOCS_MODELS_DIR` (default `<data dir>/models`), never downloaded at run time.<br/>Images: base (410 MB, BM25), `-ai` (560 MB), `-local` (950 MB, models included) |
| AI cost ([details](decisions/ai-retrieval.md#cost-and-budgets)) | Token and USD budgets per instance, library and user (daily, monthly) in one database table: harness `SpendLimits` over a `BatchSpendStore` for LLM agents, retrieval's own check before each embedding batch or rerank call;<br/>LLM searches per minute limited inside retrieval;<br/>a limit degrades to a cheaper mode with a `fallback_reason`, never an error |
| PostgreSQL and Supabase ([details](decisions/ai-retrieval.md#databases)) | psycopg 3 (already in the image through DBOS);<br/>DBOS's tables in the same database (`system_database_url` set to it, plus `dbos_system_schema`), never a separate system database;<br/>ParadeDB `pg_search` for BM25;<br/>on databases without it (Supabase), PostgreSQL full-text search behind the same search port;<br/>Supabase only as a database, session connections, pgvector in `extensions` |
| External sign-in (Teams; [details](decisions/ai-retrieval.md#sign-in-for-the-teams-milestone)) | Named providers next to local accounts: `oidc` (ADFS included), `oauth2`,<br/>`github` (github.com, a GHE Server host or `*.ghe.com`, with an optional `api_url`; organization and team membership checked via the GitHub API at sign-in and every hour, 403s for unapproved apps or SAML SSO reported as such);<br/>OIDC/OAuth2 revalidation needs a refresh token, without one a session ends after the grace period;<br/>Authlib for the web, FastMCP `OIDCProxy` / `OAuthProxy` + `MultiAuth` for MCP |

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

## Moved sections

These sections moved to the pages above. The old links still land here and point on.

- <a id="mvp-the-main-loop"></a>[MVP: the main loop](user-stories/mvp-libraries.md)
- <a id="first-run-and-access"></a>[First run and access](user-stories/mvp-libraries.md#first-run-and-access)
- <a id="add-a-library"></a>[Add a library](user-stories/mvp-libraries.md#add-a-library)
- <a id="import-and-chunking"></a>[Import and chunking](user-stories/mvp-libraries.md#import-and-chunking)
- <a id="tags"></a>[Tags](user-stories/mvp-libraries.md#tags)
- <a id="browse"></a>[Browse](user-stories/mvp-search.md#browse)
- <a id="search"></a>[Search](user-stories/mvp-search.md#search)
- <a id="use-it-from-an-ai-agent-mcp"></a>[Use it from an AI agent (MCP)](user-stories/mvp-search.md#use-it-from-an-ai-agent-mcp)
- <a id="context7-parity"></a>[context7 parity](user-stories/mvp-search.md#context7-parity)
- <a id="keep-it-in-sync"></a>[Keep it in sync](user-stories/mvp-search.md#keep-it-in-sync)
- <a id="run-it"></a>[Run it](user-stories/mvp-search.md#run-it)
- <a id="next-ai-powered-retrieval-all-optional"></a>[Next: AI-powered retrieval (all optional)](user-stories/ai-retrieval.md)
- <a id="next-richer-agent-experience"></a>[Next: richer agent experience](user-stories/next.md#next-richer-agent-experience)
- <a id="next-teams-sharing-and-roles"></a>[Next: teams, sharing and roles](user-stories/next.md#next-teams-sharing-and-roles)
- <a id="next-operations"></a>[Next: operations](user-stories/next.md#next-operations)
- <a id="later-beyond-markdown-in-git"></a>[Later: beyond Markdown in git](user-stories/next.md#later-beyond-markdown-in-git)
