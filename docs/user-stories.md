# User stories

!!! abstract "TL;DR"
    - This section lists the product's user stories with their acceptance criteria, plus the terms
      and actors they rely on. The technical decisions are on [Decisions](decisions/index.md).
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

These sections moved to other pages. The old links still land here and point on.

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
- <a id="decisions"></a>[Decisions](decisions/index.md#all-decisions)
