# Answering a query

!!! abstract "TL;DR"

    - Both `query-docs` and `search_docs` resolve the version first and then search only inside it.
    - A missing version is an error, never a fallback to another one.
    - `query-docs` packs whole chunks into a token budget; `search_docs` returns a `limit` of chunks
      with their neighbours and a `coverage` block.
    - The default version is the highest imported stable semver tag, else the default branch, else
      the most recently imported version.

Both paths resolve the version first and then search only inside it. A missing version is an error,
never a fallback to another one.

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

## `search_docs`

`search_docs` is the same path with a `limit` instead of a budget. It returns:

- chunks with their location;
- `prev_chunk_id` / `next_chunk_id`;
- the commit SHA and source link;
- a `coverage` block that says whether the search was complete;
- the retrieval mode used.

Following a neighbor is `read_chunk`. A chunk ID from before a re-sync answers `stale_chunk`.

## The default version

The default version is the highest imported stable semver tag, else the default branch, else the
most recently imported version.
