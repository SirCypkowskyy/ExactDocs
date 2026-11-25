# Flows

!!! abstract "TL;DR"

    - These pages draw the main paths through ExactDocs: importing, answering a query, choosing a
      retrieval mode, and signing in.
    - Every HTTP call that imports only validates and queues; a background job does the work.
    - Every search resolves one exact version first and searches only inside it. A missing version
      is an error, never a fallback to another one.

How the main paths through ExactDocs work. The structure behind them is in
[Architecture](../architecture/index.md); the endpoints are in the [REST API](../rest-api.md).
Planned stages are drawn dashed and labelled *planned*.

| Page | What it draws |
|---|---|
| [Importing a version](import.md) | adding a library or version, editing a library's settings, re-sync |
| [Answering a query](query.md) | `query-docs` and `search_docs` over MCP, and the default version |
| [Retrieval modes](retrieval-modes.md) | how the mode is chosen, fallbacks, reranking |
| [Authentication](authentication.md) | setup, sessions, API tokens, MCP |
