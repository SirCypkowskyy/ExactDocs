# Retrieval results

!!! abstract "TL;DR"
    - Recorded on 24 November 2026 on the whole golden set, with no provider.
    - BM25 scores alike at `h2`, `default` and `merge-400` (89.1%, 87.6% and 87.6% recall@5); `h2`'s
      lead is not significant (p 0.42), so the shipped default stays `default`.
    - The best local configuration, hybrid on bge-small at `merge-400` (91.0%), is 1.9 points above
      BM25 at `h2`, not significant (p 0.33).
    - No configuration returned a result of another version, and none signalled "no answer" on any
      of the 54 unanswerable cases.
    - Within the first 1,000 tokens of what it returns, BM25 at `default` holds the answer in 78.3%
      of the cases, at `h2` in 49.1% (#575).
    - Grouping the hits by article lifts recall@1 by about 12 points with the same context (BM25
      70.8%, hybrid on bge-small 78.3%; Grounded Docs 71.5%), at the cost of recall within a token
      budget; it is not shipped yet.

Every retrieval configuration that could run, at every chunking configuration, on the whole
[golden set](golden-set.md). The metrics are defined in [Method](method.md#retrieval-metrics);
the default each budget gets is on [Recommended defaults](defaults.md).

## The recorded run

| | |
|---|---|
| Report | `packages/exactdocs/evals/results/retrieval.json` |
| Recorded | 24 November 2026, for #503 and #501; BM25 and hybrid at `default` again on 25 November, grouped by article (#575) |
| Golden set | with its alternatives marked (`sha256:a00997851150e3b0`) |
| Machine | one self-hosted runner VM (Linux aarch64, 4 CPUs), with no provider; the runs of 25 November on 4 shared CPUs (Linux x86_64) |
| Duration | 3 h 22 min ([the command and the timings](../evals/retrieval-runs.md#the-recorded-run)) |

A full local matrix would take far longer, so it ran a subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking;
- `bm25+ce` at `default`, `h6` and `h2`, and `hybrid:bge-small-en-v1.5+ce` at `default` and `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6`;
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking).

Every result keeps each case's outcome, so every one has intervals and a paired test against its
budget's default ([Intervals and significance](method.md#intervals-and-significance)). The
latencies are those of the machine each result ran on.

!!! note "Grouped by article since 25 November (#575)"
    `search_docs` groups its results by article, and the benchmark scores each group as one result
    ([Grouped results](../evals/retrieval-benchmark.md#what-a-run-does)). BM25 at every chunking
    and hybrid search on bge-small at `default` were run again with it on 25 November and replace
    their recorded results whole, latencies included (*Recorded by another run* below,
    [the runs](../evals/retrieval-runs.md#run-again-with-results-grouped-by-article)); they have
    recall within a token budget.

    - The other results are still those of the search before grouping, one chunk per result:
      their recall@10 compares with the grouped results, their recall@1, recall@5 and MRR do not,
      and they have no budget numbers.
    - Since #571 one Pydantic case lists a heading as the corpus no longer holds it (with its
      `{#id}`), so the runs of 25 November count one answerable case fewer (0.4 points) at
      every k.

!!! warning "Two scoring rules changed since the run it replaces"
    The run it replaces (23–24 November, the same subset on the same runner) is not comparable
    with this one ([Method](method.md#retrieval-metrics)):

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
    ([Running the hosted part](../evals/retrieval-runs.md#running-the-hosted-part)). They are listed under
    "Not run" below.

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
      against 3,464 ([text calibration](../evals/text-scoring.md#calibration)).
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

## Rank 1 at no more context (#575)

Grounded Docs put a section that answers first more often than ExactDocs' search did before #575
(recall@1 71.5% with `bge-small-en-v1.5` against 58.8%, [Comparison](comparison.md)), with
results about three times as long. The
[retrieval grid](../evals/retrieval-grid.md) measured the variants that could close that gap,
for BM25 and for hybrid search on `bge-small-en-v1.5`, each scored from its text and tested
against its control (the grid's own search at `default`, which scores as the shipped BM25 does)
and against the shipped default, BM25 at `default`:

- **The heading path in the text**, in front of the indexed text (`+context-indexed`) or of the
  embedded text (`+context-embedded`; ExactDocs' own vector index already embeds the title and the
  heading path).
- **A hit widened to its section**: its parent section with the subsections (`+parent`).
- **The hits grouped by article**, as Grounded Docs groups them: one result per article, ranked by
  its best hit, holding the article's hits in article order, with the chunk on either side of each
  (`+article`) or the hits alone (`+article-hits`, the same ten chunks as the control).

`packages/exactdocs/evals/results/retrieval-grid-rank1.json`, run on 25 November 2026 on 4 shared
CPUs (Linux x86_64) with `just retrieval-grid --offline --cells ...` (the cells are in
`evals/golden/matrix.yaml`, each naming its control). The app cell `hybrid:bge-small-en-v1.5` is
ExactDocs' own hybrid search at `default`, run again on that machine for its context. Every cell
here returns one chunk per result except the grouping variants, and the run predates #571.

**What it shows:**

- **Grouping the hits by article wins at rank 1, with the same context.** `+article-hits` returns
  the same ten chunks as its control, one result per article:

    | | BM25 | `+article-hits` | hybrid, bge-small | `+article-hits` | Grounded Docs, bge-small |
    |---|---|---|---|---|---|
    | recall@1 | 58.8% | **70.8%** | 65.9% | **78.3%** | 71.5% |
    | recall@5 | 87.6% | **91.0%** | 90.6% | **93.3%** | 85.8% |
    | recall@10 | 93.3% | 93.3% | 94.0% | 94.0% | 89.1% |
    | context tokens / question | 3,437 | 3,440 | 3,121 | 3,119 | 7,360 |

    - Against its control, recall@1 gains 12.0 points with BM25 and 12.4 with hybrid search, and
      recall@5 3.4 and 2.6 points, all significant (p 0.008 or under); recall@10 does not move,
      since the ten chunks are the same.
    - The same holds on top of the embedded heading path, the form of hybrid search ExactDocs ships
      (`+context-embedded+article-hits`: recall@1 75.7%, +12.4 points; recall@5 94.0%, +3.0).
- **But the answer then sits further into what is returned.** A result now holds several chunks,
  so recall within a token budget falls against the control: BM25 `+article-hits` finds the
  answer within 1,000 tokens in 43.5% of the cases (78.3% without grouping), within 2,000 in 71.5%
  (89.1%), whole results; with the text cut at the budget, 67.8% and 84.6%. It still finds it more
  often than Grounded Docs at every budget, under both rules (Grounded Docs with bge-small: 34.5%,
  58.8%, 75.7% whole; 58.4%, 73.0%, 82.4% cut).
- **With the neighbouring chunks (`+article`)** rank 1 gains a little more (BM25 72.3%, hybrid
  79.0%) and recall@5 too (92.9%, 94.4%), but the context doubles (6,881 and 6,239 tokens per
  question), and within 1,000 and 2,000 tokens it falls below Grounded Docs (BM25 23.2% and 52.8%,
  whole results).
- **Widening a hit to its parent section (`+parent`)** gains at rank 1 too (BM25 +4.5 points,
  hybrid +5.2), at four times the context (14,232 and 12,832 tokens per question), and loses at
  every budget.
- **The heading path in the text does nothing measurable.** In front of the indexed text:
  BM25 +0.8 points of recall@1 (p 0.38), hybrid +0.0; in front of the embedded text: hybrid
  -2.6 (p 0.13); both: -1.1 (p 0.56). ExactDocs' own index already weights the heading path for
  BM25 and embeds it for vectors.
- **Smaller chunks do not help the grouping**: `h6/bm25+article` reaches 70.4% at rank 1, below
  `default/bm25+article` (72.3%). The `h6` hybrid cells were not run (each embeds the corpus at
  `h6` again, about 40 minutes on this machine).

So grouping by article, the hits alone, is the variant that wins at rank 1 without losing recall@5
or adding context. ExactDocs' search groups its results so since #575
([below](#grouped-by-article-575)), and the benchmark reports recall within a token budget next
to recall@1, since grouping trades one for the other.

<!-- bench:retrieval-grid -->
- Golden set: 321 cases, fingerprint `sha256:a00997851150e3b0`; ExactDocs commit `01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11`, Python 3.14.6, Linux x86_64, 4 CPUs.

#### Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 58.8% [52.8, 64.8] | 87.6% [83.5, 91.4] | 93.6% [90.6, 96.2] | 0.711 [0.666, 0.754] | 0.714 [0.676, 0.751] | 0 | 100.0% / 0.0% | 0.0% | 84.8 | 147.1 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 64.4% [58.8, 70.0] | 90.3% [86.5, 93.6] | 93.6% [90.6, 96.2] | 0.756 [0.714, 0.797] | 0.749 [0.713, 0.785] | 0 | 100.0% / 0.0% | 0.0% | 148.8 | 217.3 | 22 | 0.0000 | 3208 |
| `default/bm25` | `default` | none | ran | 58.8% [52.8, 64.8] | 87.6% [83.5, 91.4] | 93.3% [90.3, 95.9] | 0.710 [0.664, 0.754] | 0.714 [0.675, 0.751] | 0 | 100.0% / 0.0% | 0.0% | 16.3 | 23.3 | 0 | 0.0000 | 6 |
| `default/hybrid:bge-small` | `default` | local | ran | 65.9% [60.3, 71.5] | 90.6% [86.9, 94.0] | 94.0% [91.0, 96.6] | 0.765 [0.723, 0.805] | 0.755 [0.718, 0.791] | 0 | 100.0% / 0.0% | 0.0% | 41.0 | 71.6 | 22 | 0.0000 | 2389 |
| `default/bm25+context-indexed` | `default` | none | ran | 59.6% [53.6, 65.5] | 87.6% [83.5, 91.4] | 94.4% [91.8, 97.0] | 0.714 [0.669, 0.758] | 0.717 [0.679, 0.754] | 0 | 100.0% / 0.0% | 0.0% | 17.2 | 26.9 | 0 | 0.0000 | 6 |
| `default/hybrid:bge-small+context-indexed` | `default` | local | ran | 65.9% [60.3, 71.5] | 91.0% [87.6, 94.4] | 94.4% [91.4, 97.0] | 0.769 [0.727, 0.809] | 0.760 [0.723, 0.795] | 0 | 100.0% / 0.0% | 0.0% | 43.9 | 58.6 | 22 | 0.0000 | 2390 |
| `default/hybrid:bge-small+context-embedded` | `default` | local | ran | 63.3% [57.7, 69.3] | 91.0% [87.6, 94.4] | 94.0% [91.0, 96.6] | 0.751 [0.710, 0.792] | 0.747 [0.710, 0.783] | 0 | 100.0% / 0.0% | 0.0% | 41.1 | 62.4 | 22 | 0.0000 | 2300 |
| `h6/bm25+parent` | `h6` | none | ran | 62.2% [56.2, 68.2] | 88.8% [85.0, 92.1] | 94.8% [92.1, 97.0] | 0.732 [0.688, 0.775] | 0.734 [0.697, 0.770] | 0 | 100.0% / 0.0% | 0.0% | 21.7 | 33.3 | 0 | 0.0000 | 6 |
| `default/bm25+parent` | `default` | none | ran | 63.3% [57.3, 69.3] | 91.0% [87.3, 94.4] | 95.5% [92.9, 97.8] | 0.749 [0.707, 0.791] | 0.748 [0.713, 0.783] | 0 | 100.0% / 0.0% | 0.0% | 18.5 | 28.9 | 0 | 0.0000 | 6 |
| `default/bm25+article` | `default` | none | ran | 72.3% [66.7, 77.5] | 92.9% [89.5, 95.9] | 95.9% [93.3, 98.1] | 0.812 [0.773, 0.850] | 0.779 [0.745, 0.812] | 0 | 100.0% / 0.0% | 0.0% | 18.0 | 28.1 | 0 | 0.0000 | 6 |
| `default/bm25+article-hits` | `default` | none | ran | 70.8% [65.2, 76.4] | 91.0% [87.6, 94.4] | 93.3% [90.3, 95.9] | 0.794 [0.753, 0.835] | 0.758 [0.721, 0.794] | 0 | 100.0% / 0.0% | 0.0% | 21.5 | 31.5 | 0 | 0.0000 | 6 |
| `default/bm25+context-indexed+article` | `default` | none | ran | 73.4% [68.2, 78.6] | 93.3% [90.3, 95.9] | 95.9% [93.3, 98.1] | 0.817 [0.778, 0.855] | 0.780 [0.745, 0.814] | 0 | 100.0% / 0.0% | 0.0% | 19.8 | 48.1 | 0 | 0.0000 | 8 |
| `h6/bm25+article` | `h6` | none | ran | 70.4% [64.8, 76.0] | 91.8% [88.4, 94.8] | 94.8% [92.1, 97.4] | 0.795 [0.754, 0.834] | 0.760 [0.724, 0.795] | 0 | 100.0% / 0.0% | 0.0% | 19.4 | 27.4 | 0 | 0.0000 | 6 |
| `default/hybrid:bge-small+context` | `default` | local | ran | 64.8% [59.2, 70.4] | 91.4% [88.0, 94.8] | 94.8% [92.1, 97.4] | 0.763 [0.722, 0.804] | 0.757 [0.721, 0.792] | 0 | 100.0% / 0.0% | 0.0% | 42.7 | 66.8 | 22 | 0.0000 | 2300 |
| `default/hybrid:bge-small+parent` | `default` | local | ran | 71.2% [65.9, 76.4] | 92.9% [89.5, 95.9] | 95.9% [93.3, 98.1] | 0.806 [0.767, 0.844] | 0.786 [0.753, 0.819] | 0 | 100.0% / 0.0% | 0.0% | 41.7 | 57.8 | 22 | 0.0000 | 2389 |
| `default/hybrid:bge-small+article` | `default` | local | ran | 79.0% [74.2, 83.9] | 94.4% [91.4, 97.0] | 95.5% [92.9, 97.8] | 0.859 [0.824, 0.893] | 0.812 [0.779, 0.844] | 0 | 100.0% / 0.0% | 0.0% | 38.0 | 58.7 | 22 | 0.0000 | 2390 |
| `default/hybrid:bge-small+article-hits` | `default` | local | ran | 78.3% [73.4, 83.2] | 93.3% [90.3, 96.2] | 94.0% [91.0, 96.6] | 0.849 [0.812, 0.884] | 0.798 [0.763, 0.831] | 0 | 100.0% / 0.0% | 0.0% | 35.5 | 51.7 | 22 | 0.0000 | 2388 |
| `default/hybrid:bge-small+context-embedded+article` | `default` | local | ran | 76.4% [71.5, 81.7] | 95.5% [92.9, 97.8] | 95.5% [92.9, 97.8] | 0.845 [0.810, 0.880] | 0.804 [0.771, 0.837] | 0 | 100.0% / 0.0% | 0.0% | 45.2 | 67.6 | 22 | 0.0000 | 2301 |
| `default/hybrid:bge-small+context-embedded+article-hits` | `default` | local | ran | 75.7% [70.4, 80.9] | 94.0% [91.0, 96.6] | 94.0% [91.0, 96.6] | 0.836 [0.798, 0.872] | 0.790 [0.754, 0.824] | 0 | 100.0% / 0.0% | 0.0% | 46.1 | 66.1 | 22 | 0.0000 | 2301 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489).

#### Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `hybrid:bge-small-en-v1.5` | `default` | local | `bm25` at `default` | **+5.6** [+1.1, +10.5], p 0.023 | +2.6 [-0.8, +6.0], p 0.13 | +0.0 [-3.0, +3.0], p 1 | **+0.045** [+0.013, +0.077], p 0.0052 | **+0.035** [+0.007, +0.062], p 0.013 |
| `default/bm25` | `default` | none | `bm25` at `default` | +0.0 [-1.1, +1.1], p 1 | +0.0 [+0.0, +0.0], p 1 | -0.4 [-1.1, +0.0], p 0.5 | -0.001 [-0.007, +0.004], p 0.55 | -0.001 [-0.005, +0.003], p 0.77 |
| `default/hybrid:bge-small` | `default` | local | `bm25` at `default` | **+7.1** [+1.9, +12.7], p 0.01 | +3.0 [-0.4, +6.4], p 0.078 | +0.4 [-2.6, +3.4], p 0.8 | **+0.054** [+0.020, +0.088], p 0.002 | **+0.041** [+0.014, +0.069], p 0.0039 |
| `default/bm25+context-indexed` | `default` | none | `bm25` at `default` | +0.8 [-0.8, +2.2], p 0.38 | +0.0 [-1.1, +1.1], p 1 | +0.8 [-0.8, +2.2], p 0.38 | +0.003 [-0.005, +0.012], p 0.47 | +0.003 [-0.005, +0.011], p 0.49 |
| `default/hybrid:bge-small+context-indexed` | `default` | local | `bm25` at `default` | **+7.1** [+1.9, +12.4], p 0.01 | +3.4 [+0.0, +6.7], p 0.052 | +0.8 [-1.9, +3.4], p 0.61 | **+0.058** [+0.023, +0.093], p 0.0014 | **+0.046** [+0.018, +0.074], p 0.0015 |
| `default/hybrid:bge-small+context-embedded` | `default` | local | `bm25` at `default` | +4.5 [+0.0, +9.0], p 0.06 | +3.4 [+0.0, +6.7], p 0.052 | +0.4 [-2.6, +3.4], p 0.8 | **+0.041** [+0.011, +0.071], p 0.0079 | **+0.032** [+0.007, +0.058], p 0.015 |
| `h6/bm25+parent` | `h6` | none | `bm25` at `default` | +3.4 [+0.0, +7.1], p 0.076 | +1.1 [-1.1, +3.8], p 0.39 | +1.1 [-0.8, +3.0], p 0.29 | +0.022 [+0.000, +0.044], p 0.057 | **+0.020** [+0.002, +0.038], p 0.033 |
| `default/bm25+parent` | `default` | none | `bm25` at `default` | **+4.5** [+2.2, +7.1], p < 0.001 | **+3.4** [+1.5, +5.6], p 0.002 | **+1.9** [+0.4, +3.8], p 0.031 | **+0.038** [+0.023, +0.056], p < 0.001 | **+0.034** [+0.020, +0.050], p < 0.001 |
| `default/bm25+article` | `default` | none | `bm25` at `default` | **+13.5** [+9.7, +17.6], p < 0.001 | **+5.2** [+2.6, +7.9], p < 0.001 | **+2.2** [+0.8, +4.1], p 0.016 | **+0.101** [+0.075, +0.130], p < 0.001 | **+0.065** [+0.043, +0.088], p < 0.001 |
| `default/bm25+article-hits` | `default` | none | `bm25` at `default` | **+12.0** [+8.2, +16.1], p < 0.001 | **+3.4** [+1.5, +5.6], p 0.002 | -0.4 [-1.1, +0.0], p 0.5 | **+0.084** [+0.060, +0.109], p < 0.001 | **+0.044** [+0.026, +0.063], p < 0.001 |
| `default/bm25+context-indexed+article` | `default` | none | `bm25` at `default` | **+14.6** [+10.5, +19.1], p < 0.001 | **+5.6** [+3.0, +8.6], p < 0.001 | **+2.2** [+0.4, +4.5], p 0.039 | **+0.106** [+0.077, +0.137], p < 0.001 | **+0.065** [+0.042, +0.090], p < 0.001 |
| `h6/bm25+article` | `h6` | none | `bm25` at `default` | **+11.6** [+7.1, +16.5], p < 0.001 | **+4.1** [+1.5, +7.1], p 0.0042 | +1.1 [-1.1, +3.4], p 0.34 | **+0.084** [+0.054, +0.115], p < 0.001 | **+0.046** [+0.022, +0.070], p < 0.001 |
| `default/hybrid:bge-small+context` | `default` | local | `bm25` at `default` | **+6.0** [+1.1, +10.9], p 0.016 | **+3.8** [+0.4, +7.1], p 0.035 | +1.1 [-1.9, +4.1], p 0.48 | **+0.052** [+0.020, +0.085], p 0.0013 | **+0.043** [+0.015, +0.070], p 0.0021 |
| `default/hybrid:bge-small+parent` | `default` | local | `bm25` at `default` | **+12.4** [+7.1, +18.0], p < 0.001 | **+5.2** [+1.9, +9.0], p 0.0041 | +2.2 [-0.8, +5.2], p 0.17 | **+0.095** [+0.060, +0.131], p < 0.001 | **+0.072** [+0.043, +0.101], p < 0.001 |
| `default/hybrid:bge-small+article` | `default` | local | `bm25` at `default` | **+20.2** [+14.6, +26.2], p < 0.001 | **+6.7** [+3.8, +10.1], p < 0.001 | +1.9 [-0.8, +4.9], p 0.21 | **+0.148** [+0.112, +0.186], p < 0.001 | **+0.098** [+0.067, +0.128], p < 0.001 |
| `default/hybrid:bge-small+article-hits` | `default` | local | `bm25` at `default` | **+19.5** [+13.9, +25.1], p < 0.001 | **+5.6** [+2.2, +9.0], p < 0.001 | +0.4 [-2.6, +3.4], p 0.8 | **+0.138** [+0.101, +0.175], p < 0.001 | **+0.084** [+0.054, +0.114], p < 0.001 |
| `default/hybrid:bge-small+context-embedded+article` | `default` | local | `bm25` at `default` | **+17.6** [+12.4, +23.2], p < 0.001 | **+7.9** [+4.5, +11.2], p < 0.001 | +1.9 [-1.1, +4.9], p 0.24 | **+0.134** [+0.099, +0.171], p < 0.001 | **+0.090** [+0.060, +0.121], p < 0.001 |
| `default/hybrid:bge-small+context-embedded+article-hits` | `default` | local | `bm25` at `default` | **+16.9** [+11.6, +22.5], p < 0.001 | **+6.4** [+3.4, +9.7], p < 0.001 | +0.4 [-2.6, +3.4], p 0.8 | **+0.125** [+0.090, +0.160], p < 0.001 | **+0.075** [+0.046, +0.105], p < 0.001 |

#### Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text returned, the results read whole and in order: a case counts when the result that first answers it ends within the budget (#575). Cut: scored from the text only, the text cut at the budget, so the result the budget cuts counts when its part within the budget answers. Context: the estimated tokens of all the text returned per question (each chunk's content); to the first hit: up to and including the first result that answers. In brackets: the 95% interval. Against: the budget's default, the difference in points and the p-value of McNemar's test (mid-p), **bold** when significant.

| configuration | chunking | context tokens / q | tokens to first hit | within 1,000 | within 2,000 | within 4,000 | cut at 1,000 | cut at 2,000 | cut at 4,000 | against | 1,000 | 2,000 | 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 3,464 [3,320, 3,614] | 656 [571, 745] | 78.3% [73.4, 83.2] | 88.8% [85.0, 92.1] | 93.6% [90.6, 96.2] | - | - | - | - | - | - | - |
| `hybrid:bge-small-en-v1.5` | `default` | 3,202 [3,068, 3,336] | 575 [497, 656] | 80.9% [76.0, 85.8] | 89.1% [85.4, 92.5] | 93.6% [90.6, 96.2] | - | - | - | `bm25` at `default` | +2.6 [-1.5, +6.7], p 0.22 | +0.4 [-2.6, +3.8], p 0.82 | +0.0 [-3.0, +3.0], p 1 |
| `default/bm25` | `default` | 3,437 [3,292, 3,586] | 646 [564, 736] | 78.3% [73.4, 83.2] | 89.1% [85.4, 92.5] | 93.3% [90.3, 95.9] | 83.2% [78.6, 87.6] | 90.6% [87.3, 94.0] | 93.3% [90.3, 95.9] | `bm25` at `default` | +0.0 [+0.0, +0.0], p 1 | +0.4 [+0.0, +1.1], p 0.5 | -0.4 [-1.1, +0.0], p 0.5 |
| `default/hybrid:bge-small` | `default` | 3,121 [2,986, 3,258] | 569 [489, 653] | 81.7% [76.8, 86.1] | 89.5% [85.8, 92.9] | 93.3% [90.3, 96.2] | 89.1% [85.4, 92.9] | 91.8% [88.4, 94.8] | 93.6% [90.6, 96.2] | `bm25` at `default` | +3.4 [-1.1, +7.9], p 0.13 | +0.8 [-2.2, +3.8], p 0.65 | -0.4 [-3.4, +2.6], p 0.8 |
| `default/bm25+context-indexed` | `default` | 3,484 [3,336, 3,636] | 677 [587, 774] | 78.6% [73.8, 83.5] | 89.1% [85.4, 92.9] | 94.0% [91.0, 96.6] | 84.3% [79.8, 88.4] | 90.6% [87.3, 94.0] | 94.4% [91.8, 97.0] | `bm25` at `default` | +0.4 [+0.0, +1.1], p 0.5 | +0.4 [-0.8, +1.9], p 0.62 | +0.4 [-0.8, +1.9], p 0.62 |
| `default/hybrid:bge-small+context-indexed` | `default` | 3,123 [2,988, 3,259] | 567 [487, 653] | 81.7% [76.8, 86.1] | 89.9% [86.1, 93.3] | 93.6% [90.6, 96.2] | 89.5% [85.8, 92.9] | 92.1% [88.8, 95.1] | 94.0% [91.0, 96.6] | `bm25` at `default` | +3.4 [-1.1, +7.9], p 0.13 | +1.1 [-1.9, +4.5], p 0.5 | +0.0 [-3.0, +3.0], p 1 |
| `default/hybrid:bge-small+context-embedded` | `default` | 3,218 [3,080, 3,353] | 590 [511, 674] | 80.9% [76.0, 85.8] | 89.1% [85.4, 92.5] | 93.6% [90.6, 96.2] | 86.5% [82.4, 90.6] | 92.5% [89.1, 95.5] | 93.6% [90.6, 96.2] | `bm25` at `default` | +2.6 [-1.1, +6.7], p 0.18 | +0.4 [-2.6, +3.8], p 0.82 | +0.0 [-3.0, +3.0], p 1 |
| `h6/bm25+parent` | `h6` | 12,448 [11,547, 13,412] | 2,626 [2,168, 3,122] | 47.9% [41.9, 53.9] | 62.9% [57.3, 68.5] | 74.2% [68.9, 79.4] | 58.1% [52.1, 64.0] | 71.2% [65.5, 76.4] | 82.4% [77.9, 86.5] | `bm25` at `default` | **-30.3** [-36.3, -24.7], p < 0.001 | **-25.8** [-31.5, -20.6], p < 0.001 | **-19.5** [-24.3, -14.6], p < 0.001 |
| `default/bm25+parent` | `default` | 14,232 [13,111, 15,430] | 2,616 [2,185, 3,073] | 49.1% [43.1, 55.1] | 60.7% [54.7, 66.7] | 72.7% [67.4, 77.9] | 58.1% [52.1, 64.0] | 68.9% [63.3, 74.5] | 82.4% [77.9, 86.9] | `bm25` at `default` | **-29.2** [-34.8, -23.6], p < 0.001 | **-28.1** [-33.7, -22.9], p < 0.001 | **-21.0** [-25.8, -16.1], p < 0.001 |
| `default/bm25+article` | `default` | 6,881 [6,616, 7,147] | 2,640 [2,374, 2,908] | 23.2% [18.4, 28.5] | 52.8% [46.8, 58.8] | 76.0% [70.8, 80.9] | 49.1% [43.1, 55.1] | 72.7% [67.4, 77.9] | 85.4% [81.3, 89.5] | `bm25` at `default` | **-55.1** [-61.1, -49.1], p < 0.001 | **-36.0** [-41.9, -30.0], p < 0.001 | **-17.6** [-22.5, -12.7], p < 0.001 |
| `default/bm25+article-hits` | `default` | 3,440 [3,295, 3,589] | 1,424 [1,284, 1,568] | 43.5% [37.5, 49.4] | 71.5% [66.3, 77.1] | 89.5% [85.8, 92.9] | 67.8% [62.2, 73.4] | 84.6% [80.2, 88.8] | 92.1% [88.8, 95.1] | `bm25` at `default` | **-34.8** [-40.8, -28.8], p < 0.001 | **-17.2** [-22.1, -12.4], p < 0.001 | **-4.1** [-6.7, -1.9], p < 0.001 |
| `default/bm25+context-indexed+article` | `default` | 6,937 [6,661, 7,210] | 2,735 [2,458, 3,027] | 24.0% [19.1, 29.6] | 50.9% [44.9, 56.9] | 74.5% [69.3, 79.8] | 50.6% [44.6, 56.5] | 71.9% [66.3, 77.5] | 83.9% [79.4, 88.0] | `bm25` at `default` | **-54.3** [-60.3, -48.3], p < 0.001 | **-37.8** [-43.8, -31.8], p < 0.001 | **-19.1** [-24.0, -14.2], p < 0.001 |
| `h6/bm25+article` | `h6` | 5,777 [5,536, 6,026] | 2,354 [2,122, 2,597] | 25.8% [20.6, 31.5] | 56.5% [50.6, 62.5] | 77.9% [73.0, 82.8] | 50.9% [44.9, 56.9] | 73.8% [68.5, 79.0] | 85.8% [81.7, 89.9] | `bm25` at `default` | **-52.4** [-58.4, -46.4], p < 0.001 | **-32.2** [-37.8, -26.6], p < 0.001 | **-15.7** [-20.6, -11.2], p < 0.001 |
| `default/hybrid:bge-small+context` | `default` | 3,235 [3,097, 3,372] | 598 [515, 686] | 81.7% [77.1, 86.1] | 89.5% [85.8, 92.9] | 94.4% [91.4, 97.0] | 87.3% [83.2, 91.0] | 92.5% [89.1, 95.5] | 94.4% [91.4, 97.0] | `bm25` at `default` | +3.4 [-0.4, +7.5], p 0.099 | +0.8 [-2.6, +4.1], p 0.68 | +0.8 [-2.2, +3.8], p 0.65 |
| `default/hybrid:bge-small+parent` | `default` | 12,832 [11,725, 14,034] | 2,138 [1,805, 2,487] | 52.1% [46.1, 58.1] | 65.5% [59.9, 71.5] | 76.0% [71.2, 81.3] | 65.2% [59.6, 71.2] | 75.7% [70.4, 80.9] | 86.5% [82.4, 90.6] | `bm25` at `default` | **-26.2** [-32.2, -20.2], p < 0.001 | **-23.2** [-28.8, -17.6], p < 0.001 | **-17.6** [-22.9, -12.4], p < 0.001 |
| `default/hybrid:bge-small+article` | `default` | 6,239 [5,979, 6,501] | 2,358 [2,134, 2,588] | 25.5% [20.2, 31.1] | 53.9% [47.9, 59.9] | 77.5% [72.3, 82.4] | 53.6% [47.6, 59.6] | 76.8% [71.5, 81.7] | 89.9% [86.1, 93.3] | `bm25` at `default` | **-52.8** [-59.2, -46.4], p < 0.001 | **-34.8** [-40.8, -28.5], p < 0.001 | **-16.1** [-21.7, -10.9], p < 0.001 |
| `default/hybrid:bge-small+article-hits` | `default` | 3,119 [2,984, 3,256] | 1,320 [1,197, 1,439] | 45.3% [39.3, 51.3] | 76.8% [71.5, 81.7] | 92.1% [88.8, 95.1] | 70.4% [65.2, 75.7] | 86.1% [82.0, 90.3] | 93.6% [90.6, 96.2] | `bm25` at `default` | **-33.0** [-39.7, -26.2], p < 0.001 | **-12.0** [-17.2, -6.7], p < 0.001 | -1.5 [-4.5, +1.5], p 0.36 |
| `default/hybrid:bge-small+context-embedded+article` | `default` | 6,115 [5,865, 6,371] | 2,381 [2,164, 2,600] | 23.2% [18.4, 28.5] | 52.4% [46.8, 58.4] | 79.0% [74.2, 83.9] | 52.4% [46.4, 58.4] | 75.3% [70.0, 80.5] | 89.1% [85.4, 92.9] | `bm25` at `default` | **-55.1** [-61.4, -48.7], p < 0.001 | **-36.3** [-42.3, -30.3], p < 0.001 | **-14.6** [-19.9, -9.4], p < 0.001 |
| `default/hybrid:bge-small+context-embedded+article-hits` | `default` | 3,213 [3,076, 3,349] | 1,398 [1,273, 1,529] | 43.8% [37.8, 49.8] | 75.3% [70.0, 80.5] | 91.0% [87.3, 94.4] | 68.9% [63.3, 74.2] | 85.8% [81.7, 89.9] | 93.6% [90.6, 96.2] | `bm25` at `default` | **-34.5** [-41.6, -27.7], p < 0.001 | **-13.5** [-18.7, -8.2], p < 0.001 | -2.6 [-6.0, +0.8], p 0.13 |

#### Against each variant's control

Each variant against the cell it varies (`against` in the grid file), on the answerable cases both answered: the difference (recall in points, MRR and nDCG@10 as scores), its paired bootstrap interval and the p-value (McNemar's test, mid-p, for recall; a sign-flip permutation test for MRR and nDCG@10). **Bold**: significant at 5%.

| cell | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | within 1,000 | within 2,000 | within 4,000 | cut at 1,000 | cut at 2,000 | cut at 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `default/bm25+context-indexed` | `default/bm25` | +0.8 [-0.8, +2.2], p 0.38 | +0.0 [-1.1, +1.1], p 1 | +1.1 [-0.4, +3.0], p 0.22 | +0.005 [-0.004, +0.013], p 0.29 | +0.003 [-0.004, +0.011], p 0.43 | +0.4 [+0.0, +1.1], p 0.5 | +0.0 [-1.5, +1.5], p 1 | +0.8 [-0.8, +2.2], p 0.38 | +1.1 [+0.0, +2.6], p 0.12 | +0.0 [-1.5, +1.5], p 1 | +1.1 [-0.4, +3.0], p 0.22 |
| `default/hybrid:bge-small+context-indexed` | `default/hybrid:bge-small` | +0.0 [-1.9, +1.9], p 1 | +0.4 [+0.0, +1.1], p 0.5 | +0.4 [+0.0, +1.1], p 0.5 | +0.004 [-0.006, +0.014], p 0.44 | +0.005 [-0.003, +0.013], p 0.25 | +0.0 [+0.0, +0.0], p 1 | +0.4 [+0.0, +1.1], p 0.5 | +0.4 [-0.8, +1.9], p 0.62 | +0.4 [+0.0, +1.1], p 0.5 | +0.4 [+0.0, +1.1], p 0.5 | +0.4 [+0.0, +1.1], p 0.5 |
| `default/hybrid:bge-small+context-embedded` | `default/hybrid:bge-small` | -2.6 [-6.0, +0.8], p 0.13 | +0.4 [-0.8, +1.9], p 0.62 | +0.0 [-1.1, +1.1], p 1 | -0.013 [-0.032, +0.005], p 0.15 | -0.009 [-0.022, +0.004], p 0.2 | -0.8 [-3.4, +1.9], p 0.58 | -0.4 [-1.9, +0.8], p 0.62 | +0.4 [-0.8, +1.9], p 0.62 | **-2.6** [-4.9, -0.8], p 0.021 | +0.8 [+0.0, +1.9], p 0.25 | +0.0 [-1.1, +1.1], p 1 |
| `h6/bm25+parent` | `default/bm25` | +3.4 [-0.4, +7.1], p 0.087 | +1.1 [-1.1, +3.8], p 0.39 | +1.5 [-0.4, +3.8], p 0.18 | **+0.023** [+0.001, +0.046], p 0.05 | **+0.021** [+0.003, +0.039], p 0.032 | **-30.3** [-36.3, -24.7], p < 0.001 | **-26.2** [-31.8, -21.0], p < 0.001 | **-19.1** [-24.0, -14.2], p < 0.001 | **-25.1** [-30.7, -19.5], p < 0.001 | **-19.5** [-24.3, -14.6], p < 0.001 | **-10.9** [-15.0, -7.1], p < 0.001 |
| `default/bm25+parent` | `default/bm25` | **+4.5** [+2.2, +7.1], p < 0.001 | **+3.4** [+1.5, +5.6], p 0.002 | **+2.2** [+0.8, +4.1], p 0.016 | **+0.040** [+0.024, +0.057], p < 0.001 | **+0.035** [+0.020, +0.051], p < 0.001 | **-29.2** [-34.8, -23.6], p < 0.001 | **-28.5** [-34.1, -23.2], p < 0.001 | **-20.6** [-25.5, -15.7], p < 0.001 | **-25.1** [-30.7, -19.5], p < 0.001 | **-21.7** [-27.0, -16.9], p < 0.001 | **-10.9** [-14.6, -7.1], p < 0.001 |
| `default/bm25+article` | `default/bm25` | **+13.5** [+9.7, +17.6], p < 0.001 | **+5.2** [+2.6, +7.9], p < 0.001 | **+2.6** [+1.1, +4.5], p 0.0078 | **+0.102** [+0.076, +0.132], p < 0.001 | **+0.066** [+0.043, +0.089], p < 0.001 | **-55.1** [-61.1, -49.1], p < 0.001 | **-36.3** [-42.3, -30.3], p < 0.001 | **-17.2** [-22.1, -12.4], p < 0.001 | **-34.1** [-40.1, -28.1], p < 0.001 | **-18.0** [-23.2, -13.1], p < 0.001 | **-7.9** [-11.6, -4.5], p < 0.001 |
| `default/bm25+article-hits` | `default/bm25` | **+12.0** [+8.2, +16.1], p < 0.001 | **+3.4** [+1.5, +5.6], p 0.002 | +0.0 [+0.0, +0.0], p 1 | **+0.085** [+0.061, +0.110], p < 0.001 | **+0.044** [+0.026, +0.063], p < 0.001 | **-34.8** [-40.8, -28.8], p < 0.001 | **-17.6** [-22.5, -12.7], p < 0.001 | **-3.8** [-6.0, -1.5], p < 0.001 | **-15.4** [-20.2, -10.5], p < 0.001 | **-6.0** [-9.4, -3.0], p < 0.001 | -1.1 [-2.6, +0.0], p 0.12 |
| `default/bm25+context-indexed+article` | `default/bm25+context-indexed` | **+13.9** [+9.7, +18.4], p < 0.001 | **+5.6** [+3.0, +8.6], p < 0.001 | +1.5 [+0.4, +3.0], p 0.062 | **+0.103** [+0.076, +0.132], p < 0.001 | **+0.063** [+0.041, +0.086], p < 0.001 | **-54.7** [-60.7, -48.7], p < 0.001 | **-38.2** [-44.2, -32.2], p < 0.001 | **-19.5** [-24.3, -14.6], p < 0.001 | **-33.7** [-39.7, -27.7], p < 0.001 | **-18.7** [-23.6, -13.5], p < 0.001 | **-10.5** [-14.6, -6.7], p < 0.001 |
| `h6/bm25+article` | `default/bm25` | **+11.6** [+7.1, +16.5], p < 0.001 | **+4.1** [+1.5, +7.1], p 0.0042 | +1.5 [-0.8, +3.8], p 0.23 | **+0.085** [+0.055, +0.116], p < 0.001 | **+0.046** [+0.022, +0.071], p < 0.001 | **-52.4** [-58.4, -46.4], p < 0.001 | **-32.6** [-38.6, -27.0], p < 0.001 | **-15.4** [-19.9, -10.9], p < 0.001 | **-32.2** [-38.2, -26.6], p < 0.001 | **-16.9** [-21.7, -12.0], p < 0.001 | **-7.5** [-11.2, -4.1], p < 0.001 |
| `default/hybrid:bge-small+context` | `default/hybrid:bge-small` | -1.1 [-4.9, +2.6], p 0.56 | +0.8 [-0.8, +2.2], p 0.38 | +0.8 [-0.8, +2.2], p 0.38 | -0.002 [-0.023, +0.019], p 0.88 | +0.002 [-0.014, +0.017], p 0.83 | +0.0 [-2.6, +2.6], p 1 | +0.0 [-1.5, +1.5], p 1 | +1.1 [-0.4, +3.0], p 0.22 | -1.9 [-4.1, +0.4], p 0.11 | +0.8 [+0.0, +1.9], p 0.25 | +0.8 [-0.8, +2.2], p 0.38 |
| `default/hybrid:bge-small+parent` | `default/hybrid:bge-small` | **+5.2** [+2.6, +8.2], p < 0.001 | **+2.2** [+0.8, +4.1], p 0.016 | **+1.9** [+0.4, +3.8], p 0.031 | **+0.041** [+0.024, +0.060], p < 0.001 | **+0.031** [+0.016, +0.047], p < 0.001 | **-29.6** [-35.2, -24.0], p < 0.001 | **-24.0** [-29.2, -18.7], p < 0.001 | **-17.2** [-22.1, -12.4], p < 0.001 | **-24.0** [-29.2, -18.7], p < 0.001 | **-16.1** [-20.6, -12.0], p < 0.001 | **-7.1** [-10.5, -4.1], p < 0.001 |
| `default/hybrid:bge-small+article` | `default/hybrid:bge-small` | **+13.1** [+9.4, +17.2], p < 0.001 | **+3.8** [+1.5, +6.0], p < 0.001 | +1.5 [+0.4, +3.0], p 0.062 | **+0.094** [+0.068, +0.123], p < 0.001 | **+0.057** [+0.034, +0.080], p < 0.001 | **-56.2** [-62.2, -50.2], p < 0.001 | **-35.6** [-41.6, -29.6], p < 0.001 | **-15.7** [-20.6, -11.2], p < 0.001 | **-35.6** [-41.6, -29.6], p < 0.001 | **-15.0** [-19.5, -10.5], p < 0.001 | **-3.8** [-6.7, -0.8], p 0.019 |
| `default/hybrid:bge-small+article-hits` | `default/hybrid:bge-small` | **+12.4** [+8.6, +16.5], p < 0.001 | **+2.6** [+0.8, +4.9], p 0.0078 | +0.0 [+0.0, +0.0], p 1 | **+0.084** [+0.059, +0.111], p < 0.001 | **+0.043** [+0.023, +0.064], p < 0.001 | **-36.3** [-41.9, -30.7], p < 0.001 | **-12.7** [-16.9, -8.6], p < 0.001 | -1.1 [-3.0, +0.4], p 0.22 | **-18.7** [-23.6, -14.2], p < 0.001 | **-5.6** [-9.0, -2.6], p < 0.001 | +0.0 [-1.1, +1.1], p 1 |
| `default/hybrid:bge-small+context-embedded+article` | `default/hybrid:bge-small+context-embedded` | **+13.1** [+9.0, +17.2], p < 0.001 | **+4.5** [+2.2, +7.1], p < 0.001 | +1.5 [+0.4, +3.0], p 0.062 | **+0.094** [+0.068, +0.122], p < 0.001 | **+0.058** [+0.036, +0.081], p < 0.001 | **-57.7** [-63.7, -51.7], p < 0.001 | **-36.7** [-42.7, -30.7], p < 0.001 | **-14.6** [-19.1, -10.1], p < 0.001 | **-34.1** [-39.7, -28.5], p < 0.001 | **-17.2** [-22.1, -12.7], p < 0.001 | **-4.5** [-7.9, -1.5], p 0.0072 |
| `default/hybrid:bge-small+context-embedded+article-hits` | `default/hybrid:bge-small+context-embedded` | **+12.4** [+8.6, +16.5], p < 0.001 | **+3.0** [+1.1, +5.2], p 0.0039 | +0.0 [+0.0, +0.0], p 1 | **+0.084** [+0.059, +0.110], p < 0.001 | **+0.043** [+0.024, +0.063], p < 0.001 | **-37.1** [-43.1, -31.5], p < 0.001 | **-13.9** [-18.4, -9.4], p < 0.001 | **-2.6** [-4.9, -0.4], p 0.021 | **-17.6** [-22.5, -12.7], p < 0.001 | **-6.7** [-10.1, -3.4], p < 0.001 | +0.0 [-1.1, +1.1], p 1 |

Taken from an earlier run: `bm25@default`, `hybrid:bge-small-en-v1.5@default`, `default/bm25`, `default/hybrid:bge-small`, `default/bm25+context-indexed`, `default/hybrid:bge-small+context-indexed`, `default/hybrid:bge-small+context-embedded`, `h6/bm25+parent`, `default/bm25+parent`, `default/bm25+article`, `default/bm25+article-hits`, `default/bm25+context-indexed+article`, `h6/bm25+article`, `default/hybrid:bge-small+context`, `default/hybrid:bge-small+parent`, `default/hybrid:bge-small+article`, `default/hybrid:bge-small+article-hits`, `default/hybrid:bge-small+context-embedded+article`, `default/hybrid:bge-small+context-embedded+article-hits`.
<!-- /bench -->

<!-- bench:retrieval -->
## Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 70.4% [64.8, 76.0] | 91.0% [87.3, 94.4] | 93.3% [90.3, 96.2] | 0.792 [0.751, 0.833] | 0.754 [0.717, 0.790] | 0 | 100.0% / 0.0% | 0.0% | 99.7 | 133.5 | 0 | 0.0000 | - |
| `bm25+ce` | `default` | local | ran | 62.2% [56.2, 67.8] | 89.5% [85.8, 92.9] | 94.8% [91.8, 97.4] | 0.737 [0.693, 0.779] | 0.732 [0.696, 0.768] | 0 | 100.0% / 0.0% | 0.0% | 2481.9 | 2799.1 | 10945 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 76.0% [70.8, 81.3] | 92.5% [89.1, 95.5] | 93.3% [90.3, 96.2] | 0.832 [0.793, 0.869] | 0.787 [0.750, 0.821] | 0 | 100.0% / 0.0% | 0.0% | 162.8 | 214.0 | 22 | 0.0000 | 3425 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | local | ran | 61.8% [55.8, 67.4] | 88.4% [84.3, 92.1] | 93.3% [89.9, 96.2] | 0.732 [0.688, 0.775] | 0.725 [0.687, 0.761] | 0 | 100.0% / 0.0% | 0.0% | 2513.1 | 2824.6 | 10019 | 0.0000 | 1479 |
| `bm25` | `h6` | none | ran | 68.5% [62.9, 74.2] | 89.9% [86.1, 93.3] | 91.8% [88.4, 94.8] | 0.776 [0.733, 0.817] | 0.734 [0.696, 0.772] | 0 | 100.0% / 0.0% | 0.0% | 145.4 | 192.2 | 0 | 0.0000 | - |
| `bm25+ce` | `h6` | local | ran | 64.0% [58.1, 69.7] | 89.1% [85.0, 92.9] | 94.4% [91.4, 97.0] | 0.749 [0.705, 0.791] | 0.740 [0.702, 0.775] | 0 | 100.0% / 0.0% | 0.0% | 2523.9 | 2824.8 | 9158 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h6` | local | ran | 63.3% [57.3, 69.3] | 90.6% [86.9, 94.0] | 95.1% [92.5, 97.4] | 0.750 [0.707, 0.791] | 0.747 [0.710, 0.783] | 0 | 100.0% / 0.0% | 0.0% | 86.2 | 111.8 | 22 | 0.0000 | 1916 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | local | ran | 63.7% [57.7, 69.3] | 88.4% [84.3, 92.1] | 94.8% [91.8, 97.4] | 0.746 [0.703, 0.788] | 0.739 [0.702, 0.774] | 0 | 100.0% / 0.0% | 0.0% | 2537.1 | 2943.2 | 8569 | 0.0000 | 1916 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | local | ran | 44.6% [38.6, 50.6] | 79.8% [74.9, 84.6] | 88.4% [84.6, 92.1] | 0.595 [0.549, 0.642] | 0.617 [0.577, 0.658] | 0 | 100.0% / 0.0% | 0.0% | 91.0 | 119.9 | 22 | 0.0000 | 2086 |
| `bm25` | `h2` | none | ran | 71.5% [65.9, 77.1] | 92.5% [89.1, 95.5] | 93.6% [90.6, 96.2] | 0.799 [0.757, 0.838] | 0.760 [0.724, 0.796] | 0 | 100.0% / 0.0% | 0.0% | 54.6 | 70.5 | 0 | 0.0000 | - |
| `bm25+ce` | `h2` | local | ran | 56.9% [51.3, 62.9] | 85.4% [81.3, 89.5] | 90.6% [87.3, 94.0] | 0.685 [0.639, 0.730] | 0.679 [0.638, 0.719] | 0 | 100.0% / 0.0% | 0.0% | 2569.3 | 2690.8 | 21844 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h2` | local | ran | 64.4% [58.4, 70.0] | 86.1% [82.0, 90.3] | 91.4% [88.0, 94.8] | 0.741 [0.696, 0.785] | 0.715 [0.675, 0.753] | 0 | 100.0% / 0.0% | 0.0% | 47.3 | 64.0 | 22 | 0.0000 | 861 |
| `bm25` | `merge-400` | none | ran | 70.8% [65.2, 76.4] | 91.4% [88.0, 94.4] | 92.9% [89.9, 95.9] | 0.796 [0.755, 0.837] | 0.757 [0.720, 0.794] | 0 | 100.0% / 0.0% | 0.0% | 80.3 | 102.1 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | ran | 64.8% [59.2, 70.4] | 91.0% [87.6, 94.4] | 94.8% [92.1, 97.4] | 0.764 [0.723, 0.804] | 0.758 [0.721, 0.793] | 0 | 100.0% / 0.0% | 0.0% | 59.6 | 77.8 | 22 | 0.0000 | 1382 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489).

## Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | `bm25` at `h2` | -1.1 [-5.6, +3.0], p 0.62 | -1.5 [-4.1, +1.1], p 0.27 | -0.4 [-3.0, +2.2], p 0.77 | -0.007 [-0.036, +0.022], p 0.65 | -0.007 [-0.030, +0.016], p 0.57 |
| `bm25+ce` | `default` | local | `bm25` at `h2` | **-9.4** [-16.1, -2.6], p 0.0067 | -3.0 [-7.1, +0.8], p 0.15 | +1.1 [-2.2, +4.1], p 0.5 | **-0.062** [-0.109, -0.015], p 0.01 | -0.028 [-0.066, +0.010], p 0.15 |
| `hybrid:bge-small-en-v1.5` | `default` | local | `bm25` at `h2` | +4.5 [-0.8, +9.7], p 0.11 | +0.0 [-3.0, +3.0], p 1 | -0.4 [-3.8, +3.0], p 0.82 | +0.033 [-0.004, +0.070], p 0.089 | +0.026 [-0.006, +0.059], p 0.12 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | local | `bm25` at `h2` | **-9.7** [-16.5, -3.0], p 0.0045 | -4.1 [-8.2, -0.4], p 0.05 | -0.4 [-4.1, +3.0], p 0.84 | **-0.067** [-0.113, -0.020], p 0.0043 | -0.035 [-0.074, +0.003], p 0.074 |
| `bm25` | `h6` | none | `bm25` at `h2` | -3.0 [-7.9, +1.5], p 0.22 | -2.6 [-5.6, +0.0], p 0.077 | -1.9 [-4.5, +0.8], p 0.18 | -0.023 [-0.055, +0.009], p 0.15 | -0.026 [-0.053, +0.000], p 0.055 |
| `bm25+ce` | `h6` | local | `bm25` at `h2` | **-7.5** [-13.9, -0.8], p 0.026 | -3.4 [-7.5, +0.4], p 0.099 | +0.8 [-2.6, +4.1], p 0.66 | **-0.050** [-0.095, -0.004], p 0.027 | -0.021 [-0.058, +0.017], p 0.28 |
| `hybrid:bge-small-en-v1.5` | `h6` | local | `bm25` at `h2` | **-8.2** [-14.6, -1.9], p 0.013 | -1.9 [-5.6, +1.9], p 0.33 | +1.5 [-1.9, +4.9], p 0.38 | **-0.049** [-0.094, -0.005], p 0.026 | -0.014 [-0.051, +0.025], p 0.48 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | local | `bm25` at `h2` | **-7.9** [-14.2, -1.5], p 0.018 | -4.1 [-8.2, +0.0], p 0.05 | +1.1 [-2.2, +4.5], p 0.52 | **-0.053** [-0.098, -0.007], p 0.021 | -0.022 [-0.059, +0.016], p 0.27 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | local | `bm25` at `h2` | **-27.0** [-34.8, -19.1], p < 0.001 | **-12.7** [-18.0, -7.9], p < 0.001 | **-5.2** [-9.4, -1.1], p 0.014 | **-0.204** [-0.258, -0.148], p < 0.001 | **-0.143** [-0.187, -0.099], p < 0.001 |
| `bm25+ce` | `h2` | local | `bm25` at `h2` | **-14.6** [-21.3, -7.5], p < 0.001 | **-7.1** [-11.2, -3.0], p 0.0017 | -3.0 [-6.4, +0.4], p 0.11 | **-0.114** [-0.163, -0.065], p < 0.001 | **-0.081** [-0.121, -0.042], p < 0.001 |
| `hybrid:bge-small-en-v1.5` | `h2` | local | `bm25` at `h2` | **-7.1** [-13.5, -1.1], p 0.024 | **-6.4** [-10.5, -2.2], p 0.0029 | -2.2 [-5.6, +1.5], p 0.23 | **-0.058** [-0.101, -0.015], p 0.007 | **-0.046** [-0.082, -0.010], p 0.014 |
| `bm25` | `merge-400` | none | `bm25` at `h2` | -0.8 [-4.9, +3.4], p 0.73 | -1.1 [-3.8, +1.5], p 0.42 | -0.8 [-3.4, +1.9], p 0.58 | -0.003 [-0.033, +0.027], p 0.85 | -0.003 [-0.028, +0.022], p 0.79 |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | `bm25` at `h2` | **-6.7** [-13.5, -0.4], p 0.045 | -1.5 [-5.2, +2.2], p 0.42 | +1.1 [-1.9, +4.1], p 0.48 | -0.035 [-0.080, +0.010], p 0.13 | -0.003 [-0.040, +0.035], p 0.89 |

## Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text returned, the results read whole and in order: a case counts when the result that first answers it ends within the budget (#575). Context: the estimated tokens of all the text returned per question (each chunk's content); to the first hit: up to and including the first result that answers. In brackets: the 95% interval. Against: the budget's default, the difference in points and the p-value of McNemar's test (mid-p), **bold** when significant.

| configuration | chunking | context tokens / q | tokens to first hit | within 1,000 | within 2,000 | within 4,000 | against | 1,000 | 2,000 | 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 3,464 [3,320, 3,614] | 1,448 [1,307, 1,593] | 42.7% [36.7, 48.7] | 71.2% [65.5, 76.4] | 89.1% [85.4, 92.9] | `bm25` at `h2` | **+18.7** [+13.5, +24.0], p < 0.001 | **+21.7** [+16.5, +27.0], p < 0.001 | **+15.0** [+10.5, +19.9], p < 0.001 |
| `hybrid:bge-small-en-v1.5` | `default` | 3,206 [3,072, 3,340] | 1,413 [1,285, 1,546] | 42.3% [36.3, 48.3] | 73.4% [68.2, 78.6] | 90.3% [86.5, 93.6] | `bm25` at `h2` | **+18.4** [+12.7, +24.0], p < 0.001 | **+24.0** [+18.4, +30.0], p < 0.001 | **+16.1** [+11.2, +21.3], p < 0.001 |
| `bm25` | `h6` | 2,874 [2,739, 3,014] | 1,251 [1,130, 1,375] | 46.1% [40.1, 52.1] | 74.9% [69.7, 80.2] | 90.3% [86.5, 93.6] | `bm25` at `h2` | **+22.1** [+16.5, +27.7], p < 0.001 | **+25.5** [+19.9, +31.1], p < 0.001 | **+16.1** [+11.6, +21.0], p < 0.001 |
| `bm25` | `h2` | 7,065 [6,784, 7,345] | 2,765 [2,450, 3,092] | 24.0% [19.1, 29.2] | 49.4% [43.5, 55.4] | 74.2% [68.9, 79.4] | - | - | - | - |
| `bm25` | `merge-400` | 3,535 [3,398, 3,676] | 1,473 [1,345, 1,606] | 37.8% [32.2, 43.8] | 70.8% [65.2, 76.4] | 89.9% [86.1, 93.3] | `bm25` at `h2` | **+13.9** [+9.0, +18.7], p < 0.001 | **+21.3** [+15.7, +27.0], p < 0.001 | **+15.7** [+10.9, +20.6], p < 0.001 |

## By question kind (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 88.7% [79.2, 96.2] / 80.8% / 0.739 [0.648, 0.821] | 91.7% [83.3, 97.9] / 62.5% / 0.621 [0.544, 0.697] | 87.9% [79.3, 96.5] / 78.2% / 0.747 [0.661, 0.829] | 90.4% [82.7, 98.1] / 89.4% / 0.813 [0.726, 0.895] | clean 100.0%, no answer 0.0% | 96.4% [91.1, 100.0] / 90.2% / 0.833 [0.762, 0.898] |
| `bm25+ce` | `default` | 92.5% [84.9, 98.1] / 88.0% / 0.780 [0.703, 0.854] | 87.5% [77.1, 95.8] / 59.2% / 0.591 [0.514, 0.669] | 86.2% [77.6, 94.8] / 81.3% / 0.741 [0.657, 0.821] | 92.3% [84.6, 98.1] / 91.3% / 0.779 [0.696, 0.854] | clean 100.0%, no answer 0.0% | 89.3% [80.4, 96.4] / 82.1% / 0.755 [0.673, 0.834] |
| `hybrid:bge-small-en-v1.5` | `default` | 90.6% [83.0, 98.1] / 81.8% / 0.741 [0.650, 0.828] | 95.8% [89.6, 100.0] / 70.5% / 0.709 [0.635, 0.779] | 89.7% [81.0, 96.5] / 82.2% / 0.781 [0.698, 0.859] | 92.3% [84.6, 98.1] / 91.3% / 0.859 [0.781, 0.927] | clean 100.0%, no answer 0.0% | 94.6% [87.5, 100.0] / 88.4% / 0.835 [0.759, 0.903] |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 92.5% [84.9, 98.1] / 88.0% / 0.768 [0.687, 0.845] | 85.4% [75.0, 93.8] / 56.4% / 0.590 [0.512, 0.669] | 84.5% [74.1, 93.1] / 78.7% / 0.737 [0.650, 0.818] | 92.3% [84.6, 98.1] / 91.3% / 0.765 [0.680, 0.843] | clean 100.0%, no answer 0.0% | 87.5% [78.6, 94.6] / 80.4% / 0.751 [0.668, 0.831] |
| `bm25` | `h6` | 88.7% [79.2, 96.2] / 79.9% / 0.727 [0.639, 0.807] | 89.6% [81.2, 97.9] / 60.8% / 0.604 [0.527, 0.681] | 86.2% [77.6, 94.8] / 77.0% / 0.722 [0.632, 0.808] | 88.5% [78.8, 96.2] / 86.5% / 0.768 [0.672, 0.861] | clean 100.0%, no answer 0.0% | 96.4% [91.1, 100.0] / 88.4% / 0.834 [0.758, 0.901] |
| `bm25+ce` | `h6` | 90.6% [83.0, 98.1] / 88.0% / 0.794 [0.714, 0.869] | 87.5% [77.1, 95.8] / 58.2% / 0.597 [0.518, 0.675] | 86.2% [77.6, 94.8] / 81.3% / 0.751 [0.669, 0.832] | 92.3% [84.6, 98.1] / 90.4% / 0.776 [0.694, 0.852] | clean 100.0%, no answer 0.0% | 89.3% [80.4, 96.4] / 83.0% / 0.764 [0.681, 0.844] |
| `hybrid:bge-small-en-v1.5` | `h6` | 88.7% [79.2, 96.2] / 84.3% / 0.754 [0.670, 0.831] | 95.8% [89.6, 100.0] / 63.9% / 0.640 [0.567, 0.710] | 86.2% [77.6, 94.8] / 81.3% / 0.755 [0.673, 0.832] | 90.4% [82.7, 98.1] / 88.5% / 0.783 [0.703, 0.860] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 86.6% / 0.789 [0.708, 0.865] |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 92.5% [84.9, 98.1] / 89.0% / 0.793 [0.718, 0.864] | 85.4% [75.0, 93.8] / 56.4% / 0.608 [0.531, 0.682] | 84.5% [74.1, 93.1] / 80.5% / 0.756 [0.675, 0.836] | 92.3% [84.6, 98.1] / 90.4% / 0.763 [0.678, 0.841] | clean 100.0%, no answer 0.0% | 87.5% [78.6, 94.6] / 81.2% / 0.760 [0.676, 0.840] |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 83.0% [73.6, 92.5] / 79.2% / 0.681 [0.595, 0.768] | 81.2% [70.8, 91.7] / 47.6% / 0.487 [0.415, 0.556] | 75.9% [63.8, 86.2] / 67.8% / 0.572 [0.479, 0.665] | 82.7% [71.2, 92.3] / 81.7% / 0.692 [0.605, 0.778] | clean 100.0%, no answer 0.0% | 76.8% [66.1, 87.5] / 74.1% / 0.647 [0.549, 0.740] |
| `bm25` | `h2` | 92.5% [84.9, 98.1] / 84.6% / 0.809 [0.723, 0.882] | 97.9% [93.8, 100.0] / 69.8% / 0.691 [0.625, 0.755] | 87.9% [79.3, 96.5] / 78.2% / 0.732 [0.642, 0.817] | 92.3% [84.6, 98.1] / 91.3% / 0.819 [0.734, 0.898] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 84.8% / 0.750 [0.664, 0.835] |
| `bm25+ce` | `h2` | 81.1% [69.8, 90.6] / 76.1% / 0.713 [0.626, 0.795] | 87.5% [77.1, 95.8] / 60.4% / 0.614 [0.533, 0.693] | 87.9% [79.3, 96.5] / 78.7% / 0.701 [0.620, 0.780] | 86.5% [76.9, 94.2] / 85.6% / 0.754 [0.655, 0.847] | clean 100.0%, no answer 0.0% | 83.9% [73.2, 92.9] / 71.4% / 0.612 [0.517, 0.705] |
| `hybrid:bge-small-en-v1.5` | `h2` | 84.9% [75.5, 94.3] / 78.0% / 0.725 [0.638, 0.809] | 100.0% [100.0, 100.0] / 66.3% / 0.677 [0.615, 0.738] | 87.9% [79.3, 94.8] / 80.5% / 0.765 [0.681, 0.844] | 90.4% [80.8, 98.1] / 88.5% / 0.811 [0.734, 0.881] | clean 100.0%, no answer 0.0% | 69.6% [57.1, 82.1] / 60.7% / 0.596 [0.489, 0.701] |
| `bm25` | `merge-400` | 90.6% [83.0, 98.1] / 82.7% / 0.758 [0.667, 0.840] | 89.6% [81.2, 97.9] / 62.5% / 0.627 [0.552, 0.701] | 87.9% [79.3, 94.8] / 78.2% / 0.741 [0.655, 0.825] | 90.4% [82.7, 98.1] / 88.5% / 0.802 [0.711, 0.886] | clean 100.0%, no answer 0.0% | 98.2% [94.6, 100.0] / 89.3% / 0.843 [0.771, 0.908] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 88.7% [79.2, 96.2] / 84.3% / 0.762 [0.676, 0.839] | 93.8% [85.4, 100.0] / 65.6% / 0.654 [0.579, 0.728] | 87.9% [79.3, 94.8] / 83.0% / 0.781 [0.699, 0.857] | 92.3% [84.6, 98.1] / 91.3% / 0.785 [0.708, 0.859] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 83.9% / 0.793 [0.714, 0.867] |

## By project (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `bm25` | `default` | 88.7% [79.2, 96.2] / 76.1% / 0.725 [0.628, 0.811] | 89.1% [80.0, 96.4] / 76.1% / 0.703 [0.616, 0.786] | 96.3% [90.7, 100.0] / 87.4% / 0.826 [0.753, 0.892] | 82.7% [71.2, 92.3] / 75.3% / 0.704 [0.613, 0.789] | 98.1% [94.3, 100.0] / 88.0% / 0.810 [0.742, 0.874] |
| `bm25+ce` | `default` | 86.8% [77.4, 94.3] / 76.1% / 0.698 [0.609, 0.784] | 89.1% [80.0, 96.4] / 81.4% / 0.725 [0.649, 0.798] | 92.6% [85.2, 98.2] / 84.0% / 0.776 [0.696, 0.849] | 84.6% [75.0, 94.2] / 77.2% / 0.686 [0.599, 0.772] | 94.3% [86.8, 100.0] / 85.2% / 0.774 [0.697, 0.848] |
| `hybrid:bge-small-en-v1.5` | `default` | 90.6% [83.0, 98.1] / 79.2% / 0.792 [0.698, 0.875] | 90.9% [81.8, 98.2] / 81.5% / 0.741 [0.662, 0.814] | 94.4% [87.0, 100.0] / 84.6% / 0.807 [0.727, 0.877] | 88.5% [78.8, 96.2] / 83.0% / 0.769 [0.679, 0.852] | 98.1% [94.3, 100.0] / 87.1% / 0.825 [0.759, 0.886] |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 84.9% [75.5, 94.3] / 75.5% / 0.686 [0.593, 0.774] | 87.3% [78.2, 94.5] / 78.6% / 0.718 [0.638, 0.795] | 92.6% [85.2, 98.2] / 83.0% / 0.774 [0.695, 0.846] | 84.6% [75.0, 94.2] / 76.3% / 0.683 [0.596, 0.767] | 92.5% [84.9, 98.1] / 83.3% / 0.763 [0.682, 0.841] |
| `bm25` | `h6` | 88.7% [79.2, 96.2] / 75.2% / 0.703 [0.604, 0.794] | 87.3% [78.2, 94.5] / 76.1% / 0.711 [0.624, 0.793] | 94.4% [87.0, 100.0] / 83.6% / 0.783 [0.702, 0.856] | 84.6% [75.0, 94.2] / 75.3% / 0.675 [0.581, 0.765] | 94.3% [86.8, 100.0] / 84.3% / 0.796 [0.721, 0.866] |
| `bm25+ce` | `h6` | 84.9% [75.5, 94.3] / 76.1% / 0.702 [0.609, 0.790] | 89.1% [80.0, 96.4] / 79.5% / 0.720 [0.640, 0.796] | 92.6% [85.2, 98.2] / 84.0% / 0.802 [0.728, 0.872] | 84.6% [75.0, 94.2] / 78.2% / 0.692 [0.603, 0.778] | 94.3% [86.8, 100.0] / 85.2% / 0.781 [0.706, 0.853] |
| `hybrid:bge-small-en-v1.5` | `h6` | 90.6% [83.0, 98.1] / 77.4% / 0.736 [0.646, 0.820] | 90.9% [81.8, 98.2] / 81.2% / 0.713 [0.638, 0.784] | 92.6% [85.2, 98.2] / 82.7% / 0.779 [0.700, 0.851] | 86.5% [76.9, 94.2] / 79.2% / 0.689 [0.606, 0.771] | 92.5% [84.9, 98.1] / 85.9% / 0.816 [0.740, 0.884] |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 84.9% [75.5, 94.3] / 77.4% / 0.705 [0.614, 0.791] | 87.3% [78.2, 94.5] / 75.9% / 0.719 [0.637, 0.796] | 92.6% [85.2, 98.2] / 84.0% / 0.802 [0.727, 0.872] | 84.6% [75.0, 94.2] / 78.2% / 0.694 [0.610, 0.776] | 92.5% [84.9, 98.1] / 84.3% / 0.773 [0.694, 0.849] |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 73.6% [60.4, 84.9] / 64.8% / 0.580 [0.476, 0.675] | 89.1% [80.0, 96.4] / 78.2% / 0.664 [0.577, 0.745] | 74.1% [63.0, 85.2] / 65.7% / 0.586 [0.492, 0.677] | 78.8% [67.3, 88.5] / 70.5% / 0.595 [0.510, 0.678] | 83.0% [71.7, 92.5] / 73.0% / 0.660 [0.569, 0.747] |
| `bm25` | `h2` | 88.7% [79.2, 96.2] / 76.4% / 0.700 [0.606, 0.791] | 92.7% [85.5, 98.2] / 77.9% / 0.718 [0.635, 0.797] | 98.2% [94.4, 100.0] / 89.2% / 0.868 [0.803, 0.925] | 84.6% [75.0, 94.2] / 78.8% / 0.699 [0.607, 0.787] | 98.1% [94.3, 100.0] / 87.1% / 0.816 [0.745, 0.879] |
| `bm25+ce` | `h2` | 84.9% [75.5, 94.3] / 73.3% / 0.665 [0.567, 0.757] | 87.3% [78.2, 94.5] / 77.3% / 0.680 [0.590, 0.763] | 92.6% [85.2, 98.2] / 78.4% / 0.722 [0.643, 0.798] | 75.0% [63.5, 86.5] / 67.6% / 0.600 [0.502, 0.693] | 86.8% [77.4, 94.3] / 76.7% / 0.727 [0.634, 0.814] |
| `hybrid:bge-small-en-v1.5` | `h2` | 84.9% [75.5, 94.3] / 68.9% / 0.678 [0.584, 0.769] | 81.8% [70.9, 90.9] / 71.2% / 0.686 [0.588, 0.777] | 92.6% [85.2, 98.2] / 78.7% / 0.766 [0.687, 0.840] | 78.8% [67.3, 88.5] / 72.4% / 0.661 [0.565, 0.753] | 92.5% [84.9, 98.1] / 83.0% / 0.780 [0.713, 0.844] |
| `bm25` | `merge-400` | 86.8% [77.4, 94.3] / 74.8% / 0.720 [0.620, 0.810] | 92.7% [85.5, 98.2] / 79.1% / 0.719 [0.635, 0.797] | 94.4% [87.0, 100.0] / 84.6% / 0.815 [0.735, 0.887] | 84.6% [75.0, 94.2] / 78.2% / 0.726 [0.635, 0.811] | 98.1% [94.3, 100.0] / 86.2% / 0.806 [0.738, 0.869] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 90.6% [83.0, 98.1] / 79.9% / 0.758 [0.672, 0.837] | 90.9% [83.6, 98.2] / 83.0% / 0.732 [0.649, 0.807] | 94.4% [87.0, 100.0] / 82.7% / 0.776 [0.697, 0.849] | 84.6% [75.0, 94.2] / 78.2% / 0.696 [0.611, 0.777] | 94.3% [86.8, 100.0] / 85.9% / 0.826 [0.752, 0.892] |

## Models

- reranker: `local:Xenova/ms-marco-MiniLM-L-6-v2` @ `a09144355ade`
- embedding: `local:BAAI/bge-small-en-v1.5` @ `aa8f8b060edb`
- embedding: `local:snowflake/snowflake-arctic-embed-s` @ `e596f5074675`

## Recorded by another run

- `bm25` at `default`: ExactDocs `ce81d93fcd4c433b348c26923c33bba33906d40d`, Linux x86_64, 4 CPUs, 25 November 2026
- `hybrid:bge-small-en-v1.5` at `default`: ExactDocs `ce81d93fcd4c433b348c26923c33bba33906d40d`, Linux x86_64, 4 CPUs, 25 November 2026
- `bm25` at `h6`: ExactDocs `ce81d93fcd4c433b348c26923c33bba33906d40d`, Linux x86_64, 4 CPUs, 25 November 2026
- `bm25` at `h2`: ExactDocs `ce81d93fcd4c433b348c26923c33bba33906d40d`, Linux x86_64, 4 CPUs, 25 November 2026
- `bm25` at `merge-400`: ExactDocs `ce81d93fcd4c433b348c26923c33bba33906d40d`, Linux x86_64, 4 CPUs, 25 November 2026
<!-- /bench -->
