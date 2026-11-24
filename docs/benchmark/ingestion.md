# Ingestion results

What the importer makes of the [golden set](golden-set.md)'s corpus under each chunking
configuration, measured against the source at each pinned commit, with BM25 over the whole golden
set on the chunks it produced. No model is involved. The metrics are defined in
[Method](method.md#ingestion-metrics).

The recorded run is `packages/exactdocs/evals/results/ingestion.json`, recorded on 13 November
2026 with #346 on every pinned version of the five projects (the commits are on the
[Golden set](golden-set.md#the-corpus) page). The report does not record the ExactDocs commit or
the machine. #381 changed the default chunking and ran it again: the numbers are the same, under
new names (`default` is what was `h3-max-4000`, and `h6` what was `default`). The golden set's
review (#490) added expected sections to some cases, so it was recorded again on 23 November 2026
(on Linux, 4 CPUs): only the counts of expected sections and the coverage moved, every other
number is the same. #503 fixed how a hit is matched to an expected section at a coarser chunking
(a chunk now counts for every section it holds, [Method](method.md#chunking-configurations)), so
it was recorded again on 24 November 2026: only BM25 at `h2` and `merge-400` moved, to 82.8% and
81.7% recall@5 from 76.0% and 74.2%. Then #501 counted a hit on any section a case lists
([Method](method.md#retrieval-metrics)) and marked the review's added sections as alternatives,
so it was recorded once more the same day: only the BM25 columns moved (recall@5 87.6% at
`default`, 85.8% at `h6`, 89.1% at `h2`, 87.6% at `merge-400`). The lists of sections that start no chunk, and examples of each problem, are in
[`results/ingestion.md`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/evals/results/ingestion.md).

What it shows:

- Nothing is lost between configurations: every one of the 381 expected sections is still in some
  chunk, and the same 11,446 source characters (from Zod v4's symlinked README) are missing in all
  four.
- Coarser chunking trades coverage for size: `h2` starts a chunk for only half the expected
  sections and its largest chunks pass 20,000 tokens; `default` (split level 3, 4,000
  characters, a new library's chunking since #381) keeps 91.6% coverage with a p95 of 727
  tokens, against 100% and 507 tokens at `h6`, the default before.
- The problems found here are the importer's, not a configuration's: Zod v4's MDX fences hide 60
  headings, Pydantic keeps `{#id}` attributes in heading paths, MkDocs admonitions and tabs read
  as code blocks, and Pydantic v1's includes stay unexpanded.
- The BM25 column is this benchmark's own run. The [retrieval results](retrieval.md) measure BM25
  again at each chunking in a separate run, with the same match rule and the same numbers. The
  defaults are chosen from the retrieval run.

<!-- bench:ingestion -->
| configuration | coverage | held | cut fence / table / list | lost chars | tokens p50 / p95 / max | small | multi-top | empty / wrong path | headings missed / extra | BM25 recall@5 (exact) | MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `default` | 91.6% | 381/381 | 4 / 0 / 0 | 11446 of 7940351 | 114 / 738 / 8645 | 23.1% | 0.0% | 723 / 102 | 60 / 3 | 87.6% (83.5%) | 0.711 |
| `h6` | 100.0% | 381/381 | 4 / 0 / 0 | 11446 of 7940351 | 88 / 516 / 8645 | 32.2% | 0.0% | 723 / 103 | 60 / 3 | 85.8% (85.8%) | 0.689 |
| `h2` | 53.0% | 381/381 | 3 / 0 / 0 | 11446 of 7940351 | 179 / 1699 / 8645 | 14.3% | 0.6% | 726 / 95 | 60 / 3 | 89.1% (49.4%) | 0.737 |
| `merge-400` | 77.4% | 381/381 | 4 / 0 / 0 | 11446 of 7940351 | 183 / 654 / 8645 | 3.0% | 5.1% | 723 / 88 | 60 / 3 | 87.6% (73.4%) | 0.715 |

- `default`: today's default (#381): # to ### start a chunk; one over 4,000 characters is cut again at deeper headings.
- `h6`: every heading starts a chunk; nothing is merged or bounded (the default before #381).
- `h2`: only # and ## start a chunk; deeper sections stay inside their parent.
- `merge-400`: every heading starts a chunk, then one under 400 characters is merged with the next while the result stays within 4,000.

## `default` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 299 | 89.5% | 0 | 0 | 69 / 569 / 900 | 40.5% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 390 | 87.5% | 0 | 0 | 69 / 540 / 932 | 39.0% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 396 | 85.7% | 0 | 0 | 69 / 561 / 989 | 38.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 233 | 93.8% | 0 | 0 | 153 / 641 / 3017 | 10.7% | 23 / 0 | 0 / 0 | 23 | 113 | 67 |
| pydantic | v2.5.3 | 67 (1) | 537 | 92.3% | 0 | 0 | 138 / 832 / 3017 | 12.1% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 644 | 91.4% | 0 | 0 | 160 / 910 / 2762 | 10.2% | 77 / 59 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 475 | 95.5% | 0 | 0 | 140 / 585 / 3424 | 14.5% | 103 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 550 | 100.0% | 0 | 0 | 152 / 637 / 3269 | 12.4% | 110 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1253 | 100.0% | 0 | 0 | 81 / 528 / 3571 | 38.1% | 211 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 97 | 72.2% | 2 | 0 | 157 / 814 / 996 | 13.4% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 243 | 100.0% | 1 | 5289 | 169 / 630 / 2306 | 14.0% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 351 | 100.0% | 1 | 6157 | 183 / 684 / 8645 | 12.5% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1852 | 85.7% | 0 | 0 | 103 / 765 / 2493 | 24.2% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 2099 | 92.3% | 0 | 0 | 110 / 824 / 3582 | 22.3% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 2329 | 82.1% | 0 | 0 | 120 / 828 / 3582 | 21.8% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `h6` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 346 | 100.0% | 0 | 0 | 64 / 446 / 825 | 41.6% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 500 | 100.0% | 0 | 0 | 52 / 418 / 932 | 48.6% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 538 | 100.0% | 0 | 0 | 52 / 431 / 923 | 49.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 248 | 100.0% | 0 | 0 | 147 / 582 / 3017 | 10.9% | 23 / 0 | 0 / 0 | 23 | 117 | 67 |
| pydantic | v2.5.3 | 67 (1) | 553 | 100.0% | 0 | 0 | 138 / 738 / 3017 | 12.3% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 677 | 100.0% | 0 | 0 | 159 / 871 / 2762 | 10.6% | 77 / 60 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 497 | 100.0% | 0 | 0 | 134 / 540 / 3424 | 14.9% | 103 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 574 | 100.0% | 0 | 0 | 143 / 600 / 3269 | 12.9% | 110 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1322 | 100.0% | 0 | 0 | 71 / 506 / 3571 | 40.5% | 211 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 118 | 100.0% | 2 | 0 | 150 / 528 / 996 | 11.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 244 | 100.0% | 1 | 5289 | 166 / 630 / 2306 | 13.9% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 351 | 100.0% | 1 | 6157 | 183 / 684 / 8645 | 12.5% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 2853 | 100.0% | 0 | 0 | 70 / 398 / 2493 | 38.0% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 3180 | 100.0% | 0 | 0 | 77 / 448 / 3582 | 35.3% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 3464 | 100.0% | 0 | 0 | 81 / 470 / 3582 | 33.9% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `h2` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 159 | 63.2% | 0 | 0 | 123 / 1040 / 1821 | 26.4% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 224 | 62.5% | 0 | 0 | 115 / 875 / 1923 | 25.4% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 235 | 53.6% | 0 | 0 | 107 / 978 / 1946 | 25.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 136 | 68.8% | 0 | 0 | 215 / 1591 / 3017 | 7.3% | 23 / 0 | 0 / 0 | 23 | 81 | 67 |
| pydantic | v2.5.3 | 67 (1) | 400 | 53.8% | 0 | 0 | 148 / 1378 / 3017 | 9.5% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 504 | 57.1% | 0 | 0 | 156 / 1610 / 2762 | 9.7% | 77 / 55 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 339 | 63.6% | 0 | 0 | 166 / 1027 / 3424 | 10.9% | 104 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 374 | 61.9% | 0 | 0 | 179 / 1182 / 3269 | 8.8% | 111 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 893 | 75.9% | 0 | 0 | 98 / 802 / 3571 | 32.9% | 212 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 41 | 22.2% | 1 | 0 | 334 / 1846 / 1969 | 4.9% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 146 | 74.1% | 1 | 5289 | 243 / 1263 / 2306 | 7.5% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 200 | 58.8% | 1 | 6157 | 265 / 1402 / 8645 | 7.5% | 24 / 0 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 742 | 35.7% | 0 | 0 | 220 / 1906 / 2493 | 10.0% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 871 | 26.9% | 0 | 0 | 238 / 1931 / 3582 | 9.4% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 965 | 17.9% | 0 | 0 | 265 / 1929 / 3582 | 8.8% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `merge-400` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 184 | 68.4% | 0 | 0 | 160 / 561 / 891 | 4.3% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 236 | 70.8% | 0 | 0 | 153 / 605 / 932 | 3.8% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 250 | 82.1% | 0 | 0 | 153 / 560 / 989 | 3.2% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 194 | 68.8% | 0 | 0 | 215 / 637 / 3017 | 1.6% | 23 / 0 | 0 / 0 | 23 | 91 | 67 |
| pydantic | v2.5.3 | 67 (1) | 440 | 88.5% | 0 | 0 | 207 / 830 / 3017 | 5.7% | 56 / 33 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 568 | 80.0% | 0 | 0 | 213 / 930 / 2762 | 6.2% | 77 / 52 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 388 | 90.9% | 0 | 0 | 184 / 644 / 3424 | 5.1% | 103 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 455 | 90.5% | 0 | 0 | 191 / 679 / 3269 | 4.0% | 110 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 796 | 93.1% | 0 | 0 | 176 / 656 / 3571 | 9.7% | 211 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 88 | 77.8% | 2 | 0 | 200 / 564 / 996 | 0.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 182 | 81.5% | 1 | 5289 | 237 / 701 / 2306 | 1.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 273 | 70.6% | 1 | 6157 | 237 / 761 / 8645 | 1.1% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1521 | 71.4% | 0 | 0 | 171 / 544 / 2493 | 1.4% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 1768 | 46.2% | 0 | 0 | 177 / 628 / 3582 | 1.2% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 1979 | 78.6% | 0 | 0 | 181 / 627 / 3582 | 1.4% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |
<!-- /bench -->
