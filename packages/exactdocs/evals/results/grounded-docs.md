# Grounded Docs on the golden set

Grounded Docs indexed every pinned version of the golden corpus from the same files the ExactDocs importer takes; every golden question went through its search with the case's library and version, and the text it returned was scored with the text scorer, next to ExactDocs' BM25 asked and scored the same way. Definitions: docs/evals.md#grounded-docs.

## The run

- Grounded Docs 3.4.1 (npm `@arabold/docs-mcp-server`, integrity `sha512-IZQKYKs3p939Tt7N...`), Node.js v22.23.5; questions through its `search_docs` MCP tool with the case's library and version, 10 results.
- Run 2026-11-24T08:24:46+00:00: golden set 321 cases, fingerprint `sha256:7dd51c59057c279a`, projects starlette, pydantic, tanstack-query, zod, electron; ExactDocs commit `2fff1f699f034a8647f65ebf7bb8a723f9aeca64`, Python 3.14.6, Linux x86_64, 4 CPUs.
- `full-text`: no embedding model: full-text search only, what it does when no provider credentials are set. Environment: none.
- `bge-small-en-v1.5`: full-text and vector search, BAAI/bge-small-en-v1.5 served locally through an OpenAI-compatible endpoint (OPENAI_API_BASE). Environment: `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `OPENAI_API_BASE=<endpoint>/v1`, `OPENAI_API_KEY=local`.
  Embedding model BAAI/bge-small-en-v1.5 (revision `aa8f8b060edb`, 384 dimensions, stored at 512), served by retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched): indexing 6,263 texts, 2,466,665 tokens, 1,599 s of embedding (0 requests abandoned by the client); questions 321 texts, 5 s.

## Results

### Every result

| Tool and configuration | Scored by | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | version-neutral | context tokens / question | tokens to first hit |
|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 52.1% (46.1-58.1) | 81.7% (76.8-86.1) | 89.1% (85.4-92.9) | 0.651 (0.604-0.698) | 0.706 (0.668-0.743) | 0.0% | 72.2% | 3,464 (3,320-3,614) | 736 |
| ExactDocs bm25 @ default | chunk ID | 52.1% (46.1-58.1) | 81.7% (76.8-86.1) | 89.1% (85.4-92.9) | 0.651 (0.604-0.698) | 0.705 (0.667-0.742) | 0.0% | - | - | - |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 56.5% (50.6-62.5) | 84.3% (79.8-88.4) | 89.9% (86.1-93.3) | 0.688 (0.642-0.734) | 0.741 (0.705-0.778) | 0.0% | - | - | - |
| Grounded Docs full-text | text | 52.4% (46.4-58.4) | 78.6% (73.8-83.5) | 80.5% (75.7-85.0) | 0.632 (0.582-0.683) | 0.650 (0.607-0.693) | 0.0% | 80.9% | 7,935 (7,640-8,250) | 2,395 |
| Grounded Docs bge-small-en-v1.5 | text | 61.4% (55.8-67.4) | 80.5% (75.7-85.0) | 84.6% (80.2-88.8) | 0.702 (0.654-0.749) | 0.718 (0.678-0.757) | 0.0% | 79.7% | 7,360 (7,081-7,657) | 2,249 |

### Paired tests against ExactDocs

| Grounded Docs | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | +0.4 points (-6.4 to +7.1), p 0.912, not significant | -3.0 points (-8.2 to +1.9), p 0.253, not significant | -8.6 points (-13.5 to -3.8), p 0.000936, significant | -0.019 (-0.068 to +0.030), p 0.466, not significant | -0.056 (-0.096 to -0.016), p 0.0061, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | +0.4 points (-6.4 to +7.1), p 0.912, not significant | -3.0 points (-8.2 to +1.9), p 0.253, not significant | -8.6 points (-13.5 to -3.8), p 0.000936, significant | -0.019 (-0.068 to +0.030), p 0.466, not significant | -0.055 (-0.095 to -0.015), p 0.0068, significant |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -4.1 points (-11.2 to +3.0), p 0.266, not significant | -5.6 points (-10.9 to -0.4), p 0.0402, significant | -9.4 points (-14.2 to -4.5), p 0.000306, significant | -0.055 (-0.110 to -0.001), p 0.0499, significant | -0.091 (-0.136 to -0.045), p 0.0002, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | +9.4 points (+2.6 to +16.1), p 0.00878, significant | -1.1 points (-6.7 to +4.5), p 0.694, not significant | -4.5 points (-9.4 to +0.4), p 0.0725, not significant | +0.050 (-0.002 to +0.102), p 0.0605, not significant | +0.012 (-0.030 to +0.055), p 0.574, not significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | +9.4 points (+2.6 to +16.1), p 0.00878, significant | -1.1 points (-6.7 to +4.5), p 0.694, not significant | -4.5 points (-9.4 to +0.4), p 0.0725, not significant | +0.050 (-0.002 to +0.102), p 0.0605, not significant | +0.013 (-0.029 to +0.056), p 0.554, not significant |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | +4.9 points (-2.2 to +12.0), p 0.193, not significant | -3.8 points (-9.0 to +1.5), p 0.177, not significant | -5.2 points (-10.1 to -0.4), p 0.0357, significant | +0.014 (-0.041 to +0.067), p 0.616, not significant | -0.023 (-0.068 to +0.021), p 0.322, not significant |

### Every metric scored from the text

| tool | recall@1 | recall@5 | recall@10 | section recall@5 | MRR | nDCG@10 | wrong version | no answer | version-neutral | unmatched | results / q | context tokens / q | tokens to first hit | facts found |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | 52.1% | 81.7% | 89.1% | 74.9% | 0.651 | 0.706 | 0.0% | 0.0% | 72.2% | 0.0% | 10.0 | 3464 | 736 | 87.0% |
| Grounded Docs full-text | 52.4% | 78.6% | 80.5% | 71.1% | 0.632 | 0.650 | 0.0% | 0.0% | 80.9% | 0.2% | 7.5 | 7935 | 2395 | 92.3% |
| Grounded Docs bge-small-en-v1.5 | 61.4% | 80.5% | 84.6% | 73.4% | 0.702 | 0.718 | 0.0% | 0.0% | 79.7% | 0.5% | 7.0 | 7360 | 2249 | 93.5% |

### recall@5 by question kind

| Kind | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| `conceptual` | 83.0% | 81.1% | 83.0% |
| `cross-page` | 70.8% | 72.9% | 87.5% |
| `how-to` | 82.8% | 79.3% | 81.0% |
| `identifier-lookup` | 82.7% | 82.7% | 82.7% |
| `unanswerable` | - | - | - |
| `version-change` | 87.5% | 76.8% | 69.6% |

### recall@5 and context by project

| Project | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| starlette | 85.2%, 3,277 tokens | 94.4%, 5,363 tokens | 90.7%, 4,757 tokens |
| pydantic | 81.8%, 4,119 tokens | 67.3%, 8,523 tokens | 78.2%, 8,119 tokens |
| tanstack-query | 75.0%, 3,668 tokens | 82.7%, 7,952 tokens | 78.8%, 7,123 tokens |
| zod | 86.8%, 3,386 tokens | 79.2%, 7,360 tokens | 79.2%, 7,082 tokens |
| electron | 79.2%, 2,862 tokens | 69.8%, 10,413 tokens | 75.5%, 9,651 tokens |

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
- answerable cases whose first expected article is among them: 5 (zod v4.0.17: What should I use instead of .strict() and .passthrough() on objects?, zod v4.0.17: My .default("tuna") after a .transform() now has to be a number; how do I get the old pre-parse default?, zod v4.0.17: z.record(z.string()) used to work; why is it rejected now?, zod v4.0.17: An error map passed to .parse() no longer overrides the message set on my schema; is that intended?, zod v4.6.7: An object with an a: z.unknown() field now fails when a is missing; did that change?)
