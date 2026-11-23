# Retrieval benchmark

The golden set's 321 cases (`sha256:39f6f9d5e909d128`) on starlette, pydantic, tanstack-query, zod, electron, every pinned version, per configuration and chunking. ExactDocs `fe156aa8aed0ebd86bcb45e930be9769e4056535`, Darwin arm64. Recall, MRR and nDCG over answerable cases; unanswerable cases scored on returning nothing of another version (clean) and on coming back empty (no answer). Definitions: docs/evals.md#the-retrieval-benchmark.

## Recommended defaults

| budget | configuration | chunking | USD / 1000 questions | why |
|---|---|---|---|---|
| none | `bm25` | `default` | $0.0000 | best none configuration: `bm25` at `default`: recall@5 81.7%, nDCG@10 0.705, MRR 0.651, wrong-version rate 0, p95 57 ms, $0.0000 per 1000 questions |
| local | `bm25` | `default` | $0.0000 | best local configuration: `hybrid:bge-small-en-v1.5` at `h6`: recall@5 84.6%, nDCG@10 0.738, MRR 0.675, wrong-version rate 0, p95 127 ms, $0.0000 per 1000 questions; +3.0 points of recall@5 over `bm25`, under the 5-point margin: the cheaper `bm25` at `default` stays the default |
| hosted | not measured yet: needs a real-providers run | - | - | - |

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
