# AI retrieval

!!! abstract "TL;DR"

    - Every retrieval mode is a `RetrievalPipeline` on one exact version. The mode is the call's,
      else the library's, else the instance's, else the best default the eval suite allows (only
      `bm25` today).
    - Models come from **provider profiles** bound to **roles** (`llm`, `judge`, `reranker`,
      embedding). Bootstrap builds every client with explicit URLs and keys, never the SDKs'
      environment variables.
    - No AI step fails a search. A missing model, a budget, a timeout or an error answers with a
      cheaper mode and a `fallback_reason`.
    - With nothing configured, the `[ai]` and `[local]` extras are never imported.

Decided in [AI retrieval decisions](../../decisions/ai-retrieval.md) (#240) for the *Next: AI
retrieval* milestone, and built:

| Part | Issue |
|---|---|
| mode selection | #89 |
| provider profiles | #241 |
| hybrid search | #92 |
| HyDE | #94 |
| the reranker | #93 |
| LLM judge | #96 |
| local models | #245 |
| agentic search, with its answer cache and repo guidance | #98, #100, #101 ([Agentic search](../agentic.md)) |

## Pages

| Page | What it covers |
|---|---|
| [Profiles, modes and hybrid search](modes.md) | provider profiles and roles, how a mode is chosen, `hybrid` and reciprocal rank fusion |
| [HyDE, reranker and LLM judge](hyde-rerank.md) | `hybrid_hyde` and its cache, the cross-encoder reranker, the LLM judge |

## Local models (#245)

Bootstrap's `ModelFactory` is `AiModels`: `local` profiles go to `LocalModels`
(`bootstrap/local_models.py`), every other kind to `PydanticAiModels`.

### Pulling and checking

- `LocalModels` imports nothing heavy. A model is known by its folder in `EXACTDOCS_MODELS_DIR` and
  the marker that `exactdocs models pull` writes last.
- `exactdocs models pull` (`bootstrap/models_pull.py`) is the only code that contacts the Hub, at
  the commits `PINNED_MODEL_REVISIONS` fixes for the defaults.
- At build time `_ai_configuration` turns off, with an error naming the pull command, every instance
  role whose local model is missing or was pulled at another pinned commit. It warns about a
  `local:` role with no `local` profile.

### Loading

- Its first use, or `Container.running`'s warm-up for the instance's roles, imports
  `bootstrap/local_sdk.py` (fastembed).
- It loads the model in a worker thread (the load lock is only ever taken there), once per process,
  with:
    - `specific_model_path` and `local_files_only`, which never reach Hub code;
    - half the cores for ONNX Runtime;
    - no CPU memory arena.

### The adapters

`retrieval/adapters/driven/local_models.py`: `LocalEmbeddings`, `LocalReranker`.

- They never import fastembed: they call the loaded model through small structural types.
- Document batches (at most 16 texts) run on a one-worker pool; query embeddings and reranks on a
  two-worker pool of their own. A search never waits behind an embedding job (up to three calls at
  once, each with half the cores).
- ONNX Runtime's errors become `EmbeddingFailedError` / `RerankerError`.
- `Container.running` shuts both pools down when it ends.
- `AiEmbeddingModels` wraps a `LocalEmbedder` handle with them, and a pydantic-ai `Embedder` with
  `PydanticAiEmbeddings`.

### Timeouts and spend

- An unset reranker timeout is 5 s when the search's reranker (the instance's or a library's own) is
  on a `local` profile, 2 s otherwise (`RerankLimits.timeout_for`, per search).
- A `local` model's tokens are recorded in the spend ledger's `local_tokens` and count toward no
  token budget. No budget stops its embedding job or a search's call to it (#284).

## How it fits the structure

Every mode is a pipeline, and its models come through the ports below. The `[ai]` extra is declared
and installed for development; the model-free test proves none of it is imported when no model is
configured.

- **All in `retrieval`.** No new domain: every consumer is retrieval.
    - New driven ports: `Embeddings`, `Reranker`, `VectorIndex`, the `SpendLedger` (whose adapter
      also implements the harness `BatchSpendStore`), and ports for the HyDE writer, the judge and
      the agent explorer.
    - Their adapters (pydantic-ai, fastembed, sqlite-vec, pgvector) live in
      `retrieval/adapters/driven/`, and the architecture test lists those libraries among the ones
      the core may not import.
- **Wiring.**
    - Bootstrap turns the configured provider profiles into pydantic-ai models and HTTP clients, and
      imports any of it only when a role is configured. With nothing configured the `exactdocs[ai]`
      and `exactdocs[local]` extras are never imported (the model-free test).
    - Bootstrap implements retrieval's `ModelFactory` port (a resolved provider profile in, a
      callable model, embedder or reranker out), always with explicit URLs and keys, never the SDKs'
      environment variables.
    - Retrieval declares its own secret-box port. The Fernet adapter that seals repository
      credentials moved from ingestion to `bootstrap` (#248), so no domain depends on another's
      adapter.
- **Storage.** `retrieval_embedding_spaces` records each (model, dimensions, input format). Its
  vectors sit in one adapter-managed table per space, keyed by `retrieval_chunks` row, searched
  exactly within the active manifest (sqlite-vec on SQLite, pgvector on PostgreSQL and Supabase).
- **Jobs.** Embedding runs are an `embed` ingestion job kind with resumable steps, reaching
  retrieval through a bridge, like indexing.
- **PostgreSQL** (#103, see [Persistence](../persistence.md#postgresql-103)):
    - psycopg 3;
    - DBOS's tables in the same database (`system_database_url` plus `dbos_system_schema`);
    - a per-library advisory lock replacing `TagLocks`;
    - PostgreSQL full-text search, the adapter databases without `pg_search` (such as Supabase) keep;
    - `pg_search`'s BM25 (#104) where the extension is installed, chosen at start.
