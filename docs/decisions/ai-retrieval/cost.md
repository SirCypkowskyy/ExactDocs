# Cost, telemetry and evaluation

!!! abstract "TL;DR"
    - Every model call records tokens and USD. A USD budget on a model with no known price is
      refused at start. `local` models cost nothing and count toward no token budget.
    - Budgets (#95) are token and USD limits per instance, library and user, per UTC day and month,
      in one `retrieval_ai_spend` table. stdio MCP writes that ledger through a narrow writable
      connection.
    - A budget or rate limit never fails a search: it skips the LLM step and says why in
      `fallback_reason`.
    - Telemetry uses pydantic-ai's OpenTelemetry with `include_content=False` and never carries
      prompt text.
    - Eval gates: wrong-version rate 0, recall@5 at most 2 points below the baseline, and a new
      default mode must beat BM25 recall@5 by at least 5 points.

## Cost and budgets

- **Accounting.** Every model call records input and output tokens and its price in USD:
  pydantic-ai's bundled `genai-prices` data, or the operator's per-model price
  (`[ai.prices]`). A USD budget on a model with no known price is refused at start; tokens are
  always counted.
- **Local models and token budgets (#284, decided by the owner).** In-process (`local`) models
  cost nothing.
    - Their tokens are still **recorded**, for visibility: `local_tokens` in the ledger row and in
      `GET /api/v1/ai/usage`, included in its input and output tokens.
    - They **count toward no token budget**: a row's budgeted `tokens` leave them out.
    - No budget is checked before a local call either:
        - a search's local query embedding and rerank always run
        - a local embedding job is never stopped, nor held back from the queue, by a budget, even
          one that paid calls have used up (`ai_budget_reached` is for paid models only)
    - Before #284 local tokens counted. Local search traffic alone (about 16k tokens per rerank of
      32 candidates) could use up an instance or library token budget and so stop the local
      embedding job, while the searches themselves were exempt.
    - Self-hosted endpoints (`ollama`, `vllm`, TEI) are not `local`: they count as paid, tokens
      included.
    - **Rows written before the upgrade** (migration `b5e8d2a7c4f9`) get `local_tokens = 0`.

        !!! warning "Local tokens before the upgrade stay counted"
            A row does not record which model spent its tokens, so no backfill is possible, and
            local tokens already in the current day and month windows stay counted until each
            window resets. An instance with a monthly token budget and paid models can therefore
            keep refusing paid calls and a paid embed job until the month ends; the operator can
            raise the budget meanwhile.

- **Budgets** (#95):
    - token and USD limits
    - per instance, per library and per user (the token's account; stdio MCP counts to instance and
      library)
    - per UTC day and month
    - in one `retrieval_ai_spend` table (an atomic upsert per scope key and window) that works on
      SQLite and PostgreSQL, across processes
    - **LLM agents** (HyDE, judge, agentic) are limited by the harness `SpendLimits` capability.
      Our store implements the harness **`BatchSpendStore`** protocol (`get_many` / `add_many`
      over `SpendEntry`) structurally. Its older `SpendStore` protocol is deprecated since 0.60.0:
      `SpendLimits` wraps it, warns, and loses the token-based deduplication of replays.
    - **Embedding and rerank calls** (`Embedder`, the HTTP rerankers, fastembed) never run
      through an agent, so `SpendLimits` cannot see them. Retrieval records and checks them
      itself, against the same table and the same rows, before each batch (the embed job) or
      call (rerank); fastembed's calls are recorded but never checked (local models, above).
    - **We own the key format.** A ledger row is keyed by (scope kind, scope id, window, window
      start), in our own format. The harness builds its `SpendEntry.key` with private helpers
      (`store_key`, `bucket` in `pydantic_ai_harness/spend_limits/_budget.py`, not exported), so our
      `BatchSpendStore` adapter parses each key the harness hands it into our row key, and never
      imports the private module. A contract test pins the harness 0.73.0 key format: a harness
      bump that changes it fails the test instead of splitting the spend over two sets of rows.
    - A check runs before each call or batch, so a burst can overshoot by at most the calls
      already in flight.
    - **stdio MCP processes write the ledger too** (#274, decided by the owner: a narrow
      writable connection).
        - `serve --stdio` opens the database read-only, and opens one more engine for
          `retrieval_ai_spend` and `retrieval_ai_spend_replays` only. It uses the same keys and
          the same replay deduplication as a server (the same `SqliteSpendLedger`).
        - On SQLite that engine opens the existing file with `mode=rw` and a `sqlite3` authorizer
          that denies:
            - every insert, update or delete outside those two tables
            - every schema change
            - `ATTACH`
            - every `PRAGMA` but a read of a short allow-list (no `wal_checkpoint` or
              `incremental_vacuum`)
        - On PostgreSQL it is the same role without `default_transaction_read_only`: the limit is
          the code path (only the ledger is given that engine), not the database.
        - This is the one documented exception to stdio's read-only guarantee.
        - A failed write is logged and the spend kept in the process's memory
          (`ReadOnlySpendLedger`), so the AI call never fails for it.
        - Rejected:
            - handing the spend to the server over its API (stdio needs no running server or
              token)
            - a queued file the server imports (spend unseen until the import, and a second format
              to keep)
- **Per-call limits:** pydantic-ai `UsageLimits` on every call; for the agent also
  `max_tool_calls` and Monty's resource limits.
- **Rate limit:** LLM searches per minute per caller, enforced inside retrieval so it covers
  REST, HTTP MCP and stdio alike. It replaces FastMCP's `SlidingWindowRateLimitingMiddleware`,
  which only sees MCP and limits every tool, not just the expensive ones.
- **Degrade, never fail.**
    - A budget or rate limit skips the LLM step and answers with the next cheaper mode, saying why
      (`fallback_reason`: `llm_budget_reached`, `llm_rate_limited`).
    - An exhausted embedding budget stops the `embed` job of a paid model (`ai_budget_reached`),
      retried when the window resets, while BM25 keeps answering. A local model's job runs on.
- **Visibility:** `GET /api/v1/ai/usage` and the UI (#102) show spend and budget left per scope;
  `exactdocs ai estimate` prints the tokens and USD of embedding every version before it starts.

## Telemetry

- pydantic-ai's own OpenTelemetry instrumentation, `InstrumentationSettings(include_content=False)`,
  on the global providers that `bootstrap/otel_sdk.py` sets up (never Logfire, see
  [Telemetry](../../architecture/telemetry.md)). Spans for model and embedding calls nest under the
  existing `retrieval.<search>` spans, with new stages `embed_query`, `hyde`, `rerank`, `judge` and
  `agent`; agent tool calls nest inside `run_code`.
- **No prompt text, ever.** `include_content=False` is the first guard; `ScrubbingExporter` also
  drops `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions` and
  tool-call arguments as a second one. `EXACTDOCS_TELEMETRY_QUERY_TEXT` keeps covering the query
  text of request spans only; it never turns prompts on.
- **Metrics** (OTLP and `/metrics`): pydantic-ai's `gen_ai.client.token.usage`,
  `gen_ai.client.operation.duration` and `operation.cost`; ours: `exactdocs.ai.fallbacks` (by mode
  and reason), `exactdocs.ai.cache_hits` (by cache and mode), `exactdocs.embedding.backlog` (chunks waiting). Labels
  are bounded: provider kind, model (from configuration), operation, role, token type. Never the
  library, version, user or query, as for the existing metrics.

## Evaluation

- **Pydantic Evals 2.73.0** (dev dependency group, not an extra), datasets in the repository: the
  fixture library's expected queries plus natural-language questions, each with the expected
  version, article path and heading (#90).
- **Metrics per mode:** recall@1/5/10, MRR, **wrong-version rate**, p50 and p95 latency, tokens and
  USD per question, as a JSON report and a job summary.
- **Tiers.**

    | What | Runs | How |
    |---|---|---|
    | BM25 | every release, before anything is published | gating |
    | `hybrid` and rerank | the manual *Eval* workflow (`eval.yml`), before a release that touches retrieval | for real with `[local]` and cached ONNX models, without any secret; report-only, compared with the baseline committed in the tagged tree |
    | LLM modes | tests | with `TestModel` / `FunctionModel`; with a real provider only by a manual `workflow_dispatch` that has the key |

    - Pull requests do not run the suite (#367: it made every CI run longer). So a ranking
      regression is caught at release time, and a contributor who changes ranking runs
      `just eval` first.
    - No live endpoint is ever needed for CI or a release to pass.
- **Gates.**
    - Wrong-version rate must be 0 for every mode.
    - recall@5 may not drop more than 2 points below the baseline.
    - A mode becomes a default only when it beats BM25 recall@5 by at least 5 points with
      wrong-version rate 0.
    - Agentic runs are also checked from their traces (#99).
- How to run it, the dataset and the tiers as built: [Retrieval evals](../../evals/index.md).
