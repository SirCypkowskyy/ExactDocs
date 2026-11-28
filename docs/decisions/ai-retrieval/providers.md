# Databases and providers

!!! abstract "TL;DR"
    - SQLite stays the default. PostgreSQL (#103) uses psycopg 3 async, and DBOS keeps its system
      tables in the same database under `dbos_system_schema`.
    - BM25 on PostgreSQL is ParadeDB `pg_search`. Supabase (#244) falls back to PostgreSQL
      full-text search, and its transaction-mode pooler is refused at start.
    - Every LLM call is a pydantic-ai `Agent` on a model built from a provider profile with a
      `kind`. The factory passes explicit values only, never the SDKs' environment variables.
    - A profile uses the instance's proxy only with `ai.use_instance_proxy`, off by default.
    - Retrieval declares its own `Embeddings` and `Reranker` ports. The cross-encoder is the
      default reranker; the LLM judge is a separate `CandidateJudge` port.

## Databases

- **SQLite** stays the default: one file in the data directory, vectors in it too (one backup).
- **PostgreSQL** (#103) moves into this milestone.
    - Driver: **psycopg 3** async (`postgresql+psycopg://`). It is already in the image as a DBOS
      dependency, so it costs nothing; asyncpg would add about 32 MB and a second driver.
    - DBOS keeps its system tables in the **same database**: bootstrap sets
      `DBOSConfig.system_database_url` to the app's PostgreSQL URL and `dbos_system_schema`
      (default `dbos`) to a schema of their own. That is what makes several server processes
      safe.[^dbos-system-db]
- **BM25 on PostgreSQL** is ParadeDB `pg_search` (#104), as decided before. The CI image
  (`paradedb/paradedb`) also bundles pgvector.
- **Supabase** (#244) is supported as a PostgreSQL database, nothing more: no Supabase SDK, Auth or
  Storage.
    - It has pgvector (in the `extensions` schema) but not `pg_search`. Whenever `pg_search` is
      missing, a third adapter of the search port uses PostgreSQL full-text search: `tsvector`
      with the `simple` configuration on the same identifier-expanded column, ranked with
      `ts_rank_cd`.
    - It is not true BM25: the shared ranking suite runs on it and lists any expected-order
      difference.
    - Connections need `sslmode=require` and a session, through one of:
        - a direct connection (IPv6 only on most Supabase plans, unless the IPv4 add-on is bought)
        - the pooler in session mode on port 5432
    - The transaction-mode pooler breaks prepared statements and DBOS's `LISTEN` connection, so
      it is refused at start.
    - \#244's CI runs DBOS on `supabase/postgres` with `dbos_system_schema`.

[^dbos-system-db]: ../DBOS 3.3's default system database is a local SQLite file, today's
    `jobs.sqlite`. Given a PostgreSQL system database that does not exist, it connects to the
    `postgres` database and runs `CREATE DATABASE`, which managed services such as Supabase usually
    forbid. Pointing it at the existing app database avoids that. DBOS still first connects to
    `postgres` to check that the database exists and only logs a warning when it may not; #103 and
    \#244 verify this with a role that cannot create databases.

## Provider abstraction

### Chat and agents: pydantic-ai

Every LLM call (HyDE #94, judge #96, agentic #98) is a pydantic-ai `Agent` on a model built from a
**provider profile** (#241).

- pydantic-ai already speaks every API the owner listed and handles retries, usage, cost (bundled
  `genai-prices` data) and OpenTelemetry.
- The harness adds Code Mode, `SpendLimits` and guardrails.

A profile has a `kind`:

| Profile `kind` | pydantic-ai provider | Chat model class | Embeddings | SDK in `[ai]` |
|---|---|---|---|---|
| `openai-compatible` (custom: base URL, optional key) | `OpenAIProvider(base_url=…, api_key=…)` | `OpenAIChatModel` | `OpenAIEmbeddingModel` | `openai` |
| `openai` | `OpenAIProvider` | `OpenAIResponsesModel` | `OpenAIEmbeddingModel` | `openai` |
| `openrouter` | `OpenRouterProvider` | `OpenRouterModel` | `OpenAIEmbeddingModel` on the same provider | `openai` |
| `anthropic` | `AnthropicProvider`, with a `platform`[^anthropic-platform] | `AnthropicModel` | none: Anthropic has no embedding API | `anthropic` (Vertex auth through `google-auth`, already there via google-genai) |
| `azure` (Azure OpenAI) | `AzureProvider(azure_endpoint, api_version, api_key)`, or Entra ID with `auth = "entra"`[^azure-entra] | `OpenAIChatModel` | `OpenAIEmbeddingModel` | `openai`, `azure-identity` (about 5 MB) |
| `google-vertex` (Vertex AI) | `GoogleCloudProvider(project, location, credentials)`: a service-account file, workload identity / ADC, or an Express-mode key | `GoogleModel` | `GoogleEmbeddingModel` | `google-genai` |
| `google` (Gemini API) | `GoogleProvider(api_key)` | `GoogleModel` | `GoogleEmbeddingModel` | `google-genai` |
| `ollama`, `vllm` | `OllamaProvider(base_url)`, `VLLMProvider(base_url)` | `OllamaModel` (a subclass of `OpenAIChatModel`), `OpenAIChatModel` | `OpenAIEmbeddingModel` | `openai` |
| `litellm` (gateway) | `LiteLLMProvider` | `OpenAIChatModel` | `OpenAIEmbeddingModel` | `openai` |
| `deepseek`, `together`, `fireworks`, `cerebras`, `github` (Models), `vercel`, `moonshotai`, `heroku`, `nebius`, `ovhcloud`, `sambanova`, `alibaba` | pydantic-ai's provider of that name | `OpenAIChatModel` (`CerebrasModel` for `cerebras`, also a subclass) | where the platform has them | `openai` |
| `bedrock`, `groq`, `mistral`, `cohere`, `xai`, `huggingface` | pydantic-ai's provider of that name | its own model class | per platform | **not included**: each needs its own SDK |
| `local` | none | none (use `ollama` for a local LLM) | fastembed (#245) | `[local]` extra |

[^anthropic-platform]: ../`platform` is one of:

    - `"api"`: the default, with an optional `base_url` for gateways
    - `"vertex"`: Claude on Vertex AI, `anthropic_client=AsyncAnthropicVertex(project_id=…, region=…, base_url=…, credentials=…)`
    - `"foundry"`: Claude on Azure AI Foundry, `AsyncAnthropicFoundry(base_url=… or resource=…, api_key=… or azure_ad_token_provider=…)`
    - `"bedrock"`: `AsyncAnthropicBedrock`, needs boto3: not in the images

[^azure-entra]: ../With `auth = "entra"` (no key):

    - The provider is `AzureProvider(openai_client=AsyncAzureOpenAI(azure_endpoint=…, api_version=…, azure_ad_token_provider=…))` with the **sync** `azure.identity.get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")` (managed identity, workload identity or a client secret).
    - The sync credential blocks only when the cached token is refreshed, about once an hour. `azure.identity.aio` would need `azure-core[aio]` and so aiohttp, which is not in the lock or the budget.
    - The model name is the deployment.

- **Explicit values only, never the SDKs' environment.**
    - The provider factory always passes explicit values:
        - to every provider, a `base_url` and `api_key` (or a client built with them), with the
          fixed placeholder `"unused"` for a keyless profile
        - to Vertex: project, location and credentials
        - to `AsyncAnthropicVertex`: `base_url`, `region` and `project_id`
        - to `AsyncAnthropicFoundry`: `base_url` (or `resource`)
        - to `AsyncAzureOpenAI`: `azure_endpoint` and `api_version`
    - It never builds a model from a `"<provider>:<model>"` string (which infers the provider from
      the environment).
    - Otherwise the SDKs fall back to `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_API_VERSION`,
      `ANTHROPIC_API_KEY`, `ANTHROPIC_VERTEX_BASE_URL`, `ANTHROPIC_VERTEX_PROJECT_ID`,
      `CLOUD_ML_REGION`, `ANTHROPIC_FOUNDRY_BASE_URL`, `ANTHROPIC_FOUNDRY_RESOURCE`,
      `ANTHROPIC_FOUNDRY_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`,
      `OPENROUTER_API_KEY`, `OLLAMA_BASE_URL`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`,
      `GOOGLE_APPLICATION_CREDENTIALS` and the like. Then a keyless custom gateway would receive
      the host's OpenAI key, and every `*_BASE_URL` / `*_ENDPOINT` would redirect traffic.
    - ADC for Vertex is used only when the profile says `credentials = "adc"`.
    - \#241's socket-guard test runs with those variables set and proves none of them is used.
- **Custom endpoints** use `OpenAIProvider(base_url=…, api_key=…)` with `OpenAIChatModel` (Chat
  Completions, the most widely implemented API). pydantic-ai's `OpenAICompatibleProvider`,
  named in the first plan, was an internal base class in 2.60.0, not an entry point (2.73.0
  makes it a public provider; the custom kind stays on `OpenAIProvider`).
- **Platforms whose SDK is not included** (Bedrock, for Claude too, pulls boto3; the others their
  own clients). The images do not include them. They are reached in one of three ways:
    - through their OpenAI-compatible endpoint, as `openai-compatible`
    - through a LiteLLM gateway
    - with `uvx`, by adding the SDK: `uvx --from 'exactdocs[ai]' --with
      'pydantic-ai-slim[bedrock]==2.73.0' exactdocs serve`
- **One HTTP client per profile** on `httpx2` (what pydantic-ai 2.73.0 uses), with:
    - the proxy on the transport (a retrying transport stops httpx reading `HTTPS_PROXY`)
    - extra headers (values masked in logs)
    - exactly one retry layer
    - an overall `request_timeout`
- **The instance's proxy is opt-in for profiles (#538).**
    - The client never reads the proxy variables itself. It gets the profile's `proxy`. Failing
      that, with `ai.use_instance_proxy` (`EXACTDOCS_AI__USE_INSTANCE_PROXY`, off by default), it
      gets the instance's outbound proxy, unless `NO_PROXY` lists the endpoint.
    - It is off by default for two reasons:
        - An ambient variable must not reroute a profile's traffic (the hostile-environment test
          sets `HTTPS_PROXY` to a trap).
        - Take an instance that set `HTTPS_PROXY` for git, with an internal gateway missing from
          `NO_PROXY`. After an upgrade it would send that gateway's calls (its key, over plain
          `http://` too) to the proxy.
    - The instance's CA bundle applies to every profile: it adds no route, only trust.

### Embeddings: a small port with two kinds of adapter

pydantic-ai 2.73.0 has `Embedder` with OpenAI (and every OpenAI-compatible provider), Cohere,
Bedrock, Google/Vertex, Voyage and sentence-transformers models. Two limits apply:

- On Python 3.14 the Voyage and sentence-transformers extras are not installable (their
  requirements stop at 3.13).
- Our code never subclasses third-party bases (the only inheritance in the codebase is
  exceptions), so a local model cannot be added as an `EmbeddingModel` subclass.

Hence retrieval declares its own **`Embeddings` driven port** (embed documents, embed a query,
model identity, dimensions), with:

- an adapter over `pydantic_ai.Embedder` for every remote kind above that has embeddings; it
  batches inputs itself (`batch_size`) and sets `EmbeddingSettings(dimensions=…)` when the model
  supports shortening;
- a fastembed adapter for `local` (#245).

### Rerankers

pydantic-ai has no rerank API.

- Retrieval declares a **`Reranker` driven port** (query and candidates in, scores out) with two
  kinds of adapter:
    - HTTP, in the Cohere-compatible `/v2/rerank` dialect (Cohere, Jina, Voyage, vLLM, LiteLLM,
      Azure AI Foundry) or the TEI `/rerank` dialect (#93)
    - fastembed's `TextCrossEncoder` (#245)
- The LLM **judge** on any chat profile (#96) is a port of its own, **`CandidateJudge`**.
    - It is an LLM step, so it takes the `LlmStep` (the caller and the library-merged budgets) and
      runs as a pydantic-ai agent under the harness `SpendLimits`. A plain `Reranker` call never
      does.
    - It rates the best candidates that fit one bounded call by positional IDs (`c1`...).
    - Its answer is validated so it can only reorder them.
- A per-library `rerank_with` (else `EXACTDOCS_AI__RERANK_WITH`) chooses between the two. The
  cross-encoder is cheaper and is the default.
