# Retrieval results

Every retrieval configuration that could run, at every chunking configuration, on the whole
[golden set](golden-set.md). The metrics are defined in [Method](method.md#retrieval-metrics);
the default each budget gets is on [Recommended defaults](defaults.md).

## The recorded run

`packages/exactdocs/evals/results/retrieval.json`, recorded on 13 November 2026 with #347, with
no network, in about 1 h 40 min. A full local matrix (three embedding models, each with and
without the cross-encoder, at four chunkings) would take about six hours on that machine, so it
ran a subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking;
- `bm25+ce` at `h6` and `h2`, and `hybrid:bge-small-en-v1.5+ce` at `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6`;
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking).

#381 relabelled the run when it changed the default chunking, without measuring again: `default`
is what was `h3-max-4000`, and `h6` what was `default`. BM25 at `default` and at `h6` was run
again with #381 and matched the recorded recall.

**Intervals and tests** ([Intervals and significance](method.md#intervals-and-significance)) need
every case's outcome, and the run kept aggregates only. For #489, BM25 was run again at every
chunking (23 November 2026, Linux x86_64, 4 CPUs): its recall@k, MRR, nDCG@10, section recall and
rates matched the recorded ones exactly, overall, per kind and per project, so its per-case
outcomes were added to the recorded results (each says so in `rows_from`) with the intervals and
tests they give. Every other number, the latencies included, is still the recorded run's. The
configurations with a model were not run again (that takes hours of embedding): they show no
interval and no test until the next recorded run.

**Every hosted configuration is not measured yet**: hybrid on a hosted embedding model, HyDE,
agentic search and every configuration reranked by the LLM judge. They run only from the manual
*Retrieval eval (real providers)* workflow (`.github/workflows/eval-providers.yml`) with the
`benchmark` input ticked, or locally with `--allow-providers`
([Running the hosted part](../evals.md#running-the-hosted-part)). They are listed under
"Not run" below.

<!-- bench:retrieval-run -->
- Golden set: 321 cases, fingerprint `sha256:39f6f9d5e909d128`, projects starlette, pydantic, tanstack-query, zod, electron.
- ExactDocs commit `fe156aa8aed0ebd86bcb45e930be9769e4056535` (`0.1.1.post195.dev0+8b20c4e`), Python 3.14.8, Darwin arm64, 10 CPUs.
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

- BM25 is best at `default` (split level 3, 4,000 characters): 81.7% recall@5 (95% interval
  76.8% to 86.1%), against 79.8% at `h6`, where every heading starts a chunk. That recall@5 gap
  alone is not significant (p 0.07), but recall@10, MRR and nDCG@10 are significantly better at
  `default`, and `h2` and `merge-400` significantly worse. #381 made it the default for new
  libraries.
- Hybrid search on bge-small is the best local configuration, at `h6`, but only 3 points of
  recall@5 above BM25 at `default`, under the 5-point margin, and inside BM25's own interval;
  it cannot be tested until a recorded run keeps its per-case outcomes.
- The intervals per kind and per project are about twice as wide as the whole set's (around
  ±10 points of recall@5 on some 50 cases): differences of a few points there say little.
- The cross-encoder on BM25 matches hybrid at `h6` (84.6%) but adds about 1.3 s per
  question (p50), and loses recall at `h2`, whose chunks are longer than its window.
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
| `bm25` | `default` | none | ran | 52.1% [46.1, 58.1] | 81.7% [76.8, 86.1] | 89.1% [85.4, 92.9] | 0.651 [0.604, 0.698] | 0.705 [0.665, 0.743] | 0 | 100.0% / 0.0% | 0.0% | 47.6 | 56.7 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 56.5% | 84.3% | 90.3% | 0.687 | 0.742 | 0 | 100.0% / 0.0% | 0.0% | 69.4 | 88.9 | 22 | 0.0000 | 810 |
| `bm25` | `h6` | none | ran | 49.8% [43.8, 55.8] | 79.8% [74.9, 84.3] | 86.9% [82.8, 90.6] | 0.626 [0.578, 0.674] | 0.684 [0.643, 0.723] | 0 | 100.0% / 0.0% | 0.0% | 71.9 | 90.9 | 0 | 0.0000 | - |
| `bm25+ce` | `h6` | local | ran | 57.7% | 84.6% | 90.3% | 0.692 | 0.732 | 0 | 100.0% / 0.0% | 0.0% | 1356.6 | 1590.5 | 9158 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h6` | local | ran | 54.7% | 84.6% | 91.4% | 0.675 | 0.738 | 0 | 100.0% / 0.0% | 0.0% | 96.2 | 127.0 | 22 | 0.0000 | 1026 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | local | ran | 57.3% | 83.5% | 90.3% | 0.689 | 0.730 | 0 | 100.0% / 0.0% | 0.0% | 1389.7 | 1655.1 | 8566 | 0.0000 | 1026 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | local | ran | 40.1% | 75.3% | 84.6% | 0.547 | 0.611 | 0 | 100.0% / 0.0% | 0.0% | 95.2 | 123.4 | 22 | 0.0000 | 962 |
| `bm25` | `h2` | none | ran | 51.7% [45.7, 57.7] | 76.0% [70.8, 81.3] | 81.7% [76.8, 86.1] | 0.626 [0.576, 0.677] | 0.665 [0.622, 0.708] | 0 | 100.0% / 0.0% | 0.0% | 20.8 | 25.9 | 0 | 0.0000 | - |
| `bm25+ce` | `h2` | local | ran | 48.3% | 72.7% | 79.8% | 0.590 | 0.645 | 0 | 100.0% / 0.0% | 0.0% | 1332.1 | 1476.9 | 21844 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h2` | local | ran | 51.7% | 73.4% | 80.5% | 0.612 | 0.670 | 0 | 100.0% / 0.0% | 0.0% | 48.9 | 65.3 | 22 | 0.0000 | 462 |
| `bm25` | `merge-400` | none | ran | 49.1% [43.1, 55.1] | 74.2% [68.9, 79.4] | 80.5% [75.7, 85.0] | 0.602 [0.552, 0.652] | 0.645 [0.602, 0.689] | 0 | 100.0% / 0.0% | 0.0% | 33.6 | 39.8 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | ran | 52.1% | 78.3% | 83.5% | 0.638 | 0.687 | 0 | 100.0% / 0.0% | 0.0% | 60.7 | 75.8 | 22 | 0.0000 | 673 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489). A result recorded without its per-case outcomes has none.

## Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `bm25` | `h6` | none | `bm25` at `default` | -2.2 [-5.6, +1.1], p 0.21 | -1.9 [-3.8, +0.0], p 0.07 | **-2.2** [-4.1, -0.8], p 0.016 | **-0.025** [-0.047, -0.005], p 0.017 | **-0.021** [-0.036, -0.007], p 0.004 |
| `bm25` | `h2` | none | `bm25` at `default` | -0.4 [-5.6, +4.9], p 0.89 | **-5.6** [-10.5, -1.1], p 0.023 | **-7.5** [-12.0, -3.0], p 0.0011 | -0.025 [-0.067, +0.015], p 0.23 | **-0.040** [-0.074, -0.007], p 0.023 |
| `bm25` | `merge-400` | none | `bm25` at `default` | -3.0 [-6.7, +0.8], p 0.14 | **-7.5** [-11.2, -4.1], p < 0.001 | **-8.6** [-12.4, -5.2], p < 0.001 | **-0.049** [-0.080, -0.019], p 0.002 | **-0.060** [-0.088, -0.033], p < 0.001 |

Not tested, recorded without per-case outcomes: `hybrid:bge-small-en-v1.5` at `default`, `bm25+ce` at `h6`, `hybrid:bge-small-en-v1.5` at `h6`, `hybrid:bge-small-en-v1.5+ce` at `h6`, `hybrid:snowflake-arctic-embed-s` at `h6`, `bm25+ce` at `h2`, `hybrid:bge-small-en-v1.5` at `h2`, `hybrid:bge-small-en-v1.5` at `merge-400`.

## By question kind (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 82.7% [71.2, 92.3] / 78.2% / 0.688 [0.594, 0.778] | 71.7% [58.5, 83.0] / 53.9% / 0.585 [0.509, 0.660] | 83.0% [71.7, 92.5] / 77.4% / 0.740 [0.649, 0.827] | 82.7% [73.1, 92.3] / 82.7% / 0.745 [0.654, 0.832] | clean 100.0%, no answer 0.0% | 87.7% [79.0, 94.7] / 84.2% / 0.762 [0.685, 0.836] |
| `hybrid:bge-small-en-v1.5` | `default` | 84.6% / 81.7% / 0.700 | 75.5% / 65.1% / 0.662 | 84.9% / 81.1% / 0.744 | 86.5% / 87.5% / 0.806 | clean 100.0%, no answer 0.0% | 89.5% / 86.8% / 0.793 |
| `bm25` | `h6` | 82.7% [71.2, 92.3] / 79.2% / 0.674 [0.578, 0.765] | 66.0% [52.8, 79.2] / 50.2% / 0.561 [0.488, 0.634] | 81.1% [69.8, 90.6] / 76.4% / 0.698 [0.601, 0.790] | 80.8% [69.2, 90.4] / 79.8% / 0.698 [0.601, 0.795] | clean 100.0%, no answer 0.0% | 87.7% [79.0, 94.7] / 84.2% / 0.780 [0.698, 0.857] |
| `bm25+ce` | `h6` | 90.4% / 87.8% / 0.790 | 73.6% / 57.7% / 0.597 | 84.9% / 83.0% / 0.757 | 88.5% / 88.5% / 0.757 | clean 100.0%, no answer 0.0% | 86.0% / 83.3% / 0.760 |
| `hybrid:bge-small-en-v1.5` | `h6` | 84.6% / 82.0% / 0.730 | 77.4% / 64.8% / 0.643 | 84.9% / 82.1% / 0.756 | 86.5% / 86.5% / 0.764 | clean 100.0%, no answer 0.0% | 89.5% / 86.8% / 0.793 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 88.5% / 86.9% / 0.779 | 73.6% / 56.1% / 0.603 | 83.0% / 82.1% / 0.766 | 88.5% / 88.5% / 0.744 | clean 100.0%, no answer 0.0% | 84.2% / 81.6% / 0.756 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 82.7% / 78.8% / 0.659 | 64.1% / 45.3% / 0.469 | 75.5% / 71.7% / 0.591 | 80.8% / 81.7% / 0.682 | clean 100.0%, no answer 0.0% | 73.7% / 74.6% / 0.653 |
| `bm25` | `h2` | 78.8% [67.3, 90.4] / 72.8% / 0.692 [0.593, 0.786] | 69.8% [56.6, 81.1] / 56.3% / 0.592 [0.517, 0.666] | 83.0% [71.7, 92.5] / 76.4% / 0.717 [0.617, 0.812] | 82.7% [71.2, 92.3] / 82.7% / 0.752 [0.654, 0.843] | clean 100.0%, no answer 0.0% | 66.7% [54.4, 79.0] / 64.9% / 0.580 [0.476, 0.682] |
| `bm25+ce` | `h2` | 76.9% / 73.7% / 0.688 | 64.1% / 57.2% / 0.580 | 83.0% / 78.3% / 0.703 | 80.8% / 80.8% / 0.720 | clean 100.0%, no answer 0.0% | 59.7% / 58.8% / 0.542 |
| `hybrid:bge-small-en-v1.5` | `h2` | 80.8% / 75.6% / 0.691 | 66.0% / 64.1% / 0.634 | 83.0% / 78.3% / 0.760 | 80.8% / 80.8% / 0.744 | clean 100.0%, no answer 0.0% | 57.9% / 55.3% / 0.535 |
| `bm25` | `merge-400` | 76.9% [65.4, 88.5] / 73.4% / 0.677 [0.573, 0.774] | 60.4% [47.2, 73.6] / 48.4% / 0.496 [0.416, 0.578] | 77.4% [66.0, 88.7] / 71.7% / 0.695 [0.595, 0.792] | 69.2% [55.8, 80.8] / 68.3% / 0.614 [0.503, 0.723] | clean 100.0%, no answer 0.0% | 86.0% [77.2, 94.7] / 83.3% / 0.737 [0.651, 0.820] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 80.8% / 78.2% / 0.707 | 69.8% / 59.8% / 0.588 | 81.1% / 76.4% / 0.720 | 76.9% / 77.9% / 0.670 | clean 100.0%, no answer 0.0% | 82.5% / 79.8% / 0.746 |

## By project (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `bm25` | `default` | 79.2% [67.9, 88.7] / 70.8% / 0.692 [0.596, 0.781] | 81.8% [70.9, 90.9] / 74.1% / 0.674 [0.593, 0.754] | 85.2% [74.1, 94.4] / 81.5% / 0.761 [0.678, 0.839] | 75.0% [63.5, 86.5] / 67.6% / 0.620 [0.522, 0.714] | 86.8% [77.4, 94.3] / 82.7% / 0.775 [0.702, 0.844] |
| `hybrid:bge-small-en-v1.5` | `default` | 84.9% / 79.2% / 0.763 | 83.6% / 81.2% / 0.713 | 85.2% / 80.9% / 0.763 | 78.8% / 75.3% / 0.655 | 88.7% / 85.9% / 0.813 |
| `bm25` | `h6` | 77.4% [66.0, 88.7] / 70.8% / 0.660 [0.558, 0.754] | 81.8% [70.9, 90.9] / 73.2% / 0.668 [0.587, 0.749] | 85.2% [74.1, 94.4] / 80.6% / 0.734 [0.646, 0.818] | 75.0% [63.5, 86.5] / 68.6% / 0.601 [0.502, 0.700] | 79.2% [67.9, 88.7] / 77.0% / 0.753 [0.673, 0.828] |
| `bm25+ce` | `h6` | 81.1% / 76.1% / 0.702 | 83.6% / 79.5% / 0.720 | 90.7% / 84.0% / 0.802 | 78.8% / 75.3% / 0.658 | 88.7% / 85.2% / 0.777 |
| `hybrid:bge-small-en-v1.5` | `h6` | 84.9% / 77.4% / 0.736 | 83.6% / 81.2% / 0.713 | 87.0% / 82.7% / 0.779 | 78.8% / 75.3% / 0.646 | 88.7% / 85.9% / 0.813 |
| `hybrid:bge-small-en-v1.5+ce` | `h6` | 81.1% / 77.4% / 0.705 | 80.0% / 75.9% / 0.719 | 92.6% / 84.0% / 0.802 | 76.9% / 73.4% / 0.651 | 86.8% / 84.3% / 0.769 |
| `hybrid:snowflake-arctic-embed-s` | `h6` | 69.8% / 64.8% / 0.580 | 83.6% / 78.2% / 0.664 | 70.4% / 65.7% / 0.586 | 76.9% / 70.5% / 0.570 | 75.5% / 72.6% / 0.653 |
| `bm25` | `h2` | 77.4% [66.0, 88.7] / 70.4% / 0.639 [0.538, 0.737] | 72.7% [60.0, 83.6] / 65.5% / 0.619 [0.522, 0.712] | 85.2% [75.9, 94.4] / 81.2% / 0.792 [0.714, 0.864] | 61.5% [48.1, 75.0] / 58.0% / 0.549 [0.447, 0.650] | 83.0% [71.7, 92.5] / 77.0% / 0.722 [0.632, 0.806] |
| `bm25+ce` | `h2` | 75.5% / 68.9% / 0.634 | 72.7% / 71.8% / 0.651 | 81.5% / 78.4% / 0.720 | 55.8% / 56.1% / 0.515 | 77.4% / 72.0% / 0.700 |
| `hybrid:bge-small-en-v1.5` | `h2` | 71.7% / 65.7% / 0.629 | 72.7% / 68.5% / 0.663 | 79.6% / 78.1% / 0.752 | 63.5% / 63.8% / 0.573 | 79.2% / 76.4% / 0.730 |
| `bm25` | `merge-400` | 71.7% [58.5, 83.0] / 66.0% / 0.618 [0.511, 0.720] | 80.0% [69.1, 89.1] / 73.6% / 0.645 [0.558, 0.729] | 74.1% [63.0, 85.2] / 72.8% / 0.672 [0.570, 0.772] | 71.2% [57.7, 82.7] / 65.7% / 0.613 [0.510, 0.712] | 73.6% [62.3, 84.9] / 67.6% / 0.676 [0.581, 0.769] |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 77.4% / 71.1% / 0.680 | 81.8% / 79.4% / 0.689 | 77.8% / 75.6% / 0.698 | 75.0% / 71.5% / 0.632 | 79.2% / 74.5% / 0.734 |

## Not run

- `bm25+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:bge-small-en-v1.5+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:snowflake-arctic-embed-s+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:bge-base-en-v1.5+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:hosted`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:hosted+ce`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:hosted+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hyde:hosted`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `agentic:hosted`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))

## Models

- embedding: `local:BAAI/bge-small-en-v1.5` @ `aa8f8b060edb`
- reranker: `local:Xenova/ms-marco-MiniLM-L-6-v2` @ `a09144355ade`
- embedding: `local:snowflake/snowflake-arctic-embed-s` @ `e596f5074675`
<!-- /bench -->
