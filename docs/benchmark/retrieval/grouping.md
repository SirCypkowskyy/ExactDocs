# Grouped by article (#575)

!!! abstract "TL;DR"
    - ExactDocs' own search, run both ways on the same code and machine: grouped by article and one
      chunk per result.
    - Grouping lifts recall@1 by 12.0 points with BM25 and with hybrid search, and recall@5 by 3.8
      and 3.0; recall@10 does not move.
    - Against Grounded Docs the rank-1 gap closes (neither difference significant); at recall@5
      ExactDocs leads with both searches.
    - The answer sits further into the text: within 1,000 tokens 35.2 points fewer cases with BM25,
      still ahead of Grounded Docs at every budget.

`search_docs` groups its results by article since #575: the article of the best result comes
first with all of its results, best first, then the next article ([MCP](../../mcp/index.md)). It returns
the same chunks as before; only their order changes. The grid ran ExactDocs' own search both ways
on the same code and machine: the app cells `bm25@default` and `hybrid:bge-small-en-v1.5@default`,
which group, each against its `+by-chunk` control, which returns one chunk per result as the
search did before. The two grouped cells are the runs recorded on [Retrieval results](index.md#the-recorded-run), taken into the grid.

`packages/exactdocs/evals/results/retrieval-grid-grouped.json` was run on 25 November 2026 on 4
shared CPUs (Linux x86_64) with:

```bash
just retrieval-grid --offline \
  --cells 'bm25@default,bm25@default+by-chunk,hybrid:bge-small-en-v1.5@default,hybrid:bge-small-en-v1.5@default+by-chunk'
```

Next to Grounded Docs 3.4.1 with `bge-small-en-v1.5`, asked the same day
([Comparison](../comparison/index.md#before-and-after-grouping-by-article)):

| | BM25, one chunk per result | BM25, grouped | hybrid, one chunk per result | hybrid, grouped | Grounded Docs, bge-small |
|---|---|---|---|---|---|
| recall@1 | 58.4% | **70.4%** | 64.0% | **76.0%** | 71.2% |
| recall@5 | 87.3% | **91.0%** | 89.5% | **92.5%** | 85.4% |
| recall@10 | 93.3% | 93.3% | 93.3% | 93.3% | 88.8% |
| MRR | 0.707 | **0.792** | 0.752 | **0.832** | 0.781 |
| within 1,000 tokens | **77.9%** | 42.7% | **80.5%** | 42.3% | 34.1% |
| within 2,000 tokens | **88.4%** | 71.2% | **88.8%** | 73.4% | 58.4% |
| within 4,000 tokens | **93.3%** | 89.1% | **93.3%** | 90.3% | 75.3% |
| context tokens / question | 3,464 | 3,464 | 3,206 | 3,206 | 7,360 |

**Bold**: significantly better than the same search the other way. Within a budget: whole
results, read in order.

- **Rank 1 gains 12.0 points** with either search (32 cases gained, none lost, p < 0.001), and
  recall@5 3.8 and 3.0 points (p 0.001 and 0.004). recall@10 does not move, since the ten chunks
  are the same.
- **Against Grounded Docs the rank-1 gap closes.** It put a section that answers first 12.7
  points more often than BM25 one chunk per result (p 0.0005) and 7.1 more than hybrid search
  (p 0.0495). Grouped, BM25 is 0.8 points behind it (p 0.82) and hybrid search 4.9 points ahead
  (p 0.12), neither significant; at recall@5 both are significantly ahead (5.6 and 7.1 points,
  p 0.014 and 0.002).
- **The answer sits further into what is returned.** A case answered by a group's second or
  third chunk ends further into the text than it did as a result of its own: recall within 1,000
  tokens falls by 35.2 points with BM25 and 38.2 with hybrid search, within 2,000 by 17.2 and
  15.4, within 4,000 by 4.1 and 3.0 (all significant).
- It still finds the answer within each budget more often than Grounded Docs does, by 8.2 to 15.0
  points, all significant. The context is the same as before grouping, and the answering
  section comes first more often than Grounded Docs puts it first: what #575 set out to do.
- Since #571 one Pydantic case is a miss in all four cells (its heading lost its `{#id}`), so
  their numbers are 0.4 points under those of the [rank-1 run](rank-one.md).

<!-- bench:retrieval-grouping -->
- Golden set: 321 cases, fingerprint `sha256:a00997851150e3b0`; ExactDocs commit `8eaf089bcdba766ab65d9339b5c9f3716247d9c9`, Python 3.14.6, Linux x86_64, 4 CPUs.

#### Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 70.4% [64.8, 76.0] | 91.0% [87.3, 94.4] | 93.3% [90.3, 96.2] | 0.792 [0.751, 0.833] | 0.754 [0.717, 0.790] | 0 | 100.0% / 0.0% | 0.0% | 99.7 | 133.5 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 76.0% [70.8, 81.3] | 92.5% [89.1, 95.5] | 93.3% [90.3, 96.2] | 0.832 [0.793, 0.869] | 0.787 [0.750, 0.821] | 0 | 100.0% / 0.0% | 0.0% | 162.8 | 214.0 | 22 | 0.0000 | 3425 |
| `bm25@default+by-chunk` | `default` | none | ran | 58.4% [52.4, 64.4] | 87.3% [83.2, 91.0] | 93.3% [90.3, 96.2] | 0.707 [0.661, 0.750] | 0.711 [0.672, 0.748] | 0 | 100.0% / 0.0% | 0.0% | 88.8 | 128.7 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | local | ran | 64.0% [58.4, 69.7] | 89.5% [85.8, 92.9] | 93.3% [90.3, 96.2] | 0.752 [0.710, 0.794] | 0.746 [0.709, 0.782] | 0 | 100.0% / 0.0% | 0.0% | 158.5 | 221.9 | 22 | 0.0000 | 3487 |

In brackets: the 95% interval, a percentile bootstrap over the cases (10,000 resamples, seed 489).

#### Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `hybrid:bge-small-en-v1.5` | `default` | local | `bm25` at `default` | **+5.6** [+0.8, +10.1], p 0.02 | +1.5 [-1.5, +4.5], p 0.36 | +0.0 [-3.0, +3.0], p 1 | **+0.040** [+0.006, +0.072], p 0.019 | **+0.033** [+0.003, +0.063], p 0.029 |
| `bm25@default+by-chunk` | `default` | none | `bm25` at `default` | **-12.0** [-16.1, -8.2], p < 0.001 | **-3.8** [-6.0, -1.5], p < 0.001 | +0.0 [+0.0, +0.0], p 1 | **-0.085** [-0.110, -0.061], p < 0.001 | **-0.043** [-0.062, -0.026], p < 0.001 |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | local | `bm25` at `default` | **-6.4** [-12.0, -1.1], p 0.025 | -1.5 [-4.5, +1.5], p 0.36 | +0.0 [-3.0, +3.0], p 1 | **-0.040** [-0.076, -0.005], p 0.029 | -0.008 [-0.041, +0.024], p 0.62 |

#### Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text returned, the results read whole and in order: a case counts when the result that first answers it ends within the budget (#575). Context: the estimated tokens of all the text returned per question (each chunk's content); to the first hit: up to and including the first result that answers. In brackets: the 95% interval. Against: the budget's default, the difference in points and the p-value of McNemar's test (mid-p), **bold** when significant.

| configuration | chunking | context tokens / q | tokens to first hit | within 1,000 | within 2,000 | within 4,000 | against | 1,000 | 2,000 | 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 3,464 [3,320, 3,614] | 1,448 [1,307, 1,593] | 42.7% [36.7, 48.7] | 71.2% [65.5, 76.4] | 89.1% [85.4, 92.9] | - | - | - | - |
| `hybrid:bge-small-en-v1.5` | `default` | 3,206 [3,072, 3,340] | 1,413 [1,285, 1,546] | 42.3% [36.3, 48.3] | 73.4% [68.2, 78.6] | 90.3% [86.5, 93.6] | `bm25` at `default` | -0.4 [-6.0, +5.2], p 0.9 | +2.2 [-2.2, +7.1], p 0.36 | +1.1 [-2.6, +4.5], p 0.54 |
| `bm25@default+by-chunk` | `default` | 3,464 [3,320, 3,614] | 658 [573, 750] | 77.9% [73.0, 82.8] | 88.4% [84.6, 92.1] | 93.3% [90.3, 96.2] | `bm25` at `default` | **+35.2** [+29.2, +41.2], p < 0.001 | **+17.2** [+12.4, +22.1], p < 0.001 | **+4.1** [+1.9, +6.7], p < 0.001 |
| `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | 3,206 [3,072, 3,340] | 579 [502, 660] | 80.5% [75.7, 85.4] | 88.8% [85.0, 92.5] | 93.3% [90.3, 96.2] | `bm25` at `default` | **+37.8** [+31.5, +44.2], p < 0.001 | **+17.6** [+12.4, +22.9], p < 0.001 | **+4.1** [+0.4, +7.9], p 0.029 |

#### Against each variant's control

Each variant against the cell it varies (`against` in the grid file), on the answerable cases both answered: the difference (recall in points, MRR and nDCG@10 as scores), its paired bootstrap interval and the p-value (McNemar's test, mid-p, for recall; a sign-flip permutation test for MRR and nDCG@10). **Bold**: significant at 5%.

| cell | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | within 1,000 | within 2,000 | within 4,000 | cut at 1,000 | cut at 2,000 | cut at 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25@default` | `bm25@default+by-chunk` | **+12.0** [+8.2, +16.1], p < 0.001 | **+3.8** [+1.5, +6.0], p < 0.001 | +0.0 [+0.0, +0.0], p 1 | **+0.085** [+0.061, +0.110], p < 0.001 | **+0.043** [+0.026, +0.062], p < 0.001 | **-35.2** [-41.2, -29.2], p < 0.001 | **-17.2** [-22.1, -12.4], p < 0.001 | **-4.1** [-6.7, -1.9], p < 0.001 | - | - | - |
| `hybrid:bge-small-en-v1.5@default` | `hybrid:bge-small-en-v1.5@default+by-chunk` | **+12.0** [+8.2, +16.1], p < 0.001 | **+3.0** [+1.1, +5.2], p 0.0039 | +0.0 [+0.0, +0.0], p 1 | **+0.080** [+0.056, +0.106], p < 0.001 | **+0.041** [+0.022, +0.061], p < 0.001 | **-38.2** [-44.2, -32.6], p < 0.001 | **-15.4** [-19.9, -10.9], p < 0.001 | **-3.0** [-5.2, -1.1], p 0.0039 | - | - | - |

Taken from an earlier run: `bm25@default`, `hybrid:bge-small-en-v1.5@default`.
<!-- /bench -->
