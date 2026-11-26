# Retrieval benchmark runs

!!! abstract "TL;DR"
    - `retrieval.json` records everything needed to recompute a result: the corpus commits, the
      environment, the models and settings, and every case's outcome.
    - The recorded run (24 November 2026, 3 h 22 min on a 4-CPU aarch64 runner) covers BM25 and
      the local models on a subset of the matrix. No hosted configuration has run yet.
    - `search_docs` groups its results by article since #575, so BM25 at every chunking and hybrid
      on bge-small at `default` were run again on 25 November and replace their recorded results.
    - BM25 scores recall@5 92.5% at `h2`, 91.4% at `merge-400`, 91.0% at `default` and 89.9% at
      `h6`. `h2`'s lead is not significant (p 0.27), so the shipped default stays `default`.
    - Hybrid on bge-small at `default` reaches 92.5%, under the 5-point margin and not
      significant, so BM25 stays the default for the local budget too.
    - The manual *Eval* workflow runs BM25 at `default` with `--check`. The local and hosted parts
      never run in CI.

## Reproducing a result

`retrieval.json` (`schema_version` 1, read by #349) records, besides the metrics:

| Field | What it holds |
|---|---|
| `golden`, `cases`, `projects` | the golden set's fingerprint, its cases and projects |
| `corpus` | every pinned version as `project`, `version`, `commit` |
| `environment` | the ExactDocs commit (`-dirty` with uncommitted changes), Python, platform, CPU count, and the versions of `exactdocs`, `fastembed`, `onnxruntime`, `pydantic-ai-slim` and `pydantic-evals` |
| `chunkings` | each chunking configuration's name and library settings |
| `results` | one entry per result ([below](#per-result)) |
| `recommendations` | per `budget`: the `configuration`, `chunking`, `usd_per_1000_questions`, the `reasons` and the recall@5 `test` against the cheaper default |
| `statistics` | how the intervals and tests were computed: `seed`, `resamples`, `confidence`, `alpha` and the methods |

### Per result

??? info "Fields of each entry in `results`"
    - `configuration`, `chunking`, `budget`, `mode`, `rerank`, `status` and `reason`;
    - `models`: each role's `<profile>:<model>`, the profile's `kind` and `base_url`, and for a
      local model the Hub `revision` it was pulled at and its `dimensions`;
    - `settings`: the `ai` settings it ran with (the roles, `rerank_with`, the reranker's `top_n`
      and timeout, the judge's timeout, HyDE and agentic limits; never a key);
    - `metrics`, `by_kind`, `by_project`, each with its `intervals`;
    - `index`, `fallbacks`, `reranked`, `rerank_fallbacks`, `misses`, `errors`,
      `wrong_version_cases`, `left_version_cases`;
    - `rows`: every case's outcome by case name (its kind, project, rank, nDCG, section ranks,
      wrong version, empty, search time, tokens and USD, and since #575 `context_tokens`,
      `tokens_to_hit` and, scored from text, `cut_hits`), from which the metrics, intervals and
      tests can be recomputed;
    - `rows_from`: set when the rows come from a later run than the metrics;
    - `recorded_by`: set when a later run replaced the whole result (#575): that run's ExactDocs
      commit, platform, CPU count and date;
    - `versus_default`: the paired tests against its budget's default.

The recorded run is `packages/exactdocs/evals/results/retrieval.json` and `retrieval.md`.
`schema_version` changes when a field is renamed or removed. #489 only added fields, so it is
still 1, and a report without them still reads.

## The recorded run

| Run | |
|---|---|
| Recorded | 24 November 2026, for #503 and #501 |
| Golden set | with its alternatives marked (`sha256:a00997851150e3b0`) |
| Workflow | the manual *Retrieval eval (real providers)*, `benchmark` ticked, local configurations only ([run 45353553786](https://github.com/SirCypkowskyy/ExactDocs/actions/runs/45353553786)) |
| Machine | one self-hosted runner VM, Linux aarch64, 4 CPUs |
| ExactDocs | `8e789e6` |
| Time | 3 h 22 min |

A full local matrix (three embedding models, each with and without the cross-encoder, at four
chunkings) would take far longer there, so it ran on this subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking configuration;
- `bm25+ce` at `default`, `h6` and `h2`;
- `hybrid:bge-small-en-v1.5+ce` at `default` and `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6` (the second local embedding model);
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking);
- every hosted configuration is listed as skipped: it needs a real-providers run.

```bash
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-bench --offline \
  --configs 'bm25,hybrid:bge-small-en-v1.5,bm25+ce@h6,bm25+ce@h2,bm25+ce@default,hybrid:bge-small-en-v1.5+ce@h6,hybrid:bge-small-en-v1.5+ce@default,hybrid:snowflake-arctic-embed-s@h6' \
  --out packages/exactdocs/evals/results
```

Every result keeps its per-case `rows`, so every one has intervals and a paired test against its
budget's default (#489).

The run kept no context per case (#575). BM25 is deterministic, so its rows at every chunking were
completed from a re-run of 25 November (Linux x86_64, 4 CPUs) that gave every case the same rank,
nDCG and section ranks; `rows_from` names it, and the recorded latencies are kept. BM25 has recall
within each token budget; the other results were not run again and have none. Hybrid search on
bge-small at `default`, asked again on that machine, came back with 5 of the 321 cases at another
rank (the vectors differ in their last digits between the two machines; recall@1, @5, @10, MRR and
nDCG@10 are the same to the digit), so its rows were not replaced: that re-run is the grid's app
cell `hybrid:bge-small-en-v1.5@default` ([Retrieval results](../benchmark/retrieval/index.md)).

### Time on that runner

| Step | Time |
|---|---|
| embedding the corpus, bge-small | 25 min at `default`<br/>32 at `h6`<br/>14 at `h2`<br/>23 at `merge-400` |
| embedding the corpus, arctic-embed-s | 35 min |
| the cross-encoder | about 2.5 s per question (32 candidates) |

### What it found

| Configuration | recall@5, 24 November | grouped by article, 25 November |
|---|---|---|
| BM25 at `h2` | 89.1% | 92.5% |
| BM25 at `default` | 87.6% | 91.0% |
| BM25 at `merge-400` | 87.6% | 91.4% |
| BM25 at `h6` | 85.8% | 89.9% |
| hybrid on bge-small at `default` | 90.3% | 92.5% |
| hybrid on bge-small at `merge-400` | 91.0% | not run again |
| hybrid on arctic-embed-s at `h6` | 79.8% | not run again |

- BM25 scores alike at `h2`, `default` and `merge-400`, above `h6`, in both runs.
- `h2` comes first by the benchmark's ordering, so the summary names it for the no-model budget.
  Its lead over `default` is not significant (grouped: +1.5 points, McNemar mid-p 0.27; on
  24 November p 0.42), and the shipped default stays `default`.
- Hybrid on bge-small at `default`, grouped, is as high as BM25 at `h2`: under the 5-point margin
  and not significant (p 1). So BM25 stays the default for the local budget too. (On 24 November
  the best was hybrid at `merge-400`, 1.9 points over BM25 at `h2`, p 0.33.)
- The cross-encoder loses recall at `h2`, whose chunks are longer than its window.
- arctic-embed-s is below BM25.

### Run again with results grouped by article

`search_docs` groups its results by article since #575, and the benchmark scores each group as one
result ([Grouped results](retrieval-benchmark.md#what-a-run-does)). So the results ExactDocs'
defaults are chosen from were run again on 25 November 2026 on 4 shared CPUs (Linux x86_64,
ExactDocs `ce81d93`):

```bash
just retrieval-bench --offline --configs bm25 --out <dir>             # about 5 minutes
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-bench --offline \
  --configs 'hybrid:bge-small-en-v1.5@default' --out <dir>             # 59 minutes, embedding included
```

- Each of those five results replaced the recorded one whole: metrics, rows and latencies.
  `recorded_by` names the run, and *Recorded by another run* in `retrieval.md` lists them.
- The recommendations and the tests against each budget's default were made again from the
  results as they then stood.
- The other results (the cross-encoder, hybrid at `h6`, `h2` and `merge-400`, arctic-embed-s) are
  still those of 24 November: the search before it grouped its results, one chunk per result, with
  no context per case and so no recall within a token budget. Their recall@10 compares with the
  grouped results (grouping returns the same ten chunks); their recall@1, recall@5 and MRR do not.
- Since #571 a heading's `{#id}` is no longer part of its text, and one Pydantic case lists a
  heading with one. So that case, at rank 1 for BM25 before, is a miss in every run since
  `ce81d93`: one of the 267 answerable cases (0.4 points) fewer at every k, with or without
  grouping.
- The run that measured grouping against the search before it, on the same code and machine, is
  the grid's app cells and their `+by-chunk` controls
  ([Retrieval results](../benchmark/retrieval/grouping.md)).

### The run it replaces

It replaces a run of 23 and 24 November 2026 (the same subset on the same runner), scored by the
rules before #503 and #501. Its numbers are not comparable:

- a chunk that held the expected section next to a sibling was a miss (BM25's recall@5 was 76.0%
  at `h2` and 74.2% at `merge-400`);
- recall@k counted only a case's first listed section (81.7% at `default`).

Scored that way, BM25's results at `default` give the same 81.7%. The alternatives the review
marked add 3 cases, and the other parts of multi-part cases 13 (8 of them `cross-page`).

## Running it with local models

```bash
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models uv run exactdocs models pull \
  BAAI/bge-small-en-v1.5 Xenova/ms-marco-MiniLM-L-6-v2 \
  snowflake/snowflake-arctic-embed-s BAAI/bge-base-en-v1.5
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-bench --offline
```

- The pull is the only step that needs the network.
- The models then run on the CPU (ONNX Runtime, half the cores per call).
- Embedding the corpus dominates the run time (`index` seconds per model and chunking in the
  report), then the cross-encoder; see [the recorded run](#the-recorded-run).

## Running the hosted part

!!! warning "Only by hand, never in CI"
    The hosted part calls real providers, so only a person starts it.

The manual *Retrieval eval (real providers)* workflow (`.github/workflows/eval-providers.yml`)
with the input `benchmark` ticked runs the job *Retrieval benchmark with real providers*. It:

- configures profile `eval` from the same repository variables as the suite:
  `EVAL_PROVIDER_KIND`, `EVAL_PROVIDER_BASE_URL`, `EVAL_PROVIDER_API_VERSION`,
  `EVAL_EMBEDDING_MODEL`, `EVAL_LLM_MODEL`, `EVAL_JUDGE_MODEL`, and the secret
  `EVAL_PROVIDER_API_KEY`;
- pulls the local models;
- runs `--allow-providers` on `benchmark_configs` (default `bm25,*+judge,*:hosted*`) with
  `benchmark_args` (e.g. `--chunkings default`).

The report is the artifact `retrieval-bench-providers`. Locally the same is one command with the
roles in the environment:

```bash
EXACTDOCS_AI__PROVIDERS__EVAL__KIND=openai EXACTDOCS_AI__PROVIDERS__EVAL__API_KEY=... \
EXACTDOCS_AI__EMBEDDING__MODEL=eval:text-embedding-3-small EXACTDOCS_AI__LLM__MODEL=eval:gpt-4.1-mini \
just retrieval-bench --allow-providers --configs 'bm25,*+judge,*:hosted*'
```

The tests run the hosted part on stand-ins only (`tests/evals/test_retrieval_bench.py`, marked
`eval`, and `retrieval_bench.feature`):

- the term-hash embedding;
- one `FunctionModel` that rates as the judge, writes for HyDE and browses as the agent, priced.

They check the plumbing, the wrong-version rate of 0 and that cost reaches the report. Their
numbers are never results.

## When it runs

- **By hand, before a release that touches retrieval or chunking**: the manual *Eval* workflow
  (`eval.yml`) runs BM25 at the `default` chunking through the benchmark (step *Retrieval
  benchmark*, about a minute) with `--check`. It fails on a wrong
  version, an error, or recall@5 or nDCG@10 more than 2 points below the recorded run (the same
  golden set and projects are required).
- **Never in CI**: the local and hosted parts. Refresh the recorded run by hand when ranking,
  chunking or a model changes.
- **Pull request CI** runs the quick tests only.
