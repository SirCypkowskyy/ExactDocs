# AI providers

!!! abstract "TL;DR"
    - Every route under `/ai` is for a signed-in operator (role `admin`): anyone else gets 403
      `forbidden`, an API token 401.
    - Provider profiles come from the environment or TOML file (read-only) or from this API;
      stored keys are sealed and never returned.
    - `/ai/roles` shows the `embedding`, `reranker`, `llm` and `judge` roles and sets the
      thinking level of `llm` and `judge`.
    - `/ai/embedding` and `/ai/embedding/estimate` show embedding progress and cost;
      `/ai/usage` and `/ai/usage/history` show spend and budgets.

They show and change instance-wide settings: provider URLs and keys, spend and budgets of every
library. See [AI retrieval decisions](../decisions/ai-retrieval.md) for the kinds and what each
needs.

## Endpoints

All need an operator session, like `/users`. Library roles do not count.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ai/providers` | list provider profiles |
| `POST` | `/ai/providers` | create a profile |
| `GET` | `/ai/providers/{name}` | one profile |
| `PUT` | `/ai/providers/{name}` | create or replace a profile |
| `DELETE` | `/ai/providers/{name}` | delete a profile |
| `POST` | `/ai/providers/{name}/check` | test the profile with minimal calls |
| `GET` | `/ai/roles` | the instance roles |
| `PUT` | `/ai/roles/{role}` | set a role's thinking level |
| `GET` | `/ai/embedding/estimate` | what embedding the rest would cost |
| `GET` | `/ai/embedding` | the embedding model and its spaces |
| `GET` | `/ai/usage` | spend and budgets now |
| `GET` | `/ai/usage/history` | spend per day or month |

## Provider profiles

### `GET /ai/providers`

Every profile: the environment's and the TOML file's first (`origin: configuration`,
`read_only: true`), then those stored here (`origin: api`).

- Never a key or a header value.
- `key` says where the key comes from: `none`, `sealed`, `file`, `environment`.
- `header_names` lists the headers.
- `roles` lists the instance roles that use the profile.
- `unsupported` says what this installation lacks to call it.

### Creating and replacing

- `POST /ai/providers` (201) with `{"name": "gw", "kind": "openai-compatible", "base_url": ...,
  "api_key": ...}` creates one (409 `provider_exists`).
- `PUT /ai/providers/{name}` creates or replaces one (no `name` in the body).
- A change counts at the next call, without a restart.

Keys:

- The key is sealed with the instance's secret key and never returned.
- Without `api_key` the stored key is kept; `keep_key: false` removes it.
- If the endpoint changed (kind, platform, `base_url`, `resource`, `project`, `location`,
  `proxy`), 422 `invalid_provider` asks for the key again, so a stored key never follows a profile
  elsewhere.

| Error | When |
|---|---|
| 409 `provider_read_only` | a configured name |
| 422 `invalid_provider` | with the field at fault |
| 422 `provider_unsupported` | this installation cannot call the kind<br/>(the `[ai]` extra, boto3 for Bedrock) |
| 422 `secret_key_required` | a key when the process has no secret key |

!!! warning "Refused here, with 422 `invalid_provider`"
    - The server's own cloud identity (`credentials: "adc"`, `credentials_file`,
      `auth: "entra"`, Claude on Bedrock). It is configured in the environment or the TOML file
      only, without a `base_url`.
    - Extra `headers` that carry a credential (`Authorization`, `Cookie`, `x-api-key`, `api-key`,
      `*-key`, `*-token`, `*-secret`, `*-password`). The key goes in `api_key`.
    - A `resource`, `location` or `project` that is not one DNS label. They become part of the
      endpoint's host or path.

### Reading and deleting

- `GET /ai/providers/{name}` reads one.
- `DELETE /ai/providers/{name}` answers 204.
    - 409 `provider_in_use` while an instance role uses it.
    - A library override naming it stops counting until it exists again.

### Checking a profile

`POST /ai/providers/{name}/check`, optionally with `{"role": "embedding", "model": "e5"}`, makes
one minimal call per instance role that uses the profile, or to the model named.

Each call is reported as:

```text
{"role", "profile", "model", "status": "ok" | "error", "latency_ms", "served_model",
 "dimensions", "error"}
```

- A failed call is a check with `status: error` (its text never holds a key), not a failed
  request.
- 422 `nothing_to_check` when no role uses the profile and no model is named.

## Roles

### `GET /ai/roles`

The instance roles (`embedding`, `reranker`, `llm`, `judge`), each with:

- its `model` (`<profile>:<model>`)
- its `source`: `instance`, or `llm` for a judge that defaults to the LLM
- whether its profile exists

The `llm` and `judge` roles also have:

| Field | Meaning |
|---|---|
| `thinking` | the level their calls send; a judge that is the LLM thinks as the LLM |
| `own_thinking` | set for the role itself |
| `thinking_configured` | set in the environment or the TOML file, so read-only here |
| `thinking_unsupported` | why its model cannot take the level, which its calls then leave out |

See [Thinking level](../search.md#thinking-level).

### `PUT /ai/roles/{role}`

`{"thinking": "low"}` (`null` clears it) sets the thinking level of the `llm` or `judge` role, used
from the next call. It answers the role as `GET /ai/roles` shows it.

| Error | When |
|---|---|
| 409 `role_configured` | `EXACTDOCS_AI__<ROLE>__THINKING` sets it |
| 422 `role_takes_no_thinking` | `embedding` and `reranker` |
| 422 `thinking_unsupported` | the role's model is known to take no thinking setting<br/>(naming the role and the model) |

## Embedding

### `GET /ai/embedding/estimate`

What embedding every version not embedded yet would send and cost, before it runs
(`exactdocs ai estimate` over REST):

```text
{"model", "space_id", "versions", "chunks", "characters", "estimated_tokens",
 "usd_per_million_tokens", "estimated_usd", "note"}
```

- `characters` counts each chunk's text, heading path and article title, as embedded.
- Only active versions of libraries with AI on count, and each stored chunk once (a blob held by
  many versions is embedded once).
- Tokens are 4 characters each and the price is the bundled price list's (`null` for a model it
  does not know): an estimate, as `note` says.
- No model or tokenizer is called.
- `model` is `null` and the counts 0 when no embedding model is configured.
- 400 `vector_store_unavailable` on an instance without a vector store.
- On PostgreSQL the estimate counts from the stored chunks, with or without pgvector's extension.

### `GET /ai/embedding`

The configured embedding model and how far each embedding space has got:

```text
{"model", "spaces": [{"id", "profile_kind", "model", "dimensions", "state", "current",
  "created_at", "activated_at", "versions", "versions_embedded", "chunks", "chunks_embedded"}]}
```

- One entry per space that is not retired, oldest first.
- `current` marks the configured model's. While it is `building`, the older `active` one answers
  searches.
- `versions` counts the active versions of libraries with AI on, and `versions_embedded` those it
  has a vector for every chunk of.
- `chunks` and `chunks_embedded` count per version, so a chunk two versions share counts twice.
- `spaces` is empty without a vector store or before anything was embedded.

## Spend

### `GET /ai/usage`

What AI calls spent and what is left of each budget (`[ai.budgets]`):

```text
{"at", "llm_searches_per_minute", "scopes": [{"scope", "id", "day", "month", "budgets"}]}
```

| `scope` | `id` |
|---|---|
| `instance` | |
| `embedding` (embedding runs, instance-wide) | |
| `library` | the library ID |
| `user` | the account ID |

The instance and embedding come first, then every library and account that spent something this
month.

`day` and `month` are the current UTC windows:

```text
{"input_tokens", "output_tokens", "tokens", "local_tokens", "requests", "usd",
 "unpriced_requests"}
```

- As the providers reported. An LLM step's tokens, which the harness does not split, are input
  tokens.
- `local_tokens` are those of in-process (`local`) models, included in the input and output
  tokens.
- `tokens`, what token budgets count, leaves them out.

Each budget:

```text
{"window", "window_start", "resets_at", "usd_limit", "usd_left", "tokens_limit",
 "tokens_left", "reached", "own_usd_limit", "own_tokens_limit"}
```

- `null` for a ceiling that is not set.
- A library with budgets of its own shows the tighter of its own and the instance's per-library
  ones, with `usd_left` and `tokens_left` against it.
- Where the instance's is lower (it was lowered after the library set its own), `own_usd_limit` /
  `own_tokens_limit` give the library's own ceiling. Otherwise they are `null`.

### `GET /ai/usage/history?scope=&id=&window=&from=&to=`

What one scope spent per UTC day or month, for charts:

```text
{"scope", "id", "window", "first", "last", "entries": [{"window_start", "input_tokens",
 "output_tokens", "tokens", "local_tokens", "requests", "usd", "unpriced_requests"}]}
```

One entry per window from `first` to `last` (both included, oldest first), counted as in
`GET /ai/usage` and zero for a window with no spend.

| Parameter | Meaning |
|---|---|
| `scope`, `id` | as `GET /ai/usage` names a scope: `instance` (the default) and `embedding` take no `id`;<br/>`library` needs the library ID, `user` the account ID |
| `window` | `day` (the default) or `month` |
| `from`, `to` | UTC dates (`YYYY-MM-DD`); for months any day of a month stands for it |

- A library ID is accepted in any letter case; `id` comes back case-folded, as the ledger keeps
  it.
- `first` / `last` are the windows' first days.
- Without `to` the range ends with today's window. Without `from` it holds 30 days or 12 months up
  to `to`.
- A range ends after it starts and holds at most 366 days or 60 months. Otherwise, or for an `id`
  that does not fit the `scope`, it is 422 `invalid_spend_history`.
- Dates in the future are allowed (zero).
- Libraries and accounts that no longer exist keep their rows, so their history is still shown.
