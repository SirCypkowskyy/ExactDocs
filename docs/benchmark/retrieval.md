# Retrieval results

Every retrieval configuration that could run, at every chunking configuration, on the whole
[golden set](golden-set.md). The metrics are defined in [Method](method.md#retrieval-metrics);
the default each budget gets is on [Recommended defaults](defaults.md).

## The recorded run

`packages/exactdocs/evals/results/retrieval.json`, recorded on 23–24 November 2026 on the reviewed
golden set (#490), on one self-hosted runner VM (Linux aarch64, 4 CPUs), with no provider, in
3 h 17 min ([the command and the timings](../evals.md#the-recorded-run)). A full local matrix
would take far longer, so it ran a subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking;
- `bm25+ce` at `default`, `h6` and `h2`, and `hybrid:bge-small-en-v1.5+ce` at `default` and `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6`;
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking).

Every result keeps each case's outcome, so every one has intervals and a paired test against its
budget's default ([Intervals and significance](method.md#intervals-and-significance)). The
latencies are that runner's. The review did not change any case's first expected section, so
recall@k and MRR equal those of the run this one replaces (13 November 2026, before the review)
for every configuration both ran; nDCG@10, section recall and the per-kind numbers count the
sections and kinds the review fixed.

**BM25 was scored again for #503.** Until then a chunk counted for an expected section only when
it was the section, part of it, or named after one of its parents; a chunk that held the section
next to a sibling (`h2`, `merge-400`, and a long section cut again at `default`) was scored a
miss ([Method](method.md#chunking-configurations)). BM25 is deterministic, so it ran again at
every chunking on 24 November 2026 (Linux x86_64, 4 CPUs) with the fixed rule: the same results
for every case, re-scored, with the recorded runner's search times kept, so the latencies are
still that runner's. At `h6` no case changed; at `default` one; at `h2` 24 and at `merge-400` 34.
**The model results still have the old rule**: hybrid at `h2` and `merge-400` and the
cross-encoder at `h2` are undercounted until they are recorded again with
[#501](https://github.com/SirCypkowskyy/ExactDocs/issues/501).

**Every hosted configuration is not measured yet**: hybrid on a hosted embedding model, HyDE,
agentic search and every configuration reranked by the LLM judge. They run only from the manual
*Retrieval eval (real providers)* workflow (`.github/workflows/eval-providers.yml`) with the
`benchmark` input ticked, or locally with `--allow-providers`
([Running the hosted part](../evals.md#running-the-hosted-part)). They are listed under
"Not run" below.

<!-- bench:retrieval-run -->
- Golden set: 321 cases, fingerprint `sha256:7dd51c59057c279a`, projects starlette, pydantic, tanstack-query, zod, electron.
- ExactDocs commit `861b5ea2b502338380ef73b801397d58a6e4030f` (`0.0.0.post1.dev0+37677e5`), Python 3.14.10, Linux aarch64, 4 CPUs.
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

- BM25 scores alike at `h2`, `default` and `merge-400`: 82.8%, 81.7% and 81.7% recall@5. `h2`
  comes first by the benchmark's ordering, so the summary names it, but its lead over `default`
  is not significant on any metric (recall@5 +1.1 points, p 0.58; MRR p 0.11), and its chunks are
  about twice as long (7,065 estimated tokens in a question's ten results against 3,464,
  [text calibration](../evals.md#calibration)). `h6`, where every heading starts a chunk, is
  below them: 79.8%, and significantly worse than `h2` on recall@10, MRR and nDCG@10. The
  shipped default stays `default` (#381); a non-significant lead does not change it.
- Hybrid search on bge-small is the best local configuration, at `h6`, but only 1.9 points of
  recall@5 above BM25 at `h2`, under the 5-point margin and not significant (p 0.41).
- The intervals per kind and per project are about twice as wide as the whole set's (around
  ±10 points of recall@5 on some 50 cases): differences of a few points there say little.
- The cross-encoder on BM25 matches hybrid at `h6` and at `default` (84.6%, not significant
  over BM25: p 0.16 and 0.18) but adds about 2.5 s per question (p50) on this runner, and loses
  recall at `h2`, whose chunks are longer than its window. On hybrid it adds nothing.
- snowflake-arctic-embed-s scores below BM25.
- No configuration returned a result of another version, and none signalled "no answer" on any of
  the 54 unanswerable cases: `search_docs` gives a caller no way to tell an unanswerable question
  from an answerable one by its results today.
- On `cross-page` questions, section recall@5 is up to 19 points below recall@5: the first page
  of an answer often comes back without the second.

<!-- bench:retrieval -->
## Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 52.1% [46.1, 58.1] | 81.7% [76.8, 86.1] | 89.1% [85.4, 92.9] | 0.651 [0.604, 0.698] | 0.706 [0.668, 0.743] | 0 | 100.0% / 0.0% | 0.0% | 40.2 | 58.0 | 0 | 0.0000 | - |
| `bm25+ce` | `default` | local | ran | 55.8% [49.8, 61.8] | 84.6% [80.2, 88.8] | 90.6% [86.9, 94.0] | 0.680 [0.633, 0.726] | 0.723 [0.686, 0.759] | 0 | 100.0% / 0.0% | 0.0% | 2478.6 | 2782.6 | 10945 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 56.5% [50.6, 62.5] | 84.3% [79.8, 88.4] | 89.9% [86.1, 93.3] | 0.688 [0.642, 0.734] | 0.741 [0.705, 0.778] | 0 | 100.0% / 0.0% | 0.0% | 65.0 | 86.0 | 22 | 0.0000 | 1436 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | local | ran | 55.4% [49.4, 61.4] | 83.2% [78.6, 87.6] | 88.8% [84.6, 92.5] | 0.675 [0.628, 0.722] | 0.715 [0.677, 0.751] | 0 | 100.0% / 0.0% | 0.0% | 2502.3 | 2846.8 | 10019 | 0.0000 | 1436 |
| `bm25` | `h6` | none | ran | 49.8% [43.8, 55.8] | 79.8% [74.9, 84.3] | 86.9% [82.8, 90.6] | 0.626 [0.578, 0.674] | 0.683 [0.643, 0.722] | 0 | 100.0% / 0.0% | 0.0% | 60.0 | 78.1 | 0 | 0.0000 | - |
| `bm25+ce` | `h6` | local | ran | 57.7% [51.7, 63.7] | 84.6% [80.2, 88.8] | 90.3% [86.5, 93.6] | 0.692 [0.645, 0.737] | 0.730 [0.693, 0.765] | 0 | 100.0% / 0.0% | 0.0% | 2500.8 | 2944.6 | 9158 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h6` | local | ran | 54.7% [48.7, 60.7] | 84.6% [80.2, 88.8] | 91.4% [88.0, 94.4] | 0.676 [0.630, 0.722] | 0.738 [0.702, 0.773] | 0 | 100.0% / 0.0% | 0.0% | 82.0 | 108.7 | 22 | 0.0000 | 1830 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | local | ran | 57.3% [51.3, 63.3] | 83.5% [79.0, 88.0] | 90.3% [86.5, 93.6] | 0.689 [0.642, 0.735] | 0.728 [0.691, 0.764] | 0 | 100.0% / 0.0% | 0.0% | 2555.0 | 2987.7 | 8569 | 0.0000 | 1830 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | local | ran | 40.1% [34.5, 46.1] | 75.3% [70.0, 80.5] | 84.6% [80.2, 88.8] | 0.547 [0.500, 0.596] | 0.607 [0.568, 0.648] | 0 | 100.0% / 0.0% | 0.0% | 84.8 | 110.5 | 22 | 0.0000 | 2026 |
| `bm25` | `h2` | none | ran | 55.4% [49.4, 61.4] | 82.8% [78.3, 87.3] | 90.3% [86.5, 93.6] | 0.677 [0.630, 0.724] | 0.714 [0.677, 0.751] | 0 | 100.0% / 0.0% | 0.0% | 19.8 | 27.6 | 0 | 0.0000 | - |
| `bm25+ce` | `h2` | local | ran | 48.3% [42.3, 54.3] | 72.7% [67.4, 77.9] | 79.8% [74.9, 84.6] | 0.590 [0.539, 0.641] | 0.646 [0.604, 0.687] | 0 | 100.0% / 0.0% | 0.0% | 2460.7 | 2576.9 | 21844 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h2` | local | ran | 52.1% [46.1, 58.1] | 73.4% [68.2, 78.6] | 80.5% [75.7, 85.0] | 0.614 [0.562, 0.667] | 0.673 [0.631, 0.715] | 0 | 100.0% / 0.0% | 0.0% | 42.6 | 58.2 | 22 | 0.0000 | 818 |
| `bm25` | `merge-400` | none | ran | 53.9% [47.9, 59.9] | 81.7% [76.8, 86.1] | 88.8% [85.0, 92.5] | 0.662 [0.615, 0.708] | 0.713 [0.674, 0.749] | 0 | 100.0% / 0.0% | 0.0% | 32.4 | 44.9 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | ran | 52.1% [46.1, 58.1] | 78.3% [73.4, 83.2] | 83.5% [79.0, 87.6] | 0.638 [0.590, 0.686] | 0.683 [0.643, 0.724] | 0 | 100.0% / 0.0% | 0.0% | 56.3 | 73.6 | 22 | 0.0000 | 1363 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489).

## Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | `bm25` at `h2` | -3.4 [-8.2, +1.5], p 0.18 | -1.1 [-4.9, +2.6], p 0.58 | -1.1 [-4.1, +1.9], p 0.45 | -0.026 [-0.058, +0.006], p 0.11 | -0.009 [-0.032, +0.015], p 0.48 |
| `bm25+ce` | `default` | local | `bm25` at `h2` | +0.4 [-6.0, +7.1], p 0.91 | +1.9 [-2.6, +6.0], p 0.42 | +0.4 [-3.4, +4.1], p 0.85 | +0.003 [-0.042, +0.049], p 0.91 | +0.009 [-0.027, +0.045], p 0.63 |
| `hybrid:bge-small-en-v1.5` | `default` | local | `bm25` at `h2` | +1.1 [-4.9, +7.1], p 0.72 | +1.5 [-2.6, +5.6], p 0.49 | -0.4 [-4.1, +3.4], p 0.85 | +0.011 [-0.031, +0.054], p 0.64 | +0.027 [-0.008, +0.062], p 0.13 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | local | `bm25` at `h2` | +0.0 [-6.4, +6.7], p 1 | +0.4 [-4.1, +4.9], p 0.87 | -1.5 [-5.6, +2.2], p 0.47 | -0.002 [-0.046, +0.044], p 0.92 | +0.001 [-0.035, +0.037], p 0.96 |
| `bm25` | `h6` | none | `bm25` at `h2` | **-5.6** [-11.2, +0.0], p 0.048 | -3.0 [-7.1, +1.1], p 0.16 | **-3.4** [-6.7, -0.4], p 0.041 | **-0.051** [-0.088, -0.014], p 0.008 | **-0.032** [-0.059, -0.004], p 0.031 |
| `bm25+ce` | `h6` | local | `bm25` at `h2` | +2.2 [-4.1, +9.0], p 0.49 | +1.9 [-2.6, +6.0], p 0.42 | +0.0 [-4.1, +4.1], p 1 | +0.015 [-0.029, +0.060], p 0.52 | +0.016 [-0.019, +0.051], p 0.39 |
| `hybrid:bge-small-en-v1.5` | `h6` | local | `bm25` at `h2` | -0.8 [-6.8, +5.6], p 0.81 | +1.9 [-2.2, +6.4], p 0.41 | +1.1 [-3.0, +4.9], p 0.58 | -0.001 [-0.044, +0.043], p 0.96 | +0.023 [-0.011, +0.058], p 0.18 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | local | `bm25` at `h2` | +1.9 [-4.5, +8.2], p 0.57 | +0.8 [-3.8, +5.2], p 0.75 | +0.0 [-4.1, +4.1], p 1 | +0.012 [-0.032, +0.057], p 0.6 | +0.014 [-0.021, +0.049], p 0.44 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | local | `bm25` at `h2` | **-15.4** [-22.9, -7.5], p < 0.001 | **-7.5** [-13.5, -1.9], p 0.013 | **-5.6** [-10.1, -1.1], p 0.02 | **-0.130** [-0.184, -0.076], p < 0.001 | **-0.107** [-0.148, -0.066], p < 0.001 |
| `bm25+ce` | `h2` | local | `bm25` at `h2` | **-7.1** [-13.9, -0.4], p 0.04 | **-10.1** [-15.4, -4.9], p < 0.001 | **-10.5** [-15.7, -5.6], p < 0.001 | **-0.087** [-0.139, -0.036], p < 0.001 | **-0.069** [-0.108, -0.029], p < 0.001 |
| `hybrid:bge-small-en-v1.5` | `h2` | local | `bm25` at `h2` | -3.4 [-9.0, +2.2], p 0.25 | **-9.4** [-14.2, -4.1], p < 0.001 | **-9.7** [-15.0, -4.5], p < 0.001 | **-0.063** [-0.108, -0.018], p 0.0067 | **-0.041** [-0.078, -0.004], p 0.033 |
| `bm25` | `merge-400` | none | `bm25` at `h2` | -1.5 [-6.4, +3.4], p 0.56 | -1.1 [-4.5, +2.2], p 0.54 | -1.5 [-4.1, +1.1], p 0.3 | -0.015 [-0.048, +0.018], p 0.37 | -0.002 [-0.027, +0.024], p 0.89 |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | `bm25` at `h2` | -3.4 [-9.7, +3.0], p 0.3 | -4.5 [-9.7, +0.8], p 0.092 | **-6.7** [-11.6, -2.2], p 0.0066 | -0.039 [-0.087, +0.009], p 0.11 | -0.031 [-0.073, +0.011], p 0.15 |

## By question kind (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 83.0% [71.7, 92.5] / 78.6% / 0.695 [0.603, 0.781] | 70.8% [58.3, 83.3] / 54.3% / 0.588 [0.511, 0.663] | 82.8% [72.4, 91.4] / 72.3% / 0.710 [0.626, 0.793] | 82.7% [73.1, 92.3] / 82.4% / 0.754 [0.667, 0.837] | clean 100.0%, no answer 0.0% | 87.5% [78.6, 94.6] / 84.5% / 0.768 [0.691, 0.841] |
| `bm25+ce` | `default` | 90.6% [83.0, 98.1] / 86.2% / 0.764 [0.684, 0.839] | 72.9% [60.4, 85.4] / 59.2% / 0.591 [0.514, 0.669] | 84.5% [74.1, 93.1] / 77.9% / 0.725 [0.644, 0.804] | 88.5% [78.8, 96.2] / 90.7% / 0.776 [0.695, 0.850] | clean 100.0%, no answer 0.0% | 85.7% [76.8, 94.6] / 81.0% / 0.747 [0.665, 0.826] |
| `hybrid:bge-small-en-v1.5` | `default` | 84.9% [75.5, 94.3] / 81.1% / 0.706 [0.618, 0.791] | 75.0% [62.5, 87.5] / 64.2% / 0.657 [0.582, 0.728] | 84.5% [74.1, 93.1] / 78.2% / 0.730 [0.645, 0.811] | 86.5% [76.9, 94.2] / 88.8% / 0.814 [0.736, 0.886] | clean 100.0%, no answer 0.0% | 89.3% [80.4, 96.4] / 86.3% / 0.791 [0.712, 0.865] |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 88.7% [79.2, 96.2] / 85.2% / 0.748 [0.665, 0.828] | 70.8% [58.3, 83.3] / 56.4% / 0.590 [0.512, 0.669] | 82.8% [72.4, 91.4] / 76.4% / 0.717 [0.633, 0.800] | 88.5% [78.8, 96.2] / 90.7% / 0.762 [0.677, 0.840] | clean 100.0%, no answer 0.0% | 83.9% [73.2, 92.9] / 79.2% / 0.745 [0.663, 0.824] |
| `bm25` | `h6` | 83.0% [71.7, 92.5] / 78.6% / 0.680 [0.589, 0.766] | 66.7% [52.1, 79.2] / 51.2% / 0.563 [0.487, 0.637] | 79.3% [69.0, 89.7] / 70.9% / 0.672 [0.584, 0.759] | 80.8% [69.2, 90.4] / 79.5% / 0.704 [0.608, 0.798] | clean 100.0%, no answer 0.0% | 87.5% [78.6, 94.6] / 84.5% / 0.779 [0.697, 0.858] |
| `bm25+ce` | `h6` | 90.6% [83.0, 98.1] / 86.2% / 0.778 [0.696, 0.854] | 72.9% [60.4, 85.4] / 58.2% / 0.597 [0.518, 0.675] | 84.5% [74.1, 93.1] / 77.9% / 0.732 [0.652, 0.812] | 88.5% [78.8, 96.2] / 89.7% / 0.773 [0.691, 0.848] | clean 100.0%, no answer 0.0% | 85.7% [76.8, 94.6] / 81.8% / 0.756 [0.674, 0.836] |
| `hybrid:bge-small-en-v1.5` | `h6` | 84.9% [75.5, 94.3] / 81.5% / 0.735 [0.650, 0.812] | 77.1% [64.6, 87.5] / 63.9% / 0.640 [0.567, 0.710] | 84.5% [74.1, 93.1] / 79.0% / 0.743 [0.662, 0.818] | 86.5% [76.9, 94.2] / 87.2% / 0.776 [0.697, 0.852] | clean 100.0%, no answer 0.0% | 89.3% [80.4, 96.4] / 86.3% / 0.783 [0.701, 0.859] |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 88.7% [79.2, 96.2] / 86.2% / 0.773 [0.695, 0.848] | 72.9% [60.4, 85.4] / 56.4% / 0.608 [0.531, 0.682] | 82.8% [72.4, 91.4] / 77.9% / 0.737 [0.655, 0.817] | 88.5% [78.8, 96.2] / 89.7% / 0.759 [0.675, 0.838] | clean 100.0%, no answer 0.0% | 83.9% [73.2, 92.9] / 80.1% / 0.751 [0.669, 0.832] |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 83.0% [73.6, 92.5] / 78.3% / 0.669 [0.582, 0.755] | 66.7% [52.1, 79.2] / 47.6% / 0.487 [0.415, 0.556] | 72.4% [60.3, 82.8] / 65.1% / 0.553 [0.461, 0.645] | 80.8% [69.2, 90.4] / 81.7% / 0.690 [0.604, 0.776] | clean 100.0%, no answer 0.0% | 73.2% [60.7, 83.9] / 72.3% / 0.631 [0.534, 0.724] |
| `bm25` | `h2` | 81.1% [69.8, 90.6] / 73.9% / 0.709 [0.622, 0.790] | 75.0% [62.5, 87.5] / 60.4% / 0.644 [0.578, 0.709] | 86.2% [77.6, 94.8] / 75.4% / 0.709 [0.621, 0.796] | 86.5% [76.9, 94.2] / 86.2% / 0.807 [0.726, 0.884] | clean 100.0%, no answer 0.0% | 83.9% [73.2, 92.9] / 80.1% / 0.700 [0.614, 0.785] |
| `bm25+ce` | `h2` | 77.4% [66.0, 88.7] / 73.3% / 0.690 [0.601, 0.773] | 64.6% [50.0, 77.1] / 57.6% / 0.584 [0.500, 0.665] | 81.0% [70.7, 89.7] / 73.5% / 0.678 [0.596, 0.758] | 80.8% [69.2, 90.4] / 83.0% / 0.741 [0.641, 0.835] | clean 100.0%, no answer 0.0% | 58.9% [46.4, 71.4] / 57.7% / 0.536 [0.432, 0.638] |
| `hybrid:bge-small-en-v1.5` | `h2` | 81.1% [69.8, 90.6] / 75.2% / 0.695 [0.605, 0.780] | 64.6% [50.0, 77.1] / 62.2% / 0.625 [0.553, 0.697] | 82.8% [72.4, 91.4] / 76.1% / 0.743 [0.655, 0.826] | 80.8% [69.2, 90.4] / 82.0% / 0.762 [0.671, 0.848] | clean 100.0%, no answer 0.0% | 57.1% [44.6, 69.6] / 54.2% / 0.538 [0.429, 0.648] |
| `bm25` | `merge-400` | 81.1% [69.8, 90.6] / 77.4% / 0.713 [0.620, 0.800] | 70.8% [58.3, 83.3] / 58.0% / 0.595 [0.519, 0.671] | 81.0% [70.7, 91.4] / 72.6% / 0.711 [0.627, 0.795] | 80.8% [69.2, 90.4] / 79.5% / 0.733 [0.642, 0.820] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 88.1% / 0.794 [0.719, 0.865] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 81.1% [69.8, 90.6] / 77.7% / 0.703 [0.607, 0.791] | 70.8% [58.3, 83.3] / 59.4% / 0.582 [0.493, 0.669] | 79.3% [69.0, 89.7] / 72.9% / 0.698 [0.606, 0.786] | 76.9% [65.4, 88.5] / 79.2% / 0.683 [0.581, 0.778] | clean 100.0%, no answer 0.0% | 82.1% [71.4, 91.1] / 78.3% / 0.737 [0.651, 0.816] |

## By project (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `bm25` | `default` | 79.2% [67.9, 88.7] / 69.8% / 0.690 [0.593, 0.780] | 81.8% [70.9, 90.9] / 75.0% / 0.678 [0.598, 0.757] | 85.2% [74.1, 94.4] / 81.2% / 0.763 [0.681, 0.840] | 75.0% [63.5, 86.5] / 66.0% / 0.629 [0.541, 0.714] | 86.8% [77.4, 94.3] / 82.0% / 0.768 [0.695, 0.836] |
| `bm25+ce` | `default` | 81.1% [69.8, 90.6] / 74.2% / 0.689 [0.601, 0.773] | 83.6% [72.7, 92.7] / 80.5% / 0.722 [0.646, 0.795] | 90.7% [83.3, 98.2] / 83.6% / 0.772 [0.691, 0.845] | 78.8% [67.3, 90.4] / 73.1% / 0.658 [0.571, 0.742] | 88.7% [79.2, 96.2] / 84.9% / 0.773 [0.696, 0.847] |
| `hybrid:bge-small-en-v1.5` | `default` | 84.9% [75.5, 94.3] / 77.4% / 0.749 [0.655, 0.834] | 83.6% [72.7, 92.7] / 81.2% / 0.714 [0.640, 0.782] | 85.2% [75.9, 94.4] / 80.6% / 0.764 [0.683, 0.840] | 78.8% [67.3, 88.5] / 75.6% / 0.666 [0.580, 0.749] | 88.7% [79.2, 96.2] / 85.2% / 0.813 [0.738, 0.881] |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 79.2% [67.9, 88.7] / 73.6% / 0.675 [0.581, 0.763] | 80.0% [69.1, 89.1] / 77.7% / 0.714 [0.634, 0.790] | 92.6% [85.2, 98.2] / 82.7% / 0.773 [0.693, 0.844] | 76.9% [65.4, 88.5] / 72.4% / 0.651 [0.565, 0.732] | 86.8% [77.4, 94.3] / 83.0% / 0.761 [0.679, 0.839] |
| `bm25` | `h6` | 77.4% [66.0, 88.7] / 68.9% / 0.657 [0.556, 0.753] | 81.8% [70.9, 90.9] / 74.1% / 0.667 [0.588, 0.747] | 85.2% [74.1, 94.4] / 80.2% / 0.732 [0.642, 0.815] | 75.0% [63.5, 86.5] / 67.0% / 0.606 [0.514, 0.697] | 79.2% [67.9, 88.7] / 76.6% / 0.750 [0.669, 0.826] |
| `bm25+ce` | `h6` | 81.1% [69.8, 90.6] / 74.2% / 0.689 [0.597, 0.777] | 83.6% [72.7, 92.7] / 78.6% / 0.717 [0.638, 0.792] | 90.7% [81.5, 98.2] / 83.6% / 0.798 [0.724, 0.869] | 78.8% [67.3, 90.4] / 74.0% / 0.664 [0.575, 0.749] | 88.7% [79.2, 96.2] / 84.9% / 0.780 [0.704, 0.851] |
| `hybrid:bge-small-en-v1.5` | `h6` | 84.9% [75.5, 94.3] / 75.5% / 0.722 [0.631, 0.806] | 83.6% [72.7, 92.7] / 81.2% / 0.711 [0.636, 0.781] | 87.0% [77.8, 94.4] / 82.4% / 0.775 [0.695, 0.847] | 78.8% [67.3, 88.5] / 75.0% / 0.665 [0.582, 0.746] | 88.7% [79.2, 96.2] / 85.2% / 0.814 [0.739, 0.882] |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 81.1% [69.8, 90.6] / 75.5% / 0.695 [0.603, 0.780] | 80.0% [69.1, 89.1] / 75.0% / 0.715 [0.635, 0.791] | 92.6% [85.2, 98.2] / 83.6% / 0.798 [0.723, 0.869] | 76.9% [65.4, 88.5] / 74.0% / 0.661 [0.577, 0.741] | 86.8% [77.4, 94.3] / 84.0% / 0.770 [0.690, 0.847] |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 69.8% [56.6, 81.1] / 63.8% / 0.571 [0.468, 0.666] | 83.6% [72.7, 92.7] / 77.3% / 0.658 [0.571, 0.739] | 70.4% [57.4, 81.5] / 65.7% / 0.583 [0.490, 0.674] | 76.9% [65.4, 88.5] / 67.6% / 0.571 [0.488, 0.652] | 75.5% [64.1, 86.8] / 71.9% / 0.651 [0.559, 0.737] |
| `bm25` | `h2` | 81.1% [69.8, 90.6] / 73.0% / 0.673 [0.578, 0.765] | 83.6% [72.7, 92.7] / 74.6% / 0.691 [0.613, 0.770] | 87.0% [77.8, 94.4] / 81.5% / 0.799 [0.725, 0.869] | 73.1% [61.5, 84.6] / 67.6% / 0.638 [0.547, 0.724] | 88.7% [79.2, 96.2] / 80.6% / 0.768 [0.696, 0.835] |
| `bm25+ce` | `h2` | 75.5% [64.1, 86.8] / 67.9% / 0.629 [0.533, 0.721] | 72.7% [60.0, 83.6] / 70.9% / 0.648 [0.550, 0.740] | 81.5% [70.4, 90.7] / 78.1% / 0.716 [0.634, 0.792] | 55.8% [42.3, 69.2] / 56.1% / 0.525 [0.427, 0.622] | 77.4% [66.0, 88.7] / 72.3% / 0.707 [0.613, 0.797] |
| `hybrid:bge-small-en-v1.5` | `h2` | 71.7% [58.5, 83.0] / 63.8% / 0.620 [0.523, 0.715] | 72.7% [60.0, 83.6] / 68.5% / 0.662 [0.561, 0.757] | 79.6% [68.5, 88.9] / 77.8% / 0.755 [0.671, 0.833] | 63.5% [50.0, 76.9] / 64.1% / 0.589 [0.488, 0.687] | 79.2% [67.9, 88.7] / 75.4% / 0.736 [0.651, 0.816] |
| `bm25` | `merge-400` | 81.1% [69.8, 90.6] / 73.0% / 0.690 [0.592, 0.782] | 81.8% [70.9, 90.9] / 75.4% / 0.683 [0.607, 0.758] | 87.0% [77.8, 94.4] / 81.8% / 0.757 [0.671, 0.837] | 75.0% [63.5, 86.5] / 68.6% / 0.657 [0.566, 0.744] | 83.0% [71.7, 92.5] / 78.5% / 0.775 [0.701, 0.845] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 77.4% [66.0, 88.7] / 69.2% / 0.665 [0.564, 0.758] | 81.8% [70.9, 90.9] / 79.4% / 0.688 [0.597, 0.771] | 77.8% [66.7, 88.9] / 74.4% / 0.689 [0.593, 0.779] | 75.0% [63.5, 86.5] / 71.8% / 0.642 [0.554, 0.727] | 79.2% [67.9, 90.6] / 73.8% / 0.732 [0.637, 0.822] |

## Models

- reranker: `local:Xenova/ms-marco-MiniLM-L-6-v2` @ `a09144355ade`
- embedding: `local:BAAI/bge-small-en-v1.5` @ `aa8f8b060edb`
- embedding: `local:snowflake/snowflake-arctic-embed-s` @ `e596f5074675`
<!-- /bench -->
