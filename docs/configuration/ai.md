# Search and AI settings

!!! abstract "TL;DR"

    - Searches are BM25 until a model role is configured and a mode chosen with `EXACTDOCS_AI__MODE`.
    - Model providers, roles and budgets are described on [Search and AI models](../search/index.md).
    - `EXACTDOCS_SEARCH_BACKEND` and `EXACTDOCS_VECTOR_BACKEND` move an index out of the database.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_CONFIG_FILE` | unset | A TOML file with the same settings (the `[ai]` and `[auth]` sections among them); the environment wins over it |
| `EXACTDOCS_AI__MODE` | unset (`auto`) | The retrieval mode of searches that name none, for libraries without their own: `bm25`, `hybrid`, `hybrid_hyde` or `agentic`.<br/>Unset or `auto` means the best default mode the configured models allow, which is BM25 until the eval suite makes another mode a default.<br/>An unknown name stops the server at start; a mode whose model is not configured falls back with `fallback_reason: mode_unavailable` |
| `EXACTDOCS_AI__RERANK_WITH` | `cross_encoder` | What reranks searches when both a cross-encoder and a judge could: `cross_encoder` or `judge`.<br/>See [LLM judge](../search/reranking.md#llm-judge) |
| `EXACTDOCS_AI__PROVIDERS__<NAME>__<FIELD>`, `EXACTDOCS_AI__<ROLE>__MODEL` | unset | Provider profiles and model roles. See [AI providers and model roles](../search/providers.md) |
| `EXACTDOCS_AI__LLM__THINKING`, `EXACTDOCS_AI__JUDGE__THINKING` | unset | How much the `llm` and `judge` models think before they answer: `minimal`, `low`, `medium`, `high` or `xhigh` (any letter case), sent as each provider's own control.<br/>Unset: the provider's default (a judge that is the LLM thinks as the LLM).<br/>Set here, the level cannot be changed over the REST API or in the UI.<br/>See [Thinking level](../search/thinking.md) |
| `EXACTDOCS_AI__HYDE__CACHE_TTL` | `P30D` (30 days) | How long a HyDE hypothetical answer stays cached, in seconds or as an ISO 8601 duration.<br/>Once a day (just after UTC midnight, and at start; one process on PostgreSQL), and after every collection, the server deletes older answers and those of an `llm` model that is no longer configured.<br/>Answers are also deleted when their version's manifest is collected |
| `EXACTDOCS_AI__AGENTIC_CACHE__ENABLED`, `__THRESHOLD`, `__SCOPE`, `__TTL` | `false`, unset, `library`, `P7D` | The agentic answer cache. See [Re-asked questions](../search/answer-cache.md) |
| `EXACTDOCS_AI__BUDGETS__...`, `EXACTDOCS_AI__AGENTIC__...` | unset | Spend limits and agent limits (prices only in the TOML file).<br/>See [Budgets and rate limits](../search/budgets.md) and [Agentic search](../search/agentic.md#limits) |
| `EXACTDOCS_SEARCH_BACKEND` | `database` | Where full-text search runs: `database` (SQLite FTS5, or PostgreSQL full-text search / pg_search) or a registered external backend.<br/>The database keeps every chunk; the backend holds a copy of each version that imports, removals and re-tags keep in step and `exactdocs index rebuild` writes again.<br/>A backend that does not answer at start stops the server, naming it; an unknown name or a missing extra too.<br/>See [External index backends](../architecture.md#external-index-backends) |
| `EXACTDOCS_VECTOR_BACKEND` | `database` | Where vector searches run: `database` (sqlite-vec or pgvector) or a registered external backend.<br/>The database's store still keeps every vector, so an embedding is paid once and the backend can be rebuilt from it; the store's extension is still needed |
| `EXACTDOCS_INDEX_BACKENDS__<NAME>__<OPTION>` | unset | An external backend's options (`[index_backends.<name>]` in the TOML file): its URL, index or collection names.<br/>Keys, tokens and passwords come from the environment or an option ending in `_file`; the TOML file refuses them |
