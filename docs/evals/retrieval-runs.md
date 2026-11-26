# Retrieval benchmark runs

!!! abstract "TL;DR"
    - `retrieval.json` records everything needed to recompute a result: the corpus commits, the
      environment, the models and settings, and every case's outcome.
    - The recorded run (26 November 2026, 4 h 38 min on a 4-CPU x86_64 container) covers BM25 and
      the local models on a subset of the matrix. No hosted configuration has run yet.
    - BM25 scores recall@5 89.1% at `h2`, 87.6% at `default` and `merge-400`, and 85.8% at `h6`.
      `h2`'s lead is not significant (p 0.42), so the shipped default stays `default`.
    - Hybrid on bge-small reaches 91.0%, under the 5-point margin and not significant, so BM25
      stays the default for the local budget too.
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
      wrong version, empty, search time, tokens and USD), from which the metrics, intervals and
      tests can be recomputed;
    - `rows_from`: set when the rows come from a later run than the metrics;
    - `versus_default`: the paired tests against its budget's default.

The recorded run is `packages/exactdocs/evals/results/retrieval.json` and `retrieval.md`.
`schema_version` changes when a field is renamed or removed. #489 only added fields, so it is
still 1, and a report without them still reads.

## The recorded run

| Run | |
|---|---|
| Recorded | 26 November 2026, for #591 |
| Golden set | the `config-both` case naming its heading as #571 cuts it (`sha256:100484c7ccdb1b89`) |
| How | by hand, with the command below, local configurations only |
| Machine | one cloud container, Linux x86_64, 4 CPUs |
| ExactDocs | `08349c1` |
| Time | 4 h 38 min |

A full local matrix (three embedding models, each with and without the cross-encoder, at four
chunkings) would take far longer there, so it ran on the same subset as the run it replaces:

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

### Time on that machine

| Step | Time |
|---|---|
| embedding the corpus, bge-small | 38 min at `default`<br/>51 at `h6`<br/>20 at `h2`<br/>32 at `merge-400` |
| embedding the corpus, arctic-embed-s | 43 min |
| the cross-encoder | about 3.2 s per question (32 candidates; 2.7 s at `h2`) |

The run it replaces took 25, 32, 14 and 23 minutes for bge-small, 35 for arctic-embed-s and
about 2.5 s per question for the cross-encoder on a self-hosted aarch64 runner: the latencies in
the report are this container's, 30% to 45% higher.

### What it found

| Configuration | recall@5 |
|---|---|
| BM25 at `h2` | 89.1% |
| BM25 at `default` | 87.6% |
| BM25 at `merge-400` | 87.6% |
| BM25 at `h6` | 85.8% |
| hybrid on bge-small at `merge-400` | 91.0% |
| hybrid on arctic-embed-s at `h6` | 79.8% |

- BM25 scores alike at `h2`, `default` and `merge-400`, above `h6`.
- `h2` comes first by the benchmark's ordering, so the summary names it for the no-model budget.
  Its lead over `default` is not significant (+1.5 points, McNemar mid-p 0.42), and the shipped
  default stays `default`.
- Hybrid on bge-small at `merge-400` is 1.9 points over BM25 at `h2`: under the 5-point margin and
  not significant (p 0.33). So BM25 stays the default for the local budget too.
- The cross-encoder loses recall at `h2`, whose chunks are longer than its window.
- arctic-embed-s is below BM25.

### The run it replaces

It replaces the run of 24 November 2026 (golden set `sha256:a00997851150e3b0`, ExactDocs
`8e789e6`), from the manual *Retrieval eval (real providers)* workflow with `benchmark` ticked on
a self-hosted aarch64 runner ([run 45353553786](https://github.com/SirCypkowskyy/ExactDocs/actions/runs/45353553786)).
That run was made before #571, which takes a heading's `{#id}` out of its text; one case still
named a heading with its `{#config-both}` and became a miss in every run after #571 (#591). The
case now names the heading as the chunker cuts it, so it is answered as before.

- BM25 and the cross-encoder give the same rank on every case, so the same numbers.
- Hybrid's ranks moved in 2 to 7 cases per result (0 or 1 with the cross-encoder), in every
  project, not only Pydantic's: the embeddings were computed on another machine (x86_64, not
  aarch64) and with onnxruntime 1.32.0, not 1.31.0. That costs bge-small one case of recall@5 at
  `default` (90.3% to 89.9%) and at `h6` (90.6% to 90.3%); `merge-400` and `h2` keep theirs.
- No recommendation, significance or finding below changed.

That run replaced one of 23 and 24 November 2026 (the same subset on the same runner), scored by
the rules before #503 and #501, whose numbers are not comparable:

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
