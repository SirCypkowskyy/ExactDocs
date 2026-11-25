# E11 AI retrieval

!!! abstract "TL;DR"
    - **Goal:** Opt-in hybrid, rerank, HyDE and agentic retrieval with budgets, guardrails and evals.
    - **Stories:** RET-01 to RET-09
    - **Milestones:** Next: AI retrieval
    - **Issues, in build order:** E11-01 to E11-14 on this page; E11-15 to E11-21 were added in 2026-11 (table below)
    - **Status:** the epic ([#11](https://github.com/SirCypkowskyy/ExactDocs/issues/11)) is closed; GitHub holds the current issue bodies.

!!! info "Decisions (2026-11)"
    The [AI retrieval decisions](../decisions/ai-retrieval.md) (#240) settle providers, vector
    storage, local models, image variants, configuration, budgets, telemetry, evals and the order
    of work, and supersede the hints below where they differ (vector storage, the
    `OpenAICompatibleProvider` hint, the FastMCP rate-limit middleware). Seven issues were added,
    and E12-01 (#103) and E12-02 (#104) moved into this milestone; they stay sub-issues of epic
    E12 (#12), whose stories they deliver:

    | Plan ID | Issue | Title | Depends on |
    |---|---|---|---|
    | E11-15 | #241 | operators configure AI providers once per instance, with per-library overrides and sealed keys | E11-01 |
    | E11-16 | #242 | vectors are stored per embedding space behind one port, in SQLite with sqlite-vec | E11-01 |
    | E11-17 | #243 | vectors are stored in pgvector on PostgreSQL | E11-16, E12-01 |
    | E11-18 | #244 | ExactDocs runs on Supabase, with BM25 that works without pg_search | E12-02, E11-17 |
    | E11-19 | #245 | a local embedding model and reranker run fully offline | E11-03, E11-05 |
    | E11-20 | #246 | the image ships in three variants (base, -ai, -local), each with its own size budget | E11-15, E11-19 |
    | E11-21 | #248 | the secret box moves to bootstrap so every domain can seal secrets through its own port | - |

    Changed dependencies: E11-03 now depends on E11-15 and E11-16; E11-05 on E11-15; E11-08
    (budgets) on E11-15 and E11-03 instead of E11-06, and E11-06 (HyDE) on E11-04 and E11-08, so
    no LLM call ships unmetered; E11-14 also on E11-15; E11-15 and E12-03 also on E11-21; E12-02 no longer on E11-03. GitHub holds
    the current bodies.

All E11 issues: milestone **Next: AI retrieval**, labels `type: feature` `status: triage`
`area: backend`, Area *backend / retrieval* (E11-14: `area: web`, Area *web UI*). Code lives in retrieval adapters
and is imported only through the `exactdocs[ai]` extra (Decisions *Agent stack*); every model
call uses `httpx2`; every mode returns the MCP-05 result shape and has a "wrong version gets
nothing" test.

## E11-01 · feat: the retrieval mode is chosen per call, library and instance, from what is configured

**Stories** RET-06 (backend), MCP-05 (mode), RUN-02, C7-02 (library mode) · **Depends on** E7-04 · **Size** M

**Context.** One size does not fit every documentation set, and asking for an unavailable mode
must fail clearly.

```gherkin
Scenario: Precedence is call, then library, then instance
  Given the instance mode is "bm25" and the library's mode is "hybrid"
  When an agent searches with mode "bm25"
  Then the result says retrieval mode "bm25"
```

- [ ] `RetrievalPipeline` port with a registry of available modes from configuration; library setting validated against it
- [ ] `exactdocs[ai]` extra with pinned matching `pydantic-ai-slim` + `pydantic-ai-harness[codemode]`; a test proves nothing from it is imported when no model is configured

## E11-02 · feat: a retrieval eval suite compares modes on the fixture libraries

**Stories** RET-09, RUN-05 · **Depends on** E11-01, E5-04 · **Size** M

**Context.** Modes must be compared before one becomes a default.

```gherkin
Scenario: The suite reports per-mode metrics
  When the eval suite runs with only BM25 available
  Then it reports recall@k, wrong-version rate, cost and latency for "bm25"
```

- [ ] Pydantic Evals dataset from the fixture's expected queries plus questions; runs in CI for BM25, and for other modes when endpoints are provided
- [ ] wrong-version rate computed from returned results (the agentic trace check is added by E11-11)

## E11-03 · feat: an embedding endpoint embeds every version in the background

**Stories** RET-01 · **Depends on** E11-01 · **Size** M

**Context.** Semantic search with a model of the operator's choice, without blocking BM25.

```gherkin
Scenario: Changing the model re-embeds instead of mixing vectors
  Given chunks were embedded with model "a"
  When the operator switches to model "b"
  Then all chunks are re-embedded with "b" in the background while BM25 answers
```

- [ ] `pydantic_ai.Embedder` adapter (OpenAI-compatible, Ollama, TEI...), own batching, `EmbeddingSettings(dimensions=…)`, model + dimensions stored per vector
- [ ] vectors keyed by chunk content (dedup); background job per version
- [ ] SQLite vector storage (Decisions *Vector storage*): float32 BLOBs, brute-force cosine scoped to the active manifest, behind a `VectorIndex` port; numpy only in the `[ai]` extra; pgvector on PostgreSQL (E12-02)

## E11-04 · feat: search becomes hybrid (BM25 + vectors fused with RRF)

**Stories** RET-01 · **Depends on** E11-03 · **Size** M

```gherkin
Scenario: Hybrid search when an embedding model is configured
  Given every chunk of "v1.4.0" is embedded
  When an agent searches "how do I retry failed calls"
  Then the result says retrieval mode "hybrid"
  And no chunk from another version is returned
```

- [ ] vector search scoped to the active manifest; RRF fusion; `coverage` counts both halves
- [ ] versions not yet embedded answer with BM25 and `fallback_reason`

## E11-05 · feat: a cross-encoder reranker reorders the top candidates

**Stories** RET-02 · **Depends on** E11-01 · **Size** M

```gherkin
Scenario: A reranker timeout never fails the search
  Given a reranker endpoint that times out
  When an agent searches
  Then results arrive in the unreranked order with "reranked: false" and a fallback reason
```

- [ ] Cohere-compatible / Jina / TEI adapter; top N (default 32) reranked; errors logged and fallen back

## E11-06 · feat: an LLM endpoint enables HyDE for hybrid search

**Stories** RET-03 · **Depends on** E11-04 · **Size** M

**Context.** Companies route LLM traffic through their own gateways; HyDE improves the vector half.

```gherkin
Scenario: HyDE is the default with embeddings and an LLM
  Given an embedding model and an LLM are configured
  When an agent searches without a mode
  Then the result says retrieval mode "hybrid_hyde"
  And a repeated query for the same version reuses the cached hypothetical answer
```

- [ ] `OpenAICompatibleProvider`; proxy on the transport; exactly one retry layer; overall `request_timeout`; key stored as a secret
- [ ] extra HTTP headers and extra model parameters configurable (RET-03), headers sent on every LLM call (test with a mock gateway); header values treated as secrets in logs
- [ ] HyDE = `Agent(output_type=str)` output embedded; cache per (query, version)

## E11-07 · feat: a judge model can rerank candidates

**Stories** RET-02 · **Depends on** E11-05, E11-06, E11-08 · **Size** M

```gherkin
Scenario: The judge only rates candidates it was given
  When the judge model returns a chunk ID it was not given
  Then the output validator rejects it and the search falls back to the unreranked order
```

- [ ] one call rates all candidates (`list[...]` output, bounded score), per-call timeout, counted against RET-07 budgets

## E11-08 · feat: LLM usage is limited by budgets and rate limits

**Stories** RET-07 · **Depends on** E11-06; metrics with E10-08 · **Size** L

**Context.** HyDE and agentic retrieval cost money.

```gherkin
Scenario: Reaching the daily budget falls back to the non-LLM pipeline
  Given the instance's daily token budget is used up
  When an agent searches in "hybrid_hyde" mode
  Then the result says retrieval mode "hybrid" with fallback reason "llm_budget_reached"
```

- [ ] harness `SpendLimits` per instance, library and user; spend store = `retrieval_` tables in the shared database (Alembic), so it works on SQLite and PostgreSQL
- [ ] requests per minute per token via FastMCP `SlidingWindowRateLimitingMiddleware`
- [ ] usage via pydantic-ai `gen_ai.client.token.usage` and cost metrics (exported by E10-08)

## E11-09 · feat: agents read article outlines with `article_outline`

**Stories** RET-04 · **Depends on** E7-03 · **Size** S

```gherkin
Scenario: An outline lists headings only
  When an agent calls "article_outline" for "guide/install.md" of "v1.4.0"
  Then it gets the heading tree with chunk IDs and no body text
```

- [ ] MCP tool + REST route, typed return model; reused by the agent (E11-10)

## E11-10 · feat: agentic retrieval browses the tree in Code Mode and justifies its answer

**Stories** RET-04 · **Depends on** E11-09, E11-08 · **Size** L

**Context.** Some questions need reasoning over structure, not keyword or vector similarity.

```gherkin
Scenario: Agentic mode returns justified articles from the pinned version
  Given an LLM is configured and agentic mode is on
  When an agent searches "/fixture/docs-repo/v1.4.0" in mode "agentic"
  Then results carry a justification and the explored path
  And every result belongs to "v1.4.0"
```

- [ ] pydantic-ai agent with harness Code Mode: read tools (`list_articles`, `article_outline`, `read_article`, `read_chunk`, `search_docs`) only inside sandboxed `run_code` (Monty, never IPython), typed returns
- [ ] bounded by `max_tool_calls`, Monty resource limits, `UsageLimits`; exceeding ends the run and falls back to BM25 with the reason
- [ ] pydantic-ai instrumentation with `include_content=False`; one span per tool call, nested in `run_code` (exported by E10-07 when telemetry is on)

## E11-11 · feat: agentic retrieval only sees what the caller may see and stops on loops

**Stories** RET-04, RET-09 (agentic trace check) · **Depends on** E11-10 · **Size** M

```gherkin
Scenario: The output guardrail rejects foreign articles
  When the agent proposes an article that is not in the pinned version
  Then the guardrail rejects it and it is not returned
```

- [ ] caller access scope passed as `deps`, never as model-visible tool arguments
- [ ] output guardrail (pinned version, visibility); loop detection falls back to BM25 with the reason
- [ ] eval trace check in the E11-02 suite proves agentic runs stayed within the requested version (the only place this check lives)

## E11-12 · feat: similar agentic questions are answered from a cache

**Stories** RET-05 · **Depends on** E11-10 · **Size** M

```gherkin
Scenario: A similar question hits the cache
  Given "how do I configure retries" was answered agentically for "v1.4.0"
  When an agent asks "how to configure retry behaviour" for "v1.4.0"
  Then the cached result is returned with "cache_hit: true"
```

- [ ] similarity by hybrid search over past questions (BM25 without embeddings), configurable threshold; invalidated on re-sync

## E11-13 · feat: the repository's `AGENTS.md` / `CLAUDE.md` guide agentic retrieval

**Stories** RET-08 · **Depends on** E11-10, E3-05a · **Size** M

```gherkin
Scenario: Instruction files are untrusted notes by default
  Given the library's repository has an AGENTS.md describing its docs layout
  And the owner enabled repo guidance without marking the library trusted
  When the agent opens a directory
  Then the file reaches it as a user-channel note, not as system instructions
```

- [ ] importer keeps instruction files per version even outside the selection; off by default
- [ ] harness Repo Context over a read-only, database-backed workspace; system instructions only for trusted libraries

## E11-14 · feat: the UI shows each library's effective retrieval pipeline and LLM usage

**Stories** RET-06 (UI), RET-07 (UI) · **Depends on** E11-01, E11-08 · **Size** M · **Labels** `area: web` · **Area** web UI

```gherkin
Scenario: The effective pipeline is visible
  Given an embedding model is configured
  When the user opens a library's settings
  Then the effective pipeline "hybrid" is shown and only configured modes can be chosen
```

- [ ] library retrieval-mode setting, instance usage page (tokens, cost, budget left); vitest
