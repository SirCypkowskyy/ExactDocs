# Comparison with other tools

ExactDocs next to other documentation tools, on the same [golden set](golden-set.md): the same
questions about the same projects at the same pinned versions, every tool's results scored from
their text with the [text scorer](../evals.md#scoring-text-results), so each is measured with the
retrieval benchmark's own metrics, intervals and paired tests ([Method](method.md)). Every number
records the tool's version, its settings and the date it was measured. The tools run as their
documentation sets them up; nothing is tuned for the golden set.

## Grounded Docs

[Grounded Docs](https://github.com/arabold/docs-mcp-server) (`@arabold/docs-mcp-server`, MIT) is
the closest open-source alternative: a self-hosted MCP server that indexes each library version
separately and searches it with full-text search, and with vector search when an embedding model
is configured. It ran on this machine, so it indexed exactly what ExactDocs imports. How the run
works, and how to repeat it: [Grounded Docs](../evals.md#grounded-docs) in the evals reference.

The run of 24 November 2026 (Grounded Docs 3.4.1, both configurations, the whole golden set),
next to ExactDocs' BM25 at `default` asked and scored the same way. A hit is a result that answers
any section the case lists, a part or one of its alternatives, as in
[Retrieval metrics](method.md#retrieval-metrics):

- **Full-text search only.** Grounded Docs finds a section that answers in its top 5 a little
  less often than ExactDocs' BM25 (recall@5 83.5% against 87.6%; the paired test finds no
  significant difference, p 0.08), and less often in its top 10 (85.4% against 93.6%,
  significant); its nDCG@10 is lower (0.659 against 0.714, significant), and its recall@1 is the
  same (58.8%). It returns 7.5 results per question rather than 10, because it merges the nearby
  matches of a page into one result.
- **With `bge-small-en-v1.5`.** It puts a section that answers first more often than ExactDocs'
  BM25 (recall@1 71.5% against 58.8%, significant), and its MRR is higher (0.785 against 0.711,
  significant); recall@5 and nDCG@10 do not differ significantly (85.8% against 87.6% at 5), and
  recall@10 is lower (89.1% against 93.6%, significant). Against ExactDocs' hybrid search with
  the same model (the recorded run, scored by chunk ID), recall@1 is higher (71.5% against
  64.4%) and recall@10 lower (89.1% against 93.6%), both only just significant (p 0.0495 and
  0.041); recall@5, MRR and nDCG@10 do not differ significantly.
- **Twice the context.** Its results hold 7,360 to 7,935 estimated tokens per question, against
  ExactDocs' 3,464, and 1,998 to 2,324 tokens up to the first hit, against 656. That bigger
  context also holds more of the cases' facts (92% to 94%, against 87%).
- **Changelogs are left out.** Its default exclusion patterns skip `changelog.md` and
  `changelog.mdx` (and hidden files), so it did not index Pydantic v1's and Zod v4's changelogs,
  and four answerable Zod v4 cases list no section outside `changelog.mdx` (two more list it
  next to another page). Without those four (263 answerable cases), recall@5 is 84.8%
  full-text and 87.1% with the embedding model, against ExactDocs' 87.5%. The `version-change`
  questions, which lean on such pages, are where it trails most (recall@5 80.4% in both
  configurations, against 92.9%).
- **No result of another version** from either tool (wrong-version rate 0); 80% of Grounded Docs'
  results and 72% of ExactDocs' are version-neutral, so this says little on its own.
- **Indexing** the whole corpus (1,716 articles, 6,263 chunks) took 95 seconds with full-text
  search only (a 29.9 MB database) and 27 minutes with the embedding model on 4 shared CPUs
  (80.6 MB), almost all of it embedding 2.5 million tokens.

### How it was measured

- **Same documentation.** Every pinned version of every project was indexed from the files the
  ExactDocs importer takes at the pinned commit, byte for byte, as a local folder (`file://`), as
  the project's library at the version's name.
- **Same questions, same cut-off.** Each golden question went through Grounded Docs' `search_docs`
  MCP tool with the case's library and version and 10 results, the cut-off ExactDocs is measured
  at.
- **Same scorer.** Grounded Docs' results and ExactDocs' BM25 at `default`, asked in the same run,
  were both scored from their text, with the rules chunk-ID scoring uses: recall@k and MRR count
  the first hit on any section a case lists, section recall and nDCG@10 count each part once.
  The paired tests compare the two case by case. ExactDocs' recorded `bm25` and
  `hybrid:bge-small-en-v1.5` (scored by chunk ID, which agrees with the text scorer on 99.8% of
  decisions at `default`) are listed for reference.
- **Its documented defaults.** Scraping, its default exclusion patterns, splitting, search and
  result assembly were left as they ship. Three settings were set: telemetry off, the corpus
  folder as the one folder it may read, and the embedding request timeout raised from 30 to 300
  seconds, because the local CPU endpoint answers one request at a time and Grounded Docs sends
  several at once (it waits longer; it indexes and ranks the same). The crawl's depth limit was
  raised for the versions whose folders are deeper than its default of 3, so that every article
  was offered.
- **Same embedding model.** The vector configuration used `BAAI/bge-small-en-v1.5`, the model of
  ExactDocs' best local configuration, served from the same ONNX file through a local
  OpenAI-compatible endpoint, the way Grounded Docs reaches any local model. Grounded Docs stores
  this model's 384-dimension vectors padded with zeros to 512 (its table of known models says
  512), which changes no distance between two vectors.

What to keep in mind:

- **Bigger results.** Each Grounded Docs result is the matching chunks with the context it
  assembles around them (parent sections, neighbouring and child sections), so its ten results
  hold more text than ExactDocs' ten chunks. A result that holds a section's text answers it, so
  compare recall with the context tokens per question and the tokens up to the first hit.
- **Version-neutral text.** Most of a pinned version's text is the same in its other versions, so
  most results of both tools cannot be told apart by their text, and the wrong-version rate scored
  from text is a lower bound. Grounded Docs searches only the version it is asked for.
- **Latency is not compared.** Grounded Docs answered through MCP over HTTP; ExactDocs' BM25
  latency is its search alone, in-process.

### The recorded run

<!-- bench:grounded-docs-run -->
- Grounded Docs 3.4.1 (npm `@arabold/docs-mcp-server`, integrity `sha512-IZQKYKs3p939Tt7N...`), Node.js v22.23.5; questions through its `search_docs` MCP tool with the case's library and version, 10 results.
- Run 2026-11-24T20:47:42+00:00: golden set 321 cases, fingerprint `sha256:a00997851150e3b0`, projects starlette, pydantic, tanstack-query, zod, electron; ExactDocs commit `d2de6fdf9335f83261a061c7fd9876705d87b998`, Python 3.14.6, Linux x86_64, 4 CPUs.
- `full-text`: no embedding model: full-text search only, what it does when no provider credentials are set. Environment: none.
- `bge-small-en-v1.5`: full-text and vector search, BAAI/bge-small-en-v1.5 served locally through an OpenAI-compatible endpoint (OPENAI_API_BASE). Environment: `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `OPENAI_API_BASE=<endpoint>/v1`, `OPENAI_API_KEY=local`.
  Embedding model BAAI/bge-small-en-v1.5 (revision `aa8f8b060edb`, 384 dimensions, stored at 512), served by retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched): indexing 6,263 texts, 2,466,665 tokens, 1,599 s of embedding (0 requests abandoned by the client); questions 321 texts, 4 s.
<!-- /bench -->

<!-- bench:grounded-docs -->
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
<!-- /bench -->
