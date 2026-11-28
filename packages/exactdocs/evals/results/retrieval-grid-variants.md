# Retrieval grid

The golden set's 321 cases (`sha256:100484c7ccdb1b89`) on starlette, pydantic, tanstack-query, zod, electron, every pinned version, per configuration and chunking. ExactDocs `47c9669d8673a4a71597985dfb1bdfe4f80a2ffc`, Linux aarch64. Recall, MRR and nDCG over answerable cases; unanswerable cases scored on returning nothing of another version (clean) and on coming back empty (no answer). Definitions: docs/evals/retrieval-benchmark.md.

## Defaults tested against

| budget | configuration | chunking | USD / 1000 questions | why |
|---|---|---|---|---|
| none | `bm25` | `default` | $0.0000 | declared in the grid (`bm25@default`): what ExactDocs ships for this budget |
| local | `bm25` | `default` | $0.0000 | declared in the grid (`bm25@default`): what ExactDocs ships for this budget |
| hosted | no default declared | - | - | - |

## Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 70.8% [65.2, 76.4] | 91.4% [88.0, 94.4] | 93.6% [90.6, 96.2] | 0.796 [0.755, 0.836] | 0.757 [0.721, 0.793] | 0 | 100.0% / 0.0% | 0.0% | 99.8 | 118.7 | 0 | 0.0000 | - |
| `grep` | `raw` | none | ran | 31.8% [26.2, 37.5] | 55.8% [49.8, 61.8] | 66.7% [61.1, 72.3] | 0.418 [0.368, 0.469] | 0.422 [0.378, 0.469] | 0.0312 | 98.2% / 0.0% | 0.0% | 38.2 | 147.3 | 0 | 0.0000 | - |
| `default/hybrid:bge-small` | `default` | local | ran | 65.5% [59.9, 71.2] | 90.6% [86.9, 94.0] | 94.0% [91.0, 96.6] | 0.763 [0.722, 0.804] | 0.754 [0.718, 0.791] | 0 | 100.0% / 0.0% | 0.0% | 66.1 | 85.0 | 22 | 0.0000 | 6002 |
| `window-256+64/bm25` | `window-256+64` | none | ran | 39.3% [33.7, 45.3] | 71.2% [65.9, 76.4] | 79.0% [74.2, 83.9] | 0.527 [0.479, 0.576] | 0.536 [0.492, 0.580] | 0.0093 | 100.0% / 0.0% | 0.0% | 21.2 | 26.8 | 0 | 0.0000 | 8 |
| `window-512+128/bm25` | `window-512+128` | none | ran | 48.3% [42.3, 54.3] | 77.5% [72.3, 82.4] | 84.6% [80.2, 88.8] | 0.605 [0.556, 0.654] | 0.609 [0.565, 0.652] | 0.0218 | 98.2% / 0.0% | 0.0% | 17.7 | 21.9 | 0 | 0.0000 | 8 |
| `h6/hybrid:bge-small+parent` | `h6` | local | ran | 68.2% [62.5, 73.8] | 93.6% [90.6, 96.2] | 96.2% [94.0, 98.5] | 0.790 [0.752, 0.829] | 0.779 [0.747, 0.812] | 0 | 100.0% / 0.0% | 0.0% | 68.7 | 94.6 | 22 | 0.0000 | 6724 |
| `h6/hybrid:bge-small+article` | `h6` | local | ran | 76.0% [70.8, 80.9] | 95.1% [92.5, 97.4] | 95.9% [93.3, 98.1] | 0.844 [0.809, 0.879] | 0.804 [0.771, 0.835] | 0 | 100.0% / 0.0% | 0.0% | 68.4 | 94.0 | 22 | 0.0000 | 6724 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489).

## Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `grep` | `raw` | none | `bm25` at `default` | **-39.0** [-46.1, -31.8], p < 0.001 | **-35.6** [-41.6, -29.2], p < 0.001 | **-27.0** [-32.6, -21.3], p < 0.001 | **-0.378** [-0.435, -0.320], p < 0.001 | **-0.335** [-0.384, -0.286], p < 0.001 |
| `default/hybrid:bge-small` | `default` | local | `bm25` at `default` | -5.2 [-11.2, +0.8], p 0.086 | -0.8 [-3.8, +2.2], p 0.63 | +0.4 [-2.6, +3.4], p 0.8 | -0.032 [-0.070, +0.005], p 0.093 | -0.003 [-0.035, +0.028], p 0.85 |
| `window-256+64/bm25` | `window-256+64` | none | `bm25` at `default` | **-31.5** [-37.5, -25.5], p < 0.001 | **-20.2** [-25.8, -15.0], p < 0.001 | **-14.6** [-19.5, -10.1], p < 0.001 | **-0.269** [-0.315, -0.225], p < 0.001 | **-0.222** [-0.261, -0.182], p < 0.001 |
| `window-512+128/bm25` | `window-512+128` | none | `bm25` at `default` | **-22.5** [-28.8, -16.5], p < 0.001 | **-13.9** [-19.1, -8.6], p < 0.001 | **-9.0** [-13.5, -4.5], p < 0.001 | **-0.191** [-0.237, -0.146], p < 0.001 | **-0.149** [-0.190, -0.109], p < 0.001 |
| `h6/hybrid:bge-small+parent` | `h6` | local | `bm25` at `default` | -2.6 [-8.2, +3.0], p 0.36 | +2.2 [-0.4, +4.9], p 0.12 | +2.6 [-0.4, +5.6], p 0.096 | -0.006 [-0.041, +0.029], p 0.75 | +0.022 [-0.008, +0.052], p 0.15 |
| `h6/hybrid:bge-small+article` | `h6` | local | `bm25` at `default` | **+5.2** [+0.0, +10.1], p 0.044 | **+3.8** [+1.1, +6.7], p 0.013 | +2.2 [-0.8, +5.2], p 0.14 | **+0.049** [+0.015, +0.081], p 0.004 | **+0.046** [+0.017, +0.075], p 0.0021 |

## Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text returned, the results read whole and in order: a case counts when the result that first answers it ends within the budget (#575). Cut: scored from the text only, the text cut at the budget, so the result the budget cuts counts when its part within the budget answers. Context: the estimated tokens of all the text returned per question (each chunk's content); to the first hit: up to and including the first result that answers. In brackets: the 95% interval. Against: the budget's default, the difference in points and the p-value of McNemar's test (mid-p), **bold** when significant.

| configuration | chunking | context tokens / q | tokens to first hit | within 1,000 | within 2,000 | within 4,000 | cut at 1,000 | cut at 2,000 | cut at 4,000 | against | 1,000 | 2,000 | 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 3,464 [3,320, 3,614] | 1,444 [1,306, 1,588] | 43.1% [37.1, 49.1] | 71.5% [66.3, 76.8] | 89.5% [85.8, 92.9] | - | - | - | - | - | - | - |
| `grep` | `raw` | 7,301 [6,840, 7,785] | 2,296 [1,887, 2,742] | 30.0% [24.7, 35.6] | 44.2% [38.6, 50.2] | 55.4% [49.4, 61.4] | 37.5% [31.8, 43.5] | 47.2% [41.6, 53.6] | 56.9% [50.9, 62.9] | `bm25` at `default` | **-13.1** [-20.6, -5.6], p < 0.001 | **-27.3** [-34.5, -19.9], p < 0.001 | **-34.1** [-40.1, -28.1], p < 0.001 |
| `default/hybrid:bge-small` | `default` | 3,127 [2,990, 3,265] | 568 [489, 653] | 82.0% [77.1, 86.5] | 89.5% [85.8, 92.9] | 93.3% [90.3, 96.2] | 89.1% [85.4, 92.9] | 91.8% [88.4, 94.8] | 93.6% [90.6, 96.2] | `bm25` at `default` | **+39.0** [+32.6, +45.3], p < 0.001 | **+18.0** [+12.7, +23.2], p < 0.001 | **+3.8** [+0.4, +7.1], p 0.035 |
| `window-256+64/bm25` | `window-256+64` | 2,645 [2,631, 2,658] | 643 [567, 721] | 63.7% [58.1, 69.3] | 74.9% [69.7, 80.2] | 79.0% [74.2, 83.9] | 68.5% [62.9, 73.8] | 76.0% [70.8, 80.9] | 79.0% [74.2, 83.9] | `bm25` at `default` | **+20.6** [+13.1, +27.7], p < 0.001 | +3.4 [-3.4, +9.7], p 0.31 | **-10.5** [-15.4, -5.6], p < 0.001 |
| `window-512+128/bm25` | `window-512+128` | 5,029 [4,998, 5,058] | 1,110 [987, 1,242] | 51.7% [45.7, 57.7] | 72.7% [67.4, 77.9] | 81.7% [76.8, 86.1] | 62.9% [56.9, 68.5] | 74.9% [69.7, 80.2] | 82.4% [77.9, 86.9] | `bm25` at `default` | **+8.6** [+1.5, +15.4], p 0.015 | +1.1 [-4.5, +7.1], p 0.71 | **-7.9** [-12.7, -3.4], p 0.0013 |
| `h6/hybrid:bge-small+parent` | `h6` | 11,958 [10,988, 13,020] | 2,062 [1,751, 2,389] | 52.4% [46.4, 58.4] | 67.8% [62.2, 73.4] | 78.3% [73.4, 83.2] | 64.8% [59.2, 70.4] | 77.1% [72.3, 82.0] | 86.9% [82.8, 90.6] | `bm25` at `default` | **+9.4** [+1.9, +16.9], p 0.016 | -3.8 [-9.7, +2.6], p 0.24 | **-11.2** [-16.5, -6.4], p < 0.001 |
| `h6/hybrid:bge-small+article` | `h6` | 5,297 [5,057, 5,535] | 2,137 [1,949, 2,327] | 24.7% [19.5, 30.0] | 55.8% [49.8, 61.8] | 81.7% [76.8, 86.1] | 53.6% [47.6, 59.6] | 77.5% [72.3, 82.4] | 92.1% [88.8, 95.1] | `bm25` at `default` | **-18.4** [-24.0, -12.7], p < 0.001 | **-15.7** [-21.3, -10.1], p < 0.001 | **-7.9** [-12.7, -3.0], p 0.0016 |

## By question kind (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 88.7% [79.2, 96.2] / 80.8% / 0.739 [0.648, 0.821] | 91.7% [83.3, 97.9] / 62.5% / 0.621 [0.544, 0.697] | 87.9% [79.3, 96.5] / 78.2% / 0.747 [0.661, 0.829] | 92.3% [84.6, 98.1] / 91.3% / 0.832 [0.750, 0.909] | clean 100.0%, no answer 0.0% | 96.4% [91.1, 100.0] / 90.2% / 0.833 [0.762, 0.898] |
| `grep` | `raw` | 49.1% [35.9, 62.3] / 43.1% / 0.404 [0.303, 0.509] | 60.4% [45.8, 75.0] / 34.4% / 0.358 [0.271, 0.447] | 50.0% [37.9, 63.8] / 44.8% / 0.436 [0.332, 0.546] | 51.9% [38.5, 65.4] / 51.0% / 0.413 [0.308, 0.524] | clean 98.2%, no answer 0.0% | 67.9% [55.4, 80.4] / 58.9% / 0.489 [0.390, 0.586] |
| `default/hybrid:bge-small` | `default` | 88.7% [79.2, 96.2] / 84.3% / 0.737 [0.652, 0.818] | 93.8% [85.4, 100.0] / 66.1% / 0.653 [0.577, 0.725] | 87.9% [79.3, 94.8] / 82.2% / 0.758 [0.671, 0.840] | 90.4% [82.7, 98.1] / 89.4% / 0.791 [0.711, 0.867] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 86.6% / 0.820 [0.744, 0.889] |
| `window-256+64/bm25` | `window-256+64` | 64.1% [50.9, 77.4] / 60.4% / 0.566 [0.454, 0.675] | 70.8% [58.3, 83.3] / 40.8% / 0.393 [0.316, 0.472] | 75.9% [63.8, 86.2] / 66.1% / 0.577 [0.476, 0.675] | 73.1% [61.5, 84.6] / 73.1% / 0.590 [0.489, 0.691] | clean 100.0%, no answer 0.0% | 71.4% [58.9, 82.1] / 61.6% / 0.538 [0.439, 0.633] |
| `window-512+128/bm25` | `window-512+128` | 73.6% [62.3, 84.9] / 69.2% / 0.691 [0.593, 0.783] | 85.4% [75.0, 93.8] / 53.1% / 0.537 [0.463, 0.610] | 72.4% [60.3, 82.8] / 60.9% / 0.550 [0.447, 0.652] | 76.9% [65.4, 88.5] / 76.0% / 0.643 [0.539, 0.744] | clean 98.2%, no answer 0.0% | 80.4% [69.6, 91.1] / 71.4% / 0.621 [0.528, 0.715] |
| `h6/hybrid:bge-small+parent` | `h6` | 92.5% [84.9, 98.1] / 86.2% / 0.729 [0.648, 0.806] | 97.9% [93.8, 100.0] / 72.2% / 0.707 [0.640, 0.772] | 89.7% [81.0, 96.5] / 83.9% / 0.785 [0.708, 0.857] | 92.3% [84.6, 98.1] / 91.3% / 0.811 [0.736, 0.882] | clean 100.0%, no answer 0.0% | 96.4% [91.1, 100.0] / 91.1% / 0.854 [0.787, 0.914] |
| `h6/hybrid:bge-small+article` | `h6` | 96.2% [90.6, 100.0] / 87.4% / 0.777 [0.702, 0.847] | 97.9% [93.8, 100.0] / 75.3% / 0.717 [0.649, 0.783] | 91.4% [84.5, 98.3] / 83.9% / 0.784 [0.705, 0.858] | 92.3% [84.6, 98.1] / 90.4% / 0.836 [0.760, 0.907] | clean 100.0%, no answer 0.0% | 98.2% [94.6, 100.0] / 91.1% / 0.893 [0.835, 0.942] |

## By project (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `bm25` | `default` | 88.7% [79.2, 96.2] / 76.1% / 0.725 [0.628, 0.811] | 90.9% [81.8, 98.2] / 77.9% / 0.721 [0.637, 0.800] | 96.3% [90.7, 100.0] / 87.4% / 0.826 [0.753, 0.892] | 82.7% [71.2, 92.3] / 75.3% / 0.704 [0.613, 0.789] | 98.1% [94.3, 100.0] / 88.0% / 0.810 [0.742, 0.874] |
| `grep` | `raw` | 71.7% [58.5, 83.0] / 60.1% / 0.536 [0.432, 0.638] | 52.7% [40.0, 65.5] / 42.1% / 0.357 [0.265, 0.451] | 57.4% [44.4, 70.4] / 46.9% / 0.459 [0.356, 0.564] | 40.4% [26.9, 53.8] / 35.3% / 0.341 [0.241, 0.448] | 56.6% [43.4, 69.8] / 49.4% / 0.418 [0.316, 0.520] |
| `default/hybrid:bge-small` | `default` | 90.6% [83.0, 98.1] / 80.5% / 0.758 [0.664, 0.843] | 90.9% [81.8, 98.2] / 79.8% / 0.717 [0.641, 0.789] | 90.7% [81.5, 98.2] / 80.9% / 0.773 [0.692, 0.847] | 86.5% [76.9, 94.2] / 81.1% / 0.694 [0.606, 0.778] | 94.3% [86.8, 100.0] / 88.0% / 0.830 [0.755, 0.898] |
| `window-256+64/bm25` | `window-256+64` | 66.0% [52.8, 79.2] / 58.5% / 0.500 [0.394, 0.603] | 72.7% [60.0, 83.6] / 57.7% / 0.457 [0.369, 0.545] | 75.9% [64.8, 87.0] / 63.9% / 0.619 [0.514, 0.719] | 71.2% [59.6, 82.7] / 64.7% / 0.540 [0.443, 0.635] | 69.8% [56.6, 81.1] / 59.4% / 0.566 [0.462, 0.668] |
| `window-512+128/bm25` | `window-512+128` | 77.4% [66.0, 88.7] / 68.5% / 0.593 [0.497, 0.688] | 78.2% [67.3, 89.1] / 63.3% / 0.571 [0.477, 0.663] | 79.6% [68.5, 88.9] / 66.0% / 0.639 [0.541, 0.733] | 80.8% [69.2, 90.4] / 70.5% / 0.663 [0.565, 0.758] | 71.7% [58.5, 83.0] / 63.2% / 0.580 [0.480, 0.676] |
| `h6/hybrid:bge-small+parent` | `h6` | 96.2% [90.6, 100.0] / 86.2% / 0.816 [0.736, 0.888] | 92.7% [85.5, 98.2] / 83.0% / 0.753 [0.679, 0.823] | 96.3% [90.7, 100.0] / 85.8% / 0.772 [0.701, 0.838] | 86.5% [76.9, 94.2] / 82.0% / 0.709 [0.625, 0.790] | 96.2% [90.6, 100.0] / 89.0% / 0.846 [0.784, 0.903] |
| `h6/hybrid:bge-small+article` | `h6` | 94.3% [86.8, 100.0] / 80.2% / 0.790 [0.705, 0.867] | 94.5% [87.3, 100.0] / 85.2% / 0.783 [0.709, 0.852] | 98.2% [94.4, 100.0] / 89.8% / 0.835 [0.770, 0.892] | 90.4% [80.8, 98.1] / 84.9% / 0.774 [0.692, 0.849] | 98.1% [94.3, 100.0] / 89.0% / 0.836 [0.773, 0.894] |

## Models

- embedding: `BAAI/bge-small-en-v1.5`

## Text and context

The cells scored from their text (#491): what they return, in estimated tokens.

| cell | results/q | context tokens/q | tokens to first hit | facts found |
|---|---|---|---|---|
| `grep` | 10.0 | 7301 | 2296 | 85.8% |
| `default/hybrid:bge-small` | 10.0 | 3127 | 568 | 87.6% |
| `window-256+64/bm25` | 10.0 | 2645 | 643 | 82.2% |
| `window-512+128/bm25` | 10.0 | 5029 | 1110 | 91.7% |
| `h6/hybrid:bge-small+parent` | 10.0 | 11958 | 2062 | 94.2% |
| `h6/hybrid:bge-small+article` | 5.2 | 5297 | 2137 | 90.8% |

## Eval-only chunkers

The ingestion benchmark's metrics (#346) of each chunker the grid cuts with itself.

Sections held: of the sections the golden set expects, those that start a chunk or are a heading inside one. (Coverage and lost characters say little of windows: a window starts mid-section, and overlapping windows are not found in order.)

| chunker | chunks | tokens p50 / p95 | cuts in code / table / list | sections held |
|---|---|---|---|---|
| `default` | 11765 | 114 / 737 | 4 / 0 / 0 | 100.0% |
| `window-256+64` | 11454 | 263 / 294 | 3275 / 107 / 1035 | 100.0% |
| `window-512+128` | 6358 | 517 / 551 | 1467 / 38 / 472 | 100.0% |
| `h6` | 15482 | 88 / 516 | 4 / 0 / 0 | 100.0% |

## Against each variant's control

Each variant against the cell it varies (`against` in the grid file), on the answerable cases both answered: the difference (recall in points, MRR and nDCG@10 as scores), its paired bootstrap interval and the p-value (McNemar's test, mid-p, for recall; a sign-flip permutation test for MRR and nDCG@10). **Bold**: significant at 5%.

| cell | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | within 1,000 | within 2,000 | within 4,000 | cut at 1,000 | cut at 2,000 | cut at 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `h6/hybrid:bge-small+parent` | `default/hybrid:bge-small` | +2.6 [-1.5, +6.4], p 0.2 | **+3.0** [+1.1, +5.2], p 0.0039 | **+2.2** [+0.8, +4.1], p 0.016 | **+0.027** [+0.003, +0.051], p 0.034 | **+0.025** [+0.005, +0.045], p 0.015 | **-29.6** [-35.6, -23.6], p < 0.001 | **-21.7** [-27.0, -16.5], p < 0.001 | **-15.0** [-19.5, -10.5], p < 0.001 | **-24.3** [-30.0, -18.7], p < 0.001 | **-14.6** [-19.1, -10.1], p < 0.001 | **-6.7** [-10.1, -3.8], p < 0.001 |
| `h6/hybrid:bge-small+article` | `default/hybrid:bge-small` | **+10.5** [+5.2, +15.4], p < 0.001 | **+4.5** [+2.2, +7.1], p < 0.001 | **+1.9** [+0.4, +3.8], p 0.031 | **+0.081** [+0.048, +0.114], p < 0.001 | **+0.049** [+0.023, +0.076], p < 0.001 | **-57.3** [-63.3, -51.3], p < 0.001 | **-33.7** [-39.7, -27.7], p < 0.001 | **-11.6** [-16.5, -7.1], p < 0.001 | **-35.6** [-41.9, -29.6], p < 0.001 | **-14.2** [-19.1, -9.7], p < 0.001 | -1.5 [-4.5, +1.5], p 0.33 |

Taken from an earlier run: `bm25@default`, `default/hybrid:bge-small`, `h6/hybrid:bge-small+parent`, `h6/hybrid:bge-small+article`.
