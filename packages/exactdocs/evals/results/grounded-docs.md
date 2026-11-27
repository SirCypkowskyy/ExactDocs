# Grounded Docs on the golden set

Grounded Docs indexed every pinned version of the golden corpus from the same files the ExactDocs importer takes; every golden question went through its search with the case's library and version, and the text it returned was scored with the text scorer, next to ExactDocs' BM25 asked and scored the same way. Definitions: docs/evals/grounded-docs.md.

## The run

- Grounded Docs 3.4.1 (npm `@arabold/docs-mcp-server`, integrity `sha512-IZQKYKs3p939Tt7N...`), Node.js v22.23.5; questions through its `search_docs` MCP tool with the case's library and version, 10 results.
- Run 2026-11-27T03:18:27+00:00: golden set 321 cases, fingerprint `sha256:100484c7ccdb1b89`, projects starlette, pydantic, tanstack-query, zod, electron; ExactDocs commit `aea221ac47d2c7bd29862eebce61925d37e4ad2f`, Python 3.14.10, Linux aarch64, 2 CPUs.
- `full-text`: no embedding model: full-text search only, what it does when no provider credentials are set. Environment: none.
- `bge-small-en-v1.5`: full-text and vector search, BAAI/bge-small-en-v1.5 served locally through an OpenAI-compatible endpoint (OPENAI_API_BASE). Environment: `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `OPENAI_API_BASE=<endpoint>/v1`, `OPENAI_API_KEY=local`.
  Embedding model BAAI/bge-small-en-v1.5 (revision `aa8f8b060edb`, 384 dimensions, stored at 512), served by retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched): indexing 6,263 texts, 2,482,651 tokens, 5,389 s of embedding (0 requests abandoned by the client); questions 321 texts, 13 s.

## Results

### Every result

| Tool and configuration | Scored by | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | version-neutral | context tokens / question | tokens to first hit |
|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 70.8% (65.2-76.4) | 91.4% (88.0-94.4) | 93.6% (90.6-96.2) | 0.796 (0.755-0.836) | 0.757 (0.721-0.793) | 0.0% | 80.8% | 3,465 (3,320-3,615) | 1,444 |
| ExactDocs bm25 @ default | chunk ID | 70.8% (65.2-76.4) | 91.4% (88.0-94.4) | 93.6% (90.6-96.2) | 0.796 (0.755-0.836) | 0.757 (0.721-0.793) | 0.0% | - | 3,464 (3,320-3,614) | 1,444 |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 76.4% (71.2-81.3) | 93.3% (89.9-96.2) | 93.6% (90.6-96.2) | 0.837 (0.798-0.873) | 0.791 (0.755-0.825) | 0.0% | - | 3,212 (3,077-3,346) | 1,410 |
| Grounded Docs full-text | text | 59.2% (53.2-65.2) | 83.5% (79.0-88.0) | 85.4% (81.3-89.5) | 0.693 (0.646-0.741) | 0.660 (0.618-0.703) | 0.0% | 80.8% | 7,964 (7,672-8,280) | 2,282 |
| Grounded Docs bge-small-en-v1.5 | text | 71.9% (66.3-77.1) | 87.3% (83.2-91.0) | 90.6% (87.3-94.0) | 0.795 (0.754-0.836) | 0.742 (0.704-0.780) | 0.0% | 79.7% | 7,352 (7,076-7,649) | 2,032 |

### Paired tests against ExactDocs

| Grounded Docs | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | -11.6 points (-18.0 to -5.2), p 0.000257, significant | -7.9 points (-12.4 to -3.4), p 0.000472, significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.103 (-0.148 to -0.058), p 0.0003, significant | -0.097 (-0.136 to -0.058), p 0.0001, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | -11.6 points (-18.0 to -5.2), p 0.000257, significant | -7.9 points (-12.4 to -3.4), p 0.000472, significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.103 (-0.148 to -0.058), p 0.0003, significant | -0.097 (-0.136 to -0.058), p 0.0001, significant |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -17.2 points (-24.0 to -10.5), p 8.19e-07, significant | -9.7 points (-14.2 to -5.2), p 2.53e-05, significant | -8.2 points (-12.7 to -3.8), p 0.000606, significant | -0.144 (-0.193 to -0.094), p 0.0001, significant | -0.130 (-0.174 to -0.085), p 0.0001, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | +1.1 points (-5.6 to +7.9), p 0.744, not significant | -4.1 points (-8.2 to +0.4), p 0.073, not significant | -3.0 points (-7.1 to +1.1), p 0.15, not significant | -0.001 (-0.048 to +0.047), p 0.974, not significant | -0.015 (-0.055 to +0.025), p 0.472, not significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | +1.1 points (-5.6 to +7.9), p 0.744, not significant | -4.1 points (-8.2 to +0.4), p 0.073, not significant | -3.0 points (-7.1 to +1.1), p 0.15, not significant | -0.001 (-0.048 to +0.047), p 0.974, not significant | -0.015 (-0.055 to +0.025), p 0.472, not significant |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -4.5 points (-10.5 to +1.5), p 0.154, not significant | -6.0 points (-10.1 to -1.9), p 0.00763, significant | -3.0 points (-7.1 to +1.1), p 0.163, not significant | -0.041 (-0.086 to +0.003), p 0.0784, not significant | -0.048 (-0.089 to -0.008), p 0.0227, significant |

### Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text each tool returned. Whole results: the result that first answers the case ends within the budget. Text cut: the text is cut at the budget, and the result the budget cuts counts when its part within the budget answers (scored from text only).

| Tool and configuration | Scored by | context tokens / question | tokens to first hit | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 3,465 (3,320-3,615) | 1,444 | 43.1% (37.1-49.1) | 71.5% (66.3-76.8) | 89.5% (85.8-92.9) | 80.5% (75.7-85.4) | 88.8% (85.0-92.5) | 93.3% (90.3-96.2) |
| ExactDocs bm25 @ default | chunk ID | 3,464 (3,320-3,614) | 1,444 | 43.1% (37.1-49.1) | 71.5% (66.3-76.8) | 89.5% (85.8-92.9) | - | - | - |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 3,212 (3,077-3,346) | 1,410 | 42.3% (36.3-48.3) | 74.2% (68.9-79.4) | 90.6% (86.9-94.0) | - | - | - |
| Grounded Docs full-text | text | 7,964 (7,672-8,280) | 2,282 | 25.1% (20.2-30.3) | 53.6% (47.6-59.6) | 70.8% (65.2-76.0) | 44.9% (39.0-50.9) | 65.9% (60.3-71.5) | 77.9% (73.0-82.8) |
| Grounded Docs bge-small-en-v1.5 | text | 7,352 (7,076-7,649) | 2,032 | 34.5% (28.8-40.5) | 58.4% (52.8-64.4) | 76.8% (71.5-81.7) | 57.7% (51.7-63.7) | 71.5% (66.3-76.8) | 84.3% (79.8-88.4) |

### Paired tests within a token budget

| Grounded Docs | against | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | -18.0 points (-24.3 to -11.6), p 1.23e-07, significant | -18.0 points (-24.3 to -11.6), p 8.41e-08, significant | -18.7 points (-24.3 to -13.1), p 2.24e-10, significant | -35.6 points (-41.9 to -29.2), p 1.98e-22, significant | -22.9 points (-28.5 to -17.2), p 1.74e-13, significant | -15.4 points (-20.2 to -10.5), p 1.29e-09, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | -18.0 points (-24.3 to -11.6), p 1.23e-07, significant | -18.0 points (-24.3 to -11.6), p 8.41e-08, significant | -18.7 points (-24.3 to -13.1), p 2.24e-10, significant | - | - | - |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -17.2 points (-24.0 to -10.5), p 1.1e-06, significant | -20.6 points (-27.3 to -13.9), p 7.32e-09, significant | -19.9 points (-25.5 to -14.2), p 8.96e-11, significant | - | - | - |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | -8.6 points (-15.4 to -1.5), p 0.0149, significant | -13.1 points (-19.9 to -6.4), p 0.000222, significant | -12.7 points (-18.0 to -7.5), p 5.13e-06, significant | -22.9 points (-30.0 to -15.7), p 1.52e-09, significant | -17.2 points (-23.2 to -11.6), p 2.31e-08, significant | -9.0 points (-13.5 to -4.5), p 0.000112, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | -8.6 points (-15.4 to -1.5), p 0.0149, significant | -13.1 points (-19.9 to -6.4), p 0.000222, significant | -12.7 points (-18.0 to -7.5), p 5.13e-06, significant | - | - | - |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -7.9 points (-14.2 to -1.5), p 0.0183, significant | -15.7 points (-22.1 to -9.4), p 2.43e-06, significant | -13.9 points (-19.5 to -8.2), p 1.88e-06, significant | - | - | - |

### Every metric scored from the text

| tool | recall@1 | recall@5 | recall@10 | section recall@5 | MRR | nDCG@10 | wrong version | no answer | version-neutral | unmatched | results / q | context tokens / q | tokens to first hit | facts found |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | 70.8% | 91.4% | 93.6% | 81.0% | 0.796 | 0.757 | 0.0% | 0.0% | 80.8% | 0.0% | 5.6 | 3465 | 1444 | 87.0% |
| Grounded Docs full-text | 59.2% | 83.5% | 85.4% | 72.5% | 0.693 | 0.660 | 0.0% | 0.0% | 80.8% | 0.2% | 7.5 | 7964 | 2282 | 92.3% |
| Grounded Docs bge-small-en-v1.5 | 71.9% | 87.3% | 90.6% | 76.7% | 0.795 | 0.742 | 0.0% | 0.0% | 79.7% | 0.4% | 7.0 | 7352 | 2032 | 93.3% |

### recall@5 by question kind

| Kind | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| `conceptual` | 88.7% | 83.0% | 92.5% |
| `cross-page` | 91.7% | 87.5% | 95.8% |
| `how-to` | 87.9% | 82.8% | 82.8% |
| `identifier-lookup` | 92.3% | 84.6% | 84.6% |
| `unanswerable` | - | - | - |
| `version-change` | 96.4% | 80.4% | 82.1% |

### recall@5 and context by project

| Project | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| starlette | 96.3%, 3,278 tokens | 96.3%, 5,377 tokens | 96.3%, 4,759 tokens |
| pydantic | 90.9%, 4,119 tokens | 72.7%, 8,554 tokens | 83.6%, 8,184 tokens |
| tanstack-query | 82.7%, 3,668 tokens | 86.5%, 8,033 tokens | 90.4%, 7,079 tokens |
| zod | 98.1%, 3,386 tokens | 86.8%, 7,388 tokens | 84.9%, 7,096 tokens |
| electron | 88.7%, 2,863 tokens | 75.5%, 10,406 tokens | 81.1%, 9,572 tokens |

### Indexing

| Configuration | Indexing time | Index size | Articles offered | Pages indexed | Chunks | Chunks with a vector |
|---|---|---|---|---|---|---|
| full-text | 122 s | 30.0 MB | 1,716 | 1,712 | 6,263 | 0 |
| bge-small-en-v1.5 | 5,449 s | 80.8 MB | 1,716 | 1,712 | 6,263 | 6,263 |

| Project | Version | Articles offered | Pages indexed | Chunks | Depth / pages passed | Seconds, full-text | Seconds, bge-small-en-v1.5 |
|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 | 23 | 118 | 3 / 1000 | 4.8 | 115.7 |
| starlette | 0.52.1 | 25 | 25 | 154 | 3 / 1000 | 5.1 | 153.5 |
| starlette | 1.10.0 | 25 | 25 | 174 | 3 / 1000 | 5.3 | 179.4 |
| pydantic | v1.10.22 | 25 | 23 | 126 | 3 / 1000 | 5.3 | 124.6 |
| pydantic | v2.5.3 | 67 | 67 | 418 | 3 / 1000 | 6.8 | 391.2 |
| pydantic | v2.14.3 | 91 | 91 | 545 | 3 / 1000 | 7.7 | 501.4 |
| tanstack-query | v4.36.1 | 140 | 140 | 332 | 4 / 1000 | 7.3 | 254.2 |
| tanstack-query | v5.0.0 | 147 | 147 | 385 | 4 / 1000 | 7.7 | 303.8 |
| tanstack-query | v5.90.3 | 327 | 327 | 711 | 6 / 1000 | 11.3 | 528.2 |
| zod | v3.23.8 | 1 | 1 | 46 | 3 / 1000 | 4.1 | 48.2 |
| zod | v4.0.17 | 17 | 16 | 122 | 5 / 1000 | 4.9 | 116.4 |
| zod | v4.6.7 | 24 | 23 | 218 | 5 / 1000 | 5.7 | 217.4 |
| electron | v30.0.0 | 239 | 239 | 794 | 4 / 1000 | 14.0 | 677.7 |
| electron | v38.0.0 | 264 | 264 | 986 | 4 / 1000 | 15.3 | 855.4 |
| electron | v45.3.2 | 301 | 301 | 1,134 | 4 / 1000 | 17.0 | 981.6 |

Articles not indexed:

- pydantic v1.10.22: `docs/.benchmarks_table.md`, `docs/changelog.md`
- zod v4.0.17: `packages/docs/content/v4/changelog.mdx`
- zod v4.6.7: `packages/docs/content/v4/changelog.mdx`
- answerable cases that list no other article: 4 (zod v4.0.17: What should I use instead of .strict() and .passthrough() on objects?, zod v4.0.17: My .default("tuna") after a .transform() now has to be a number; how do I get the old pre-parse default?, zod v4.0.17: z.record(z.string()) used to work; why is it rejected now?, zod v4.6.7: An object with an a: z.unknown() field now fails when a is missing; did that change?)
