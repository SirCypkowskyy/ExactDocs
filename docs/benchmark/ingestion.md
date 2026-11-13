# Ingestion results

What the importer makes of the [golden set](golden-set.md)'s corpus under each chunking
configuration, measured against the source at each pinned commit, with BM25 over the whole golden
set on the chunks it produced. No model is involved. The metrics are defined in
[Method](method.md#ingestion-metrics).

The recorded run is `packages/exactdocs/evals/results/ingestion.json`, recorded on 13 November
2026 with #346 on every pinned version of the five projects (the commits are on the
[Golden set](golden-set.md#the-corpus) page). The report does not record the ExactDocs commit or
the machine. The lists of sections that start no chunk, and examples of each problem, are in
[`results/ingestion.md`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/evals/results/ingestion.md).

What it shows:

- Nothing is lost between configurations: every one of the 367 expected sections is still in some
  chunk, and the same 11,446 source characters (from Zod v4's symlinked README) are missing in all
  four.
- Coarser chunking trades coverage for size: `h2` starts a chunk for only half the expected
  sections and its largest chunks pass 20,000 tokens; `h3-max-4000` keeps 91.3% coverage with a
  p95 of 727 tokens.
- The problems found here are the importer's, not a configuration's: Zod v4's MDX fences hide 60
  headings, Pydantic keeps `{#id}` attributes in heading paths, MkDocs admonitions and tabs read
  as code blocks, and Pydantic v1's includes stay unexpanded.
- The BM25 column is this benchmark's own run. The [retrieval results](retrieval.md) measure BM25
  again at each chunking in a separate run, and their numbers differ (for `h2`, 76.0% recall@5
  there against 81.3% here). The defaults are chosen from the retrieval run.

<!-- bench:ingestion -->
| configuration | coverage | held | cut fence / table / list | lost chars | tokens p50 / p95 / max | small | multi-top | empty / wrong path | headings missed / extra | BM25 recall@5 (exact) | MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `default` | 100.0% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 88 / 507 / 9276 | 32.2% | 0.0% | 713 / 103 | 60 / 3 | 79.4% (79.4%) | 0.626 |
| `h2` | 49.9% | 367/367 | 3 / 0 / 0 | 11446 of 7940351 | 166 / 1311 / 22515 | 15.1% | 0.6% | 716 / 95 | 60 / 3 | 81.3% (37.8%) | 0.670 |
| `h3-max-4000` | 91.3% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 114 / 727 / 9276 | 23.1% | 0.0% | 713 / 102 | 60 / 3 | 81.3% (76.4%) | 0.651 |
| `merge-400` | 77.1% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 183 / 651 / 9276 | 3.0% | 5.1% | 713 / 88 | 60 / 3 | 74.2% (65.2%) | 0.604 |

- `default`: today's default: every heading starts a chunk; nothing is merged or bounded.
- `h2`: only # and ## start a chunk; deeper sections stay inside their parent.
- `h3-max-4000`: # to ### start a chunk; one over 4,000 characters is cut again at deeper headings.
- `merge-400`: every heading starts a chunk, then one under 400 characters is merged with the next while the result stays within 4,000.

## `default` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 346 | 100.0% | 0 | 0 | 64 / 446 / 825 | 41.6% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 500 | 100.0% | 0 | 0 | 52 / 418 / 932 | 48.6% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 538 | 100.0% | 0 | 0 | 52 / 431 / 923 | 49.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 246 | 100.0% | 0 | 0 | 147 / 582 / 3216 | 11.0% | 23 / 0 | 0 / 0 | 23 | 117 | 67 |
| pydantic | v2.5.3 | 67 (1) | 549 | 100.0% | 0 | 0 | 138 / 729 / 3226 | 12.4% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 674 | 100.0% | 0 | 0 | 156 / 871 / 3116 | 10.7% | 77 / 60 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 494 | 100.0% | 0 | 0 | 133 / 526 / 3572 | 15.0% | 100 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 571 | 100.0% | 0 | 0 | 142 / 598 / 3417 | 13.0% | 107 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1318 | 100.0% | 0 | 0 | 70 / 506 / 3719 | 40.6% | 207 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 118 | 100.0% | 2 | 0 | 150 / 528 / 996 | 11.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 242 | 100.0% | 1 | 5289 | 164 / 630 / 2721 | 14.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 348 | 100.0% | 1 | 6157 | 183 / 684 / 9276 | 12.4% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 2852 | 100.0% | 0 | 0 | 70 / 395 / 2732 | 38.0% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 3174 | 100.0% | 0 | 0 | 77 / 440 / 5140 | 35.4% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 3455 | 100.0% | 0 | 0 | 80 / 464 / 5140 | 34.0% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `h2` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 157 | 57.9% | 0 | 0 | 122 / 875 / 3993 | 26.8% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 222 | 60.9% | 0 | 0 | 114 / 759 / 3992 | 25.7% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 232 | 53.6% | 0 | 0 | 106 / 875 / 3992 | 25.4% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 129 | 68.8% | 0 | 0 | 207 / 1513 / 5995 | 7.8% | 23 / 0 | 0 / 0 | 23 | 79 | 67 |
| pydantic | v2.5.3 | 67 (1) | 382 | 37.5% | 0 | 0 | 138 / 1124 / 8044 | 10.0% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 477 | 57.1% | 0 | 0 | 144 / 1476 / 8983 | 10.3% | 77 / 55 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 332 | 61.9% | 0 | 0 | 164 / 900 / 4911 | 11.1% | 101 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 362 | 61.9% | 0 | 0 | 174 / 900 / 5431 | 9.1% | 108 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 879 | 68.0% | 0 | 0 | 96 / 708 / 5971 | 33.5% | 208 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 37 | 16.7% | 1 | 0 | 311 / 4007 / 4411 | 5.4% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 143 | 72.0% | 1 | 5289 | 243 / 1171 / 3984 | 7.7% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 191 | 59.4% | 1 | 6157 | 259 / 1479 / 9276 | 7.3% | 24 / 0 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 685 | 34.6% | 0 | 0 | 195 / 1610 / 19229 | 10.8% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 787 | 26.9% | 0 | 0 | 211 / 1867 / 21312 | 10.3% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 862 | 14.3% | 0 | 0 | 220 / 1963 / 22515 | 9.9% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `h3-max-4000` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 299 | 89.5% | 0 | 0 | 69 / 569 / 900 | 40.5% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 390 | 87.0% | 0 | 0 | 69 / 540 / 932 | 39.0% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 396 | 85.7% | 0 | 0 | 69 / 561 / 989 | 38.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 231 | 93.8% | 0 | 0 | 153 / 641 / 3216 | 10.8% | 23 / 0 | 0 / 0 | 23 | 113 | 67 |
| pydantic | v2.5.3 | 67 (1) | 533 | 91.7% | 0 | 0 | 136 / 830 / 3226 | 12.2% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 641 | 91.4% | 0 | 0 | 160 / 910 / 3116 | 10.3% | 77 / 59 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 472 | 95.2% | 0 | 0 | 140 / 550 / 3572 | 14.6% | 100 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 547 | 100.0% | 0 | 0 | 152 / 614 / 3417 | 12.4% | 107 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1249 | 100.0% | 0 | 0 | 80 / 523 / 3719 | 38.3% | 207 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 97 | 72.2% | 2 | 0 | 157 / 814 / 996 | 13.4% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 241 | 100.0% | 1 | 5289 | 167 / 630 / 2721 | 14.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 348 | 100.0% | 1 | 6157 | 183 / 684 / 9276 | 12.4% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1851 | 84.6% | 0 | 0 | 103 / 765 / 2732 | 24.2% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 2093 | 92.3% | 0 | 0 | 109 / 819 / 5140 | 22.4% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 2320 | 82.1% | 0 | 0 | 119 / 821 / 5140 | 21.9% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `merge-400` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 184 | 68.4% | 0 | 0 | 160 / 561 / 891 | 4.3% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 236 | 73.9% | 0 | 0 | 153 / 605 / 932 | 3.8% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 250 | 82.1% | 0 | 0 | 153 / 560 / 989 | 3.2% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 192 | 68.8% | 0 | 0 | 216 / 637 / 3216 | 1.6% | 23 / 0 | 0 / 0 | 23 | 91 | 67 |
| pydantic | v2.5.3 | 67 (1) | 436 | 87.5% | 0 | 0 | 207 / 830 / 3226 | 5.7% | 56 / 33 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 566 | 80.0% | 0 | 0 | 213 / 930 / 3116 | 6.2% | 77 / 52 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 385 | 90.5% | 0 | 0 | 184 / 644 / 3572 | 5.2% | 100 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 452 | 90.5% | 0 | 0 | 189 / 659 / 3417 | 4.0% | 107 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 792 | 92.0% | 0 | 0 | 174 / 651 / 3719 | 9.7% | 207 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 88 | 77.8% | 2 | 0 | 200 / 564 / 996 | 0.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 180 | 80.0% | 1 | 5289 | 237 / 701 / 2721 | 1.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 270 | 71.9% | 1 | 6157 | 237 / 761 / 9276 | 0.7% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1520 | 69.2% | 0 | 0 | 171 / 544 / 2732 | 1.4% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 1762 | 46.2% | 0 | 0 | 177 / 621 / 5140 | 1.2% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 1970 | 78.6% | 0 | 0 | 181 / 615 / 5140 | 1.4% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |
<!-- /bench -->
