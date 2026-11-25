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

Decided in [AI retrieval decisions](../decisions/ai-retrieval.md) (#240) for the *Next: AI
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
| agentic search, with its answer cache and repo guidance | #98, #100, #101 ([Agentic search](agentic.md)) |

## Profiles and roles (#241)

### What retrieval's models hold

- **`ProviderProfile`**: a named endpoint with a `kind`, validated per kind. Never a plaintext key:
  a stored key is sealed, a file is named, an environment key stays in bootstrap.
- **`InstanceRoles`**.
- **A library's `LibraryAi` overrides**: AI on or off, its own `llm`/`judge`/`reranker`; never the
  embedding.
- **`bind_role`** resolves which `<profile>:<model>` a role uses for a library: the library's, else
  the instance's; the judge, else the LLM.

### `AiProviders`

`AiProviders` (in `use_cases`):

- puts the configured profiles (read-only, injected by bootstrap from `EXACTDOCS_AI__...` and the
  `EXACTDOCS_CONFIG_FILE` TOML) in front of the `ProviderProfiles` port (`retrieval_ai_providers`,
  managed over REST);
- implements `ModelRoles` (`ProfileModelRoles`): a role counts when it resolves to an existing
  profile, and a library with AI off has none.

Keys sent over REST go through retrieval's `SecretBox` port, which bootstrap fills with the Fernet
box under its own HKDF purpose (`AI_KEYS_PURPOSE`).

`AiProviders.model_for(role, library)` is the path every AI pipeline takes, so a profile edited over
REST counts at the next call.

### The `ModelFactory`

The `ModelFactory` port (`unsupported`, `chat_model`, `embedder`, `reranker`, `check`) is implemented
in bootstrap by `ai_models.PydanticAiModels`, which imports no SDK itself.

- The first call loads `ai_sdk.py` (pydantic-ai, the OpenAI, Anthropic and Google SDKs,
  azure-identity) and builds every client with explicit values.
- Before that it removes `OPENAI_CUSTOM_HEADERS` / `ANTHROPIC_CUSTOM_HEADERS` from the process: the
  SDKs merge them over the key, in the constructor, so `copy()` cannot undo them.

### One HTTP client per profile

Each profile has one `httpx2` client, built under a per-profile lock, rebuilt when the profile
changes and closed when it is deleted (`ModelFactory.release`). The client has:

- **a proxy on the transport**: the profile's own, else the instance's outbound proxy when
  `ai.use_instance_proxy` is on and `NO_PROXY` does not list the endpoint;
- the instance's CA bundle;
- `trust_env=False`, extra headers;
- no transport retries, so the SDK's are the one layer;
- an overall timeout;
- **a request hook** that:
    - refuses any scheme, host or port but the profile's endpoint;
    - drops `OpenAI-Organization` / `OpenAI-Project` filled from the environment;
    - for Claude on Foundry with Entra ID, signs each request with a fresh token.

An Entra ID token provider is built once per profile: a chain of client secret or certificate,
workload identity and managed identity. The profile's proxy, or the instance's with
`ai.use_instance_proxy`, goes to the first two only.

### Cloud-identity profiles

Profiles signed with the server's own cloud identity (ADC, a service-account file, Entra ID, Claude
on Bedrock):

- come from configuration only and take no `base_url` (`ProviderProfile` refuses both), so their
  endpoint is always derived;
- `resource`, `location` and `project` are single DNS labels;
- `ai_sdk._official_url` builds a derived endpoint with `httpx2.URL(scheme=..., host=...)` and
  refuses a host that is not the provider's exact endpoint form (`AZURE_OPENAI_HOST`,
  `FOUNDRY_HOST`, `BEDROCK_HOST`, `VERTEX_HOST`).

### Checks

- `exactdocs ai check` and `POST /api/v1/ai/providers/{name}/check` make one minimal call per role.
- The socket-guard test (`tests/bootstrap/test_ai_no_outbound.py`) runs with the SDKs' variables
  pointing at a trap.

## Mode selection (#89)

Each mode is a `RetrievalPipeline` driven port: `run(PipelineRequest) -> PipelineAnswer`. One exact
version goes in; hits and the mode that really answered come out, with a `fallback_reason` when a
cheaper one did.

- `RetrievalModule.build` registers `Bm25Pipeline` and any further pipelines it is given.
- `RetrievalModes` (in `use_cases`):
    1. asks the `ModelRoles` port which roles the searched library may use (per library: one with AI
       off has none);
    2. builds a `ModeRegistry` (a mode can run when it has a pipeline and its roles);
    3. picks the mode: the call's, else the library's (`LibraryModes` port,
       `retrieval_library_settings`), else the instance's (`EXACTDOCS_AI__MODE`), else the best of
       `DEFAULT_MODE_ORDER`.
- `DEFAULT_MODE_ORDER` lists a mode only once the eval suite marks it `eligible_as_default`
  ([Retrieval evals](../evals.md#gates)). Only `bm25` is listed yet, so an operator, a library or a
  call chooses `hybrid`.
- Removing a library drops its mode too (`ForgetLibrary`, called by the removal bridge after the
  catalog).

### The vector store port (#242)

- The `VectorIndex` driven port: create, activate and retire a space, upsert and delete vectors by
  `ChunkKey`, nearest within one manifest, a manifest's coverage and missing chunks.
- It has an in-memory reference and the SQLite adapter (see
  [Vector store](embeddings.md#vector-store-ret-01-242)), and one contract test for both
  (`tests/retrieval/test_vector_index.py`), which the pgvector adapter (#243) runs too.
- `OpenEmbeddingSpace` finds the space of a model, or creates a new one when the model, its
  dimensions or the input format changed, so two models never share one.
- `RetrievalModes` asks `VectorIndex.available()` once an embedding role is configured. When its
  extension cannot load (sqlite-vec, or pgvector's `vector`), the hybrid modes are unavailable and a
  setting that needs them falls back to BM25 with `fallback_reason: vector_store_unavailable`.

## Hybrid search (#92)

`HybridPipeline` (in `use_cases`) is registered for `hybrid` whenever a vector store exists (SQLite
with sqlite-vec, PostgreSQL with pgvector).

1. It asks the `SearchIndex` for the version's best `RRF_DEPTH` (50) BM25 hits.
2. It embeds the query with the configured model (`Embeddings.embed_query`, in a
   `<search>.embed_query` span without the query text, within `QUERY_EMBEDDING_TIMEOUT` seconds).
   A paid embedding model is first checked against the budgets of the embedding, instance, library
   and caller scopes, and its usage is recorded once to the same rows through `AiSpend.record`.
3. It asks `VectorIndex.nearest` for the 50 nearest chunks of the same manifest in
   `PipelineRequest.space`.
4. It fuses the two rankings with reciprocal rank fusion (`reciprocal_rank_fusion`, `k` = 60). Ties
   go to BM25's order, so an exact identifier stays first.

Rules:

- Both halves are scoped to the version's manifest and filtered by tags before ranking, so no chunk
  of another version can come in.
- The vector half always runs, also when BM25 matches nothing (a synonym the docs never use). A
  hybrid answer has hits whenever the version has embedded chunks that pass the tag filter; there is
  no similarity floor.
- A chunk only the vectors found gets the first 24 words of its text as its snippet.
- `coverage.candidates` counts the chunks of both halves once.
- Reranking (below) runs after the pipeline, on the fused order, like for any mode. The pipeline is
  asked for the reranker's top N when that is more than the limit.

The pipeline never fails a search. BM25 answers with:

| `fallback_reason` | When |
|---|---|
| `embedding_in_progress` | the space no longer matches the configured model (a switch of models) |
| `llm_budget_reached` | a budget the query embedding counts to is used up (as a paid rerank over budget) |
| `embedding_unavailable` | the model failed, timed out or answered an unusable vector (or the key could not be opened) |
| `vector_store_unavailable` | the store cannot search |

## HyDE (#94)

`HydePipeline` (in `use_cases`) is registered for `hybrid_hyde` when a vector store exists and a
`HypotheticalAnswers` writer is given.

1. It resolves the library's `llm` role (`AiProviders.profile_for`, from the profile as it is now;
   nothing is sent for a library with AI off).
2. It looks the answer up in the `HypotheticalAnswerCache` port by `HydeKey`: the searched manifest,
   the model (`<profile>:<model>`) and a SHA-256 of the normalized query (case folded, whitespace
   collapsed; never the text).
3. On a miss, in a `<search>.hyde` span without the query, within `HYDE_TIMEOUT` (10 s), it builds
   the chat model (`ModelFactory.chat_model`) and calls the writer.
4. The answer is then embedded for the vector half
   (`HybridPipeline.fuse(embed=answer, mode=hybrid_hyde)`), while BM25 searches the query itself.

Keys and removal:

- A new manifest of the version is a new key.
- The removal use cases (`CollectChunks`, `RemoveChunks`, `DiscardPendingChunks`) forget the answers
  of the manifests they remove.

### The writer

`ai_hyde.PydanticAiHypotheticalAnswers` loads `ai_hyde_sdk` only then, which runs:

- one pydantic-ai `Agent(output_type=str)` with the fixed `HYDE_INSTRUCTIONS` and
  `max_tokens = HYDE_MAX_TOKENS`;
- inside `agent_limits`: the harness `SpendLimits` over the ledger (so its spend lands in the
  caller's instance, library and user rows, priced by the price book) and pydantic-ai's
  `UsageLimits`.

The budgets it gets come from `AiSpend.budgets_for(library_ai)`, the seam where per-library budgets
(#102) merge in.

### Fallbacks

- Budgets and the rate limit are checked before (`within_budget` turns the choice into `hybrid`).
- A `SpendLimitExceeded` at the request answers `hybrid` with `llm_budget_reached`.
- An LLM error, an empty answer, a model that cannot be built or a timeout answers `hybrid` with
  `llm_unavailable`. Only the error's class is logged.
- When hybrid's own query embedding fails too, the reason given is hybrid's (it names the mode that
  answered, BM25).

!!! note "A rare lost spend"

    A timeout that strikes after the provider answered may cancel the harness while it records the
    spend, which is then lost. This is as rare as the in-flight overshoot the budgets already accept.

### The cache

- The cache is `retrieval_hyde_answers` (`SqliteHypothesisCache`, SQLite and PostgreSQL).
- A read-only process (`serve --stdio`) reads it and keeps its own answers in a bounded LRU
  (`ReadOnlyHypothesisCache`, `HYDE_MEMORY_CACHE_SIZE`).
- A cache that cannot be read is a miss, and one that cannot be written costs a call next time. Only
  the error's class is logged.
- A cached answer is no LLM call. `RetrievalModes.within_budget` reads it first
  (`HydePipeline.cached_answer`) and passes it on in `ModeChoice.hypothesis` (one cache read per
  search), so a hit answers `hybrid_hyde` even with a budget used up, and is not counted against the
  LLM search rate limit.
- A search whose hypothetical answer came from the cache is counted in `exactdocs.ai.cache_hits`
  (cache `hyde_answer`, #100).

`PruneHypotheses` deletes:

- answers older than `[ai.hyde] cache_ttl` (30 days);
- those of an `llm` model no longer configured (neither the instance's nor any library's override,
  or its profile is gone).

It runs at start, once a day just after UTC midnight with the embedding re-queue
(`Container.nightly`, the same single leader on PostgreSQL as `requeue_daily`), and after every
collection (`CollectChunks`).

### Data at rest

- The table stores the hypothetical answers in plain text. They are written from user queries and
  often restate them.
- The query itself is stored only as an HMAC-SHA256 of its normalized text, keyed with a key derived
  from the instance's secret key (`EXACTDOCS_SECRET_KEY` or the key file) for its own HKDF purpose,
  `exactdocs hyde cache v1` (`HYDE_CACHE_PURPOSE`). The hashes cannot be checked against a list of
  likely queries without that key.
- A read-only process without a secret key caches nothing.
- Rotating the secret key only makes every cached answer a miss.

## Reranker (#93)

Reranking is a flag on top of any mode (`ModeChoice.rerank`, with the library's `rerank_top_n` or
the instance's `[ai.reranker] top_n`).

1. `RetrievalModes.run` asks the pipeline for the top N when that is more than the call's limit.
2. The search use cases open a `rerank` stage span (no query, no text) and call
   `RetrievalModes.rerank`, which hands the answer to `Reranking` (in `use_cases`).
3. `Reranking` reads the candidates' chunk text. It is handed back to the use case, which reads only
   the chunks it lacks; a candidate whose chunk is gone is dropped and no longer counted in
   `coverage.candidates`.
4. Under `asyncio.timeout` (`RerankLimits.timeout_for` the profile's kind), it builds the library's
   reranker (the `ModelFactory`'s `reranker`, typed as the `Reranker` driven port: query and
   documents in, one score each out) and calls it.
5. `models.reorder` orders the scored head by score (ties keep the mode's order) and keeps the rest
   after it. The use case then cuts to the limit (`PipelineAnswer.cut`).

### One profile read per search

- The reranker's model and profile are read once per search (`Reranking.profile`, carried on
  `ModeChoice.reranker_profile`):
    - by `within_budget` when a budget needs the profile's kind;
    - else by `RetrievalModes.rerank`, from the library settings `RetrievalModes.choose` read once
      for the search.
- The kind, the timeout, the build and the recorded spend all use that read.
- The read is bounded by `RerankLimits.longest` and guarded like the call. A stored profile that
  cannot be read in time or at all answers `reranker_timeout` / `reranker_failed` (#284).

### Errors

- Any build failure, and anything the call raises (a client closed under it, an `ExceptionGroup` of
  its batches), is re-raised as a `RerankerError` naming only the exception's class. Cancellation
  passes through.
- A timeout, a `RerankerError` or a `ProviderUnsupportedError` keeps the mode's order with
  `fallback_reason` `reranker_timeout` / `reranker_failed`, and is logged without the query.

### Loading the SDKs

The provider SDKs are loaded in a worker thread, never on the event loop:

- at start when a profile other than `local` exists (`Container.running`,
  `PydanticAiModels.warm`). A failed load is logged as a warning and never stops the start;
- else on first use.

### The HTTP adapter

`adapters/driven/http_reranker.py`, `HttpReranker`:

- speaks the Cohere-compatible `/rerank` (`openai-compatible`, `vllm`, `litellm` profiles; Voyage's
  `data` answer too) or TEI's (`tei` profiles);
- cuts the texts to `MAX_RERANK_*_CHARS`;
- sends batches the endpoint accepts concurrently (a `TaskGroup`: one failed batch cancels the
  rest);
- turns every failure into a `RerankerError` without the URL, key or text.

Bootstrap's `ai_sdk.reranker` builds it on the profile's one guarded `httpx2` client.

## LLM judge (#96)

### What reranks

`RetrievalModes.choose` decides what reranks with `models.pick_reranker`:

- the library's `rerank_with`, else the instance's (`EXACTDOCS_AI__RERANK_WITH`, `cross_encoder` by
  default);
- the judge reranks only when chosen and its role resolves (`judge`, else `llm`);
- else the cross-encoder does, when there is one (`ModeChoice.reranker`).

### The window

`Reranking` hands the best of the same candidates that fit one bounded call
(`models.judge_window`) to the `CandidateJudge` driven port:

- at most `JUDGE_MAX_CANDIDATES` (64);
- while the input stays within `JUDGE_INPUT_TOKEN_BUDGET` (18,500) together with the largest output
  cap under the step's `LLM_TOKEN_LIMIT`[^limit].

The input is the text as cut and escaped, estimated by `models.estimated_tokens`:

| Text | Counted as |
|---|---|
| ASCII | `CHARS_PER_TOKEN` characters per token |
| long ASCII runs without whitespace, such as base64 | `DENSE_CHARS_PER_TOKEN` (1.5) characters per token |
| a code point above U+FFFF | its 4 UTF-8 bytes |
| every other character, control characters included | one token each, since CJK runs at about one token per character |

The budget's headroom covers 3 real tokens per estimated one: ASCII code with escaped entities runs
at about 1.7 characters per token, base64 broken by spaces at about 1.4, and rare BMP scripts such
as Yi at about 3 tokens a character.

[^limit]: pydantic-ai checks that limit only after a request, so a larger prompt would be sent,
    paid for and then refused.

The call:

- runs under `asyncio.timeout` (`[ai.judge] timeout`, 10 s);
- with an `LlmStep` whose budgets are `AiSpend.budgets_for(library_ai)`;
- the candidates beyond the window keep their order after the judged ones.

A timeout that strikes after the provider answered may cancel `SpendLimits` while it records the
spend, which is then lost, as for HyDE: the in-flight overshoot the decision record already accepts.

### The adapter

`adapters/driven/ai_judge.py`, with the SDK side in `ai_judge_sdk.py`, loaded on first use. It runs
one `Agent(output_type=list[Rating])`:

- **Each rating** is a positional ID (`c1` ... `cN`, `models.judge_id`) and an `int` from 0 to
  `JUDGE_MAX_SCORE` (bounded by the schema, strict, no extra fields). The ID is never a chunk ID:
  short to answer and nothing a candidate could imitate usefully.
- **Instructions:** the fixed `JUDGE_INSTRUCTIONS` say the query and the candidates are untrusted
  data.
- **The user prompt** comes from `models.judge_prompt`: the query in `<query>`, each candidate in
  `<candidate id="...">`, cut to `MAX_JUDGE_*_CHARS` and with `&`, `<`, `>` escaped, so no text can
  close or forge a delimiter.
- **An output validator** over `models.judged_scores`: exactly one rating per candidate given, each
  ID mapped back exactly, no unknown ID. It runs with `retries=0`, so a refused answer is never asked
  for again.
- **`max_tokens`** from `models.judge_max_tokens`: 512, plus 48 per candidate, so a pretty-printed
  answer fits with room for a model's reasoning.
- **`agent_limits`**: `SpendLimits` over the ledger, `UsageLimits`.

`Reranking` checks the ratings again with `judged_scores` before `models.reorder`, so the judge can
only reorder what it was given.

| Outcome | `fallback_reason` |
|---|---|
| a budget refusal | `llm_budget_reached` |
| a timeout | `reranker_timeout` |
| anything else (refused ratings, an error, a profile that cannot chat) | `reranker_failed`, logged with the fault's fixed text only |

Its spend is recorded by the harness, not by `RetrievalModes._record_rerank`.

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
- **PostgreSQL** (#103, see [Persistence](persistence.md#postgresql-103)):
    - psycopg 3;
    - DBOS's tables in the same database (`system_database_url` plus `dbos_system_schema`);
    - a per-library advisory lock replacing `TagLocks`;
    - PostgreSQL full-text search, the adapter databases without `pg_search` (such as Supabase) keep;
    - `pg_search`'s BM25 (#104) where the extension is installed, chosen at start.
