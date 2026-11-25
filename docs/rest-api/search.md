# Search and answers

!!! abstract "TL;DR"
    - `PUT .../retrieval` sets a library's default search mode, AI switch, model overrides,
      reranking, budgets and `repo_guidance`.
    - A search's own `mode` always wins. Modes that need a model never fail for it: they fall back
      and say why in `fallback_reason`.
    - `GET /search` ranks the default versions of many libraries at once (`bm25`, `vector` or
      `hybrid`).
    - `POST /answer` has an agent read the chosen libraries and write a cited answer;
      `/answer/stream` is the same over server-sent events.
    - Budgets and the LLM search rate limit never fail a search; they skip the LLM step.

## Endpoints

| Method | Path | Purpose | Role |
|---|---|---|---|
| `GET` | `/libraries/{owner}/{repo}/retrieval` | a library's retrieval settings | `viewer` |
| `PUT` | `/libraries/{owner}/{repo}/retrieval` | replace them | `admin` |
| `GET` | `/libraries/{owner}/{repo}/search?mode=` | search one version | `viewer` |
| `GET` | `/search?q=` | search across libraries | readable libraries |
| `GET` | `/chunks/{chunk_id}` | one chunk | `viewer` |
| `GET` | `/answer` | whether the agentic answer can run | any caller |
| `POST` | `/answer` | agentic answer | readable libraries |
| `POST` | `/answer/stream` | the same, as server-sent events | readable libraries |

## Retrieval mode and AI overrides

`PUT /libraries/{owner}/{repo}/retrieval` (RET-06) replaces the library's settings. Every field is
optional; an omitted one takes its default.

??? example "Request"
    ```json
    {"mode": "hybrid", "ai_enabled": true, "llm": "corp:small", "judge": null, "reranker": null,
     "rerank_top_n": 16, "rerank_with": "judge",
     "budgets": {"daily_usd": 1, "monthly_tokens": 500000},
     "repo_guidance": "notes"}
    ```

### Fields

| Field | Meaning | `null` or default |
|---|---|---|
| `mode` | the mode its searches use when a call names none | `null`: see below |
| `ai_enabled` | `false` sends nothing of the library to any AI provider;<br/>its searches are BM25 | |
| `llm`, `judge`, `reranker` | `<profile>:<model>`, replacing the instance's role<br/>for this library | |
| `llm_thinking`, `judge_thinking` | `minimal`, `low`, `medium`, `high`, `xhigh` | `null`: the instance's |
| `rerank_top_n` | 1 to 200: how many of its best candidates the reranker reorders | `null`: `EXACTDOCS_AI__RERANKER__TOP_N`, 32 by default |
| `rerank_with` | `cross_encoder` or `judge` | `null`: `EXACTDOCS_AI__RERANK_WITH`,<br/>`cross_encoder` by default |
| `repo_guidance` | `off`, `notes` or `trusted` | `off` |
| `budgets` | `daily_usd`, `monthly_usd`, `daily_tokens`, `monthly_tokens` | `null`: not limited by the library |

#### `mode`

- `null`: the instance's `EXACTDOCS_AI__MODE` applies, else the best default mode configured. That
  is BM25 unless a mode the eval suite made a default can run, and none is yet.
- It must be available with the settings sent. 422 `mode_unavailable` names the model role it
  needs that is not configured, or says the vector store is unavailable: its extension cannot be
  loaded (sqlite-vec on SQLite, pgvector's `vector` on PostgreSQL). `fallback_reason` is
  `vector_store_unavailable` where a setting is skipped for that reason.

#### Model overrides

- There is no `embedding` override (one vector space per instance).
- 404 `unknown_provider` for a profile that does not exist.
- 422 `provider_unsupported` for one this installation cannot call (an extra or SDK is missing).
- 422 `invalid_model` when not written `<profile>:<model>`.
- `llm_thinking` and `judge_thinking` set how much the role's model thinks before it answers, its
  own or the instance's ([Thinking level](../search/thinking.md)). 422
  `thinking_unsupported` names the role and the model when the model is known to take no thinking
  setting.

#### `rerank_with`

- `cross_encoder`: the `reranker` role.
- `judge`: the `judge` role, else the `llm` role. An LLM rates every candidate in one call.
- The judge reranks only when chosen. Chosen without a judge configured, the cross-encoder
  reranks.

#### `repo_guidance`

What the repository's `AGENTS.md` / `CLAUDE.md` do for agentic search (RET-08):

| Value | Effect |
|---|---|
| `off` (default) | imports keep none |
| `notes` | each version keeps the root's and the selected folders' files, even outside the selected paths;<br/>a folder's file reaches the agent as an untrusted user-channel note when it opens that folder |
| `trusted` | as `notes`, and the root's file is also part of the agent's system instructions |

- 422 for any other value.
- Turning it on (`off` to `notes` / `trusted`) queues a `reprocess` job of the library (see
  `GET /libraries/{owner}/{repo}/jobs`), which re-imports every version at its commit so it keeps
  its files.
- Otherwise `notes`, `trusted` and `off` apply at the next search.

#### `budgets`

The library's own spend limits per UTC day and month.

- Each may be at most the instance's: the lowest of `[ai.budgets]`'s instance and
  `per_library_...` ceilings of that window and unit. 422 `budget_above_instance` otherwise.
- A stored budget the instance's limit was lowered below since may be sent again unchanged or
  lowered (the instance's, the tighter, applies). Only raising it is refused, so other settings
  can still be saved.
- The tighter of the library's and the instance's per-library limit applies, to its LLM steps,
  paid reranks and embedding alike.

### `GET .../retrieval`

Returns the settings with:

- `instance_mode`
- `effective_mode`: the mode a search without `mode` runs in now, with `fallback_reason` when a
  setting is skipped
- `available_modes`
- `configured_roles` of the library
- `effective_rerank_top_n`, `instance_rerank_with` and `effective_reranker` (`cross_encoder`,
  `judge`, or `null` when nothing reranks)
- its `budgets` and the `budget_ceilings` they may not exceed (`null`: no ceiling)
- its `repo_guidance`

404 for an unknown library.

## Search modes on one version

A search's own `mode` (`GET /libraries/{owner}/{repo}/search?mode=`) always wins. An unavailable
one is a 422 `mode_unavailable` as well.

### `hybrid`

- Fuses the version's 50 best BM25 chunks with its 50 nearest by vector (reciprocal rank fusion,
  `k` = 60).
- `coverage.candidates` counts the chunks of both, once each.
- The vector half always runs, so a word no chunk of the version contains still gets the
  version's nearest chunks (never another version's).
- It never fails for its model. BM25 answers instead, with `fallback_reason`:

| `fallback_reason` | When |
|---|---|
| `embedding_in_progress` | the version is not embedded with the configured model |
| `llm_budget_reached` | a budget its query embedding counts to (embedding, instance, library or user) is used up |
| `embedding_unavailable` | the model fails or times out on the query |

### `hybrid_hyde`

- Embeds the LLM's hypothetical answer to the query instead of the query. BM25 still searches the
  query.
- The answer is cached per query, version and LLM, so a repeated query calls no LLM.
- Without that answer it answers `hybrid` (or BM25, as above) with `fallback_reason`
  `llm_budget_reached`, `llm_rate_limited`, or `llm_unavailable` when the LLM fails, answers
  nothing or does not answer within 10 s.

### `vector`

`mode=vector` on one version (#428) ranks its chunks by their vectors alone, with no BM25 half,
and falls back exactly as `hybrid` does. It is never a default.

!!! info "Budgets and rate limits"
    A budget or the LLM search rate limit never fails a search. One that would run an LLM step
    answers in the best mode without one, with `fallback_reason` `llm_budget_reached` or
    `llm_rate_limited`. A paid rerank over budget is skipped (`reranked: false`,
    `fallback_reason: llm_budget_reached`).

## Search across libraries

`GET /search?q=` (#428) ranks, in one ranking, the default versions of every library the caller
may read (and the API token's library scope allows), or of the chosen ones.

| Parameter | Meaning |
|---|---|
| `library` | repeated or comma-separated, at most 50;<br/>an unknown or unreadable one is 404 `not_found` |
| `mode` | `bm25` (default), `vector` or `hybrid`;<br/>`hybrid_hyde` and `agentic` are refused |

- The vector modes need an embedding model. 422 `mode_unavailable` names the `embedding` role
  otherwise.
- Each result names its `library` and `version`, and carries `bm25_rank` and `vector_rank`
  (1-based; `null` where that ranking did not hold it).
- `vector` embeds the query once and ranks the chunks of every searched version the configured
  model has embedded, nearest first. `score` is the cosine similarity.
- `hybrid` fuses that ranking with the BM25 one (RRF, `k` = 60, 50 of each).
- A library with AI off, or whose default version is not embedded with the current model yet, is
  left out of the vector ranking and named in `libraries_without_vectors`.
- When no searched version can be ranked by vectors, or the model fails, BM25 answers with
  `retrieval_mode: bm25` and `fallback_reason` (`embedding_in_progress`, `embedding_unavailable`,
  `vector_store_unavailable`, `llm_budget_reached`).
- The query embedding counts to the embedding budget, the instance and the caller, never to a
  library.
- `libraries` counts BM25 matches per library over every readable library whatever the mode.
- Nothing is reranked (`reranked: false`).

## Agentic answer

`POST /answer` (#428) has an agent on the `llm` role read the default version of every chosen
library and write an answer.

??? example "Request"
    ```json
    {"question": "...", "libraries": ["..."], "tags": ["..."],
     "tags_match": "any", "max_sources": 8}
    ```

None chosen means every library you may read, the first 20; `libraries_omitted` counts the rest.

### The answer

| Field | Meaning |
|---|---|
| `answer` | Markdown, model output, at most 8000 characters |
| `sources` | the cited chunks, below |
| `usage` | `requests`, tokens, `tool_calls` out of `max_tool_calls`, `cost_usd` |

Each source has `library`, `version`, `commit_sha`, `chunk_id`, `article_path`, `heading_path`,
`anchor`, `source_url`, `quote` (a passage of the chunk, kept only when the chunk holds it
verbatim) and `reason` (the model's sentence).

### What it reads

- Only libraries you may read (your role and your API token's library scope) with AI on.
    - A chosen one you may not read is 404 `version_not_indexed`.
    - One with AI off is named in `libraries_without_ai` and nothing of it is sent. When none
      remains: `fallback_reason: mode_unavailable`.
- A cited chunk outside the chosen libraries, your permissions or the tags is dropped.

### Limits

- The run is bounded by `[ai.agentic]`: tool calls, model requests, tokens, time, loops.
- It is counted to the instance, the caller and every library read (the budgets), and once to the
  LLM search rate limit.
- A run that stops answers 200 with `answer: ""`, the chunks it had read as `sources`, and
  `fallback_reason` `agent_limit_reached`, `agent_loop_detected`, `agent_failed`,
  `llm_budget_reached` or `llm_rate_limited`.
- 422 `mode_unavailable` without an `llm` role.

### Availability and streaming

- `GET /answer` says whether it can run: `{"available", "reason", "max_tool_calls"}`.
- `POST /answer/stream` is the same call as server-sent events. The search playground uses it.

| Event | Data |
|---|---|
| `progress` | `{"tool_calls", "max_tool_calls"}`, after each tool call |
| `answer` | the body above, once |
| `error` | `{"error", "detail"}`, instead of `answer` |

Closing the stream cancels the run.

## Agentic search

`mode=agentic` (RET-04, never a default) lets an agent on the `llm` role browse the version and
pick the chunks that answer the question. It browses outlines, articles, chunks and BM25, all of
that version only.

### Results

- The picks the version holds and the call's tags allow, in the agent's order (`score` 1, 1/2,
  1/3...).
- Each with `justification` (the model's own sentence, untrusted text) and `explored_path` (the
  read calls up to the one that reached its article).
- Other modes return `justification: null` and `explored_path: []`.
- Both are model output: control characters are removed, a justification is at most 600
  characters, a path at most 50 calls of at most 120 characters of argument each.
- `coverage.candidates` counts the chunks the agent saw.

### Bounds

- The call's tags apply to the agent's reads too.
- The agent's reads are bound to the version and the call's tags (its `deps`, never a tool
  argument), and an output guardrail removes any pick outside them before the answer is used.

| `fallback_reason` | When |
|---|---|
| `agent_limit_reached` | a run past one of its limits (`[ai.agentic]`: tool calls, model requests, tokens,<br/>the sandbox's time, memory or host calls, its timeout) |
| `llm_budget_reached` | a budget reached during the run |
| `agent_loop_detected` | the same call (tool and arguments) made `max_repeated_calls` times (3 by default) |
| `agent_failed` | a model that fails or answers nothing usable, or a read that fails on the server |

A run that falls back is answered by the best mode without an LLM step.

### The agentic cache

A question that asks again what one answered agentically before is answered from that answer with
`cache_hit: true`. Every other search has `false`.

- "Asks again" means the same content words in the same order, numbers and negations. With an
  embedding model, its cosine confirms it at `[ai.agentic_cache] threshold`.
- The earlier question must have asked for the same version (manifest), tags, `llm` model and
  limits.
- Its chunks are checked again against the version and the tags.
- It calls no LLM and uses no budget.
- `query-docs` and the MCP tools carry `cache_hit` too.

## Reranking

With a `reranker` role (RET-02), a search's best candidates are reordered by the reranker.

- `reranked: true`, `coverage.reranked` counts them, and each reranked result's `score` is the
  reranker's.
- When `limit` is more than the top N, the reranked results come first and the rest follow in the
  mode's order with the mode's scores, which are not comparable with the reranker's.
- A reranker that times out or fails never fails the search. Results keep the mode's order with
  `reranked: false` and `fallback_reason` `reranker_timeout` or `reranker_failed`, unless the mode
  itself fell back, whose reason is kept.

### With the judge

With `rerank_with: judge` (#96), the LLM judge reorders them instead.

- Each reranked result's `score` is its rating over 10 (0 to 1).
- It rates only the best candidates that fit one bounded call: at most 64, about 32 full-size
  English or code chunks, or 9 CJK. `coverage.reranked` counts them, and the rest keep the mode's
  order after them.
- Ratings are refused (`reranker_failed`) when they name an ID it was not given (it sees `c1` to
  `cN`, never chunk IDs), or are not one score from 0 to 10 per candidate.
- A used-up budget or the LLM search rate limit skips it (`llm_budget_reached`,
  `llm_rate_limited`).
