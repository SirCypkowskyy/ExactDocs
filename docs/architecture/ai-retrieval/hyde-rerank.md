# HyDE, reranker and LLM judge

!!! abstract "TL;DR"
    - `hybrid_hyde` embeds an LLM-written hypothetical answer for the vector half (within 10 s) while
      BM25 searches the query; on failure it answers `hybrid` with `llm_budget_reached` or
      `llm_unavailable`.
    - Answers are cached by manifest, model and a hash of the normalized query; a hit is no LLM call,
      and answers older than 30 days are pruned.
    - Reranking is a flag on any mode, by the cross-encoder by default (`rerank_with`) or the LLM
      judge; a failure keeps the mode's order with `reranker_timeout` / `reranker_failed`.
    - The judge rates at most 64 candidates within 18,500 input tokens and 10 s, and can only reorder
      what it was given.

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

[^limit]: ../pydantic-ai checks that limit only after a request, so a larger prompt would be sent,
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
