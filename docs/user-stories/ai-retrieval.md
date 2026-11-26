# Next: AI-powered retrieval (all optional)

!!! abstract "TL;DR"
    - RET-01 to RET-09, all optional: embeddings for hybrid search, a reranker or judge model, an
      LLM for HyDE, and an agentic mode that browses the library tree in Code Mode.
    - Existing versions are embedded in the background while BM25 keeps answering; changing the
      model re-embeds instead of mixing vectors.
    - Reranker errors, timeouts and LLM limits never fail a search: it falls back and says so.
    - Mode precedence is call > library > instance. LLM usage has per-minute limits and token or
      USD budgets per instance, library and user (RET-07).
    - Agentic results are cached for similar questions (RET-05), repository `AGENTS.md` /
      `CLAUDE.md` files can guide the agent (off by default), and an eval suite compares modes.

- **[RET-01]** As an operator, I want to configure an embedding model endpoint (OpenAI-compatible API, Ollama, TEI, a local server) with key, base URL, dimensions and batch size, because I want semantic search with the model of my choice.
    - Acceptance:
        - search becomes hybrid (BM25 + vectors, fused with RRF)
        - existing versions are embedded in the background while BM25 keeps answering
        - changing the model re-embeds instead of mixing vectors.
    - Implementation:
        - [`pydantic_ai.Embedder`](https://pydantic.dev/docs/ai/guides/embeddings/) (OpenAI-compatible, OpenAI, OpenRouter, Azure OpenAI, Vertex AI, Ollama, vLLM) behind our own `Embeddings` port
        - local models run in-process only through fastembed (ONNX, no torch) in the optional `exactdocs[local]` extra and `-local` image
        - sentence-transformers stays unsupported, to keep installs light.
- **[RET-02]** As an operator, I want to configure a reranker, either a cross-encoder endpoint (Cohere-compatible, Jina, TEI, local) or a **judge model** (any pydantic-ai model, ideally a fast decision model via the System One API or Ollama, otherwise a small LLM) that rates each candidate chunk's relevance to the query, because reranking the top results improves precision.
    - Acceptance:
        - the top N candidates (configurable, default 32) are reranked
        - judge calls count against the RET-07 budgets
        - a reranker error or timeout falls back to the unreranked order (`reranked: false`) and is logged, never failing the search. The judge returns a bounded relevance score (pydantic-ai decision models do this natively)
        - each judge call has a timeout. Inspired by harness [Smart Search](https://pydantic.dev/docs/ai/harness/smart-search/)'s judge step, but on our header-based chunks, with no shell, workspace or files on disk.
- **[RET-03]** As an operator, I want to configure an LLM (endpoint, API key, model, optional HTTP proxy, timeouts, extra headers and parameters), because HyDE and agentic retrieval need one, and companies route LLM traffic through their own gateways.
    - Acceptance:
        - any OpenAI-compatible endpoint works
        - the key is stored as a secret
        - with embeddings also configured, hybrid search uses HyDE by default
        - HyDE outputs are cached per query and version.
    - Implementation:
        - `OpenAIProvider(base_url=…, api_key=…)` with `OpenAIChatModel` for custom OpenAI-compatible endpoints, and pydantic-ai's own providers for OpenAI, OpenRouter, Anthropic, Azure OpenAI and Vertex AI (see [AI retrieval decisions](../decisions/ai-retrieval/providers.md#provider-abstraction))
        - the proxy is set on the transport (`httpx2.AsyncHTTPTransport(proxy=…)`), because a retrying transport stops httpx reading `HTTPS_PROXY`
        - exactly one layer retries (transport or `max_retries`)
        - `request_timeout` is the overall deadline. HyDE is a plain `Agent(output_type=str)` whose output is embedded. For RET-01, the adapter batches inputs itself (`Embedder` has no batch size), sets `EmbeddingSettings(dimensions=…)` and stores model and dimensions with each vector. For RET-02, an LLM judge rates all candidates in one call (`list[...]` output) with an output validator that rejects chunk IDs it was not given.
- **[RET-04]** As a user or AI agent, I want an optional agentic retrieval mode where a pydantic-ai agent browses the library tree (list articles, read headings, open articles) until it finds the articles that answer the question, and returns them with a justification, because some questions need reasoning over structure, not keyword or vector similarity.
    - Acceptance:
        - selected by `mode="agentic"` or the library/instance setting
        - returns the MCP-05 result shape
        - step and token limits are enforced
        - the agent reads article outlines (headings only) through an `article_outline` tool that is also exposed over MCP
        - it uses the same read tools as MCP, so it only sees what the caller may see (the caller's access scope is passed as pydantic-ai `deps`, never as tool arguments the model can see or change)
        - tools are offered only inside Code Mode's sandboxed `run_code` (never IPython Code Mode), each with a typed return model
        - a run is bounded by `max_tool_calls`, Monty resource limits and `UsageLimits`
        - [loop detection](https://pydantic.dev/docs/ai/harness/detect-loops/), a usage or spend limit ends the run and falls back to BM25, with the reason in the response
        - an [output guardrail](https://pydantic.dev/docs/ai/harness/guardrails/) rejects article IDs that are not in the pinned version or not visible to the caller.
    - Implementation: the agent uses pydantic-ai harness [Code Mode](https://pydantic.dev/docs/ai/harness/code-mode/): our read tools (`list_articles`, `article_outline`, `read_article`, `read_chunk`, `search_docs`) are exposed as functions inside one sandboxed `run_code` (Monty), so the model can walk the tree, open many outlines in parallel and filter results in code within one or two model turns. [Repo Context](https://pydantic.dev/docs/ai/harness/repo-context/) can feed the library's own `AGENTS.md` / `CLAUDE.md` files to the agent as guidance about how the docs are organized.
- **[RET-05]** As ExactDocs, I want to cache agentic retrieval results and reuse them for similar later questions, because agentic retrieval is slow and expensive and questions repeat.
    - Acceptance:
        - a question similar enough to a cached one (threshold configurable) for the same version returns the cached result with `cache_hit: true`
        - similarity uses hybrid search over past questions, or BM25 when no embedding model is configured
        - entries are invalidated when the version is re-synced.
- **[RET-06]** As a library contributor (per library) or operator (instance default), I want to set the retrieval mode (e.g. BM25 for a tiny library, agentic for a complex one), because one size does not fit every documentation set.
    - Acceptance:
        - the effective pipeline per library is shown in the UI
        - settings are validated against what is configured
        - precedence is call > library > instance.
- **[RET-07]** As an operator, I want limits on LLM usage (requests per minute, daily token budget, per-call step limit), because HyDE and agentic retrieval cost money.
    - Acceptance:
        - token or USD budgets per instance, library and user, enforced in one `retrieval_` table that works on SQLite and PostgreSQL: LLM agents (HyDE, judge, agentic) through harness [`SpendLimits`](https://pydantic.dev/docs/ai/harness/spend/) over our `BatchSpendStore`, embedding and rerank calls (which run through no agent) by retrieval's own check against the same table before each batch or call
        - LLM searches per minute per caller are limited inside retrieval (REST, HTTP MCP and stdio), not by FastMCP middleware
        - LLM token and cost metrics come from pydantic-ai's built-in `gen_ai.client.token.usage` and cost metrics
        - when a limit is reached, calls fall back to the non-LLM pipeline and say so in `retrieval_mode`
        - usage is visible in the UI and metrics.
- **[RET-08]** As a library owner, I want the repository's `AGENTS.md` / `CLAUDE.md` files to guide agentic retrieval, because they often describe how the docs are organized.
    - Acceptance:
        - the importer keeps each version's instruction files even outside the selected paths
        - they reach the agent through harness [Repo Context](https://pydantic.dev/docs/ai/harness/repo-context/) over a read-only, database-backed [workspace](https://pydantic.dev/docs/ai/core-concepts/workspace/)
        - off by default
        - delivered as user-channel notes when the agent opens a directory (nested traversal), and as system instructions only when the owner marks the library as trusted, because repo content is untrusted.
- **[RET-09]** As a maintainer, I want a retrieval eval suite built with [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) that reports recall@k, wrong-version rate, cost and latency per retrieval mode, because modes must be compared before one becomes a default.
    - Acceptance:
        - runs on the fixture libraries in CI for BM25 and, when model endpoints are provided, for the other modes
        - trace checks prove agentic runs stayed within the requested version.
