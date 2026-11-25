# Vectors, embedding and budgets

!!! abstract "TL;DR"

    - Each embedding space (model, dimensions, metric, input format) gets its own vector table, one
      vector per chunk row. Search is exact, within one manifest: sqlite-vec on SQLite, pgvector on
      PostgreSQL.
    - An `embed` job of ingestion embeds one version in durable batches. A library with AI off is
      never planned or sent.
    - Every paid call is recorded in `retrieval_ai_spend` per instance, library, user and embedding
      scope. Budgets and a per-caller rate limit are checked before each LLM step, rerank or batch.

## Vector store (RET-01, #242)

`retrieval_embedding_spaces` records each embedding space:

- profile kind, model, dimensions, metric, input format;
- state `building`/`active`/`retired`;
- created and activated times. IDs are never reused.

Its vectors live in a table the `SqliteVectorIndex` adapter creates with the space and drops when
it is retired, `retrieval_vec_<id>`:

- one little-endian float32 BLOB of fixed size per `retrieval_chunks` row, referenced with
  `ON DELETE CASCADE`, so a blob shared by many versions is embedded once and garbage collection
  removes vectors with their chunk sets;
- plain tables, so `exactdocs backup` copies them and `exactdocs reindex` leaves them alone.

Search is exact: `vec_distance_cosine` over one manifest's chunks, joined from
`retrieval_manifest_chunks`, ordered and limited in SQL.

- **Loading sqlite-vec** (`[ai]` extra): it is imported and loaded into a pooled connection only
  when that connection first searches, or when `available()` is asked, which happens only once an
  embedding role is configured.
- **Per connection**, that connection also gets `PRAGMA mmap_size` (`VECTOR_MMAP_BYTES`, 1 GiB; the
  setting is per connection) and remembers in its `info` that it is loaded and the dimensions of the
  spaces it searched, so a search is one query.
- A revision that rebuilds `retrieval_chunks` must keep its `id`s (or rebuild the vector tables
  too).
- The tables and row mapping both stores share are in `adapters/driven/vector_tables.py`.

## Vector store on PostgreSQL (#243)

`PostgresVectorIndex` keeps the same layout with a `vector(<dimensions>)` column (pgvector).

- **Storage.** The column is set to `STORAGE MAIN`, so a vector that fits in a page stays in its row
  instead of TOAST (2.5 times faster on #242's benchmark; larger ones still go to TOAST).
- **Search** is exact, `<=>` over one manifest's chunks with the same join, tag conditions, clamping
  and order as on SQLite, and no index, so the 2,000-dimension limit of pgvector's indexes does not
  apply.
- **Finding the extension.** When the store is first needed, a plain read finds the extension and
  its schema (no write turn, so a probe or the first search does not queue behind writers). The type
  and operator are qualified with that schema (`public`, `extensions` on Supabase), and the answer
  is kept for the process's life.
- **Creating it.** When it is missing, a process that may write creates it in a write turn
  (`CREATE EXTENSION IF NOT EXISTS vector`; two processes never create it together).
- **When creating fails.** pgvector is not a trusted extension, so a role that is not superuser
  cannot create it. The store then reports unavailable with a sentence saying what to run, logs it,
  keeps that answer, and `/healthz` names `vector` in `vector_store_missing`.
- **Read-only processes** (`serve --stdio`) never create it. They report "not created yet" and look
  again at the next check, as they do after a failure that may pass (the database unreachable, a
  write turn that timed out).
- **Statistics.** Activating a space runs `ANALYZE` on its table, so the first searches after an
  embed are planned with statistics.
- pgvector's Python package (`[ai]` extra) is imported then, for its SQLAlchemy type.
- `bootstrap.container.vector_index` picks the store by the database's dialect.

## Background embedding (RET-01, #91)

The embedding role (instance-wide) is resolved at each call into an `EmbeddingTarget` (profile kind,
model, configured dimensions, input format 1). Its space is the newest one it made that is not
retired.

An `embed` job of ingestion embeds one version through the `VersionEmbedder` bridge to retrieval's
`PlanEmbedding`, `EmbedBatch` and `FinishEmbedding`:

1. **Plan.** Creates the space of a new model (asking the model its dimensions once with a fixed
   text, unless they are configured) and then queues every other version.
2. **Batch.** Each batch:
    - reads up to `batch_size` chunks without a vector (`VectorIndex.missing`);
    - embeds their article title (catalog bridge `ArticleTitles`: one query by path over the plan's
      manifest), heading path and text through the `Embeddings` port (adapter over pydantic-ai's
      `Embedder`, from the `ModelFactory`'s handle);
    - records the provider's reported tokens in `retrieval_ai_spend`;
    - stores the vectors.
3. **Finish.** Activates the space once it covers every active version of every library with AI on,
   then retires every other space, newer ones too (a model switched to and back from leaves one no
   configured model finishes). Their tables are dropped.

Rules around it:

- A library with AI off is never planned or sent, and a batch re-reads its library's setting and the
  configured model first.
- A batch the model did not answer for now (a timeout, a 429, a 5xx) is tried again inside its step,
  `EMBED_ATTEMPTS` times with doubling waits. Then the job fails and the next start or import queues
  the version again.
- A search in a hybrid mode answers BM25 with `embedding_in_progress` while the configured model's
  space does not cover the version. Otherwise the pipeline is given that space
  (`PipelineRequest.space`) and must search it, never the active one
  ([Hybrid search](ai-retrieval.md#hybrid-search-92)).
- Saving over REST the profile the embedding role uses queues the embedding too
  (`bootstrap/embedding.py`), and the start queues what is missing in the background.
- A search uses up its caller's LLM rate limit only once its version resolved.

### The spend ledger

`retrieval_ai_spend` is one row per (scope kind, scope ID, UTC window, window start) with an atomic
upsert on SQLite and PostgreSQL.

- Each batch adds to three rows, for the day and the month:
    - the instance's (`instance`, `""`);
    - its library's (`library`, the library ID);
    - the embedding budget's (`embedding`, `""`).
- `unpriced` counts the requests whose model has no known price.
- Before each batch `AiSpend.embedding_batch` checks the embedding, instance and library budgets and
  raises `AiBudgetReachedError` (`ai_budget_reached`), which fails the job. A library's budget is
  its own `LibraryAi.budgets` from `retrieval_library_settings`, merged with the instance's
  per-library limit by `Budgets.for_library`: the tighter ceiling wins.
- `ListUnembeddedVersions` leaves such a library out.

### Nightly re-queue

Bootstrap queues the missing embedding again just after each UTC midnight, when the windows reset
(`requeue_daily`):

- a random delay of up to five minutes;
- on PostgreSQL only the process holding a session advisory lock queues, since `EmbeddingQueue`
  checks and inserts without one atomic step;
- the lock is checked again every night (`RequeueLeader`): a session that failed is closed and a new
  one opened (never while the server stops), and a failed night is logged, so the loop only ends
  when the server stops;
- a failure raised while the stop cancels it (a `PendingRollbackError`, or a database error during
  the rollback, replacing the `CancelledError`) ends it too (`being_cancelled`).

The stop waits for the nightly upkeep at most `UPKEEP_STOP_SECONDS` (5 s, under `docker stop`'s 10 s
grace), then cancels it again and waits `UPKEEP_RECANCEL_SECONDS` (1 s) more. If it still runs, the
stop logs a warning and goes on without it, so its connection may outlive the engine's dispose (a
late failure of it is logged).

!!! tip "Size the pool for it"

    Each server process keeps one pooled connection open for the nightly upkeep (the lock lives in
    that session).

### Estimates and missing stores

- `exactdocs ai estimate` counts the distinct chunks without a vector (`VectorIndex.pending`) with
  their titles at 4 characters per token, priced from the bundled `genai-prices` data. A model the
  instance runs itself (`ollama`, `vllm` or `local`) is never priced from another provider's list.
- An instance without a vector store plans, queues and estimates nothing.
- One whose store cannot be loaded (sqlite-vec, or pgvector's `vector` not in the PostgreSQL
  database) skips each `embed` job with `vector_store_unavailable`.

## Budgets (RET-07, #95)

`AiSpend` (retrieval's use-case layer):

- reads and adds the ledger rows through the `SpendLedger` port;
- holds the instance's `Budgets`: a `BudgetLimit` per scope kind and window, in millionths of a US
  dollar and in tokens;
- holds a `CallRates` port: an in-memory sliding minute per caller, per process.

The ledger owns its key format, `SpendKey` (scope kind, scope ID, window, window start). Scopes are
`instance`, `library`, `user` (an account ID) and `embedding`.

### Where the checks run

The search use cases call `RetrievalModes.within_budget` right after `choose`, with the caller, so
every later stage sees the same choice. The caller is:

- over REST, the session's or token's account, through a FastAPI dependency;
- over HTTP MCP, the token's `client_id`;
- over stdio, `None`.

`within_budget` skips:

- an LLM step (`llm_budget_reached`, `llm_rate_limited`), answering in `ModeChoice.cheaper`, the
  best mode without an LLM;
- a paid rerank (any reranker profile but `local`);
- the LLM judge, which is an LLM step: refused for the reason the search's own LLM step was, else
  checked against the budgets, and against the rate limit too unless the search's own LLM step
  already counted it.

A rerank that ran (`RetrievalModes.rerank`, #93's `Reranking`) is recorded for the caller's scopes
(`ModeChoice.caller`): one request, its tokens estimated from the characters sent, priced with the
`PriceBook`.

### LLM agents

LLM agents get `agent_limits(...)` (`adapters/driven/harness_spend.py`):

- the harness `SpendLimits` with one budget per caller scope and window (a ceiling, or a plain
  counter) over `LedgerSpendStore`;
- `LedgerSpendStore` implements the harness `BatchSpendStore` structurally and parses each harness
  key (`<name>|<window>|<scope>|<bucket>`, pinned by a contract test) into a `SpendKey`;
- plus pydantic-ai `UsageLimits` per step.

The step's price comes from the caller's `PriceBook` lookup (a `price` function for the harness;
`None` falls back to genai-prices), and the clock is read in UTC. Replay tokens of the harness are
kept in `retrieval_ai_spend_replays`, claimed in the same transaction as the addition.

### Read-only processes (#274)

- A read-only stdio process reads the shared rows and adds its own spend to them over a second
  engine that may write the ledger alone (`open_spend_ledger_database`: a SQLite authorizer, on
  PostgreSQL the code path).
- A write that fails is logged and kept in memory (`ReadOnlySpendLedger`).
- In memory, replay tokens of windows a replay can no longer reach are dropped
  (`SpendWindow.kept_since`), as on SQL.

### Prices

- `PriceBook` looks in the operator's `[ai.prices]`, then free kinds, then the bundled list.
- Bootstrap refuses a US dollar budget at start when a configured role's model has no price.
