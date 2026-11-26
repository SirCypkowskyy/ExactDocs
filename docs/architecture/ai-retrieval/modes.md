# Profiles, modes and hybrid search

!!! abstract "TL;DR"
    - A role uses the library's `<profile>:<model>`, else the instance's; the judge falls back to
      the LLM, and a library with AI off has no roles.
    - Every AI pipeline goes through `AiProviders.model_for`, so a profile edited over REST counts at
      the next call.
    - The mode is the call's, else the library's, else the instance's (`EXACTDOCS_AI__MODE`), else
      the best of `DEFAULT_MODE_ORDER`, which lists only `bm25` yet.
    - `hybrid` fuses the 50 best BM25 hits and the 50 nearest chunks by reciprocal rank fusion
      (`k` = 60); ties go to BM25's order.
    - The pipeline never fails a search: BM25 answers instead, with a `fallback_reason`.

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
  ([Retrieval evals](../../evals/gates.md#gates)). Only `bm25` is listed yet, so an operator, a library or a
  call chooses `hybrid`.
- Removing a library drops its mode too (`ForgetLibrary`, called by the removal bridge after the
  catalog).

### The vector store port (#242)

- The `VectorIndex` driven port: create, activate and retire a space, upsert and delete vectors by
  `ChunkKey`, nearest within one manifest, a manifest's coverage and missing chunks.
- It has an in-memory reference and the SQLite adapter (see
  [Vector store](../embeddings.md#vector-store-ret-01-242)), and one contract test for both
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
- Reranking ([Reranker](hyde-rerank.md#reranker-93)) runs after the pipeline, on the fused order, like for any mode. The pipeline is
  asked for the reranker's top N when that is more than the limit.

The pipeline never fails a search. BM25 answers with:

| `fallback_reason` | When |
|---|---|
| `embedding_in_progress` | the space no longer matches the configured model (a switch of models) |
| `llm_budget_reached` | a budget the query embedding counts to is used up (as a paid rerank over budget) |
| `embedding_unavailable` | the model failed, timed out or answered an unusable vector (or the key could not be opened) |
| `vector_store_unavailable` | the store cannot search |
