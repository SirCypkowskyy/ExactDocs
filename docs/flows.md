# Flows

How the main paths through ExactDocs work as built in MVP-1 (v0.2.0). The structure behind them
is in [Architecture](architecture.md); the endpoints are in the [REST API](rest-api.md). Planned
stages are drawn dashed and labelled *planned*.

## Importing a version

Adding a library, adding another version and re-syncing a branch all end in the same worker. The
HTTP call only validates and queues; the work happens in a job ([Background jobs](architecture.md#background-jobs)).

```mermaid
sequenceDiagram
    autonumber
    actor U as User (UI or REST)
    participant API as REST: POST /libraries
    participant Q as Job queue (ingestion_jobs)
    participant W as Worker (DBOS workflow)
    participant G as Git host
    participant C as Catalog
    participant R as Retrieval

    U->>API: url, ref, include and exclude paths, credential?
    API->>G: ls-remote: resolve the ref to a commit SHA
    API->>C: create the library with its selection
    API->>Q: queue an import job pinned to the commit
    API-->>U: 201 with library_id, commit_sha, job_id
    loop poll GET /jobs/{job_id}
        U->>Q: state, done / total, problems
    end
    W->>Q: start the oldest queued job whose library has none running
    W->>G: shallow, blobless fetch of the pinned commit, sparse checkout of the selected paths
    W->>W: read each file, parse the ones not stored before (front matter, tags), chunk by headings: 100 files per durable step
    W->>C: store the articles as a pending manifest
    W->>R: index the chunks (reusing chunk sets by blob SHA and chunking config)
    alt every step succeeded
        W->>C: activate the manifest (one transaction)
        Note over C: the previous manifest becomes superseded,<br/>readers now see the new version
        W->>Q: job succeeded
    else a step failed, or the process was stopped
        W->>R: discard the pending chunks
        W->>C: discard the pending manifest
        Note over C: readers still see the last good version
        W->>Q: job failed with a message, or resumed on the next start
    end
```

A process that stops or is killed mid-import resumes the job on the next start: the steps it
completed (files listed, batches parsed and chunked) are taken from DBOS's stored results, and
the import goes on from the first unfinished one.

Skipped files (binary, too large, undecodable...) do not fail the import: they are recorded as
job problems with a code, and the version is published without them.

### Editing a library's settings

`PUT /libraries/{owner}/{repo}/settings` stores new paths, tag rules and chunking, then queues
one job for the whole library. Changed paths: a `reprocess` job runs the `refresh` pipeline for
each version at the commit it serves, so each version's new manifest replaces the old one at
once. Changed chunking: a `rechunk` job copies each version's active manifest into a pending one,
re-derives its imported tags, cuts the stored text with the new chunking (reusing chunk sets
already cut with it), indexes the copy and activates it, without fetching (a version stored by an
older parser, or with an article only its file can rebuild exactly, is re-imported at its commit
instead). Only tag rules changed: a `retag` job
re-derives each stored article's imported tags (front matter plus rules) and writes them per
version in one transaction, then copies them onto the chunks, without fetching. Until a version
is done it serves its previous state; one that fails keeps it.
In the web UI, paths and tag rules are edited in *Files and tags* on the library's settings page
(it leaves the chunking as stored): saving a change first warns that every version is
re-processed (naming them), then follows the job's progress; a Preview shows which files the
typed paths take in the default version (not for a private library yet: a preview cannot use its
stored credential). When the newest re-processing failed, the section shows it with *Run again*,
which sends the stored settings back.

### Re-sync

`POST /libraries/{owner}/{repo}/sync` compares each *branch* and *tag* version with the remote.
A branch that moved gets a `refresh` job, which is the same pipeline pinned to the new commit;
unchanged files reuse their stored chunks, and the new manifest replaces the old one in place.
A tag that moved is reported (`tag_moved`), never re-imported by a sync: the user confirms its
re-import (`POST .../versions/reimport`, the button on the error in the library list and in Re-sync, `exactdocs sync --confirm`),
which queues a `refresh` job of the tag pinned to its new commit. Every upstream problem leaves the
last good version served and is recorded on a failed job with a stable `error_code`.

```mermaid
flowchart TD
    sync["POST /libraries/owner/repo/sync"] --> each{"for each version"}
    each -->|commit| pinned["pinned: never moves"]
    each -->|branch with a job queued or running| importing["importing: left alone"]
    each -->|branch or tag| ask["ask the remote for the tip"]
    ask -->|remote unreadable| err422["422 repo_unreachable or auth_failed: versions keep what they served"]
    ask -->|branch or tag gone upstream| failed["failed ref_deleted: the version keeps serving"]
    ask -->|tag at another commit| moved["failed tag_moved: reported, not re-imported"]
    moved -->|user confirms: POST versions/reimport| queued
    ask -->|tag at the same commit| pinnedtag["pinned"]
    ask -->|branch at the same commit| uptodate["up_to_date"]
    ask -->|branch at a new commit| queued["queued: refresh job"]
    queued --> run["worker: import pinned to the new commit"]
    run -->|ok| swap["manifest activated, chunk IDs of changed sections answer stale_chunk"]
    run -->|error| keep["job failed, the last good manifest stays active"]
```

## Answering a query

Both paths resolve the version first and then search only inside it. A missing version is an
error, never a fallback to another one.

```mermaid
sequenceDiagram
    autonumber
    actor A as AI agent
    participant M as /mcp (FastMCP)
    participant I as Identity
    participant R as Retrieval
    participant C as Catalog
    participant S as BM25 index (SQLite FTS5)

    A->>M: query-docs(libraryId "/owner/repo" or "/owner/repo/ref", query, language?)
    M->>I: verify the bearer token (no token over stdio)
    I-->>M: the account it acts as
    M->>R: query_docs
    R->>C: resolve the version: the given ref, else the default version
    C-->>R: version, commit SHA and its active manifest
    R->>S: BM25 search in that manifest, tag filter applied before ranking
    S-->>R: ranked chunk IDs
    R->>R: language first (if asked), then pack whole chunks into the token budget
    R-->>M: sections, omitted count, version and commit used
    M-->>A: notice (untrusted content) + verbatim sections
    opt a section was too large for the budget
        A->>M: read_chunk(chunk_id)
        M-->>A: the chunk verbatim
    end
```

`search_docs` is the same path with a `limit` instead of a budget: it returns chunks with their
location, `prev_chunk_id` / `next_chunk_id`, the commit SHA and source link, a `coverage` block
that says whether the search was complete, and the retrieval mode used. Following a neighbor is
`read_chunk`; a chunk ID from before a re-sync answers `stale_chunk`.

The default version is the highest imported stable semver tag, else the default branch, else the
most recently imported version.

## Retrieval modes

Only BM25 is built; the other modes are the design for the *Next: AI retrieval* milestone. Which
mode answers is decided per call (RET-06): the call's `mode`, else the library's mode, else the
instance's (`EXACTDOCS_AI__MODE`), else the best mode the configured model roles allow. A
mode is available when it has a pipeline and its roles are configured (`hybrid`: embedding;
`hybrid_hyde`: embedding and LLM; `agentic`: LLM) and, for the hybrid modes, the vector store can
load (sqlite-vec); reranking is a flag on top. A mode the call asks for that is not available is an
error naming the missing role; a library or instance mode that is not available is skipped, and the
result says so (`fallback_reason: mode_unavailable`, or `vector_store_unavailable` when only the
vector store is missing).

```mermaid
flowchart TD
    q["query + library version"] --> asked{"mode in the call?"}
    asked -->|"available"| run
    asked -->|"not available"| err["error mode_unavailable:<br/>missing role + available modes"]
    asked -->|"none"| lib{"library mode<br/>available?"}
    lib -->|yes| run
    lib -->|"none or not available"| inst{"instance mode<br/>available?"}
    inst -->|yes| run
    inst -->|"none or not available"| best["best available<br/>(HyDE, hybrid, BM25)"]
    best --> run
    run["the mode's pipeline, on this one version"] --> out["verbatim chunks + retrieval_mode + reranked<br/>+ coverage + fallback_reason"]

    subgraph planned ["Planned: configured endpoints upgrade the pipeline"]
        direction TB
        start["query"] --> emb
        emb{"embedding model?"} -->|no| bm25p["BM25"]
        emb -->|yes| llm{"LLM?"}
        llm -->|no| hyb["hybrid: BM25 + vectors"]
        llm -->|yes| hyde["hybrid with HyDE"]
        bm25p --> rr
        hyb --> rr
        hyde --> rr
        rr{"reranker?"} -->|yes| rerank["rerank"]
        rr -->|no| done["result"]
        rerank --> done
        agentic["LLM + agentic mode:<br/>an agent browses the article tree"]
    end
    style planned stroke-dasharray: 5 5
```

## Authentication

```mermaid
sequenceDiagram
    autonumber
    actor U as Admin (browser)
    participant H as App-wide checks
    participant G as SetupGuard
    participant ID as Identity
    actor A as Agent or script

    Note over H: every request: Host must be allowed (localhost + EXACTDOCS_ALLOWED_HOSTS),<br/>an unsafe request with a foreign Origin is 403
    U->>H: GET /api/v1/libraries (fresh instance)
    H->>G: allowed
    G-->>U: 403 setup_required (only setup, session state and openapi.json are open)
    U->>ID: POST /api/v1/setup (username, password 12 to 1024 chars)
    ID-->>U: 201, the first admin (argon2id hash), atomically, only once
    U->>ID: POST /api/v1/session
    ID-->>U: 201 + HttpOnly SameSite=Lax cookie, Path=/api (token stored as SHA-256)
    U->>ID: POST /api/v1/tokens (session cookie only)
    ID-->>U: exd_... shown once (only its SHA-256 is stored)
    U->>A: hand over the token
    A->>ID: REST: Authorization: Bearer exd_...
    ID-->>A: acts as the account (401 for unknown, expired or revoked)
    A->>ID: MCP /mcp: Authorization: Bearer exd_... (the cookie is never read)
    ID-->>A: acts as the account
    Note over U,ID: Sessions end after 7 days unused or 30 days in all,<br/>sign-out and exactdocs admin reset-password delete them server-side
```

`exactdocs serve --stdio` skips all of this: it opens the database read-only and exposes the
read-only tools only.
