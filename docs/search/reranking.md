# Reranker and LLM judge

!!! abstract "TL;DR"

    - A cross-encoder reranker reorders the best candidates of every search.
    - An LLM judge can rerank instead, where it is chosen with `rerank_with = "judge"`.
    - A reranker or judge that fails never fails a search: the order stays, with `reranked: false`.
    - Only the query and the chunk text are sent, never a library, version or user.

## Reranker

A cross-encoder reranker reorders the best candidates of every search (`search_docs`, `query-docs`,
the REST search) for precision. A hybrid search is reranked the same way, after the fusion. The
reranker speaks one of two HTTP dialects:

```toml
[ai.providers.cohere]                   # Cohere-compatible POST <base_url>/rerank
kind = "openai-compatible"
base_url = "https://api.cohere.com/v2"  # Jina: https://api.jina.ai/v1, Voyage: https://api.voyageai.com/v1
api_key_file = "/run/secrets/cohere_key"

[ai.providers.tei]                      # Text Embeddings Inference: POST <base_url>/rerank
kind = "tei"
base_url = "http://tei:8080"

[ai.reranker]
model = "cohere:rerank-v3.5"            # or "tei:BAAI/bge-reranker-base" (TEI serves one model)
top_n = 32                              # candidates reranked per search (1 to 200)
timeout = 2.0                           # seconds for building the reranker and its call
```

vLLM and LiteLLM (`kind = "vllm"` or `"litellm"`, with a base URL ending in `/v1` or `/v2`) and
Azure AI Foundry's Cohere deployments (`openai-compatible`) speak the Cohere-compatible dialect
too. A `tei` profile still needs the `exactdocs[ai]` extra, like every profile, although it only
uses `httpx2`.

Only the query and the candidates' chunk text are sent: each cut to 8,000 characters, in batches
of 100 (32 for TEI). A library name, a version or a user is never sent.

A reranker that times out, fails or answers something unusable never fails a search. The results
keep their order with `reranked: false` and `fallback_reason` `reranker_timeout` or
`reranker_failed`, and the failure is logged without the query. Whatever the reranker raises (an
HTTP client closed under the call because its profile was edited, a partly installed SDK) counts as
`reranker_failed`. Traces show it as the `rerank` stage, without the query or any text.

With a `limit` above `top_n`, the reranked results come first and the rest follow in the mode's
order, with the mode's scores, which are not comparable with the reranker's.

A vector backend with a ranker of its own can rerank instead (#473): with Azure AI Search and a
`semantic_configuration`, a hybrid search that reranks is reranked by Azure's semantic ranker in
the same request (the query's text goes to Azure with it, which already holds the chunks), says
`reranked: true`, and the reranker above is not called for it. Whatever Azure does not rerank
(other modes, a ranker over capacity or refused) is reranked here as above. See
[Azure AI Search](../configuration/index-backends/azure-search.md).

With any provider profile other than `local` configured, the provider SDKs are loaded in a worker
thread at start, so the first search never waits for them. A load that fails is a warning, not a
stop.

## LLM judge

Without a cross-encoder endpoint, or for better judgments than one gives, a small, fast LLM can
rerank instead. The `judge` role (any chat profile; it defaults to the `llm` role) rates every
candidate in one call, with a whole score from 0 to 10 per candidate. Since it costs an LLM call
per search, it only reranks where it is chosen:

```toml
[ai.judge]
model = "corp:gpt-4.1-mini"             # optional: the [ai.llm] model when unset
timeout = 10.0                          # seconds for building the model and its one call

[ai]
rerank_with = "judge"                   # EXACTDOCS_AI__RERANK_WITH; default "cross_encoder"
```

A library chooses for itself with `rerank_with` (`cross_encoder` or `judge`) in its retrieval
settings or the UI; unset, the instance's choice applies. When both a cross-encoder and a judge
are configured, the cheaper cross-encoder reranks unless the judge is chosen. A library that
chooses the judge without one configured is reranked by the cross-encoder, if there is one.

### What the judge sees

It gets the best of the same top N as the cross-encoder, as many as fit
one bounded call: at most 64 candidates and about 18,500 input tokens.[^judge-tokens] That keeps
the call under the 60,000 tokens one LLM step may use, even for code full of escaped `<`, `>` and
`&`, or base64 broken by spaces, or rare scripts at 3 tokens a character, so a call is never
stopped after it was paid for. With 2,000 characters per candidate that is about 32 English or code
candidates, or 9 CJK ones. Candidates beyond those keep the mode's order after the judged ones, and
`coverage.reranked` counts only the judged.

The judge gets the query and each candidate's chunk text (cut to 2,000 characters), named by
position (`c1`, `c2`...), never by chunk ID, and never a library name, a version or a user. The
prompt and the instructions mark them as untrusted, delimited text, and every `<`, `>` and `&` in
them is escaped, so a candidate cannot close its delimiter.

### What it may answer

Its answer may only reorder the candidates it was given. Ratings that name
an ID it was not given (anything but exactly `c1` to `cN`), rate a candidate twice, leave one out or
go outside 0 to 10 are refused at once, with no retry, and the search keeps its order with
`fallback_reason` `reranker_failed`. A judge that does not answer within its timeout keeps the
order with `reranker_timeout`.

It is an LLM step, so it counts against the budgets and the LLM search rate limit (once per search,
together with HyDE's step). Once a budget is used up, the search keeps its order with
`fallback_reason` `llm_budget_reached` without calling it. Traces show it as the `judge` stage,
without the query, the candidates or the ratings.

[^judge-tokens]: Tokens are estimated at 4 characters per token for ASCII text, 1.5 for long ASCII
    runs without whitespace (base64, hashes), 4 tokens for a character above U+FFFF (CJK Extension
    B, emoji) and one token for any other character (CJK, Cyrillic, control characters...).
