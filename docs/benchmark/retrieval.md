# Retrieval results

Every retrieval configuration that could run, at every chunking configuration, on the whole
[golden set](golden-set.md). The metrics are defined in [Method](method.md#retrieval-metrics);
the default each budget gets is on [Recommended defaults](defaults.md).

## The recorded run

`packages/exactdocs/evals/results/retrieval.json`, recorded on 24 November 2026 for #503 and #501
on the golden set with its alternatives marked (`sha256:a00997851150e3b0`), on one self-hosted
runner VM (Linux aarch64, 4 CPUs), with no provider, in 3 h 22 min
([the command and the timings](../evals.md#the-recorded-run)). A full local matrix would take far
longer, so it ran a subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking;
- `bm25+ce` at `default`, `h6` and `h2`, and `hybrid:bge-small-en-v1.5+ce` at `default` and `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6`;
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking).

Every result keeps each case's outcome, so every one has intervals and a paired test against its
budget's default ([Intervals and significance](method.md#intervals-and-significance)). The
latencies are that runner's.

**Two scoring rules changed since the run it replaces** (23–24 November, the same subset on the
same runner), so its numbers are not comparable with that one's
([Method](method.md#retrieval-metrics)):

- A chunk counts for every section it holds (#503). Before, a chunk that held the expected section
  next to a sibling was a miss, which undercounted `h2` and `merge-400` (BM25's recall@5 was 76.0%
  and 74.2% there).
- recall@k and MRR count a hit on any section a case lists, and section recall and nDCG@10 count
  each part of the answer once, an alternative counting as its part (#501). Before, recall@k
  counted the first listed section only. This alone lifts BM25's recall@5 at `default` from 81.7%
  to 87.6%: 3 cases by the alternatives the review marked, 13 by the other parts of multi-part
  cases (8 of them `cross-page`).

**Every hosted configuration is not measured yet**: hybrid on a hosted embedding model, HyDE,
agentic search and every configuration reranked by the LLM judge. They run only from the manual
*Retrieval eval (real providers)* workflow (`.github/workflows/eval-providers.yml`) with the
`benchmark` input ticked, or locally with `--allow-providers`
([Running the hosted part](../evals.md#running-the-hosted-part)). They are listed under
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

- BM25 scores alike at `h2`, `default` and `merge-400`: 89.1%, 87.6% and 87.6% recall@5. `h2`
  comes first by the benchmark's ordering, so the summary names it, but its lead over `default`
  is not significant on any metric (recall@5 +1.5 points, p 0.42; recall@1 p 0.24; MRR p 0.13),
  and its chunks are about twice as long (7,065 estimated tokens in a question's ten results
  against 3,464, [text calibration](../evals.md#calibration)). `h6`, where every heading starts a
  chunk, is below them: 85.8%, with MRR and nDCG@10 significantly worse than at `default`. The
  shipped default stays `default` (#381); a non-significant lead does not change it.
- Hybrid search on bge-small is the best local configuration, at `merge-400` (91.0%), but only
  1.9 points of recall@5 above BM25 at `h2`, under the 5-point margin and not significant
  (p 0.33). At `default`, `h6` and `merge-400` it ranks the answer higher than BM25 at `default`
  (MRR and nDCG@10 significantly better) without finding significantly more answers in the top 5.
- The intervals per kind and per project are about twice as wide as the whole set's (around
  ±10 points of recall@5 on some 50 cases): differences of a few points there say little.
- The cross-encoder on BM25 reaches 89.5% at `default` and 89.1% at `h6`, not significant over
  BM25 at `default` (p 0.36 and 0.46), at about 2.5 s per question (p50) on this runner, and loses
  recall at `h2` (85.4%, significantly below its `default`), whose chunks are longer than its
  window. On hybrid it adds nothing. At `h6` it ranks the first hit slightly higher than at
  `default` (recall@1 +1.9 points, significant for both rerankers, recall@5 the same).
- snowflake-arctic-embed-s scores below BM25 (79.8%).
- No configuration returned a result of another version, and none signalled "no answer" on any of
  the 54 unanswerable cases: `search_docs` gives a caller no way to tell an unanswerable question
  from an answerable one by its results today.
- On `cross-page` questions, section recall@5 is about a third below recall@5 (33 to 34 points for
  BM25 and hybrid): a hit on one page of the answer is common, all of its pages much rarer.

<!-- bench:retrieval -->
## Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 58.8% [52.8, 64.8] | 87.6% [83.5, 91.4] | 93.6% [90.6, 96.2] | 0.711 [0.666, 0.754] | 0.714 [0.676, 0.751] | 0 | 100.0% / 0.0% | 0.0% | 39.3 | 51.8 | 0 | 0.0000 | - |
| `bm25+ce` | `default` | local | ran | 62.2% [56.2, 67.8] | 89.5% [85.8, 92.9] | 94.8% [91.8, 97.4] | 0.737 [0.693, 0.779] | 0.732 [0.696, 0.768] | 0 | 100.0% / 0.0% | 0.0% | 2481.9 | 2799.1 | 10945 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 64.4% [58.8, 70.0] | 90.3% [86.5, 93.6] | 93.6% [90.6, 96.2] | 0.756 [0.714, 0.798] | 0.749 [0.712, 0.785] | 0 | 100.0% / 0.0% | 0.0% | 66.0 | 86.9 | 22 | 0.0000 | 1479 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | local | ran | 61.8% [55.8, 67.4] | 88.4% [84.3, 92.1] | 93.3% [89.9, 96.2] | 0.732 [0.688, 0.775] | 0.725 [0.687, 0.761] | 0 | 100.0% / 0.0% | 0.0% | 2513.1 | 2824.6 | 10019 | 0.0000 | 1479 |
| `bm25` | `h6` | none | ran | 56.9% [50.9, 62.9] | 85.8% [81.7, 89.9] | 92.1% [88.8, 95.1] | 0.689 [0.642, 0.734] | 0.692 [0.652, 0.730] | 0 | 100.0% / 0.0% | 0.0% | 60.9 | 75.0 | 0 | 0.0000 | - |
| `bm25+ce` | `h6` | local | ran | 64.0% [58.1, 69.7] | 89.1% [85.0, 92.9] | 94.4% [91.4, 97.0] | 0.749 [0.705, 0.791] | 0.740 [0.702, 0.775] | 0 | 100.0% / 0.0% | 0.0% | 2523.9 | 2824.8 | 9158 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h6` | local | ran | 63.3% [57.3, 69.3] | 90.6% [86.9, 94.0] | 95.1% [92.5, 97.4] | 0.750 [0.707, 0.791] | 0.747 [0.710, 0.783] | 0 | 100.0% / 0.0% | 0.0% | 86.2 | 111.8 | 22 | 0.0000 | 1916 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | local | ran | 63.7% [57.7, 69.3] | 88.4% [84.3, 92.1] | 94.8% [91.8, 97.4] | 0.746 [0.703, 0.788] | 0.739 [0.702, 0.774] | 0 | 100.0% / 0.0% | 0.0% | 2537.1 | 2943.2 | 8569 | 0.0000 | 1916 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | local | ran | 44.6% [38.6, 50.6] | 79.8% [74.9, 84.6] | 88.4% [84.6, 92.1] | 0.595 [0.549, 0.642] | 0.617 [0.577, 0.658] | 0 | 100.0% / 0.0% | 0.0% | 91.0 | 119.9 | 22 | 0.0000 | 2086 |
| `bm25` | `h2` | none | ran | 61.8% [55.8, 67.8] | 89.1% [85.4, 92.5] | 94.0% [91.0, 96.6] | 0.737 [0.693, 0.779] | 0.724 [0.686, 0.761] | 0 | 100.0% / 0.0% | 0.0% | 20.4 | 30.2 | 0 | 0.0000 | - |
| `bm25+ce` | `h2` | local | ran | 56.9% [51.3, 62.9] | 85.4% [81.3, 89.5] | 90.6% [87.3, 94.0] | 0.685 [0.639, 0.730] | 0.679 [0.638, 0.719] | 0 | 100.0% / 0.0% | 0.0% | 2569.3 | 2690.8 | 21844 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h2` | local | ran | 64.4% [58.4, 70.0] | 86.1% [82.0, 90.3] | 91.4% [88.0, 94.8] | 0.741 [0.696, 0.785] | 0.715 [0.675, 0.753] | 0 | 100.0% / 0.0% | 0.0% | 47.3 | 64.0 | 22 | 0.0000 | 861 |
| `bm25` | `merge-400` | none | ran | 59.6% [53.6, 65.5] | 87.6% [83.5, 91.4] | 93.3% [90.3, 95.9] | 0.715 [0.671, 0.759] | 0.720 [0.682, 0.756] | 0 | 100.0% / 0.0% | 0.0% | 32.9 | 52.3 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | ran | 64.8% [59.2, 70.4] | 91.0% [87.6, 94.4] | 94.8% [92.1, 97.4] | 0.764 [0.723, 0.804] | 0.758 [0.721, 0.793] | 0 | 100.0% / 0.0% | 0.0% | 59.6 | 77.8 | 22 | 0.0000 | 1382 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489).

## Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | `bm25` at `h2` | -3.0 [-7.9, +1.9], p 0.24 | -1.5 [-5.2, +2.2], p 0.42 | -0.4 [-3.0, +2.2], p 0.77 | -0.026 [-0.057, +0.006], p 0.13 | -0.010 [-0.034, +0.015], p 0.43 |
| `bm25+ce` | `default` | local | `bm25` at `h2` | +0.4 [-6.4, +7.5], p 0.92 | +0.4 [-3.8, +4.5], p 0.86 | +0.8 [-2.2, +3.8], p 0.65 | +0.000 [-0.046, +0.048], p 0.99 | +0.008 [-0.029, +0.045], p 0.67 |
| `hybrid:bge-small-en-v1.5` | `default` | local | `bm25` at `h2` | +2.6 [-3.4, +9.0], p 0.42 | +1.1 [-2.6, +4.9], p 0.56 | -0.4 [-3.8, +3.0], p 0.82 | +0.019 [-0.023, +0.062], p 0.36 | +0.025 [-0.010, +0.061], p 0.17 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | local | `bm25` at `h2` | +0.0 [-6.7, +7.1], p 1 | -0.8 [-5.2, +3.4], p 0.74 | -0.8 [-4.1, +2.6], p 0.68 | -0.004 [-0.049, +0.043], p 0.86 | +0.001 [-0.036, +0.038], p 0.95 |
| `bm25` | `h6` | none | `bm25` at `h2` | -4.9 [-10.5, +0.8], p 0.092 | -3.4 [-7.1, +0.4], p 0.087 | -1.9 [-4.5, +0.8], p 0.18 | **-0.048** [-0.084, -0.011], p 0.0097 | **-0.033** [-0.060, -0.004], p 0.023 |
| `bm25+ce` | `h6` | local | `bm25` at `h2` | +2.2 [-4.5, +9.0], p 0.51 | +0.0 [-4.1, +4.1], p 1 | +0.4 [-3.0, +3.4], p 0.82 | +0.012 [-0.032, +0.058], p 0.6 | +0.016 [-0.020, +0.052], p 0.39 |
| `hybrid:bge-small-en-v1.5` | `h6` | local | `bm25` at `h2` | +1.5 [-4.9, +7.9], p 0.64 | +1.5 [-2.2, +5.2], p 0.44 | +1.1 [-2.2, +4.5], p 0.5 | +0.013 [-0.030, +0.057], p 0.54 | +0.023 [-0.013, +0.059], p 0.22 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | local | `bm25` at `h2` | +1.9 [-4.9, +8.6], p 0.58 | -0.8 [-4.9, +3.4], p 0.73 | +0.8 [-2.6, +4.1], p 0.66 | +0.010 [-0.035, +0.055], p 0.67 | +0.015 [-0.021, +0.050], p 0.43 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | local | `bm25` at `h2` | **-17.2** [-25.1, -9.4], p < 0.001 | **-9.4** [-14.6, -4.5], p < 0.001 | **-5.6** [-9.7, -1.9], p 0.007 | **-0.142** [-0.195, -0.087], p < 0.001 | **-0.107** [-0.149, -0.064], p < 0.001 |
| `bm25+ce` | `h2` | local | `bm25` at `h2` | -4.9 [-11.6, +2.2], p 0.16 | -3.8 [-8.2, +0.8], p 0.11 | -3.4 [-6.7, +0.0], p 0.064 | **-0.052** [-0.099, -0.003], p 0.034 | **-0.045** [-0.083, -0.007], p 0.024 |
| `hybrid:bge-small-en-v1.5` | `h2` | local | `bm25` at `h2` | +2.6 [-3.4, +8.6], p 0.38 | -3.0 [-7.5, +1.5], p 0.21 | -2.6 [-6.0, +0.8], p 0.15 | +0.004 [-0.038, +0.046], p 0.84 | -0.009 [-0.044, +0.024], p 0.59 |
| `bm25` | `merge-400` | none | `bm25` at `h2` | -2.2 [-7.1, +2.6], p 0.38 | -1.5 [-4.5, +1.5], p 0.36 | -0.8 [-3.4, +1.9], p 0.58 | -0.021 [-0.054, +0.013], p 0.21 | -0.004 [-0.030, +0.022], p 0.77 |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | `bm25` at `h2` | +3.0 [-3.8, +9.7], p 0.37 | +1.9 [-1.9, +5.6], p 0.33 | +0.8 [-2.2, +3.8], p 0.63 | +0.028 [-0.017, +0.073], p 0.23 | +0.034 [-0.002, +0.070], p 0.075 |

## Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text returned, the results read whole and in order: a case counts when the result that first answers it ends within the budget (#575). Context: the estimated tokens of all the text returned per question (each chunk's content); to the first hit: up to and including the first result that answers. In brackets: the 95% interval. Against: the budget's default, the difference in points and the p-value of McNemar's test (mid-p), **bold** when significant.

| configuration | chunking | context tokens / q | tokens to first hit | within 1,000 | within 2,000 | within 4,000 | against | 1,000 | 2,000 | 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 3,464 [3,320, 3,614] | 656 [571, 745] | 78.3% [73.4, 83.2] | 88.8% [85.0, 92.1] | 93.6% [90.6, 96.2] | `bm25` at `h2` | **+29.2** [+23.6, +35.2], p < 0.001 | **+12.0** [+7.9, +16.5], p < 0.001 | **+4.5** [+1.5, +7.5], p 0.0044 |
| `bm25` | `h6` | 2,876 [2,740, 3,016] | 583 [509, 661] | 77.9% [73.0, 82.8] | 89.1% [85.4, 92.5] | 92.1% [88.8, 95.1] | `bm25` at `h2` | **+28.8** [+23.2, +34.8], p < 0.001 | **+12.4** [+7.9, +16.9], p < 0.001 | +3.0 [+0.0, +6.4], p 0.064 |
| `bm25` | `h2` | 7,065 [6,784, 7,345] | 1,366 [1,205, 1,537] | 49.1% [43.1, 55.1] | 76.8% [71.5, 82.0] | 89.1% [85.4, 92.5] | - | - | - | - |
| `bm25` | `merge-400` | 3,534 [3,398, 3,674] | 656 [575, 745] | 77.9% [73.0, 82.8] | 88.0% [83.9, 91.8] | 93.3% [90.3, 95.9] | `bm25` at `h2` | **+28.8** [+22.9, +34.8], p < 0.001 | **+11.2** [+7.1, +15.4], p < 0.001 | **+4.1** [+1.1, +7.5], p 0.012 |

## By question kind (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 86.8% [77.4, 94.3] / 80.5% / 0.712 [0.622, 0.796] | 87.5% [77.1, 95.8] / 54.3% / 0.588 [0.511, 0.663] | 84.5% [75.9, 93.1] / 75.6% / 0.729 [0.643, 0.813] | 86.5% [76.9, 94.2] / 84.6% / 0.757 [0.671, 0.839] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 85.7% / 0.770 [0.693, 0.843] |
| `bm25+ce` | `default` | 92.5% [84.9, 98.1] / 88.0% / 0.780 [0.703, 0.854] | 87.5% [77.1, 95.8] / 59.2% / 0.591 [0.514, 0.669] | 86.2% [77.6, 94.8] / 81.3% / 0.741 [0.657, 0.821] | 92.3% [84.6, 98.1] / 91.3% / 0.779 [0.696, 0.854] | clean 100.0%, no answer 0.0% | 89.3% [80.4, 96.4] / 82.1% / 0.755 [0.673, 0.834] |
| `hybrid:bge-small-en-v1.5` | `default` | 88.7% [79.2, 96.2] / 84.0% / 0.726 [0.639, 0.810] | 93.8% [85.4, 100.0] / 64.2% / 0.657 [0.582, 0.728] | 86.2% [77.6, 94.8] / 80.5% / 0.742 [0.656, 0.824] | 90.4% [82.7, 98.1] / 89.4% / 0.819 [0.742, 0.891] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 86.6% / 0.792 [0.714, 0.866] |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 92.5% [84.9, 98.1] / 88.0% / 0.768 [0.687, 0.845] | 85.4% [75.0, 93.8] / 56.4% / 0.590 [0.512, 0.669] | 84.5% [74.1, 93.1] / 78.7% / 0.737 [0.650, 0.818] | 92.3% [84.6, 98.1] / 91.3% / 0.765 [0.680, 0.843] | clean 100.0%, no answer 0.0% | 87.5% [78.6, 94.6] / 80.4% / 0.751 [0.668, 0.831] |
| `bm25` | `h6` | 86.8% [77.4, 94.3] / 81.5% / 0.697 [0.608, 0.781] | 85.4% [75.0, 93.8] / 51.2% / 0.563 [0.487, 0.637] | 82.8% [72.4, 91.4] / 73.9% / 0.689 [0.600, 0.776] | 82.7% [71.2, 92.3] / 81.7% / 0.708 [0.613, 0.802] | clean 100.0%, no answer 0.0% | 91.1% [82.1, 98.2] / 85.7% / 0.784 [0.702, 0.863] |
| `bm25+ce` | `h6` | 90.6% [83.0, 98.1] / 88.0% / 0.794 [0.714, 0.869] | 87.5% [77.1, 95.8] / 58.2% / 0.597 [0.518, 0.675] | 86.2% [77.6, 94.8] / 81.3% / 0.751 [0.669, 0.832] | 92.3% [84.6, 98.1] / 90.4% / 0.776 [0.694, 0.852] | clean 100.0%, no answer 0.0% | 89.3% [80.4, 96.4] / 83.0% / 0.764 [0.681, 0.844] |
| `hybrid:bge-small-en-v1.5` | `h6` | 88.7% [79.2, 96.2] / 84.3% / 0.754 [0.670, 0.831] | 95.8% [89.6, 100.0] / 63.9% / 0.640 [0.567, 0.710] | 86.2% [77.6, 94.8] / 81.3% / 0.755 [0.673, 0.832] | 90.4% [82.7, 98.1] / 88.5% / 0.783 [0.703, 0.860] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 86.6% / 0.789 [0.708, 0.865] |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 92.5% [84.9, 98.1] / 89.0% / 0.793 [0.718, 0.864] | 85.4% [75.0, 93.8] / 56.4% / 0.608 [0.531, 0.682] | 84.5% [74.1, 93.1] / 80.5% / 0.756 [0.675, 0.836] | 92.3% [84.6, 98.1] / 90.4% / 0.763 [0.678, 0.841] | clean 100.0%, no answer 0.0% | 87.5% [78.6, 94.6] / 81.2% / 0.760 [0.676, 0.840] |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 83.0% [73.6, 92.5] / 79.2% / 0.681 [0.595, 0.768] | 81.2% [70.8, 91.7] / 47.6% / 0.487 [0.415, 0.556] | 75.9% [63.8, 86.2] / 67.8% / 0.572 [0.479, 0.665] | 82.7% [71.2, 92.3] / 81.7% / 0.692 [0.605, 0.778] | clean 100.0%, no answer 0.0% | 76.8% [66.1, 87.5] / 74.1% / 0.647 [0.549, 0.740] |
| `bm25` | `h2` | 84.9% [75.5, 94.3] / 78.0% / 0.733 [0.647, 0.813] | 95.8% [89.6, 100.0] / 60.4% / 0.644 [0.578, 0.709] | 86.2% [77.6, 94.8] / 78.2% / 0.728 [0.639, 0.816] | 90.4% [82.7, 98.1] / 88.5% / 0.807 [0.726, 0.884] | clean 100.0%, no answer 0.0% | 89.3% [80.4, 96.4] / 80.4% / 0.703 [0.616, 0.788] |
| `bm25+ce` | `h2` | 81.1% [69.8, 90.6] / 76.1% / 0.713 [0.626, 0.795] | 87.5% [77.1, 95.8] / 60.4% / 0.614 [0.533, 0.693] | 87.9% [79.3, 96.5] / 78.7% / 0.701 [0.620, 0.780] | 86.5% [76.9, 94.2] / 85.6% / 0.754 [0.655, 0.847] | clean 100.0%, no answer 0.0% | 83.9% [73.2, 92.9] / 71.4% / 0.612 [0.517, 0.705] |
| `hybrid:bge-small-en-v1.5` | `h2` | 84.9% [75.5, 94.3] / 78.0% / 0.725 [0.638, 0.809] | 100.0% [100.0, 100.0] / 66.3% / 0.677 [0.615, 0.738] | 87.9% [79.3, 94.8] / 80.5% / 0.765 [0.681, 0.844] | 90.4% [80.8, 98.1] / 88.5% / 0.811 [0.734, 0.881] | clean 100.0%, no answer 0.0% | 69.6% [57.1, 82.1] / 60.7% / 0.596 [0.489, 0.701] |
| `bm25` | `merge-400` | 86.8% [77.4, 94.3] / 81.5% / 0.731 [0.640, 0.815] | 89.6% [81.2, 97.9] / 58.0% / 0.595 [0.519, 0.671] | 82.8% [72.4, 91.4] / 74.7% / 0.724 [0.638, 0.808] | 82.7% [71.2, 92.3] / 81.7% / 0.736 [0.645, 0.822] | clean 100.0%, no answer 0.0% | 96.4% [91.1, 100.0] / 88.4% / 0.798 [0.723, 0.869] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 88.7% [79.2, 96.2] / 84.3% / 0.762 [0.676, 0.839] | 93.8% [85.4, 100.0] / 65.6% / 0.654 [0.579, 0.728] | 87.9% [79.3, 94.8] / 83.0% / 0.781 [0.699, 0.857] | 92.3% [84.6, 98.1] / 91.3% / 0.785 [0.708, 0.859] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 83.9% / 0.793 [0.714, 0.867] |

## By project (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `bm25` | `default` | 83.0% [71.7, 92.5] / 70.8% / 0.692 [0.596, 0.781] | 89.1% [80.0, 96.4] / 75.9% / 0.677 [0.597, 0.756] | 90.7% [81.5, 98.2] / 81.5% / 0.765 [0.682, 0.841] | 80.8% [69.2, 90.4] / 71.5% / 0.661 [0.572, 0.746] | 94.3% [86.8, 100.0] / 83.3% / 0.776 [0.703, 0.846] |
| `bm25+ce` | `default` | 86.8% [77.4, 94.3] / 76.1% / 0.698 [0.609, 0.784] | 89.1% [80.0, 96.4] / 81.4% / 0.725 [0.649, 0.798] | 92.6% [85.2, 98.2] / 84.0% / 0.776 [0.696, 0.849] | 84.6% [75.0, 94.2] / 77.2% / 0.686 [0.599, 0.772] | 94.3% [86.8, 100.0] / 85.2% / 0.774 [0.697, 0.848] |
| `hybrid:bge-small-en-v1.5` | `default` | 90.6% [83.0, 98.1] / 79.2% / 0.763 [0.669, 0.848] | 90.9% [81.8, 98.2] / 81.2% / 0.713 [0.638, 0.782] | 90.7% [81.5, 98.2] / 80.9% / 0.767 [0.686, 0.842] | 86.5% [76.9, 94.2] / 79.2% / 0.688 [0.600, 0.773] | 92.5% [84.9, 98.1] / 85.9% / 0.814 [0.739, 0.882] |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 84.9% [75.5, 94.3] / 75.5% / 0.686 [0.593, 0.774] | 87.3% [78.2, 94.5] / 78.6% / 0.718 [0.638, 0.795] | 92.6% [85.2, 98.2] / 83.0% / 0.774 [0.695, 0.846] | 84.6% [75.0, 94.2] / 76.3% / 0.683 [0.596, 0.767] | 92.5% [84.9, 98.1] / 83.3% / 0.763 [0.682, 0.841] |
| `bm25` | `h6` | 79.2% [67.9, 88.7] / 70.8% / 0.660 [0.558, 0.754] | 89.1% [80.0, 96.4] / 75.0% / 0.669 [0.589, 0.750] | 88.9% [79.6, 96.3] / 80.6% / 0.734 [0.646, 0.818] | 82.7% [73.1, 92.3] / 72.4% / 0.639 [0.548, 0.728] | 88.7% [79.2, 96.2] / 77.7% / 0.754 [0.674, 0.830] |
| `bm25+ce` | `h6` | 84.9% [75.5, 94.3] / 76.1% / 0.702 [0.609, 0.790] | 89.1% [80.0, 96.4] / 79.5% / 0.720 [0.640, 0.796] | 92.6% [85.2, 98.2] / 84.0% / 0.802 [0.728, 0.872] | 84.6% [75.0, 94.2] / 78.2% / 0.692 [0.603, 0.778] | 94.3% [86.8, 100.0] / 85.2% / 0.781 [0.706, 0.853] |
| `hybrid:bge-small-en-v1.5` | `h6` | 90.6% [83.0, 98.1] / 77.4% / 0.736 [0.646, 0.820] | 90.9% [81.8, 98.2] / 81.2% / 0.713 [0.638, 0.784] | 92.6% [85.2, 98.2] / 82.7% / 0.779 [0.700, 0.851] | 86.5% [76.9, 94.2] / 79.2% / 0.689 [0.606, 0.771] | 92.5% [84.9, 98.1] / 85.9% / 0.816 [0.740, 0.884] |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 84.9% [75.5, 94.3] / 77.4% / 0.705 [0.614, 0.791] | 87.3% [78.2, 94.5] / 75.9% / 0.719 [0.637, 0.796] | 92.6% [85.2, 98.2] / 84.0% / 0.802 [0.727, 0.872] | 84.6% [75.0, 94.2] / 78.2% / 0.694 [0.610, 0.776] | 92.5% [84.9, 98.1] / 84.3% / 0.773 [0.694, 0.849] |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 73.6% [60.4, 84.9] / 64.8% / 0.580 [0.476, 0.675] | 89.1% [80.0, 96.4] / 78.2% / 0.664 [0.577, 0.745] | 74.1% [63.0, 85.2] / 65.7% / 0.586 [0.492, 0.677] | 78.8% [67.3, 88.5] / 70.5% / 0.595 [0.510, 0.678] | 83.0% [71.7, 92.5] / 73.0% / 0.660 [0.569, 0.747] |
| `bm25` | `h2` | 88.7% [79.2, 96.2] / 74.8% / 0.680 [0.585, 0.772] | 89.1% [80.0, 96.4] / 74.6% / 0.694 [0.615, 0.774] | 92.6% [85.2, 98.2] / 81.8% / 0.801 [0.727, 0.870] | 82.7% [73.1, 92.3] / 73.4% / 0.669 [0.578, 0.754] | 92.5% [84.9, 98.1] / 82.4% / 0.775 [0.703, 0.843] |
| `bm25+ce` | `h2` | 84.9% [75.5, 94.3] / 73.3% / 0.665 [0.567, 0.757] | 87.3% [78.2, 94.5] / 77.3% / 0.680 [0.590, 0.763] | 92.6% [85.2, 98.2] / 78.4% / 0.722 [0.643, 0.798] | 75.0% [63.5, 86.5] / 67.6% / 0.600 [0.502, 0.693] | 86.8% [77.4, 94.3] / 76.7% / 0.727 [0.634, 0.814] |
| `hybrid:bge-small-en-v1.5` | `h2` | 84.9% [75.5, 94.3] / 68.9% / 0.678 [0.584, 0.769] | 81.8% [70.9, 90.9] / 71.2% / 0.686 [0.588, 0.777] | 92.6% [85.2, 98.2] / 78.7% / 0.766 [0.687, 0.840] | 78.8% [67.3, 88.5] / 72.4% / 0.661 [0.565, 0.753] | 92.5% [84.9, 98.1] / 83.0% / 0.780 [0.713, 0.844] |
| `bm25` | `merge-400` | 84.9% [75.5, 94.3] / 74.8% / 0.693 [0.595, 0.784] | 89.1% [80.0, 96.4] / 75.4% / 0.684 [0.608, 0.760] | 90.7% [81.5, 98.2] / 82.1% / 0.758 [0.672, 0.838] | 82.7% [71.2, 92.3] / 74.4% / 0.685 [0.596, 0.771] | 90.6% [83.0, 98.1] / 79.6% / 0.780 [0.707, 0.849] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 90.6% [83.0, 98.1] / 79.9% / 0.758 [0.672, 0.837] | 90.9% [83.6, 98.2] / 83.0% / 0.732 [0.649, 0.807] | 94.4% [87.0, 100.0] / 82.7% / 0.776 [0.697, 0.849] | 84.6% [75.0, 94.2] / 78.2% / 0.696 [0.611, 0.777] | 94.3% [86.8, 100.0] / 85.9% / 0.826 [0.752, 0.892] |

## Models

- reranker: `local:Xenova/ms-marco-MiniLM-L-6-v2` @ `a09144355ade`
- embedding: `local:BAAI/bge-small-en-v1.5` @ `aa8f8b060edb`
- embedding: `local:snowflake/snowflake-arctic-embed-s` @ `e596f5074675`
<!-- /bench -->
