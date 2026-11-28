# Windows and baselines (#494)

!!! abstract "TL;DR"
    - A keyword grep over the raw Markdown finds the answer in the top 5 in 55.8% of the cases;
      ExactDocs' BM25 does in 91.4%. Fixed windows with BM25 land in between: 71.2% at 256 tokens,
      77.5% at 512.
    - Heading chunks at `h6` with hybrid search on bge-small, grouped by article, beat the shipped
      default on recall@1 (+5.2 points, p 0.044) and recall@5 (+3.8, p 0.013). They return 5,297
      tokens per question against 3,464, and they lose within every token budget.
    - Not run yet: the fixed-window RAG baseline, the hybrid window cells, and both bge-base cells.

The [retrieval grid](../../evals/retrieval-grid.md) cells that the
[rank-1 run](rank-one.md) did not cover: the plain baselines, fixed token windows with overlap, and
small heading chunks with hybrid search widened to their parent section or grouped by article.
Every cell is tested against the shipped default (BM25 at `default`), and each variant against its
control.

| | |
|---|---|
| Report | `packages/exactdocs/evals/results/retrieval-grid-variants.json` |
| Recorded | 27 and 28 November 2026, for #494 |
| Golden set | `sha256:100484c7ccdb1b89`, the same as the [retrieval results](index.md) |
| Machine | self-hosted runner VMs (Linux aarch64, 2 vCPUs), with no provider |
| Commands | `just retrieval-grid --cells 'h6/hybrid:bge-small+parent,h6/hybrid:bge-small+article'` on one VM (3 h 35 min); then `--cells 'grep,window-256+64/bm25,window-512+128/bm25,h6/hybrid:bge-small+*'` on another, which took the first VM's cells and ran the rest in 2 min 25 s |

`default/hybrid:bge-small` is the grid's own hybrid search at `default`, the control of both `h6`
cells. Embedding the corpus for it with bge-small took 6,002 s (1 h 40 min) on 2 vCPUs, and
6,724 s for `h6`.

**What it shows:**

- **The baselines set a low floor.** Grep returns twice the text of BM25 (7,301 tokens per
  question against 3,464) and still finds the answer in the top 10 in only 66.7% of the cases.
  Within 1,000 tokens it holds the answer in 30.0%, BM25 in 43.1%.
- **Windows lose to heading chunks.** With BM25, windows of 256 and 512 tokens score 14 to 20
  points of recall@5 below `default`, both p < 0.001. A small window puts the answer earlier in
  the text, so the 256-token windows hold it within 1,000 tokens more often (63.7%, p < 0.001).
  Within 4,000 tokens both fall behind again. Windows cut code blocks 3,275 times at 256 tokens
  and 1,467 times at 512; the heading chunker cuts them 4 times.
- **`h6` with hybrid search and article grouping scores best here, with more text.** It beats
  its control on every rank metric (recall@1 +10.5, p < 0.001) and the shipped default on
  recall@1, recall@5, MRR and nDCG@10. The recall@5 lead is under the benchmark's 5-point margin
  ([Method](../method/index.md)). It returns 1.5 times the context, and loses within 1,000,
  2,000 and 4,000 tokens (-18.4, -15.7 and -7.9 points). ExactDocs' own hybrid search at `h6`
  scored 94.0% recall@5, not significantly above the default (p 0.12,
  [Every result](results.md)). Whether to ship it is #656.
- **Widening `h6` hits to their parent** adds 3.0 points of recall@5 over the control (p 0.0039)
  but returns 11,958 tokens per question.

!!! note "Not run yet"
    The runner capacity was cut to one VM while the grid ran, so these cells were stopped and
    stay unmeasured (#494):

    - `rag:window-256+64/bge-small`, the fixed-window RAG baseline (about 2.5 h on 2 vCPUs);
    - `window-256+64/hybrid:bge-small`, `window-512+128/hybrid:bge-small` and
      `window-256+64/hybrid:bge-small+context-embedded`;
    - `hybrid:bge-base-en-v1.5` at `default` and the grid's `default/hybrid:bge-base` (about 5 to
      7 h of embedding each);
    - every hosted embedding model and reranker (no provider is configured).

    The cross-encoder at `default` is in the [retrieval results](index.md), not here.

## Every table

`just bench-pages` writes these from the report.

<!-- bench:retrieval-grid-variants -->
- Golden set: 321 cases, fingerprint `sha256:100484c7ccdb1b89`; ExactDocs commit `47c9669d8673a4a71597985dfb1bdfe4f80a2ffc`, Python 3.14.10, Linux aarch64, 2 CPUs.

#### Every configuration

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

#### Against the budget's default

Each result against its budget's default, on the answerable cases both answered: the difference (recall@k in points, MRR and nDCG@10 as scores), its paired bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for recall@k or of a sign-flip permutation test for MRR and nDCG@10. **Bold**: significant at 5%.

| configuration | chunking | budget | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| `grep` | `raw` | none | `bm25` at `default` | **-39.0** [-46.1, -31.8], p < 0.001 | **-35.6** [-41.6, -29.2], p < 0.001 | **-27.0** [-32.6, -21.3], p < 0.001 | **-0.378** [-0.435, -0.320], p < 0.001 | **-0.335** [-0.384, -0.286], p < 0.001 |
| `default/hybrid:bge-small` | `default` | local | `bm25` at `default` | -5.2 [-11.2, +0.8], p 0.086 | -0.8 [-3.8, +2.2], p 0.63 | +0.4 [-2.6, +3.4], p 0.8 | -0.032 [-0.070, +0.005], p 0.093 | -0.003 [-0.035, +0.028], p 0.85 |
| `window-256+64/bm25` | `window-256+64` | none | `bm25` at `default` | **-31.5** [-37.5, -25.5], p < 0.001 | **-20.2** [-25.8, -15.0], p < 0.001 | **-14.6** [-19.5, -10.1], p < 0.001 | **-0.269** [-0.315, -0.225], p < 0.001 | **-0.222** [-0.261, -0.182], p < 0.001 |
| `window-512+128/bm25` | `window-512+128` | none | `bm25` at `default` | **-22.5** [-28.8, -16.5], p < 0.001 | **-13.9** [-19.1, -8.6], p < 0.001 | **-9.0** [-13.5, -4.5], p < 0.001 | **-0.191** [-0.237, -0.146], p < 0.001 | **-0.149** [-0.190, -0.109], p < 0.001 |
| `h6/hybrid:bge-small+parent` | `h6` | local | `bm25` at `default` | -2.6 [-8.2, +3.0], p 0.36 | +2.2 [-0.4, +4.9], p 0.12 | +2.6 [-0.4, +5.6], p 0.096 | -0.006 [-0.041, +0.029], p 0.75 | +0.022 [-0.008, +0.052], p 0.15 |
| `h6/hybrid:bge-small+article` | `h6` | local | `bm25` at `default` | **+5.2** [+0.0, +10.1], p 0.044 | **+3.8** [+1.1, +6.7], p 0.013 | +2.2 [-0.8, +5.2], p 0.14 | **+0.049** [+0.015, +0.081], p 0.004 | **+0.046** [+0.017, +0.075], p 0.0021 |

#### Within a token budget

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

#### Against each variant's control

Each variant against the cell it varies (`against` in the grid file), on the answerable cases both answered: the difference (recall in points, MRR and nDCG@10 as scores), its paired bootstrap interval and the p-value (McNemar's test, mid-p, for recall; a sign-flip permutation test for MRR and nDCG@10). **Bold**: significant at 5%.

| cell | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | within 1,000 | within 2,000 | within 4,000 | cut at 1,000 | cut at 2,000 | cut at 4,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `h6/hybrid:bge-small+parent` | `default/hybrid:bge-small` | +2.6 [-1.5, +6.4], p 0.2 | **+3.0** [+1.1, +5.2], p 0.0039 | **+2.2** [+0.8, +4.1], p 0.016 | **+0.027** [+0.003, +0.051], p 0.034 | **+0.025** [+0.005, +0.045], p 0.015 | **-29.6** [-35.6, -23.6], p < 0.001 | **-21.7** [-27.0, -16.5], p < 0.001 | **-15.0** [-19.5, -10.5], p < 0.001 | **-24.3** [-30.0, -18.7], p < 0.001 | **-14.6** [-19.1, -10.1], p < 0.001 | **-6.7** [-10.1, -3.8], p < 0.001 |
| `h6/hybrid:bge-small+article` | `default/hybrid:bge-small` | **+10.5** [+5.2, +15.4], p < 0.001 | **+4.5** [+2.2, +7.1], p < 0.001 | **+1.9** [+0.4, +3.8], p 0.031 | **+0.081** [+0.048, +0.114], p < 0.001 | **+0.049** [+0.023, +0.076], p < 0.001 | **-57.3** [-63.3, -51.3], p < 0.001 | **-33.7** [-39.7, -27.7], p < 0.001 | **-11.6** [-16.5, -7.1], p < 0.001 | **-35.6** [-41.9, -29.6], p < 0.001 | **-14.2** [-19.1, -9.7], p < 0.001 | -1.5 [-4.5, +1.5], p 0.33 |

Taken from an earlier run: `bm25@default`, `default/hybrid:bge-small`, `h6/hybrid:bge-small+parent`, `h6/hybrid:bge-small+article`.
<!-- /bench -->
