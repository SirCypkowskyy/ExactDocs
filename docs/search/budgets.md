# Budgets and rate limits

!!! abstract "TL;DR"

    - `[ai.budgets]` caps spend in US dollars and tokens per UTC day and month, per instance, library, account and embedding runs.
    - Reaching a limit degrades search, and BM25 keeps answering.
    - Prices come from the bundled `genai-prices` data; give unknown models a price.
    - `local` models cost nothing and count toward no token budget.

```toml
[ai.budgets]
daily_usd = 10
monthly_embedding_usd = 50
per_library_daily_usd = 2
per_user_daily_usd = 1
llm_searches_per_minute = 30

[ai.prices."corp:gpt-4.1-mini"]   # only for models genai-prices does not know
input_usd_per_mtok = 0.40
output_usd_per_mtok = 1.60
```

`[ai.budgets]` (or `EXACTDOCS_AI__BUDGETS__...`) caps spend in US dollars and tokens per UTC day
and month:

| Scope | Settings |
|---|---|
| the instance | `daily_usd`, `monthly_usd`, `daily_tokens`, `monthly_tokens` |
| each library | `per_library_...` |
| each account (the API token's or the session's; stdio MCP counts to the instance and library only) | `per_user_...` |
| embedding runs | `daily_embedding_...`, `monthly_embedding_...` |

`llm_searches_per_minute` limits each caller's LLM searches over REST, HTTP MCP and stdio alike,
counted per server process.

Every model call is counted from the usage the provider reports, in one `retrieval_ai_spend` table
shared by every server process and by stdio MCP processes. Those open the database read-only but
add their spend to this table over a connection that may write only it (see
[stdio](../mcp.md#without-a-network-port-stdio)). The tokens are recorded per UTC day and month for
the instance, the library and embedding runs. LLM agents are held by the harness `SpendLimits`,
and embedding and rerank calls by retrieval's own check before each batch or call, so a burst can
overshoot by the calls already in flight.

Reaching a limit degrades search; it never breaks it:

- the LLM step is skipped, and the result names the cheaper mode with
  `fallback_reason: llm_budget_reached` (or `llm_rate_limited`);
- a paid rerank is skipped (`reranked: false`). A rerank that ran counts one request and its
  tokens, estimated at 4 characters per token since rerank endpoints report none;
- an `embed` job of a paid model stops before its next batch with `ai_budget_reached` and is queued
  again after the window resets (each UTC midnight, by one server process, a few minutes after at
  random);
- BM25 keeps answering.

**Prices** come from the `genai-prices` data bundled with pydantic-ai, which is never fetched. A
model it does not know gets `input_usd_per_mtok` and `output_usd_per_mtok` under
`[ai.prices."<profile>:<model>"]`, as above.

- `local` models cost nothing. Their tokens are recorded (`local_tokens` in the usage) but count
  toward no token budget, so local search traffic never uses up a budget, and no budget stops a
  local embedding job or a search's local query embedding or rerank. Tokens recorded before this
  rule existed (local ones included, since older rows do not say which model spent them) stay
  counted until their day or month window resets.
- Self-hosted endpoints (`ollama`, `vllm`, a TEI reranker) count as paid and are never priced from
  another provider's list. With a US dollar budget, give them a price of 0
  (`input_usd_per_mtok = 0`) if they cost nothing.
- A US dollar budget together with a configured model that has no price is refused at start.

**Usage**: `GET /api/v1/ai/usage` (admins) shows what the instance, embedding runs, each library and
each account spent today and this month, and what is left of each budget (a library's own budget
where it is tighter); `GET /api/v1/ai/usage/history` shows one of those scopes per UTC day or
month, zero-filled, for up to 366 days or 60 months ([REST API](../rest-api/ai.md#spend)). `/metrics` has pydantic-ai's `gen_ai.client.token.usage` and
`operation.cost`, `exactdocs_ai_fallbacks_total` by mode and reason, and
`exactdocs_ai_cache_hits_total` (searches whose LLM step a cache answered) by cache
(`agentic_answer`, `hyde_answer`) and mode, never by library, user or query. Spans never carry
prompts or completions, even with `EXACTDOCS_TELEMETRY_QUERY_TEXT` on.
