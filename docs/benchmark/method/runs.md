# Running and refreshing

!!! abstract "TL;DR"
    - Pull requests run only stand-ins and the golden-set rules; every recorded run is started by
      hand, and none in CI calls a hosted model.
    - Each report records what a rerun needs: the golden set's fingerprint, the pinned commits, the
      ExactDocs commit, the machine and the models.
    - `just bench-pages` refills the pages and the history of every run from the reports; a pull
      request test fails when they differ.

What runs in CI and what by hand, how to reproduce a recorded run, and how the pages are refilled
from the recorded runs.

## What runs where

| Run | Where | Models |
|---|---|---|
| quick tests of all three benchmarks and the text scorer | every pull request (`uv run pytest`, `uv run behave`) | stand-ins only, tiny local corpora |
| `just golden-validate` rules | every pull request (pytest) | none |
| ingestion benchmark `--check` | by hand: the manual *Eval* workflow (`eval.yml`) | none |
| retrieval benchmark, BM25 at `default`, `--check` | by hand: the manual *Eval* workflow (`eval.yml`) | none |
| retrieval benchmark with local models | by hand (`just retrieval-bench --offline`) | local, pulled with `exactdocs models pull` |
| retrieval benchmark, hosted configurations | by hand: the manual *Retrieval eval (real providers)* workflow (`eval-providers.yml`),<br/>with the `benchmark` input ticked | hosted |
| text scorer calibration | by hand (`just text-bench --offline`), when the matcher or the chunker changes | none |
| agent benchmark, quick tests of every arm | every pull request (`uv run pytest`, `uv run behave`) | stand-ins, stand-in documentation tools |
| Grounded Docs on the golden set | by hand (`just grounded-bench --offline`),<br/>or the manual *Grounded Docs benchmark* workflow (`grounded-bench.yml`);<br/>quick tests replay recorded responses on every pull request | local, `BAAI/bge-small-en-v1.5`<br/>pulled with `exactdocs models pull` |
| agent benchmark | by hand: the manual *Agent benchmark (real providers)* workflow (`agent-bench.yml`),<br/>or `just agent-bench run` locally | hosted (Ollama Cloud for the recorded run) |

No CI or release run calls a hosted model or needs a secret.

## Reproducing a run

Each JSON report records what a rerun needs. `retrieval.json` holds the golden set's
fingerprint, every pinned commit, the ExactDocs commit, the machine, the library versions, each
model with its Hub revision, the AI settings of each configuration, every case's outcome, and
the seed and resamples of the intervals
([Reproducing a result](../../evals/retrieval-runs.md#reproducing-a-result)). The commands:

```bash
just ingestion-bench --offline --out packages/exactdocs/evals/results
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-bench --offline \
  --configs 'bm25,hybrid:bge-small-en-v1.5,bm25+ce@h6,bm25+ce@h2,bm25+ce@default,hybrid:bge-small-en-v1.5+ce@h6,hybrid:bge-small-en-v1.5+ce@default,hybrid:snowflake-arctic-embed-s@h6' \
  --out packages/exactdocs/evals/results
```

The second is the recorded retrieval run ([The recorded run](../../evals/retrieval-runs.md#the-recorded-run)): 3 h
17 min on a 4-CPU runner, most of it embedding the corpus and the cross-encoder. The run recorded
now was split by chunking over five 2-vCPU VMs, 7 h 23 min in all.

## Coding tasks

The coding tasks (#496) check code, not prose: an agent with the workspace tools and one
documentation arm completes a request in a small project that pins one library version, and the
task passes only when its hidden tests pass in a sandbox with exactly that version installed. The
report gives the **pass rate** (overall, per project, and over the tasks pinning a version
released after the model's training cutoff), the share of tasks whose changed code uses an API the
pinned version does not have (**forbidden-API rate**), and the **files changed** per task, each
with its 95% interval ([Intervals and significance](metrics.md#intervals-and-significance)); each arm's pass rate is tested against `none`'s on the same tasks
by McNemar's test (mid-p). Most tasks come as version pairs, the same request pinned at two
versions where the right code differs. The task format, the sandbox and the commands are in
[Version-pinned coding tasks](../../evals/coding-tasks.md).

## Refreshing these pages

The tables on the benchmark pages are not typed by hand. Each page holds generated blocks between
`<!-- bench:<name> -->` and `<!-- /bench -->` markers, and `just bench-pages` refills them from
`packages/exactdocs/evals/results/ingestion.json`, `retrieval.json`, `agent.json`,
`grounded-docs.json`, `harness-bench.json`, `coding-tasks.json`, the grid's
`retrieval-grid-rank1.json` and `retrieval-grid-grouped.json` and the golden set, with the benchmarks' own Markdown renderers. Everything outside the markers is
prose.

A recorded report is overwritten by the next run, so `just bench-pages` also keeps every run in
`packages/exactdocs/evals/results/history.json`, one row per result:

- it adds each current result the history does not hold yet, dated by the report (`started_at`,
  `date`, a result's `recorded_by`) or, when the report records no date, today;
- a result equal to one already held in everything but its date and commit is not added again, so
  a result kept by `--resume` or recorded by another run stays one row;
- the *Every run* page of each benchmark (for example [Every retrieval run](../retrieval/history.md))
  shows the history as a table, newest first. In the browser it sorts by any column, filters by a
  column's values or a date range and charts one metric over time
  (`docs/javascripts/bench-history.js`); the Markdown is the same table.

The runs recorded before the history existed (13 to 26 November 2026) were read back from git,
each dated by the commit that recorded it.

```bash
just bench-pages            # rewrite the blocks and the history after a new recorded run
just bench-pages --check    # fail when a page or the history differs from the reports
```

A pull request test runs the check, so a recorded run or a golden-set change that does not
refresh the pages and the history fails CI. The prose around the tables (the findings on
[Recommended defaults](../defaults.md), the run dates) is updated by hand in the same pull request.
