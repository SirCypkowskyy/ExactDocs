# Retrieval benchmark runs

!!! abstract "TL;DR"
    - `retrieval.json` records everything needed to recompute a result: the corpus commits, the
      environment, the models and settings, and every case's outcome.
    - The recorded run (26 and 27 November 2026, five 2-vCPU aarch64 runner VMs, one chunking
      each) covers BM25 and the local models on a subset of the matrix, every result grouped by
      article (#575). No hosted configuration has run yet.
    - BM25 scores recall@5 92.9% at `h2`, 91.8% at `merge-400`, 91.4% at `default` and 90.3% at
      `h6`. `h2`'s lead is not significant (p 0.27), so the shipped default stays `default`.
    - Hybrid on bge-small reaches 94.0% at `merge-400` and `h6`, under the 5-point margin and not
      significant (p 0.13 and 0.12), so BM25 stays the default for the local budget too.
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
| Recorded | 26 and 27 November 2026, for #598 |
| Golden set | one heading without its attribute list (`sha256:100484c7ccdb1b89`) |
| Workflow | a temporary workflow on a branch, one job per chunking ([run 45868335522](https://github.com/SirCypkowskyy/ExactDocs/actions/runs/45868335522) for `default` and `h6`, [run 45903219806](https://github.com/SirCypkowskyy/ExactDocs/actions/runs/45903219806) for `h2` and `merge-400`) |
| Machine | five self-hosted runner VMs, Linux aarch64, 2 vCPUs each |
| ExactDocs | `7f532c0`: develop at `fcd125d` with the temporary workflow added (`h2` and `merge-400` on `e530273`, which changes only that workflow) |
| Time | 7 h 23 min from the first start to the last result; per VM below |

A full local matrix (three embedding models, each with and without the cross-encoder, at four
chunkings) would take far longer there, so it ran the same subset as the run before it:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking configuration;
- `bm25+ce` at `default`, `h6` and `h2`;
- `hybrid:bge-small-en-v1.5+ce` at `default` and `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6` (the second local embedding model);
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking on 4 CPUs);
- every hosted configuration is listed as skipped: it needs a real-providers run.

Each job ran one chunking (`h6` on two jobs):

```bash
just retrieval-bench --chunkings default --configs 'bm25,bm25+ce,hybrid:bge-small-en-v1.5,hybrid:bge-small-en-v1.5+ce' --out <dir>
just retrieval-bench --chunkings h6 --configs 'bm25,bm25+ce,hybrid:snowflake-arctic-embed-s' --out <dir>
just retrieval-bench --chunkings h6 --configs 'hybrid:bge-small-en-v1.5,hybrid:bge-small-en-v1.5+ce' --out <dir>
just retrieval-bench --chunkings h2 --configs 'bm25,bm25+ce,hybrid:bge-small-en-v1.5' --out <dir>
just retrieval-bench --chunkings merge-400 --configs 'bm25,hybrid:bge-small-en-v1.5' --out <dir>
```

The five reports were merged into one: their results in chunking order, then the recommendations
and the tests against each budget's default made again from all of them with the benchmark's own
`recommend` and `against_defaults`. The environment is the `default` job's. Every result keeps its
per-case `rows`, so every one has intervals, a paired test against its budget's default (#489)
and recall within each token budget (#575).

### Time on those VMs

| Step | Time |
|---|---|
| embedding the corpus, bge-small | 2 h 27 min at `default`<br/>3 h at `h6`<br/>1 h 21 min at `h2`<br/>2 h 11 min at `merge-400` |
| embedding the corpus, arctic-embed-s | 3 h 8 min |
| the cross-encoder | about 15 s per question (32 candidates) |
| BM25 | about a minute per chunking, import included |

Embedding took about six times as long as on the 4-CPU runner of 24 November (25 minutes at
`default` there), and the cross-encoder about six times (2.5 s per question).

### What it found

| Configuration | recall@5, 24 and 25 November | 26 and 27 November |
|---|---|---|
| BM25 at `h2` | 92.5% | 92.9% |
| BM25 at `merge-400` | 91.4% | 91.8% |
| BM25 at `default` | 91.0% | 91.4% |
| BM25 at `h6` | 89.9% | 90.3% |
| hybrid on bge-small at `default` | 92.5% | 93.3% |
| hybrid on bge-small at `h6` | 90.6%, one chunk per result | 94.0% |
| hybrid on bge-small at `merge-400` | 91.0%, one chunk per result | 94.0% |
| BM25 with the cross-encoder at `default` | 89.5%, one chunk per result | 93.6% |
| hybrid on arctic-embed-s at `h6` | 79.8%, one chunk per result | 86.5% |

- BM25 gives every case the rank it had on 25 November but one: the Pydantic `config-both` case,
  a miss there since #571 cut `{#config-both}` out of the heading and found again since #594
  dropped it from the case (0.4 points at every k).
- `h2` comes first by the benchmark's ordering, so the summary names it for the no-model budget.
  Its lead over `default` is not significant (+1.5 points, McNemar mid-p 0.27), and the shipped
  default stays `default`.
- Hybrid on bge-small at `merge-400` is the best local result, 1.1 points over BM25 at `h2`: under
  the 5-point margin and not significant (p 0.50). So BM25 stays the default for the local budget
  too.
- The results of 24 November were one chunk per result; grouped by article, the cross-encoder and
  hybrid at `h6`, `h2` and `merge-400` gain 11 to 15 points of recall@1, and the cross-encoder no
  longer loses recall against BM25 at `default` and `h6`. It still does at `h2`, whose chunks are
  longer than its window.
- arctic-embed-s is below BM25.

### The run it replaces

It replaces the run of 24 November 2026 (the same subset on one 4-CPU runner, ExactDocs `8e789e6`,
[run 45353553786](https://github.com/SirCypkowskyy/ExactDocs/actions/runs/45353553786)), of which
BM25 at every chunking and hybrid on bge-small at `default` were run again on 25 November (Linux
x86_64, `ce81d93`) with the results grouped by article. Both were on the golden set before #594
(`sha256:a00997851150e3b0`). The earlier history is on [Every run](../benchmark/retrieval/history.md).

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
