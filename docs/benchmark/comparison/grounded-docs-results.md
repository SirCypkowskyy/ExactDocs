# Grounded Docs: every table

The tables of the recorded run (`packages/exactdocs/evals/results/grounded-docs.json`), measured as
[How Grounded Docs was measured](grounded-docs.md) says.

<!-- bench:grounded-docs -->
### Every result

| Tool and configuration | Scored by | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | version-neutral | context tokens / question | tokens to first hit |
|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 70.4% (64.8-76.0) | 91.0% (87.3-94.4) | 93.3% (90.3-96.2) | 0.792 (0.751-0.833) | 0.754 (0.717-0.790) | 0.0% | 80.8% | 3,465 (3,320-3,615) | 1,448 |
| ExactDocs bm25 @ default | chunk ID | 70.4% (64.8-76.0) | 91.0% (87.3-94.4) | 93.3% (90.3-96.2) | 0.792 (0.751-0.833) | 0.754 (0.717-0.790) | 0.0% | - | 3,464 (3,320-3,614) | 1,448 |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 76.0% (70.8-81.3) | 92.5% (89.1-95.5) | 93.3% (90.3-96.2) | 0.832 (0.793-0.869) | 0.787 (0.750-0.821) | 0.0% | - | 3,206 (3,072-3,340) | 1,413 |
| Grounded Docs full-text | text | 58.4% (52.4-64.4) | 83.2% (78.6-87.6) | 85.0% (80.5-89.1) | 0.685 (0.638-0.734) | 0.655 (0.612-0.698) | 0.0% | 80.9% | 7,935 (7,640-8,250) | 2,332 |
| Grounded Docs bge-small-en-v1.5 | text | 71.2% (65.9-76.4) | 85.4% (81.3-89.5) | 88.8% (85.0-92.5) | 0.781 (0.738-0.823) | 0.727 (0.687-0.766) | 0.0% | 79.7% | 7,360 (7,081-7,657) | 2,004 |

### Paired tests against ExactDocs

| Grounded Docs | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | -12.0 points (-18.0 to -6.0), p 0.000142, significant | -7.9 points (-12.4 to -3.4), p 0.000472, significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.107 (-0.151 to -0.062), p 0.0001, significant | -0.099 (-0.137 to -0.060), p 0.0001, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | -12.0 points (-18.0 to -6.0), p 0.000142, significant | -7.9 points (-12.4 to -3.4), p 0.000472, significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.107 (-0.151 to -0.062), p 0.0001, significant | -0.099 (-0.137 to -0.060), p 0.0001, significant |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -17.6 points (-24.3 to -10.9), p 3.88e-07, significant | -9.4 points (-13.9 to -4.9), p 6.88e-05, significant | -8.2 points (-12.7 to -3.8), p 0.000606, significant | -0.146 (-0.196 to -0.096), p 0.0001, significant | -0.132 (-0.175 to -0.088), p 0.0001, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | +0.8 points (-5.6 to +7.1), p 0.822, not significant | -5.6 points (-10.1 to -1.1), p 0.0138, significant | -4.5 points (-8.2 to -0.8), p 0.0295, significant | -0.011 (-0.058 to +0.036), p 0.644, not significant | -0.027 (-0.067 to +0.013), p 0.2, not significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | +0.8 points (-5.6 to +7.1), p 0.822, not significant | -5.6 points (-10.1 to -1.1), p 0.0138, significant | -4.5 points (-8.2 to -0.8), p 0.0295, significant | -0.011 (-0.058 to +0.036), p 0.644, not significant | -0.027 (-0.067 to +0.013), p 0.2, not significant |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -4.9 points (-10.9 to +1.1), p 0.12, not significant | -7.1 points (-11.6 to -2.6), p 0.00222, significant | -4.5 points (-8.6 to -0.4), p 0.041, significant | -0.050 (-0.096 to -0.005), p 0.032, significant | -0.060 (-0.101 to -0.019), p 0.0053, significant |

### Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text each tool returned. Whole results: the result that first answers the case ends within the budget. Text cut: the text is cut at the budget, and the result the budget cuts counts when its part within the budget answers (scored from text only).

| Tool and configuration | Scored by | context tokens / question | tokens to first hit | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 3,465 (3,320-3,615) | 1,448 | 42.7% (36.7-48.7) | 71.2% (65.5-76.4) | 89.1% (85.4-92.9) | 80.2% (75.3-84.6) | 88.4% (84.3-92.1) | 92.9% (89.5-95.9) |
| ExactDocs bm25 @ default | chunk ID | 3,464 (3,320-3,614) | 1,448 | 42.7% (36.7-48.7) | 71.2% (65.5-76.4) | 89.1% (85.4-92.9) | - | - | - |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 3,206 (3,072-3,340) | 1,413 | 42.3% (36.3-48.3) | 73.4% (68.2-78.6) | 90.3% (86.5-93.6) | - | - | - |
| Grounded Docs full-text | text | 7,935 (7,640-8,250) | 2,332 | 24.7% (19.9-30.0) | 53.2% (47.2-59.2) | 69.7% (64.0-75.3) | 44.2% (38.2-50.2) | 65.5% (59.9-71.2) | 76.8% (71.5-81.7) |
| Grounded Docs bge-small-en-v1.5 | text | 7,360 (7,081-7,657) | 2,004 | 34.1% (28.5-39.7) | 58.4% (52.4-64.4) | 75.3% (70.0-80.5) | 58.1% (52.1-64.0) | 72.7% (67.4-77.9) | 82.0% (77.5-86.5) |

### Paired tests within a token budget

| Grounded Docs | against | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | -18.0 points (-24.3 to -11.6), p 1.23e-07, significant | -18.0 points (-24.3 to -11.6), p 8.41e-08, significant | -19.5 points (-25.1 to -13.9), p 3.24e-11, significant | -36.0 points (-42.3 to -29.6), p 2.8e-23, significant | -22.9 points (-28.5 to -17.2), p 1.74e-13, significant | -16.1 points (-21.0 to -11.2), p 3.89e-10, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | -18.0 points (-24.3 to -11.6), p 1.23e-07, significant | -18.0 points (-24.3 to -11.6), p 8.41e-08, significant | -19.5 points (-25.1 to -13.9), p 3.24e-11, significant | - | - | - |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -17.6 points (-24.3 to -10.9), p 7.25e-07, significant | -20.2 points (-27.0 to -13.5), p 1.72e-08, significant | -20.6 points (-26.2 to -15.0), p 2.96e-11, significant | - | - | - |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | -8.6 points (-15.4 to -1.9), p 0.0138, significant | -12.7 points (-19.1 to -6.4), p 0.000224, significant | -13.9 points (-19.1 to -8.6), p 7.56e-07, significant | -22.1 points (-28.8 to -15.0), p 3.79e-09, significant | -15.7 points (-21.3 to -10.1), p 1.68e-07, significant | -10.9 points (-15.4 to -6.4), p 2.83e-06, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | -8.6 points (-15.4 to -1.9), p 0.0138, significant | -12.7 points (-19.1 to -6.4), p 0.000224, significant | -13.9 points (-19.1 to -8.6), p 7.56e-07, significant | - | - | - |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -8.2 points (-14.6 to -1.9), p 0.0117, significant | -15.0 points (-21.3 to -8.6), p 5.66e-06, significant | -15.0 points (-20.6 to -9.4), p 2.79e-07, significant | - | - | - |

### Every metric scored from the text

| tool | recall@1 | recall@5 | recall@10 | section recall@5 | MRR | nDCG@10 | wrong version | no answer | version-neutral | unmatched | results / q | context tokens / q | tokens to first hit | facts found |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | 70.4% | 91.0% | 93.3% | 80.6% | 0.792 | 0.754 | 0.0% | 0.0% | 80.8% | 0.0% | 5.6 | 3465 | 1448 | 87.0% |
| Grounded Docs full-text | 58.4% | 83.2% | 85.0% | 72.3% | 0.685 | 0.655 | 0.0% | 0.0% | 80.9% | 0.2% | 7.5 | 7935 | 2332 | 92.3% |
| Grounded Docs bge-small-en-v1.5 | 71.2% | 85.4% | 88.8% | 75.0% | 0.781 | 0.727 | 0.0% | 0.0% | 79.7% | 0.5% | 7.0 | 7360 | 2004 | 93.5% |

### recall@5 by question kind

| Kind | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| `conceptual` | 88.7% | 83.0% | 86.8% |
| `cross-page` | 91.7% | 87.5% | 95.8% |
| `how-to` | 87.9% | 82.8% | 82.8% |
| `identifier-lookup` | 90.4% | 82.7% | 82.7% |
| `unanswerable` | - | - | - |
| `version-change` | 96.4% | 80.4% | 80.4% |

### recall@5 and context by project

| Project | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| starlette | 96.3%, 3,278 tokens | 96.3%, 5,363 tokens | 94.4%, 4,757 tokens |
| pydantic | 89.1%, 4,119 tokens | 70.9%, 8,523 tokens | 81.8%, 8,119 tokens |
| tanstack-query | 82.7%, 3,668 tokens | 86.5%, 7,952 tokens | 88.5%, 7,123 tokens |
| zod | 98.1%, 3,386 tokens | 86.8%, 7,360 tokens | 83.0%, 7,082 tokens |
| electron | 88.7%, 2,863 tokens | 75.5%, 10,413 tokens | 79.2%, 9,651 tokens |

### Indexing

| Configuration | Indexing time | Index size | Articles offered | Pages indexed | Chunks | Chunks with a vector |
|---|---|---|---|---|---|---|
| full-text | 95 s | 29.9 MB | 1,716 | 1,712 | 6,263 | 0 |
| bge-small-en-v1.5 | 1,644 s | 80.6 MB | 1,716 | 1,712 | 6,263 | 6,263 |

| Project | Version | Articles offered | Pages indexed | Chunks | Depth / pages passed | Seconds, full-text | Seconds, bge-small-en-v1.5 |
|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 | 23 | 118 | 3 / 1000 | 3.5 | 38.2 |
| starlette | 0.52.1 | 25 | 25 | 154 | 3 / 1000 | 3.6 | 52.9 |
| starlette | 1.10.0 | 25 | 25 | 174 | 3 / 1000 | 4.3 | 63.6 |
| pydantic | v1.10.22 | 25 | 23 | 126 | 3 / 1000 | 4.7 | 40.4 |
| pydantic | v2.5.3 | 67 | 67 | 418 | 3 / 1000 | 6.0 | 126.6 |
| pydantic | v2.14.3 | 91 | 91 | 545 | 3 / 1000 | 6.0 | 162.4 |
| tanstack-query | v4.36.1 | 140 | 140 | 332 | 4 / 1000 | 5.5 | 75.2 |
| tanstack-query | v5.0.0 | 147 | 147 | 385 | 4 / 1000 | 6.1 | 91.5 |
| tanstack-query | v5.90.3 | 327 | 327 | 711 | 6 / 1000 | 10.2 | 143.2 |
| zod | v3.23.8 | 1 | 1 | 46 | 3 / 1000 | 3.1 | 17.1 |
| zod | v4.0.17 | 17 | 16 | 122 | 5 / 1000 | 3.9 | 36.7 |
| zod | v4.6.7 | 24 | 23 | 218 | 5 / 1000 | 3.9 | 65.2 |
| electron | v30.0.0 | 239 | 239 | 794 | 4 / 1000 | 11.6 | 192.0 |
| electron | v38.0.0 | 264 | 264 | 986 | 4 / 1000 | 11.2 | 253.8 |
| electron | v45.3.2 | 301 | 301 | 1,134 | 4 / 1000 | 11.7 | 285.0 |

Articles not indexed:

- pydantic v1.10.22: `docs/.benchmarks_table.md`, `docs/changelog.md`
- zod v4.0.17: `packages/docs/content/v4/changelog.mdx`
- zod v4.6.7: `packages/docs/content/v4/changelog.mdx`
- answerable cases that list no other article: 4 (zod v4.0.17: What should I use instead of .strict() and .passthrough() on objects?, zod v4.0.17: My .default("tuna") after a .transform() now has to be a number; how do I get the old pre-parse default?, zod v4.0.17: z.record(z.string()) used to work; why is it rejected now?, zod v4.6.7: An object with an a: z.unknown() field now fails when a is missing; did that change?)
<!-- /bench -->
