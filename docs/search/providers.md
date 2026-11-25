# AI providers and model roles

!!! abstract "TL;DR"

    - Model endpoints are provider profiles, used by roles as `<profile>:<model>`; they need the `exactdocs[ai]` extra.
    - There are four roles: `embedding`, `reranker`, `llm` and `judge`.
    - Profiles never read `OPENAI_API_KEY` and similar variables, and extra headers carry no credentials.
    - Profiles from the environment or the file are read-only over REST.

Model endpoints are provider profiles. Each is named once, and every role uses it as
`<profile>:<model>`. Configure them in the environment or in the TOML file that
`EXACTDOCS_CONFIG_FILE` names; the environment wins, field by field. They need the `exactdocs[ai]`
extra (`uvx --from 'exactdocs[ai]' exactdocs serve`, or an `-ai` image). While no profile is
configured, none of this is imported and nothing is sent anywhere.

```toml
# EXACTDOCS_CONFIG_FILE=/etc/exactdocs/exactdocs.toml
[ai.providers.corp]                     # a company gateway speaking the OpenAI API
kind = "openai-compatible"
base_url = "https://llm.example.com/v1"
api_key_file = "/run/secrets/corp_llm_key"   # never api_key in the file
headers = { "X-Team" = "docs" }     # no credentials here: Authorization, *-key, *-token are refused
proxy = "http://proxy.example.com:3128"
request_timeout = 30

[ai.llm]
model = "corp:gpt-4.1-mini"

[ai.embedding]
model = "corp:text-embedding-3-small"   # instance-wide only
dimensions = 1024                       # optional: ask the model for shorter vectors
batch_size = 64                         # chunks per call and per durable step
```

The same in the environment: `EXACTDOCS_AI__PROVIDERS__CORP__KIND=openai-compatible`,
`EXACTDOCS_AI__PROVIDERS__CORP__API_KEY=...`, `EXACTDOCS_AI__LLM__MODEL=corp:gpt-4.1-mini`.

There are four roles: `embedding`, `reranker`, `llm` and `judge`. The `judge` defaults to the `llm`.

A profile's `proxy` carries its calls (and its Entra ID sign-in) and wins over everything else. A
profile without one connects directly, whatever `HTTPS_PROXY` says, unless
`EXACTDOCS_AI__USE_INSTANCE_PROXY=true`: then it goes through the instance's outbound proxy
unless `NO_PROXY` lists its endpoint. The instance's CA bundle (`EXACTDOCS_CA_BUNDLE`, or
`SSL_CERT_FILE`) is trusted by every profile. See
[Behind a corporate proxy](../deployment/corporate-proxy.md).

## Provider kinds

| Kind | Notes |
|---|---|
| `openai-compatible` | any gateway: a base URL and an optional key |
| `openai`, `openrouter` | |
| `anthropic` | `platform = "api"`, `"vertex"`, `"foundry"`, or `"bedrock"` (needs boto3, which the images do not include) |
| `azure` | Azure OpenAI: `base_url` or `resource`, `api_version`, and a key or `auth = "entra"` |
| `google-vertex` | `project`, `location` and `credentials_file`, or `credentials = "adc"`, or an Express-mode key |
| `google` | the Gemini API |
| `ollama`, `vllm`, `litellm` | self-hosted servers |
| `deepseek`, `together`, `fireworks`, `cerebras`, `github`, `vercel`, `moonshotai`, `heroku`, `nebius`, `ovhcloud`, `sambanova`, `alibaba` | pydantic-ai's OpenAI-API providers |
| `tei` | Text Embeddings Inference serving a reranker; the `reranker` role only |
| `local` | models in this process; see [Local models](local-models.md) |

Groq, Mistral, Cohere, xAI and Bedrock are reached through their OpenAI-compatible endpoint or
through LiteLLM.

## How profiles handle credentials

Every SDK client gets its endpoint, key (`unused` for a profile without one), project, region and
API version from the profile, and nothing else. `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
`ANTHROPIC_API_KEY`, `AZURE_OPENAI_*`, `GOOGLE_*` and similar variables are never read, and each
profile's HTTP client refuses any scheme, host or port but its own endpoint's.
`OPENAI_CUSTOM_HEADERS` and `ANTHROPIC_CUSTOM_HEADERS` are removed from the process before any SDK
client is built, because the SDKs would let them replace a profile's key.

Extra headers carry no credentials. `Authorization`, `Cookie`, `x-api-key`, `api-key` and names
ending in `-key`, `-token`, `-secret` or `-password` are refused with "use the key field", so no
credential sits unsealed in the database or the file.

The server's own cloud identity (`credentials = "adc"`, `credentials_file`, `auth = "entra"`, and
Claude on Bedrock, which signs with the AWS identity) is only used by profiles from the environment
or the TOML file, never by ones created over REST. Such a profile takes no `base_url`. Its endpoint
is derived from `location` or `resource` (Google's, Azure's or AWS's own), so the token never
reaches another host:

- `resource`, `location` and `project` must each be a single DNS label (letters, digits, inner
  hyphens). GCP's legacy domain-scoped project IDs (`example.com:project`) are therefore refused.
- A derived endpoint is built with a URL constructor and checked against the provider's exact host
  form: `<resource>.openai.azure.com`, `<resource>.services.ai.azure.com`,
  `bedrock-runtime.<region>.amazonaws.com`, or Vertex AI's `aiplatform` hosts.
- An Entra ID credential chain (client secret or certificate, workload identity, managed identity,
  user-assigned through `AZURE_CLIENT_ID`) is built once per profile. The profile's `proxy` carries
  the calls to `login.microsoftonline.com`, but never those to managed identity's local endpoint.
  Entra ID never uses the Azure CLI, PowerShell, VS Code or any developer sign-in; for local
  development, use a client secret (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`).
- Google's token refresh uses the standard proxy variables, because google-auth reads them
  itself; the server sets them from its outbound settings at start
  ([Behind a corporate proxy](../deployment/corporate-proxy.md)).

## Managing profiles

Over REST (`/api/v1/ai/providers`, admins only), profiles can be created, changed, deleted and
checked. Their keys are sealed with the secret key (`EXACTDOCS_SECRET_KEY` or `secret.key`, under a
key derivation of their own) and never returned. Profiles from the environment or the file are
read-only there. A stored key is dropped, not reused, when the profile's endpoint changes.

`exactdocs ai check`, run where the server runs, makes one minimal call per role and prints the
latency, the model that answered and an embedding's dimensions, never a key.
`POST /api/v1/ai/providers/{name}/check` does the same for one profile.

The *AI* page of the web UI (admins only) lists the providers and roles (never a key) with a check
per profile, the embedding progress of each space (`GET /api/v1/ai/embedding`), and the usage and
budgets described below.

<figure class="xd-shot" markdown>

![The AI page: a google-vertex profile named gcp, used for the embedding role with gemini-embedding-001; the embedding space at 100%, 199,071 of 199,071 chunks and 34 of 34 versions; and today's and this month's usage of the instance, the embedding runs and the first libraries, with the instance's daily and monthly budgets.](../assets/screenshots/ai-light.webp#only-light){ loading=lazy }
![The AI page: a google-vertex profile named gcp, used for the embedding role with gemini-embedding-001; the embedding space at 100%, 199,071 of 199,071 chunks and 34 of 34 versions; and today's and this month's usage of the instance, the embedding runs and the first libraries, with the instance's daily and monthly budgets.](../assets/screenshots/ai-dark.webp#only-dark){ loading=lazy }

<figcaption>The <em>AI</em> page, with Gemini embeddings on Vertex AI.</figcaption>

</figure>

## Per-library settings

`PUT /api/v1/libraries/{owner}/{repo}/retrieval` sets, for one library:

- whether AI is on. When it is off, nothing of the library is ever sent to a provider and its
  searches are BM25;
- its own `llm`, `judge` and `reranker`, and its own `rerank_top_n`;
- its own thinking levels, `llm_thinking` and `judge_thinking` (see [Thinking level](thinking.md));
- what reranks it: `rerank_with`, `cross_encoder` or `judge`;
- its own spend limits per day and month (`budgets`), no higher than the instance's;
- its `repo_guidance` (see [Repo guidance](agentic.md#repo-guidance)).

The embedding model is instance-wide only. The library's settings page (*Retrieval and AI*) shows
the pipeline its searches run now and edits all of these.
