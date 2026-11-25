# Retrieval grid

The golden set's 321 cases (`sha256:a00997851150e3b0`) on starlette, pydantic, tanstack-query, zod, electron, every pinned version, per configuration and chunking. ExactDocs `8eaf089bcdba766ab65d9339b5c9f3716247d9c9`, Linux x86_64. Recall, MRR and nDCG over answerable cases; unanswerable cases scored on returning nothing of another version (clean) and on coming back empty (no answer). Definitions: docs/evals/retrieval-benchmark.md.

## Defaults tested against

| budget | configuration | chunking | USD / 1000 questions | why |
|---|---|---|---|---|
| none | `bm25` | `default` | $0.0000 | declared in the grid (`bm25@default`): what ExactDocs ships for this budget |
| local | `bm25` | `default` | $0.0000 | declared in the grid (`bm25@default`): what ExactDocs ships for this budget |
| hosted | no default declared | - | - | - |

## Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 70.4% [64.8, 76.0] | 91.0% [87.3, 94.4] | 93.3% [90.3, 96.2] | 0.792 [0.751, 0.833] | 0.754 [0.717, 0.790] | 0 | 100.0% / 0.0% | 0.0% | 99.7 | 133.5 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 76.0% [70.8, 81.3] | 92.5% [89.1, 95.5] | 93.3% [90.3, 96.2] | 0.832 [0.793, 0.869] | 0.787 [0.750, 0.821] | 0 | 100.0% / 0.0% | 0.0% | 162.8 | 214.0 | 22 | 0.0000 | 3425 |
| `bm25@default+by-chunk` | `default` | none | ran | 58.4% [52.4, 64.4] | 87.3% [83.2, 91.0] | 93.3% [90.3, 96.2] | 0.707 [0.661, 0.750] | 0.711 [0.672, 0.748] | 0 | 100.0% / 0.0% | 0.0% | 88.8 | 128.7 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | local | ran | 64.0% [58.4, 69.7] | 89.5% [85.8, 92.9] | 93.3% [90.3, 96.2] | 0.752 [0.710, 0.794] | 0.746 [0.709, 0.782] | 0 | 100.0% / 0.0% | 0.0% | 158.5 | 221.9 | 22 | 0.0000 | 3487 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489).

## Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `hybrid:bge-small-en-v1.5` | `default` | local | `bm25` at `default` | **+5.6** [+0.8, +10.1], p 0.02 | +1.5 [-1.5, +4.5], p 0.36 | +0.0 [-3.0, +3.0], p 1 | **+0.040** [+0.006, +0.072], p 0.019 | **+0.033** [+0.003, +0.063], p 0.029 |
| `bm25@default+by-chunk` | `default` | none | `bm25` at `default` | **-12.0** [-16.1, -8.2], p < 0.001 | **-3.8** [-6.0, -1.5], p < 0.001 | +0.0 [+0.0, +0.0], p 1 | **-0.085** [-0.110, -0.061], p < 0.001 | **-0.043** [-0.062, -0.026], p < 0.001 |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | local | `bm25` at `default` | **-6.4** [-12.0, -1.1], p 0.025 | -1.5 [-4.5, +1.5], p 0.36 | +0.0 [-3.0, +3.0], p 1 | **-0.040** [-0.076, -0.005], p 0.029 | -0.008 [-0.041, +0.024], p 0.62 |

## Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text returned, the results read whole and in order: a case counts when the result that first answers it ends within the budget (#575). Context: the estimated tokens of all the text returned per question (each chunk's content); to the first hit: up to and including the first result that answers. In brackets: the 95% interval. Against: the budget's default, the difference in points and the p-value of McNemar's test (mid-p), **bold** when significant.

| configuration | chunking | context tokens / q | tokens to first hit | within 1,000 | within 2,000 | within 4,000 | against | 1,000 | 2,000 | 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 3,464 [3,320, 3,614] | 1,448 [1,307, 1,593] | 42.7% [36.7, 48.7] | 71.2% [65.5, 76.4] | 89.1% [85.4, 92.9] | - | - | - | - |
| `hybrid:bge-small-en-v1.5` | `default` | 3,206 [3,072, 3,340] | 1,413 [1,285, 1,546] | 42.3% [36.3, 48.3] | 73.4% [68.2, 78.6] | 90.3% [86.5, 93.6] | `bm25` at `default` | -0.4 [-6.0, +5.2], p 0.9 | +2.2 [-2.2, +7.1], p 0.36 | +1.1 [-2.6, +4.5], p 0.54 |
| `bm25@default+by-chunk` | `default` | 3,464 [3,320, 3,614] | 658 [573, 750] | 77.9% [73.0, 82.8] | 88.4% [84.6, 92.1] | 93.3% [90.3, 96.2] | `bm25` at `default` | **+35.2** [+29.2, +41.2], p < 0.001 | **+17.2** [+12.4, +22.1], p < 0.001 | **+4.1** [+1.9, +6.7], p < 0.001 |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | 3,206 [3,072, 3,340] | 579 [502, 660] | 80.5% [75.7, 85.4] | 88.8% [85.0, 92.5] | 93.3% [90.3, 96.2] | `bm25` at `default` | **+37.8** [+31.5, +44.2], p < 0.001 | **+17.6** [+12.4, +22.9], p < 0.001 | **+4.1** [+0.4, +7.9], p 0.029 |

## By question kind (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 88.7% [79.2, 96.2] / 80.8% / 0.739 [0.648, 0.821] | 91.7% [83.3, 97.9] / 62.5% / 0.621 [0.544, 0.697] | 87.9% [79.3, 96.5] / 78.2% / 0.747 [0.661, 0.829] | 90.4% [82.7, 98.1] / 89.4% / 0.813 [0.726, 0.895] | clean 100.0%, no answer 0.0% | 96.4% [91.1, 100.0] / 90.2% / 0.833 [0.762, 0.898] |
| `hybrid:bge-small-en-v1.5` | `default` | 90.6% [83.0, 98.1] / 81.8% / 0.741 [0.650, 0.828] | 95.8% [89.6, 100.0] / 70.5% / 0.709 [0.635, 0.779] | 89.7% [81.0, 96.5] / 82.2% / 0.781 [0.698, 0.859] | 92.3% [84.6, 98.1] / 91.3% / 0.859 [0.781, 0.927] | clean 100.0%, no answer 0.0% | 94.6% [87.5, 100.0] / 88.4% / 0.835 [0.759, 0.903] |
| `bm25@default+by-chunk` | `default` | 86.8% [77.4, 94.3] / 80.5% / 0.712 [0.622, 0.796] | 87.5% [77.1, 95.8] / 54.3% / 0.588 [0.511, 0.663] | 84.5% [75.9, 93.1] / 75.6% / 0.729 [0.643, 0.813] | 84.6% [75.0, 94.2] / 82.7% / 0.738 [0.648, 0.824] | clean 100.0%, no answer 0.0% | 92.9% [85.7, 98.2] / 85.7% / 0.770 [0.693, 0.843] |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | 88.7% [79.2, 96.2] / 84.0% / 0.725 [0.637, 0.810] | 93.8% [85.4, 100.0] / 64.2% / 0.657 [0.582, 0.729] | 86.2% [77.6, 94.8] / 80.5% / 0.742 [0.656, 0.824] | 88.5% [78.8, 96.2] / 87.5% / 0.806 [0.726, 0.881] | clean 100.0%, no answer 0.0% | 91.1% [82.1, 98.2] / 84.8% / 0.788 [0.707, 0.864] |

## By project (recall@5 / section recall@5 / nDCG@10)

A kind or a project holds only part of the cases (about 50 per kind in the golden set), so its intervals, in brackets, are much wider than the whole set's.

| configuration | chunking | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `bm25` | `default` | 88.7% [79.2, 96.2] / 76.1% / 0.725 [0.628, 0.811] | 89.1% [80.0, 96.4] / 76.1% / 0.703 [0.616, 0.786] | 96.3% [90.7, 100.0] / 87.4% / 0.826 [0.753, 0.892] | 82.7% [71.2, 92.3] / 75.3% / 0.704 [0.613, 0.789] | 98.1% [94.3, 100.0] / 88.0% / 0.810 [0.742, 0.874] |
| `hybrid:bge-small-en-v1.5` | `default` | 90.6% [83.0, 98.1] / 79.2% / 0.792 [0.698, 0.875] | 90.9% [81.8, 98.2] / 81.5% / 0.741 [0.662, 0.814] | 94.4% [87.0, 100.0] / 84.6% / 0.807 [0.727, 0.877] | 88.5% [78.8, 96.2] / 83.0% / 0.769 [0.679, 0.852] | 98.1% [94.3, 100.0] / 87.1% / 0.825 [0.759, 0.886] |
| `bm25@default+by-chunk` | `default` | 83.0% [71.7, 92.5] / 70.8% / 0.692 [0.596, 0.781] | 87.3% [78.2, 94.5] / 74.1% / 0.659 [0.574, 0.739] | 90.7% [81.5, 98.2] / 81.5% / 0.765 [0.682, 0.841] | 80.8% [69.2, 90.4] / 71.5% / 0.661 [0.572, 0.746] | 94.3% [86.8, 100.0] / 83.3% / 0.776 [0.703, 0.846] |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | 90.6% [83.0, 98.1] / 79.2% / 0.763 [0.669, 0.848] | 87.3% [78.2, 94.5] / 77.6% / 0.694 [0.616, 0.767] | 90.7% [81.5, 98.2] / 80.9% / 0.763 [0.680, 0.840] | 86.5% [76.9, 94.2] / 79.2% / 0.693 [0.608, 0.776] | 92.5% [84.9, 98.1] / 85.9% / 0.814 [0.739, 0.882] |

## Models

- embedding: `local:BAAI/bge-small-en-v1.5` @ `aa8f8b060edb`

## Text and context

The cells scored from their text (#491): what they return, in estimated tokens.

| cell | results/q | context tokens/q | tokens to first hit | facts found |
|---|---|---|---|---|

## Eval-only chunkers

The ingestion benchmark's metrics (#346) of each chunker the grid cuts with itself.

Sections held: of the sections the golden set expects, those that start a chunk or are a heading inside one. (Coverage and lost characters say little of windows: a window starts mid-section, and overlapping windows are not found in order.)

| chunker | chunks | tokens p50 / p95 | cuts in code / table / list | sections held |
|---|---|---|---|---|

## Against each variant's control

Each variant against the cell it varies (`against` in the grid file), on the answerable cases both answered: the difference (recall in points, MRR and nDCG@10 as scores), its paired bootstrap interval and the p-value (McNemar's test, mid-p, for recall; a sign-flip permutation test for MRR and nDCG@10). **Bold**: significant at 5%.

| cell | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | within 1,000 | within 2,000 | within 4,000 | cut at 1,000 | cut at 2,000 | cut at 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25@default` | `bm25@default+by-chunk` | **+12.0** [+8.2, +16.1], p < 0.001 | **+3.8** [+1.5, +6.0], p < 0.001 | +0.0 [+0.0, +0.0], p 1 | **+0.085** [+0.061, +0.110], p < 0.001 | **+0.043** [+0.026, +0.062], p < 0.001 | **-35.2** [-41.2, -29.2], p < 0.001 | **-17.2** [-22.1, -12.4], p < 0.001 | **-4.1** [-6.7, -1.9], p < 0.001 | - | - | - |
| `hybrid:bge-small-en-v1.5@default` | `hybrid:bge-small-en-v1.5@default+by-chunk` | **+12.0** [+8.2, +16.1], p < 0.001 | **+3.0** [+1.1, +5.2], p 0.0039 | +0.0 [+0.0, +0.0], p 1 | **+0.080** [+0.056, +0.106], p < 0.001 | **+0.041** [+0.022, +0.061], p < 0.001 | **-38.2** [-44.2, -32.6], p < 0.001 | **-15.4** [-19.9, -10.9], p < 0.001 | **-3.0** [-5.2, -1.1], p 0.0039 | - | - | - |

Taken from an earlier run: `bm25@default`, `hybrid:bge-small-en-v1.5@default`.
