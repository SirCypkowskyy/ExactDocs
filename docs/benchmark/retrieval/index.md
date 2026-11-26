# Retrieval results

!!! abstract "TL;DR"
    - Recorded on 24 November 2026 on the whole golden set, with no provider. Since #575
      `search_docs` groups its results by article, and BM25 at every chunking and hybrid on
      bge-small at `default` were run again with it on 25 November.
    - BM25 scores alike at `h2`, `default` and `merge-400` (92.5%, 91.0% and 91.4% recall@5); `h2`'s
      lead is not significant (p 0.27), so the shipped default stays `default`.
    - Hybrid on bge-small at `default` puts the answer first more often than BM25 (76.0% against
      70.4%, p 0.02), but not in the top 5 significantly more often (92.5%, p 0.36).
    - Grouping by article lifts recall@1 by 12.0 points with BM25 and with hybrid search, from the
      same chunks, past Grounded Docs' lead (71.2%). The answer then sits further into what is
      returned: within the first 1,000 tokens BM25 holds it in 42.7% of the cases, 77.9% before
      grouping, still more often than Grounded Docs (34.1%).
    - No configuration returned a result of another version, and none signalled "no answer" on any
      of the 54 unanswerable cases.

Every retrieval configuration that could run, at every chunking configuration, on the whole
[golden set](../golden-set.md). The metrics are defined in [Method](../method/metrics.md#retrieval-metrics);
the default each budget gets is on [Recommended defaults](../defaults.md).

## Which page do I need

| Page | What it holds |
|---|---|
| [Every result](results.md) | every configuration at every chunking, against the budget's default, within a token budget, per kind, project and model |
| [Rank 1 at no more context](rank-one.md) | the grid's variants for rank 1 (#575): what they found |
| [Rank 1: every table](rank-one-tables.md) | the grid's tables behind it |
| [Grouped by article](grouping.md) | the grid run of the grouping as shipped, and what it changed |
| [Every run](history.md) | every recorded run of the benchmark and the grid, sortable and filterable |

## The recorded run

| | |
|---|---|
| Report | `packages/exactdocs/evals/results/retrieval.json` |
| Recorded | 24 November 2026, for #503 and #501; BM25 and hybrid at `default` again on 25 November, grouped by article (#575) |
| Golden set | with its alternatives marked (`sha256:a00997851150e3b0`) |
| Machine | one self-hosted runner VM (Linux aarch64, 4 CPUs), with no provider; the runs of 25 November on 4 shared CPUs (Linux x86_64) |
| Duration | 3 h 22 min ([the command and the timings](../../evals/retrieval-runs.md#the-recorded-run)) |

A full local matrix would take far longer, so it ran a subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking;
- `bm25+ce` at `default`, `h6` and `h2`, and `hybrid:bge-small-en-v1.5+ce` at `default` and `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6`;
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking).

Every result keeps each case's outcome, so every one has intervals and a paired test against its
budget's default ([Intervals and significance](../method/metrics.md#intervals-and-significance)). The
latencies are those of the machine each result ran on.

!!! note "Grouped by article since 25 November (#575)"
    `search_docs` groups its results by article, and the benchmark scores each group as one result
    ([Grouped results](../../evals/retrieval-benchmark.md#what-a-run-does)). BM25 at every chunking
    and hybrid search on bge-small at `default` were run again with it on 25 November and replace
    their recorded results whole, latencies included (*Recorded by another run* on [Every result](results.md#recorded-by-another-run),
    [the runs](../../evals/retrieval-runs.md#run-again-with-results-grouped-by-article)); they have
    recall within a token budget.

    - The other results are still those of the search before grouping, one chunk per result:
      their recall@10 compares with the grouped results, their recall@1, recall@5 and MRR do not,
      and they have no budget numbers.
    - Since #571 one Pydantic case lists a heading as the corpus no longer holds it (with its
      `{#id}`), so the runs of 25 November count one answerable case fewer (0.4 points) at
      every k.

!!! warning "Two scoring rules changed since the run it replaces"
    The run it replaces (23–24 November, the same subset on the same runner) is not comparable
    with this one ([Method](../method/metrics.md#retrieval-metrics)):

    - A chunk counts for every section it holds (#503). Before, a chunk that held the expected
      section next to a sibling was a miss, which undercounted `h2` and `merge-400` (BM25's
      recall@5 was 76.0% and 74.2% there).
    - recall@k and MRR count a hit on any section a case lists, and section recall and nDCG@10
      count each part of the answer once, an alternative counting as its part (#501). Before,
      recall@k counted the first listed section only. This alone lifts BM25's recall@5 at
      `default` from 81.7% to 87.6%: 3 cases by the alternatives the review marked, 13 by the
      other parts of multi-part cases (8 of them `cross-page`).

!!! note "Every hosted configuration is not measured yet"
    That is hybrid on a hosted embedding model, HyDE, agentic search and every configuration
    reranked by the LLM judge. They run only from the manual *Retrieval eval (real providers)*
    workflow (`.github/workflows/eval-providers.yml`) with the `benchmark` input ticked, or
    locally with `--allow-providers`
    ([Running the hosted part](../../evals/retrieval-runs.md#running-the-hosted-part)). None of them is in the recorded
    run.

<!-- bench:retrieval-run -->
- Golden set: 321 cases, fingerprint `sha256:a00997851150e3b0`, projects starlette, pydantic, tanstack-query, zod, electron.
- ExactDocs commit `8e789e67177adf9514418b566473dca937ca638d` (`0.0.0.post1.dev0+0f6e6d1`), Python 3.14.10, Linux aarch64, 4 CPUs.
- Libraries: fastembed 0.9.1, onnxruntime 1.31.0, pydantic-ai-slim 2.60.0, pydantic-evals 2.60.0.

| Project | Version | Commit |
|---|---|---|
| starlette | 0.27.0 | `0c4b68ac4e179a788e38bac28f299dcad0f36e99` |
| starlette | 0.52.1 | `e5b8a5d200504a2608bed11fe6f66b1d20b9ae2c` |
| starlette | 1.10.0 | `8aa828ceaff764a2e57932fb42fdf105a47c4c83` |
| pydantic | v1.10.22 | `5e6e87f7da283d8d13965d0186c88acdd531eda9` |
| pydantic | v2.5.3 | `9f58e785a5f1f2c34437f6e9b6adcd5b969e0df4` |
| pydantic | v2.14.3 | `ea492e04654ab7f7a1f9287ea912419452ead4dd` |
| tanstack-query | v4.36.1 | `6532ed3cbe49f04b3cb31f80ea88b5886416d51a` |
| tanstack-query | v5.0.0 | `3be9b4580ef8face761e354e5dc57bb56c9ff4a1` |
| tanstack-query | v5.90.3 | `4d8da1e29e97ad5b0c151822d4962849515b4478` |
| zod | v3.23.8 | `ca42965df46b2f7e2747db29c40a26bcb32a51d5` |
| zod | v4.0.17 | `cc63f950158db212c5e9b75e7d22faca851ea624` |
| zod | v4.6.7 | `b500a2ee95134f81d74da7911d7378dd2853d042` |
| electron | v30.0.0 | `c37c7fd3c48d686e4b98431aaf1a1187f603e758` |
| electron | v38.0.0 | `79433861fe10e4f7841153461fd3778b400a4c0b` |
| electron | v45.3.2 | `9ee9e7718172287d068cee397097c2d79a137eec` |
<!-- /bench -->

## What it shows

- **BM25 scores alike at `h2`, `default` and `merge-400`**: 92.5%, 91.0% and 91.4% recall@5.
    - `h2` comes first by the benchmark's ordering, so the summary names it, but its lead over
      `default` is not significant on any metric (recall@5 +1.5 points, p 0.27; recall@1 p 0.62;
      MRR p 0.65).
    - Its chunks are about twice as long: 7,065 estimated tokens in a question's ten results
      against 3,464 ([text calibration](../../evals/text-scoring.md#calibration)).
    - `h6`, where every heading starts a chunk, is below them: 89.9%, with MRR and nDCG@10
      significantly worse than at `default` (p 0.047 and 0.004).
    - The shipped default stays `default` (#381); a non-significant lead does not change it.
- **At the same amount of context `default` is far ahead of `h2`** (#575).
    - Within the first 1,000 estimated tokens of what BM25 returned, a section that answers is
      there in 42.7% of the cases at `default` and 24.0% at `h2`; within 2,000, 71.2% against
      49.4% (both significant).
    - `h6`, whose chunks are shorter, holds it a little more often (46.1% and 74.9%, significant),
      `merge-400` a little less often within 1,000 tokens (37.8%).
- **Hybrid search on bge-small at `default`** reaches 92.5% recall@5 and 76.0% recall@1.
    - It puts the answer first more often than BM25 at `default` (+5.6 points, p 0.02; MRR and
      nDCG@10 significantly better too).
    - It does not find significantly more answers in the top 5 (+1.5 points, p 0.36), nor within
      any token budget.
- **The intervals per kind and per project** are about twice as wide as the whole set's (around
  ±10 points of recall@5 on some 50 cases): differences of a few points there say little.
- **The results not run again since grouping** (24 November, one chunk per result):
    - Hybrid on bge-small reached 91.0% recall@5 at `merge-400` and 90.6% at `h6`, and 86.1% at
      `h2`.
    - The cross-encoder on BM25 reached 89.5% at `default` and 89.1% at `h6`, neither significant
      over BM25 at `default` then (p 0.36 and 0.46), at about 2.5 s per question (p50) on that
      runner. It lost recall at `h2` (85.4%), whose chunks are longer than its window, and on
      hybrid it added nothing.
    - snowflake-arctic-embed-s scored below BM25 (79.8%).
- No configuration returned a result of another version, and none signalled "no answer" on any of
  the 54 unanswerable cases: `search_docs` gives a caller no way to tell an unanswerable question
  from an answerable one by its results today.
- On `cross-page` questions, section recall@5 is 25 to 29 points below recall@5 for BM25 and
  hybrid at `default`: a hit on one page of the answer is common, all of its pages much rarer.
