# Retrieval eval suite

!!! abstract "TL;DR"
    - One dataset of questions, each pinned to a version, runs through every retrieval mode on the
      fixture docs repository, imported for real.
    - Per mode it reports recall@1/5/10, MRR, the wrong-version rate, p50 and p95 latency, and
      tokens and USD per question.
    - It runs on releases and locally, never on pull requests. If you change ranking, chunking,
      the search index, a mode, the dataset or the fixture, run `just eval` (and
      `uv run pytest -m eval`) before you open the pull request.
    - By default it is model-free, so only BM25 runs, and `bm25` is the only gating mode.

The fixture is imported with every heading starting a chunk (`split_level` 6, no bound), because
the dataset names its `####` sections. A new library's default since #381 would hold them inside
their parent.

## When it runs

!!! warning "On releases and locally, not on pull requests"
    CI on a pull request or a push to `develop` or `main` runs no eval step, and `uv run pytest`
    skips the suite's end-to-end tests. So a ranking regression is caught when a release is cut,
    not on the pull request that caused it.

    **If you change ranking, chunking, the search index, a retrieval mode, the dataset or the
    fixture, run `just eval` (and `uv run pytest -m eval`) before you open the pull request**, and
    say in it that you did.

- The release workflow (`.github/workflows/release.yml`, job *Retrieval eval*) runs all of it
  before anything is published. A failing gate stops the release (see [Tiers](#tiers)).
- The suite's pytest tests that import the fixture and run the suite end to end carry the marker
  `eval`, which `addopts` deselects (`-m "not eval"` in `pyproject.toml`).
    - The quick ones (the dataset, fingerprints, evaluators and gates on stand-in retrievers) stay
      in the default run.
    - `uv run pytest -m eval` (or `just test -m eval`) runs the marked ones.
    - A new test that imports the fixture and searches it gets `@pytest.mark.eval`.
- The behave scenarios in `retrieval_eval.feature` take a few seconds and stay in the default run.

## Running it

```bash
just eval                       # every mode; those that cannot run are listed with the reason
just eval --modes bm25          # one mode
just eval --report out.json     # JSON report elsewhere (default: reports/evals/retrieval.json)
just eval --baseline develop.json --ratchet --reference-dataset develop.yaml   # a branch against develop's baseline
just eval --configured-models --local-roles embedding,reranker   # local models from EXACTDOCS_AI__...
                                # (after `exactdocs models pull`; see the release's eval job)
just eval --offline-embedding --ratchet   # hybrid on an in-process term-hash embedding (no model): what the release runs
just eval --help
```

What a run does:

1. Builds the fixture repository in a temporary directory.
2. Imports `v1.3.0`, `v1.4.0` and `next` with the real importer.
3. Asks `search_docs` for the top 10 of every question in each mode, and reads every returned
   chunk back with `read_chunk`.
4. Prints a Markdown summary, appends it to `$GITHUB_STEP_SUMMARY` when that is set, and writes
   the JSON report.

| Exit code | When |
|---|---|
| 0 | every gate passed |
| 1 | a gate failed |
| 2 | a usage error, such as a `--baseline` or `--reference-dataset` path that does not exist |

A case whose version or expected section the fixture does not have fails the suite too, rather
than counting as a miss.

### Models

- By default the run is **model-free**: the app is built with no model role, whatever
  `EXACTDOCS_AI__...` configures, so only BM25 runs.
- `--configured-models` uses the configured models instead. Before the questions, every version
  is embedded the way the `embed` jobs would, when the embedding role may be called
  (`--local-roles embedding` or `--allow-providers`).
- Tokens and USD per question are what the spend ledger grew by during each search, so hybrid's
  include its query's embedding.

### The offline embedding

`--offline-embedding` runs `hybrid` without any model. The embedding role is an in-process
stand-in that hashes each term of a text into one dimension (`HashEmbeddingModels(by_terms=True)`,
see `tests/fixtures/offline_embedding.py`).

- Texts sharing terms are near, so the run checks the fusion and the wrong-version gate of
  hybrid, end to end.
- It finds no paraphrase a real model would, so its recall says nothing about whether hybrid
  should be a default.
    - The report gives hybrid's `eligible_as_default` as `null` with
      `not_judged: "offline embedding"`, and the summary says so.
    - The flag refuses `--write-baseline` and `--configured-models`.

`uv run pytest -m eval` runs the same BM25 run (`tests/evals/`), so a ranking change that breaks
a gate also fails those tests.

## The dataset

`packages/exactdocs/evals/retrieval_eval/dataset.yaml`, in Pydantic Evals' YAML format. Each case
is a question pinned to one version, and the section that answers it:

```yaml
- name: 'v1.4.0: Which failures does the client repeat by default?'
  inputs: {query: Which failures does the client repeat by default?, version: v1.4.0}
  metadata: {kind: question}
  expected_output:
    hits:
    - version: v1.4.0
      article: docs/guide/resilience.md
      heading_path: [Resilience, Retry policy, retry_policy]
```

| Case | What it is |
|---|---|
| `kind: identifier` | the fixture's [`expected-queries.yaml`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/tests/fixtures/docs-repo/expected-queries.yaml), one case per asserted version, tag filters included |
| `kind: question` | a natural-language question, the way an agent asks, often in words the section does not use |
| `hits: []` | the version has no answer (`retry_policy` in `v1.3.0`) |

- A test keeps the `identifier` cases and `expected-queries.yaml` in step: a query added to the
  ranking table must be added here too.
- A `question` case can be worded far from its section: "replace an API key without downtime"
  for *Rotating tokens*.
- A `hits: []` case counts for the wrong-version rate only: whatever a mode returns for it must
  still be of that version.

To add a case:

1. Add it to the YAML. A test checks that its section exists in that version.
2. If the content it needs is missing, extend the fixture as its README says.
3. Rewrite the baseline ([Changing the dataset](gates.md#changing-the-dataset)).

## Metrics

| Metric | Over | Meaning |
|---|---|---|
| recall@1, recall@5, recall@10 | questions whose version has an answer | the expected section is in the first k results |
| MRR | the same | mean of 1 / its rank (0 when it is not in the top 10) |
| wrong-version rate | every question | share of questions with at least one result of another version |
| p50 / p95 latency | every question | time of the search alone (not the reads below), one question at a time |
| tokens / USD per question | every question | what the models cost, read from the spend ledger around each search; 0 for BM25 |

### The version of a result

The version of a result is the version **of its chunk**, not the version the answer names.

- Every returned chunk ID is read back with `read_chunk`, which serves it from the version the ID
  was issued for (chunk IDs hash their version).
- Its version and commit are compared with the question's.
- So a search that lets another version's chunk through fails the suite even when it labels that
  chunk with the version asked for.

!!! note
    Today `search_docs` already drops a pipeline's hit of another version, since it loads chunks
    from the asked version's manifest only. The eval is the check that this stays true for every
    mode and adapter.

### Agentic traces

Agentic runs are also checked from their traces (#99), and only here.

- The suite hands the app a recorder of the agentic explorer's reads
  (`Container.build(agent_reads=...)`; every `run_on_fixture` builder takes it).
- Each answer carries its run's trace: for every read the agent made, the version and manifest it
  was bound to and those of what it returned to the agent (never its arguments or the text).
- `StayedInVersion` asserts `stayed_in_version` for each case. These fail it:
    - a read bound to another version;
    - a read that served something of another version or manifest;
    - reads bound to more than one manifest;
    - an `agentic` answer with results but no trace.
- This checks what the agent was shown on the way, where the wrong-version rate checks what it
  returned.
- The report counts `traced_runs` and lists the failing cases in `left_version_cases`. Any of them
  fails the suite, and a mode with one is never `eligible_as_default`.

### What else the report lists

Per mode, the JSON report also lists:

- the cases with a wrong version, and the offending results;
- the questions whose section was not in the top 10;
- the questions that raised;
- how many a cheaper mode answered (`fallbacks`);
- how many a reranker reordered (`reranked`);
- with a reranker role configured, how many came back with results but not reranked
  (`rerank_fallbacks`: the reranker failed or timed out, whatever `fallback_reason` shows).

The Markdown summary repeats the last two for a mode that was reranked.

### Evaluating the reranker

Reranking is a flag on top of every mode, so a run with a `reranker` role configured measures each
mode reranked. Compare two runs on the same dataset, one without the role and one with it:

| Reranker | Flag | Example |
|---|---|---|
| hosted | `--allow-providers` | `EXACTDOCS_AI__RERANKER__MODEL=cohere:rerank-v3.5 just eval --configured-models --modes bm25 --allow-providers` |
| on this machine (such as TEI on localhost) | `--local-roles reranker` | the same command with `--local-roles reranker` |

- Without either flag the reranked modes are `skipped`, and no request leaves the machine.
- Check `rerank_fallbacks` is 0: a reranker that timed out was not measured.

### Evaluating the LLM judge

The judge (#96) reranks like the cross-encoder, so it is measured the same way: a run with
`EXACTDOCS_AI__RERANK_WITH=judge` and a `judge` (or `llm`) role measures each mode reranked by it.

```bash
EXACTDOCS_AI__JUDGE__MODEL=corp:gpt-4.1-mini EXACTDOCS_AI__RERANK_WITH=judge just eval \
  --configured-models --modes bm25 --allow-providers
```

- Each mode's outcome says what reranked it (`reranker`: `cross_encoder` or `judge`).
- The judge's tokens and USD reach `tokens_per_question` / `usd_per_question`.
- Compare with a run reranked by the cross-encoder (or none) on the same dataset.
- Check `rerank_fallbacks` is 0: a refused or timed-out judgment keeps the mode's order and was
  not measured.
- A hosted judge is `skipped` without `--allow-providers` (or `--local-roles judge` for one on
  this machine, such as Ollama).

Where a judge runs:

- **At every release, on a stand-in only** (`tests/evals/`, `offline_judge_container`, marked
  `eval`; also run by `uv run pytest -m eval`). The stand-in is a pydantic-ai `FunctionModel` that
  rates candidates by the query words they share, priced. It checks the plumbing, the
  wrong-version rate of 0 and the cost per question without a provider. Its recall says nothing
  about a real judge.
- **A real one** runs in the manual *Retrieval eval (real providers)* workflow, with
  `EVAL_JUDGE_MODEL` and `EVAL_RERANK_WITH=judge`.

## Tiers

| Tier | Modes | Where they run for real |
|---|---|---|
| release (gating) | `bm25` | the release's *Retrieval eval* job, before anything is published; no model |
| local (report-only) | `hybrid`, with rerank when a reranker is configured | at every release: on the term-hash stand-in, then on the default local models |
| provider | `hybrid_hyde`, `agentic`, any mode reranked by the LLM judge | in tests on stand-in models; with a real provider only by hand |

### Release (gating)

- Step *Retrieval eval (BM25 gating, hybrid on term-hash)* runs on SQLite.
- Step *Retrieval eval on pg_search (BM25, gating)* runs on ParadeDB's BM25 (#104), with
  `--expect-engine pg_search`, so a fallback to PostgreSQL full-text search fails it.
- Both gate against the tagged tree's `baseline.json`.
- The suite runs on the database `EXACTDOCS_DATABASE_URL` names. To run it on PostgreSQL by hand:

  ```bash
  EXACTDOCS_DATABASE_URL=postgresql+psycopg://.../<empty database> EXACTDOCS_SECRET_KEY=... just eval
  ```

### Local (report-only)

- At every release, in the SQLite step, on the term-hash stand-in (`--offline-embedding`). Its
  wrong-version rate must be 0; its recall is not a measure of hybrid.
- With real models: the last steps of the same job (#245), with the `[local]` extra and the
  default models cached between releases, no secret.
    - `bm25` and `hybrid` on `BAAI/bge-small-en-v1.5`;
    - then both reranked by `Xenova/ms-marco-MiniLM-L-6-v2`, with the reranker timeout raised to
      30 s so every rerank is measured;
    - compared with the tagged tree's baseline.
- These steps never stop a release (`continue-on-error`). Their summary marks `default-eligible`.

### Provider

In tests, with pydantic-ai's `TestModel` / `FunctionModel`:

- `hybrid_hyde`: `tests/evals/`, `run_on_fixture` with `offline_hyde_container`, the term-hash
  embedding and a priced stand-in LLM, `llm` in `local_roles`. Its wrong-version rate must be 0,
  and its tokens and USD reach `tokens_per_question` / `usd_per_question`.
- `agentic`: `test_agentic_is_evaluated_on_a_scripted_model_and_stays_in_the_version` runs the
  whole suite through the real pipeline, Code Mode and limits on a scripted `FunctionModel`, in
  the release's *Retrieval eval* job (`pytest -m eval`). It fails on any wrong-version answer or
  any read outside the version in a run's trace.

With a real provider, only by hand:

- `just eval --configured-models --allow-providers`;
- or the manual *Retrieval eval (real providers)* workflow (`.github/workflows/eval-providers.yml`,
  `workflow_dispatch` only). It configures profile `eval` from the repository variables
  `EVAL_PROVIDER_KIND`, `EVAL_PROVIDER_BASE_URL`, `EVAL_PROVIDER_API_VERSION` and
  `EVAL_<ROLE>_MODEL`, and the secret `EVAL_PROVIDER_API_KEY`.

### Which modes may run

- A mode whose model role is not configured is reported as `unavailable`, with the role it lacks.
- Whether a configured mode may run is decided **per model role**, not per tier. Every role its
  search calls (its own, and the reranker when one is configured) must be listed in
  `--local-roles`, the roles whose model runs on this machine. Otherwise the mode is `skipped`
  unless `--allow-providers` is given.
- So a `hybrid` run on a hosted embedding model is skipped like `agentic` is.
- No CI or release run calls a hosted model, and none needs a secret to pass.[^profiles]

[^profiles]: Provider profiles exist now (#241). Deriving `--local-roles` from a role's profile
    kind is a follow-up.

## Adding a mode

The suite asks for a mode through the same `search_docs` an agent uses (`mode=<name>`), so a new
mode needs no change to the cases or the evaluators:

1. Give it a tier in `MODES` (`retrieval_eval/suite.py`); a test fails until every
   `RetrievalMode` has one.
2. If it reports spend, fill `tokens` and `usd` of the answer in `SearchDocsRetriever`.
3. Run `just eval` with the mode configured, then `--write-baseline` once its numbers are agreed.
