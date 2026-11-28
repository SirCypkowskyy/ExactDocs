# AI retrieval decisions

!!! abstract "TL;DR"
    - This record covers how embeddings, rerankers and LLMs are added on top of BM25 in the
      *Next: AI retrieval* milestone, and how sign-in for the Teams milestone will work.
    - BM25 stays the default. With nothing configured, nothing from `[ai]` or `[local]` is
      imported and nothing leaves the instance but git traffic.
    - LLM calls go through pydantic-ai provider profiles that always get explicit URLs and keys.
      Embeddings and rerankers sit behind our own ports.
    - Vectors live in sqlite-vec on SQLite and pgvector on PostgreSQL and Supabase, one table per
      embedding space, searched exactly within one manifest.
    - Token and USD budgets and rate limits degrade search to a cheaper mode and never fail it.
      Images come as base (400 MB), `-ai` (560 MB) and `-local` (950 MB, models included).

| | |
|---|---|
| **Status** | Accepted, 2026-11-07 |
| **Scope** | Milestone *Next: AI retrieval* (#89 to #104, #241 to #246); sign-in for #105 and #106 (recorded here, built in *Next: Teams & integrations*) |
| **Issue** | #240 |
| **Decided by** | The owner decided the databases, the LLM providers and the sign-in providers; the rest was proposed in #240 and is open to change in review |

This record fixes, for embeddings, rerankers and LLMs on top of BM25:

- how ExactDocs adds them
- where their vectors live
- how operators configure them
- what they cost
- what leaves the instance

Each issue of the milestone points here instead of deciding these again.

- The short form is in the [Decisions](index.md#all-decisions) table.
- The architecture of what is built today is in [Architecture](../architecture/index.md).

## Pages

| Page | What it covers |
|---|---|
| [Databases and providers](ai-retrieval/providers.md) | PostgreSQL and Supabase, pydantic-ai provider profiles, embedding and reranker ports |
| [Local models and the vector store](ai-retrieval/local-models.md) | fastembed and ONNX models, image variants, sqlite-vec and pgvector, embedding spaces |
| [Configuration and the no-outbound guarantee](ai-retrieval/configuration.md) | `EXACTDOCS_AI__...` and the TOML file, roles, per-library overrides, what may leave the instance |
| [Cost, telemetry and evaluation](ai-retrieval/cost.md) | spend recording, token and USD budgets, rate limits, telemetry, the eval gates |
| [Code layout, order of work and dependencies](ai-retrieval/delivery.md) | where the AI code lives, the waves of work, pinned dependency versions |
| [Sign-in for the Teams milestone](ai-retrieval/sign-in.md) | OIDC, OAuth2 and GitHub providers, group revalidation, Authlib and FastMCP for MCP |

## Context

- ExactDocs is a BM25 search server by default and must stay one:
    - a 384 MB image within a 400 MB budget
    - a model-free wheel and image, checked by CI (RUN-02, [Size and model-free
      budgets](../releasing/images.md#size-and-model-free-budgets))
    - no outbound connection but git
- The owner decided:
    - **Databases:** local SQLite with vector search inside SQLite, PostgreSQL with pgvector, and
      Supabase (managed PostgreSQL with pgvector).
    - **LLM providers:** a custom OpenAI-compatible API (base URL plus an optional key), OpenAI,
      OpenRouter, Anthropic, Azure OpenAI, Google Vertex AI and other popular platforms.
    - **Sign-in** (Teams): custom OIDC, OAuth, ADFS and GitHub with organization and team
      membership checks, GitHub Enterprise Server (GHE) included.
- The earlier plan named:
    - pydantic-ai and its harness
    - float32 BLOBs with numpy for SQLite vectors
    - `OpenAICompatibleProvider` for custom endpoints
    - FastMCP's rate-limit middleware
    - "no in-process models"

    Checking the current releases changed several of these (below).

## Summary

| Topic | Decision |
|---|---|
| Chat and agents | **pydantic-ai-slim 2.73.0** models and providers, one profile per endpoint, always given explicit URLs and keys (never the SDKs' environment variables);<br/>harness 0.73.0 for Code Mode, spend limits and guardrails |
| Embeddings | Our own `Embeddings` port; adapters over `pydantic_ai.Embedder` (remote) and **fastembed** (local) |
| Rerankers | Our own `Reranker` port (Cohere-compatible and TEI HTTP adapters, fastembed cross-encoder) and a separate `CandidateJudge` port for an LLM judge under the harness `SpendLimits`;<br/>a per-library setting chooses (default: cross-encoder) |
| Vector store | One `VectorIndex` port;<br/>**sqlite-vec** on SQLite, **pgvector** on PostgreSQL and Supabase;<br/>one table per embedding space, exact search scoped to the manifest |
| Databases | SQLite (default), PostgreSQL on **psycopg 3** (#103), ParadeDB for BM25 (#104), Supabase as "PostgreSQL without pg_search" (#244) |
| Packaging | `exactdocs[ai]` and `exactdocs[local]` extras; images **base** (400 MB), **-ai** (560 MB), **-local** (950 MB, models included) |
| Configuration | Named provider profiles and roles in env or a TOML file;<br/>UI-managed profiles with keys sealed by the existing secret box;<br/>per-library overrides except the embedding model |
| Offline | Nothing configured: nothing imported, nothing sent. `-local`: no network needed at all |
| Cost | Token and USD budgets per instance, library and user, daily and monthly, in one database table: harness `SpendLimits` (over a `BatchSpendStore`) for LLM agents, retrieval's own check for embeddings and rerankers;<br/>rate limits inside retrieval;<br/>a limit degrades search, never fails it |
| Telemetry | pydantic-ai's OpenTelemetry instrumentation with `include_content=False`; `gen_ai.*` metrics without library, user or query labels |
| Evals | Pydantic Evals on the fixture libraries;<br/>wrong-version rate 0 is a hard gate;<br/>BM25 gates on releases, the rest by hand and locally, not on PRs (#367);<br/>real local models in the manual eval workflow, LLMs only with test models or by hand |
| Sign-in (Teams) | Several named providers: `oidc` (ADFS included), `oauth2`, `github` (GHE base URL, org and team membership via the GitHub API) |

## Consequences

- Operators choose an image: base for BM25, `-ai` for hosted models, `-local` for air-gapped
  semantic search. The base image and `uvx exactdocs` do not grow.
- PostgreSQL and Supabase arrive before teams and roles, so a shared database exists before
  sign-in (#105) needs one.
- Three search adapters (FTS5, pg_search, PostgreSQL full-text) and two vector adapters must keep
  passing one ranking suite and one contract test.
- A model change makes hybrid answer BM25 per version until re-embedding finishes; this is
  visible (`fallback_reason`) and never mixes vectors.

## Rejected options

| Option | Why not |
|---|---|
| numpy brute force over BLOBs on SQLite (earlier decision) | sqlite-vec does the same exact search in SQL, next to the manifest join, in a 214 KB wheel; numpy is 57 MB |
| `vec0` virtual tables or an ANN index | Every query is scoped to one manifest, which a join expresses and a partition key does not;<br/>exact search is fast enough there and reproducible |
| sentence-transformers / torch for local models | Hundreds of MB, and not installable through pydantic-ai on Python 3.14 |
| Putting `[ai]` in the base image | +141 MB over a 400 MB budget that is already 96 % used, for installs that only use BM25 |
| asyncpg | About 32 MB more and a second PostgreSQL driver next to psycopg, which DBOS already needs |
| A separate `ai` domain | Every consumer is retrieval; a domain would need bridges for each call without isolating anything |
| FastMCP rate-limit middleware for LLM limits | Covers MCP only and every tool, and answers with an error instead of degrading |
| A Supabase SDK or Supabase Auth | Only the database is needed; sign-in follows the Teams decisions |

## Moved sections

These sections moved to the pages above. The old links still land here and point on.

- <a id="databases"></a>[Databases](ai-retrieval/providers.md#databases)
- <a id="provider-abstraction"></a>[Provider abstraction](ai-retrieval/providers.md#provider-abstraction)
- <a id="chat-and-agents-pydantic-ai"></a>[Chat and agents: pydantic-ai](ai-retrieval/providers.md#chat-and-agents-pydantic-ai)
- <a id="embeddings-a-small-port-with-two-kinds-of-adapter"></a>[Embeddings: a small port with two kinds of adapter](ai-retrieval/providers.md#embeddings-a-small-port-with-two-kinds-of-adapter)
- <a id="rerankers"></a>[Rerankers](ai-retrieval/providers.md#rerankers)
- <a id="local-and-offline-models"></a>[Local and offline models](ai-retrieval/local-models.md#local-and-offline-models)
- <a id="image-variants"></a>[Image variants](ai-retrieval/local-models.md#image-variants)
- <a id="vector-store"></a>[Vector store](ai-retrieval/local-models.md#vector-store)
- <a id="configuration"></a>[Configuration](ai-retrieval/configuration.md#configuration)
- <a id="offline-and-no-outbound-guarantees"></a>[Offline and no-outbound guarantees](ai-retrieval/configuration.md#offline-and-no-outbound-guarantees)
- <a id="cost-and-budgets"></a>[Cost and budgets](ai-retrieval/cost.md#cost-and-budgets)
- <a id="telemetry"></a>[Telemetry](ai-retrieval/cost.md#telemetry)
- <a id="evaluation"></a>[Evaluation](ai-retrieval/cost.md#evaluation)
- <a id="where-the-code-lives"></a>[Where the code lives](ai-retrieval/delivery.md#where-the-code-lives)
- <a id="order-of-work"></a>[Order of work](ai-retrieval/delivery.md#order-of-work)
- <a id="sign-in-for-the-teams-milestone"></a>[Sign-in for the Teams milestone](ai-retrieval/sign-in.md)
- <a id="pinned-dependencies"></a>[Pinned dependencies](ai-retrieval/delivery.md#pinned-dependencies)
