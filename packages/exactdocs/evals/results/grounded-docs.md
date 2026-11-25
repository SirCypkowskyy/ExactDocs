# Grounded Docs on the golden set

Grounded Docs indexed every pinned version of the golden corpus from the same files the ExactDocs importer takes; every golden question went through its search with the case's library and version, and the text it returned was scored with the text scorer, next to ExactDocs' BM25 asked and scored the same way. Definitions: docs/evals/grounded-docs.md.

## The run

- Grounded Docs 3.4.1 (npm `@arabold/docs-mcp-server`, integrity `sha512-IZQKYKs3p939Tt7N...`), Node.js v22.23.5; questions through its `search_docs` MCP tool with the case's library and version, 10 results.
- Run 2026-11-25T10:53:10+00:00: golden set 321 cases, fingerprint `sha256:a00997851150e3b0`, projects starlette, pydantic, tanstack-query, zod, electron; ExactDocs commit `12125cf2892e6ca5309de872d07cc0ff5773e7a6`, Python 3.14.6, Linux x86_64, 4 CPUs.
- `full-text`: no embedding model: full-text search only, what it does when no provider credentials are set. Environment: none.
- `bge-small-en-v1.5`: full-text and vector search, BAAI/bge-small-en-v1.5 served locally through an OpenAI-compatible endpoint (OPENAI_API_BASE). Environment: `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `OPENAI_API_BASE=<endpoint>/v1`, `OPENAI_API_KEY=local`.
  Embedding model BAAI/bge-small-en-v1.5 (revision `aa8f8b060edb`, 384 dimensions, stored at 512), served by retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched): indexing 6,263 texts, 2,466,665 tokens, 1,599 s of embedding (0 requests abandoned by the client); questions 321 texts, 7 s.

## Results

### Every result

| Tool and configuration | Scored by | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | version-neutral | context tokens / question | tokens to first hit |
|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 58.8% (52.8-64.8) | 87.6% (83.5-91.4) | 93.6% (90.6-96.2) | 0.711 (0.666-0.754) | 0.714 (0.676-0.751) | 0.0% | 72.2% | 3,464 (3,320-3,614) | 656 |
| ExactDocs bm25 @ default | chunk ID | 58.8% (52.8-64.8) | 87.6% (83.5-91.4) | 93.6% (90.6-96.2) | 0.711 (0.666-0.754) | 0.714 (0.676-0.751) | 0.0% | - | - | - |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 64.4% (58.8-70.0) | 90.3% (86.5-93.6) | 93.6% (90.6-96.2) | 0.756 (0.714-0.798) | 0.749 (0.712-0.785) | 0.0% | - | - | - |
| Grounded Docs full-text | text | 58.8% (52.8-64.8) | 83.5% (79.0-88.0) | 85.4% (81.3-89.5) | 0.689 (0.642-0.737) | 0.659 (0.616-0.702) | 0.0% | 80.9% | 7,935 (7,640-8,250) | 2,324 |
| Grounded Docs bge-small-en-v1.5 | text | 71.5% (66.3-76.8) | 85.8% (81.7-89.9) | 89.1% (85.4-92.9) | 0.785 (0.743-0.826) | 0.731 (0.691-0.770) | 0.0% | 79.7% | 7,360 (7,081-7,657) | 1,998 |

### Paired tests against ExactDocs

| Grounded Docs | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | +0.0 points (-6.7 to +6.7), p 1, not significant | -4.1 points (-8.6 to +0.4), p 0.0807, not significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.022 (-0.069 to +0.027), p 0.368, not significant | -0.055 (-0.096 to -0.015), p 0.0072, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | +0.0 points (-6.7 to +6.7), p 1, not significant | -4.1 points (-8.6 to +0.4), p 0.0807, not significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.022 (-0.069 to +0.027), p 0.368, not significant | -0.055 (-0.096 to -0.015), p 0.0072, significant |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -5.6 points (-12.7 to +1.5), p 0.125, not significant | -6.7 points (-11.2 to -2.2), p 0.0054, significant | -8.2 points (-12.7 to -3.8), p 0.000606, significant | -0.067 (-0.118 to -0.014), p 0.0138, significant | -0.090 (-0.136 to -0.044), p 0.0002, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | +12.7 points (+6.0 to +19.9), p 0.00049, significant | -1.9 points (-6.4 to +3.0), p 0.441, not significant | -4.5 points (-8.2 to -0.8), p 0.0295, significant | +0.074 (+0.024 to +0.126), p 0.0049, significant | +0.016 (-0.026 to +0.059), p 0.466, not significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | +12.7 points (+6.0 to +19.9), p 0.00049, significant | -1.9 points (-6.4 to +3.0), p 0.441, not significant | -4.5 points (-8.2 to -0.8), p 0.0295, significant | +0.074 (+0.024 to +0.126), p 0.0049, significant | +0.016 (-0.026 to +0.059), p 0.466, not significant |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | +7.1 points (+0.4 to +13.9), p 0.0495, significant | -4.5 points (-9.0 to +0.0), p 0.0532, not significant | -4.5 points (-8.6 to +0.0), p 0.041, significant | +0.029 (-0.022 to +0.079), p 0.272, not significant | -0.018 (-0.064 to +0.026), p 0.422, not significant |

### Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text each tool returned. Whole results: the result that first answers the case ends within the budget. Text cut: the text is cut at the budget, and the result the budget cuts counts when its part within the budget answers (scored from text only).

| Tool and configuration | Scored by | context tokens / question | tokens to first hit | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 3,464 (3,320-3,614) | 656 | 78.3% (73.4-83.2) | 88.8% (85.0-92.1) | 93.6% (90.6-96.2) | 83.5% (79.0-88.0) | 90.3% (86.5-93.6) | 93.6% (90.6-96.2) |
| ExactDocs bm25 @ default | chunk ID | - | - | - | - | - | - | - | - |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | - | - | - | - | - | - | - | - |
| Grounded Docs full-text | text | 7,935 (7,640-8,250) | 2,324 | 25.1% (20.2-30.3) | 53.6% (47.6-59.6) | 70.0% (64.4-75.3) | 44.6% (38.6-50.6) | 65.9% (60.3-71.5) | 77.1% (71.9-82.0) |
| Grounded Docs bge-small-en-v1.5 | text | 7,360 (7,081-7,657) | 1,998 | 34.5% (28.8-40.5) | 58.8% (53.2-64.8) | 75.7% (70.4-80.9) | 58.4% (52.4-64.0) | 73.0% (67.8-78.3) | 82.4% (77.9-86.9) |

### Paired tests within a token budget

| Grounded Docs | against | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | -53.2 points (-59.2 to -47.2), p 1.22e-40, significant | -35.2 points (-41.6 to -28.8), p 9.84e-23, significant | -23.6 points (-29.2 to -18.4), p 4.62e-16, significant | -39.0 points (-45.3 to -32.6), p 1.8e-25, significant | -24.3 points (-30.0 to -18.7), p 5.79e-15, significant | -16.5 points (-21.3 to -11.6), p 2.14e-10, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | - | - | - | - | - | - |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | - | - | - | - | - | - |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | -43.8 points (-50.6 to -37.1), p 1.06e-26, significant | -30.0 points (-36.3 to -23.6), p 4.45e-17, significant | -18.0 points (-23.2 to -12.7), p 5.38e-11, significant | -25.1 points (-31.8 to -18.4), p 4.7e-12, significant | -17.2 points (-22.9 to -11.6), p 4.04e-09, significant | -11.2 points (-15.7 to -6.7), p 1.64e-06, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | - | - | - | - | - | - |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | - | - | - | - | - | - |

### Every metric scored from the text

| tool | recall@1 | recall@5 | recall@10 | section recall@5 | MRR | nDCG@10 | wrong version | no answer | version-neutral | unmatched | results / q | context tokens / q | tokens to first hit | facts found |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | 58.8% | 87.6% | 93.6% | 76.6% | 0.711 | 0.714 | 0.0% | 0.0% | 72.2% | 0.0% | 10.0 | 3464 | 656 | 87.0% |
| Grounded Docs full-text | 58.8% | 83.5% | 85.4% | 72.7% | 0.689 | 0.659 | 0.0% | 0.0% | 80.9% | 0.2% | 7.5 | 7935 | 2324 | 92.3% |
| Grounded Docs bge-small-en-v1.5 | 71.5% | 85.8% | 89.1% | 75.4% | 0.785 | 0.731 | 0.0% | 0.0% | 79.7% | 0.5% | 7.0 | 7360 | 1998 | 93.5% |

### recall@5 by question kind

| Kind | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| `conceptual` | 86.8% | 83.0% | 86.8% |
| `cross-page` | 87.5% | 87.5% | 95.8% |
| `how-to` | 84.5% | 82.8% | 82.8% |
| `identifier-lookup` | 86.5% | 84.6% | 84.6% |
| `unanswerable` | - | - | - |
| `version-change` | 92.9% | 80.4% | 80.4% |

### recall@5 and context by project

| Project | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| starlette | 90.7%, 3,277 tokens | 96.3%, 5,363 tokens | 94.4%, 4,757 tokens |
| pydantic | 89.1%, 4,119 tokens | 72.7%, 8,523 tokens | 83.6%, 8,119 tokens |
| tanstack-query | 80.8%, 3,668 tokens | 86.5%, 7,952 tokens | 88.5%, 7,123 tokens |
| zod | 94.3%, 3,386 tokens | 86.8%, 7,360 tokens | 83.0%, 7,082 tokens |
| electron | 83.0%, 2,862 tokens | 75.5%, 10,413 tokens | 79.2%, 9,651 tokens |

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
