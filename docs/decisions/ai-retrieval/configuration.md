# Configuration and the no-outbound guarantee

!!! abstract "TL;DR"
    - Instance settings come from `EXACTDOCS_AI__...` variables or a TOML file named by
      `EXACTDOCS_CONFIG_FILE`. The environment wins, and a key in the file is refused.
    - Roles (`embedding`, `reranker`, `llm`, `judge`) are `<profile>:<model>`. UI-managed profiles
      keep their keys sealed by the Fernet secret box; cloud identities are configuration only.
    - Per-library overrides cover AI on or off, mode, models, rerank `top_n`, agentic limits and
      budgets, but not the embedding model. Mode precedence is call, library, instance.
    - With nothing configured no `[ai]` or `[local]` module is imported. A configured provider gets
      connections only to its base URL and identity endpoints, and tiktoken is never used.
    - The agentic answer cache is opt-in and serves only near-verbatim re-asks. Setting repo
      guidance to `trusted` is admin-only.

## Configuration

**Instance level, in the environment or a TOML file.**

- Settings gain an `ai` section, read from:
    - `EXACTDOCS_AI__...` variables (pydantic-settings, `__` as the nesting delimiter)
    - an optional TOML file named by `EXACTDOCS_CONFIG_FILE`
- The environment wins.
- The file holds no secrets: a key in it is refused. Keys come from the environment, from
  `api_key_file` (Docker and Kubernetes secrets), or from the UI.

??? example "A full `exactdocs.toml`"

    ```toml
    # exactdocs.toml (EXACTDOCS_CONFIG_FILE=/etc/exactdocs/exactdocs.toml)
    [ai.providers.corp]                     # a company gateway
    kind = "openai-compatible"
    base_url = "https://llm.example.com/v1"
    api_key_file = "/run/secrets/corp_llm_key"
    headers = { "X-Team" = "docs" }
    proxy = "http://proxy.example.com:3128"
    request_timeout = 30

    [ai.providers.vertex]
    kind = "google-vertex"
    project = "acme-ml"
    location = "europe-west4"
    credentials_file = "/run/secrets/vertex.json"

    [ai.providers.offline]
    kind = "local"                          # needs the [local] extra and `exactdocs models pull`

    [ai.embedding]
    model = "corp:text-embedding-3-small"   # <profile>:<model>, instance-wide only
    dimensions = 1024                       # optional
    batch_size = 64

    [ai.reranker]
    model = "offline:Xenova/ms-marco-MiniLM-L-6-v2"
    top_n = 32

    [ai.llm]
    model = "vertex:gemini-2.5-flash"

    [ai.judge]                              # optional, defaults to [ai.llm]
    model = "corp:gpt-4.1-mini"

    [ai.budgets]
    daily_usd = 10
    monthly_embedding_usd = 50
    per_library_daily_usd = 2
    per_user_daily_usd = 1
    llm_searches_per_minute = 30

    [ai.prices."corp:gpt-4.1-mini"]         # only for models genai-prices does not know
    input_usd_per_mtok = 0.40
    output_usd_per_mtok = 1.60
    ```

The same in the environment: `EXACTDOCS_AI__PROVIDERS__CORP__KIND=openai-compatible`,
`EXACTDOCS_AI__PROVIDERS__CORP__API_KEY=…`, `EXACTDOCS_AI__LLM__MODEL=corp:gpt-4.1-mini`.

- **Roles:** `embedding`, `reranker`, `llm`, `judge`; a role is `<profile>:<model>`. What is set
  decides which modes are available (#89), as in [Lightweight by
  default](../../user-stories.md#lightweight-by-default).
- **Profiles managed in the UI or REST** (`/api/v1/ai/providers`, admin only, #241).
    - Retrieval stores them, with their keys **sealed by the existing Fernet secret box**
      (`EXACTDOCS_SECRET_KEY`, the one that seals repository credentials).
    - A key is never returned. Without a secret key the UI refuses to store one.
    - Profiles from the environment or the file are shown read-only.
    - Retrieval declares its own small `SecretBox` port. The Fernet adapter itself **moves from
      ingestion to `bootstrap`** first (#248): otherwise retrieval (#241) and identity (#105) would
      depend on another domain's adapter module. The kernel cannot hold it (it needs
      `cryptography`).
- **The server's cloud identity is configuration only** (#241 review).
    - A profile signed with ADC, a service-account file, Entra ID or the AWS identity (Claude on
      Bedrock) is configured in the environment or the file, never over REST.
    - It takes no `base_url`: its endpoint is derived from `location` or `resource`, each a single
      DNS label. So a token of the machine's identity reaches only Google's, Azure's or AWS's
      endpoints.
    - Extra headers may not carry credentials (`Authorization`, `*-key`, `*-token`, ...): keys go
      in the key field.
- **Per-library overrides.** Retrieval stores them (#102). The library's admins and creator edit
  them, and so do operators, since library roles (E12-05). They cover:
    - AI on or off (off: nothing of the library is ever sent to a provider)
    - the retrieval mode
    - the `llm`, `judge` and `reranker` profile and model
    - rerank `top_n`
    - agentic limits
    - budgets no higher than the instance's

    **Not** the embedding model: one space per instance keeps cross-library search (E5-06)
    comparable and the storage simple.
- **Precedence** for the mode stays call, then library, then instance, then the best available.

## Offline and no-outbound guarantees

| Situation | Guarantee | Proved by |
|---|---|---|
| Nothing configured (any install) | No module of `[ai]` or `[local]` is imported, sqlite-vec is not loaded, no connection is opened except to git remotes | the model-free test, extended with a socket guard (#241) |
| `[ai]` installed, nothing configured | Same as above | same test with the extra installed |
| A provider configured | Connections only to that profile's base URL, plus its identity endpoints: for Vertex with a service-account file `oauth2.googleapis.com`, with ADC or workload identity the GCE metadata server (`metadata.google.internal` / `169.254.169.254`);<br/>for Azure with Entra ID `login.microsoftonline.com` (or the managed-identity endpoint, `169.254.169.254` / `IDENTITY_ENDPOINT`). No telemetry to any vendor (no Logfire);<br/>`genai-prices` data is the bundled copy, never updated over the network;<br/>tiktoken is never used (below) | socket-guard test allowing only the mock endpoint, with the SDKs' `*_API_KEY` / `*_BASE_URL` variables set (#241) |
| `local` roles | No connection at all;<br/>models load from their folder on disk (`specific_model_path`, `local_files_only`);<br/>only `exactdocs models pull` contacts the Hub | test with sockets blocked (#245); `-local` smoke test with `--network none` (#246) |
| A library with AI off | No chunk, query or instruction file of it reaches any provider; its searches answer BM25 | scenario in #241 and #91 |

**No tiktoken.**

- The `openai` extra installs tiktoken, which downloads its encoding files from
  `openaipublic.blob.core.windows.net` on first use (pydantic-ai's
  `OpenAIEmbeddingModel.count_tokens` calls it).
- ExactDocs never calls `count_tokens`:
    - accounting uses the `usage` the provider returns
    - `exactdocs ai estimate` estimates from characters (4 per token) and says it is an estimate
- A test asserts that tiktoken is never used: a chat role does not import it, and no encoding is
  ever loaded.[^tiktoken-import]

[^tiktoken-import]: ../pydantic-ai 2.73.0's `pydantic_ai.embeddings.openai` imports tiktoken when it
    loads, so an OpenAI-API embedding role imports the module, but never calls it. Found in #241.

**What stays on the instance.**

- **HyDE's hypothetical answers** (#94), written from user queries:
    - cached in `retrieval_hyde_answers` per manifest, model and an HMAC of the normalized query
      (keyed from the instance's secret key, never the query text)
    - deleted after `[ai.hyde] cache_ttl` (30 days), with their manifest, or once their model is no
      longer configured
- **The agentic answer cache** (#100, `retrieval_agentic_answers`):
    - It keeps agentic answers (chunk IDs, justifications, explored paths) per manifest, `llm`
      model and a fingerprint of the tag filter and agentic limits.
    - The question is kept as HMACs of it and of each term (HKDF purpose `exactdocs agentic cache
      v1`) and, with an embedding model, as its embedding.
    - Answers are deleted after `[ai.agentic_cache] ttl` (7 days), with their manifest, with the
      library's settings, or once their model or embedding model is no longer configured. All of
      them are deleted once the cache is turned off.
    - Scope:
        - `scope = "library"` (the default): a cached answer, its model-written justifications
          included, is served to every caller of the library's version. So one caller can read the
          gist of another's question.
        - `scope = "caller"` keeps each caller's answers to themselves.
    - The cache is opt-in (`enabled = false` by default, with an embedding model too). It trades
      exactness for cost, and serves only near-verbatim re-asks:
        - the same content words in the same order (only plurals folded, filler dropped, symbols
          and single-letter names kept as terms)
        - with the same numbers, versions, operators (`>=`, `~`, a trailing `+`...) and negations,
          so a swap ("replace requests with httpx" and the reverse) misses
        - an embedding only confirms such a match and never makes two questions with different
          terms match (on the default local model, siblings such as enable/disable and
          client/server score as high as paraphrases)
    - Correct answers come before hit rate. The accepted losses are:
        - re-asks in another word order ("retry configuration" for "configure retries", "E42
          error" for "error E42"): order is compared as is, never as a set, also when no relation
          word is present
        - a verb and its noun ("migration" / "migrate", "validation" / "validate")
        - synonyms ("set up" / "configure")
        - inflections other than plurals ("connecting" / "connect", "logging" / "log"): `-ing` and
          `-ed` are never folded, since "meaning" / "mean" and "hosting" / "host" are other words

**What leaves the instance when a role is set.**

| Role | Receives |
|---|---|
| **embedding** | chunk text (in background jobs) and query text |
| **reranker** and **judge** | query text and candidate chunk text |
| **llm** (HyDE, agentic) | query text and the docs the agent opens;<br/>for a library with repo guidance on (#101), the instruction files (`AGENTS.md` / `CLAUDE.md`) of the folders the agent opens (the root's in its system instructions for a `trusted` library) |

Library names, user identities and tokens are never sent.

**Repo guidance and trust (#101).**

- `trusted` puts repository text into the agent's system instructions, so who may set it matters.
- It has the gate of every other per-library AI setting (E12-05): the `admin` role on the library,
  which an API token has when its account does.
- So setting `trusted` is admin-only. For now, `notes` and `off` are admin-only too.
