# Retrieval results

!!! abstract "TL;DR"
    - Recorded on 26 and 27 November 2026 on the whole golden set, with no provider: every result
      on #571's chunker and grouped by article as `search_docs` returns it (#575).
    - BM25 scores alike at `h2`, `merge-400` and `default` (92.9%, 91.8% and 91.4% recall@5); `h2`'s
      lead is not significant (p 0.27), so the shipped default stays `default`.
    - Hybrid on bge-small at `default` puts the answer first more often than BM25 (76.4% against
      70.8%, p 0.02), but not in the top 5 significantly more often (93.3%, p 0.24). At `h6` and
      `merge-400` it reaches 94.0%, still not significant (p 0.12 and 0.13).
    - Grouped, the cross-encoder no longer loses recall at `default` and `h6`: on BM25 at `default`
      it reaches 76.4% recall@1 (p 0.04) and 93.6% recall@5 (p 0.21), at about 15 s per question
      on 2 vCPUs.
    - Within the first 1,000 tokens BM25 at `default` holds the answer in 43.1% of the cases.
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
| [Windows and baselines](grid-variants.md) | the grid's keyword grep baseline, fixed token windows and `h6` hybrid cells (#494) |
| [Every run](history.md) | every recorded run of the benchmark and the grid, sortable and filterable |

## The recorded run

| | |
|---|---|
| Report | `packages/exactdocs/evals/results/retrieval.json` |
| Recorded | 26 and 27 November 2026, for #598 |
| Golden set | one heading without its attribute list (`sha256:100484c7ccdb1b89`) |
| Machine | five self-hosted runner VMs (Linux aarch64, 2 vCPUs each), one chunking per VM (`h6` on two), with no provider |
| Duration | 2 h 14 min to 5 h 9 min per VM, 7 h 23 min from the first start to the last result ([the command and the timings](../../evals/retrieval-runs.md#the-recorded-run)) |

A full local matrix would take far longer, so it ran a subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking;
- `bm25+ce` at `default`, `h6` and `h2`, and `hybrid:bge-small-en-v1.5+ce` at `default` and `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6`;
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking on 4 CPUs).

Every result keeps each case's outcome, so every one has intervals, a paired test against its
budget's default and recall within a token budget
([Intervals and significance](../method/metrics.md#intervals-and-significance)). The latencies are
those of a 2-vCPU VM; the cross-encoder takes about six times as long per question there as on the
4-CPU runner of 24 November.

!!! note "What changed since the run it replaces"
    The run it replaces (24 November, with BM25 and hybrid at `default` again on 25 November) mixed
    two searches: the results run again on 25 November were grouped by article, the others were
    one chunk per result.

    - Every result is now grouped by article. The cross-encoder and hybrid at `h6`, `h2` and
      `merge-400` gain the most: grouping lifts their recall@1 by 11 to 15 points.
    - Since #571 the chunker leaves a heading's `{#id}` out of its text, and since #594 the one
      Pydantic case that named a heading with it names it without. That case is found again, so
      BM25 gives every case the same rank as on 25 November except that one: 0.4 points more at
      every k.
    - Hybrid on bge-small at `default` finds that case too and puts 4 others at another rank
      (92.5% to 93.3% recall@5): its vectors of 25 November were computed on Linux x86_64, these
      on aarch64.

!!! note "Every hosted configuration is not measured yet"
    That is hybrid on a hosted embedding model, HyDE, agentic search and every configuration
    reranked by the LLM judge. They run only from the manual *Retrieval eval (real providers)*
    workflow (`.github/workflows/eval-providers.yml`) with the `benchmark` input ticked, or
    locally with `--allow-providers`
    ([Running the hosted part](../../evals/retrieval-runs.md#running-the-hosted-part)). None of them is in the recorded
    run.

<!-- bench:retrieval-run -->
- Golden set: 321 cases, fingerprint `sha256:100484c7ccdb1b89`, projects starlette, pydantic, tanstack-query, zod, electron.
- ExactDocs commit `7f532c0482d559c7226469c5f70e5146466adbce` (`0.0.0.post1.dev0+2ab81c57`), Python 3.14.10, Linux aarch64, 2 CPUs.
- Libraries: fastembed 0.9.1, onnxruntime 1.32.0, pydantic-ai-slim 2.60.0, pydantic-evals 2.60.0.

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

- **BM25 scores alike at `h2`, `merge-400` and `default`**: 92.9%, 91.8% and 91.4% recall@5.
    - `h2` comes first by the benchmark's ordering, so the summary names it, but its lead over
      `default` is not significant on any metric (recall@5 +1.5 points, p 0.27; recall@1 p 0.62;
      MRR p 0.65).
    - Its chunks are about twice as long: 7,065 estimated tokens in a question's ten results
      against 3,464 ([text calibration](../../evals/text-scoring.md#calibration)).
    - `h6`, where every heading starts a chunk, is below them: 90.3%, with MRR and nDCG@10
      significantly worse than at `default` (p 0.047 and 0.004).
    - The shipped default stays `default` (#381); a non-significant lead does not change it.
- **At the same amount of context `default` is far ahead of `h2`** (#575).
    - Within the first 1,000 estimated tokens of what BM25 returned, a section that answers is
      there in 43.1% of the cases at `default` and 24.3% at `h2`; within 2,000, 71.5% against
      49.8% (both significant).
    - `h6`, whose chunks are shorter, holds it a little more often (46.4% and 75.3%, significant),
      `merge-400` less often within 1,000 tokens (38.2%, p 0.03).
- **Hybrid search on bge-small** reaches 93.3% recall@5 and 76.4% recall@1 at `default`, and
  94.0% recall@5 at `h6` and `merge-400`.
    - At `default`, `h6` and `merge-400` it puts the answer first more often than BM25 at
      `default` (+5.2 to +5.6 points, p 0.02 to 0.05; MRR and nDCG@10 significantly better too).
    - It does not find significantly more answers in the top 5 at any chunking (+1.9 to +2.6
      points, p 0.12 to 0.24). At `h6` it holds the answer within 2,000 and 4,000 tokens more
      often than BM25 at `default` (79.8% and 94.4% against 71.5% and 89.5%, both significant).
    - At `h2` it scores 90.6%, below BM25 at `h2`.
- **The cross-encoder** (MiniLM over 32 candidates) ranks the answer first more often than BM25
  at `default`, on BM25 at `default` and `h6` (76.4% and 76.0% recall@1, p 0.04 and 0.05), but
  finds no significantly more answers in the top 5 (93.6% and 93.3%, p 0.21 and 0.29).
    - It loses recall at `h2` (89.5% against 92.9% for BM25 there, p 0.10), whose chunks are longer
      than its window, and on hybrid it adds nothing (92.9% against 93.3% at `default`).
    - It costs about 15 s per question (p50) on a 2-vCPU VM.
- **snowflake-arctic-embed-s** scores below BM25 (86.5% recall@5 at `h6`, p 0.02 against BM25 at
  `default`).
- **The intervals per kind and per project** are about twice as wide as the whole set's (around
  ±10 points of recall@5 on some 50 cases): differences of a few points there say little.
- No configuration returned a result of another version, and none signalled "no answer" on any of
  the 54 unanswerable cases: `search_docs` gives a caller no way to tell an unanswerable question
  from an answerable one by its results today.
- On `cross-page` questions, section recall@5 is 25 to 29 points below recall@5 for BM25 and
  hybrid at `default`: a hit on one page of the answer is common, all of its pages much rarer.
