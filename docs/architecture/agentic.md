# Agentic search

!!! abstract "TL;DR"

    - In `agentic` mode (#98) an LLM agent browses one pinned version through five read tools,
      inside harness Code Mode. The browser and tag filter are its `deps`, never a tool argument.
    - The agent's picks are looked up again in the pinned manifest, so a chunk of another version or
      a made-up ID is dropped. The wrong-version guarantee does not rest on the model.
    - Guardrails end a run on a repeated call, a host error or a limit, and the search falls back to
      BM25 or hybrid with the reason.
    - The answer cache (#100) is opt-in, stores no question text, and serves only a re-asked
      question. Repo guidance (#101) feeds `AGENTS.md` / `CLAUDE.md` to the agent when a library
      turns it on.

## The agent (#98)

`AgenticPipeline` (in `use_cases`) is registered for `agentic` when the module is given an
`Explorer`, as bootstrap always does.

1. It resolves the library's `llm` role.
2. It builds the model through `AiProviders.model_for`.
3. It runs the `Explorer` driven port in a `<search>.agent` span, within `AgentBounds.timeout`.

### What the agent reads

- The agent reads through a `VersionBrowser`, retrieval's implementation of the `DocsBrowser` port:
  `list_articles`, `article_outline`, `read_article`, `read_chunk`, `search_docs`.
- It is bound to the request's `SearchableVersion`:
    - chunks, outlines and BM25 come from its manifest;
    - articles come from the `VersionArticles` port (bootstrap's `CatalogVersionArticles`). Each
      answer names the manifest the catalog served it from, and the browser drops one from any other
      manifest.
- The browser and the call's tag filter are the caller's access scope. It is the agent's `deps`,
  never a tool argument.
- The browser applies the call's tag filter to every read.
- The browser records each call as a step, and the first step that reached each article, which
  becomes a result's `explored_path`.
- `explored_path` and `justification` go through `models.model_text` (no control characters, cut).

### Checking the answer

- The agent's picks are looked up in the pinned manifest under the tag filter, so a chunk of another
  version or a made-up ID is dropped. The wrong-version guarantee does not rest on the model.
- A run that stops raises `AgentStoppedError(reason)`. `RetrievalModes.run` answers it with
  `ModeChoice.without_llm(reason)` (BM25, or hybrid), keeping the agent's reason first:
  `agent_limit_reached`, `llm_budget_reached`, `agent_loop_detected`, `agent_failed`.

### The pydantic-ai adapter

It is split like the embedding one: `adapters/driven/ai_explorer.py` imports nothing of `[ai]` and
loads `ai_explorer_sdk.py` at the first agentic search. That module runs a pydantic-ai `Agent` with:

- the browser as `deps` (never a tool argument);
- harness `CodeMode` around the five read tools: typed `TypedDict` returns, `run_code` is the
  model's only tool, Monty limits from `AgentBounds`;
- the `SpendLimits` of `harness_spend.agent_limits` over the ledger. The budgets come from
  `AiSpend.budgets_for(ai)`, given the `LibraryAi` the search read once and carried in
  `ModeChoice.library_ai` / `PipelineRequest.library_ai`: the instance's today, the seam where a
  library's own budgets are merged;
- `UsageLimits` (`tool_calls_limit` counts `run_code` and each read call).

### Ending a run

- Code Mode hands a tripped Monty limit back to the model as a retry. `_RunEnders` (a capability
  wrapping the `run_code` call) turns it into the end of the run instead.
- A read that raises on the host is recorded by class in the agent's `deps`, and the sandbox sees
  only the fixed `READ_FAILED`, so no SQL, DSN or path reaches the model. `_RunEnders` then ends the
  run (`agent_failed`), even when the snippet caught the error.

### Guardrails (#99)

- `_RunEnders` also counts every call by tool name and a hash of its arguments (pydantic-ai-harness
  0.60.0 has no loop detection).
- The `max_repeated_calls`-th identical call (3 by default) ends the run with `agent_loop_detected`:
    - a repeated `run_code` before it runs;
    - a repeated read by raising the fixed `REPEATED_CALL` into the sandbox (so do the reads after
      it), ending the run when the snippet returns.
- A loop whose arguments change each time escapes the hash. It is bounded by Code Mode's per-snippet
  `max_tool_calls` and `UsageLimits.tool_calls_limit`, and ends with `agent_limit_reached`.
- The harness `OutputGuardrail` runs `DocsBrowser.admit` on the answer and replaces it with the
  admitted picks only. A host error in that check ends the run as `agent_failed`.
- The pipeline's own check after it stays, so the guarantee holds whatever the adapter does.

### Recording reads

- Each read is also recorded through the `AgentReads` port as an `AgentRead`: the version and
  manifest it was bound to, and those of what it served; never its argument or the text.
- Bootstrap wires the OpenTelemetry adapter (an `exactdocs.agent.read` event on the read's span)
  when telemetry is on.
- The eval suite wires its own recorder, which is where every agentic run is checked against the
  version asked for ([Retrieval evals](../evals.md)).
- The model is instrumented with `include_content=False` (the factory's, or wrapped there), so the
  agent run, its model requests and its tool calls get spans (the read calls nested in `run_code`)
  and `gen_ai.client.token.usage`, without content.

## Agentic answer cache (#100)

`AgentAnswerCaching` (in `use_cases`) answers a question asked again. It is given to
`AgenticPipeline` when the module has an `AgentAnswerCache` and a key, and
`[ai.agentic_cache] enabled` is true: the cache is opt-in.

### Settings

| Setting | Meaning |
|---|---|
| `threshold` unset | `DEFAULT_AGENT_CACHE_THRESHOLD` (0.8) with an embedding model, `DEFAULT_BM25_CACHE_THRESHOLD` (0.9) without |
| `scope = "caller"` | adds `caller_audience` (an HMAC of the account) to the fingerprint |
| `scope = "library"` | answers are served to every caller of the version |
| `ttl` | 7 days |

### The scope

Like HyDE's cache it is read once, by `RetrievalModes.within_budget`, **before** the budget and the
rate limit. `AgenticPipeline.cached_answer` resolves the library's `llm` model (nothing for a library
with AI off) and builds the search's `AgentCacheScope`:

- the manifest;
- the model;
- a SHA-256 fingerprint of the tag filter (tags sorted, `match`), every `AgentBounds` field,
  `AGENT_CACHE_FORMAT` and the similarity space (`bm25`, or the embedding role's
  `EmbeddingTarget.identity`).

A re-sync is a new manifest, so a new scope; so is another model, filter, limit or embedding model.

### Finding a hit

1. The scope's answers (`AgentAnswerCache.scoped`, at most `AGENT_CACHE_PER_SCOPE` = 200, newest
   first) are read first. With none that could serve, nothing is embedded.
2. They are compared with the question (`CachedQuestion.similarity`, below). Words find the
   candidates first; with none, nothing is embedded.
3. With some, the question is embedded to confirm them, as a query by the instance's embedding
   model. It is checked against the embedding budget and the instance's, library's and caller's
   budgets the LLM step is checked against, and recorded like a hybrid query embedding. A failure or
   a budget leaves the words to decide.
4. The LLM search rate limit is not consulted there: counting it would charge a search the cache may
   answer.
5. Only an answer asked for at least as many chunks qualifies.
6. The most similar at or above `threshold` whose picks the pinned manifest still holds under the tag
   filter is the hit, carried in `ModeChoice.agent_cache` / `PipelineRequest.agent_cache`.
   `within_budget` then skips the LLM budget and rate-limit checks.

### Similarity

`CachedQuestion.similarity` is:

| Score | When |
|---|---|
| 1 | the same normalized question |
| 0 | their `question_guards` differ, or their `question_terms` differ as sequences |
| 1, or the cosine of their embeddings when both have one | otherwise |

So an embedding only confirms a re-asked question and never bridges two questions with different
terms. On `BAAI/bge-small-en-v1.5`, opposites and siblings ("enable"/"disable", "client"/"server")
score 0.85 to 0.96, as real paraphrases do, so no threshold separates them.

??? info "`question_guards` and `question_terms` in detail"

    **Guards:** signed numbers and versions in order; words with digits such as `python3`; and the
    polarity words `not`, `no`, `never`, `without`..., with `n't`, `cannot` and the
    apostrophe-less `dont`, `cant`... read as `not`.

    **Terms:** the content words in order.

    - Filler is dropped (`how`, `do`, `I`, `want`...). Question words such as `when` and `why`,
      prepositions and conjunctions stay.
    - Only plurals are folded, with a no-fold list such as `https`, `news`, `lens`; never `-ing`,
      `-ed`, `-ation`, `-ate` or `-ment`.
    - Symbols are terms in their places (`>`, `->`, `c++`; `≥` and the like written the ASCII way;
      sentence punctuation dropped).
    - Single letters are terms (`a` and `i` only next to a symbol or a direction word).
    - Numbers stay in their places with a comparison operator right before and a `+` right after
      them (`#>=3.8`, `#3.8+`).
    - `to` is kept except as an infinitive.

    Order is compared as is, so a swap of any relation ("A with B", "A than B", "from v1 to v2")
    misses without a rule per word, and a re-ask in another word order misses too (accepted).

`AGENT_CACHE_FORMAT` is 4: rows of an earlier term format are another scope.

### Serving and storing

- `AgenticPipeline.run` turns a hit's picks into hits through the same `_answer` as a fresh run
  (looked up again in the manifest under the filter).
- It marks `PipelineAnswer.cache_hit` (`cache_hit` in `search_docs` and `query_docs`) and counts
  `exactdocs.ai.cache_hits` (`SearchTracer.cache_hit`, labels cache and mode only).
- A miss runs the agent and stores its kept picks, with justifications and explored paths, under the
  lookup's scope and question. It embeds the question then if the lookup did not (once per search).
- A cache that fails is a miss and an unwritten answer; only the error's class is logged.

### Forgetting

- `_removed` forgets the answers of removed manifests, with HyDE's.
- `SetLibraryRetrieval` and `ForgetLibrary` forget a library's (`forget_library`).
- `PruneHypotheses` (nightly and after every collection) deletes those older than
  `[ai.agentic_cache] ttl` (7 days), of an `llm` model no longer configured, or of another
  similarity space.
- The store is wired whether the cache is on or off, so a library's or a manifest's answers are
  still forgotten with the cache off, and the prune then deletes them all.

Adapters: `SqliteAgentAnswerCache` (`retrieval_agentic_answers`, SQLite and PostgreSQL),
`InMemoryAgentAnswerCache`, and `ReadOnlyAgentAnswerCache` for `serve --stdio`.

### Data at rest

- No question text is stored: an HMAC-SHA256 of the normalized question and a 64-bit HMAC of each
  term, keyed from the secret key for the HKDF purpose `exactdocs agentic cache v1`
  (`AGENT_CACHE_PURPOSE`).
- With an embedding model, the question's embedding is stored as float32. An embedding can be partly
  inverted, so the table is treated as holding the question's meaning.
- The answers are stored as returned: chunk IDs, and the model-written justifications and explored
  paths, which may quote the question's words. With `scope = "library"` they are served to every
  caller of the version.
- Without a secret key (a read-only process) or with `enabled = false` nothing is cached, and the
  nightly prune deletes what was.

## Repo guidance (#101)

A library's `LibraryAi.repo_guidance` (`off`, `notes`, `trusted`) decides what its `AGENTS.md` /
`CLAUDE.md` files do.

### At import

Ingestion asks through its `GuidancePolicy` port (bootstrap's `RetrievalGuidancePolicy`, over
`GetLibraryRetrieval`) in the import step "fetch the instruction files". With `KEEP`:

- the root's and every selected file's folder's files (`instruction_candidates`, also outside the
  selection) are read one by one through the `RepositoryFiles` port;
- `GitCli.read_files` reads the trees, then each blob capped at 32 KiB. A symlink is followed one hop
  inside the repository, else refused. An oversized file is a job problem and the others are kept;
- the files travel in `ImportedVersion.instructions` to the catalog, which keeps them per manifest
  (`catalog_manifest_instructions`, copied with a re-chunk, deleted with the manifest).

### At search

1. The `AgenticPipeline` reads the searched manifest's files through the `InstructionFiles` port
   (bootstrap's `CatalogInstructionFiles`, over `GetInstructionFiles`).
2. It bounds and defuses them (`GuidanceFiles.of`):
    - at most `MAX_GUIDANCE_FILES` / `MAX_GUIDANCE_CHARS`;
    - NFKC;
    - control and default-ignorable characters dropped;
    - every `<` / `>` and lookalike written `&lt;` / `&gt;`.
3. It passes them in `AgentRun.guidance`.

`ai_guidance_sdk.py` gives the agent harness `RepoContext` over `GuidanceBackend`, an in-memory,
read-only workspace backend holding only those files:

| Mode | Nested traversal | Walk-up autoload |
|---|---|---|
| `notes` | always: a folder's file as a user-channel note once the agent opens it | no |
| `trusted` | always | yes: the root's file in the system instructions |

`Traversals` emits the harness's filesystem events after each read tool.

### Safety

- The tools, the browser and `AgentBounds` are set before the run, so a file can change none of
  them.
- RepoContext listens to the run's events, so a run with guidance streams its model requests.
- Its model is wrapped in `UsageFloor`, which counts each side of a streamed response as at least
  `models.estimated_tokens`, so a server that reports no usage cannot switch off `UsageLimits` or
  the budgets.

### Turning it on

Turning guidance on for a library already imported is bootstrap's `SetRetrievalThenReprocess` (the
REST setting): it queues a `reprocess`, which re-imports every version at its commit.
