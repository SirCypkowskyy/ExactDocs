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
next to ExactDocs' BM25 at `default` asked and scored the same way:

- **Full-text search only.** Grounded Docs finds the expected section in its top 5 about as often
  as ExactDocs' BM25 (recall@5 78.6% against 81.7%; the paired test finds no significant
  difference), but less often in its top 10 (80.5% against 89.1%, significant), and its nDCG@10
  is lower (0.650 against 0.706, significant). It returns 7.5 results per question rather than
  10, because it merges the nearby matches of a page into one result.
- **With `bge-small-en-v1.5`.** It puts the expected section first more often than ExactDocs'
  BM25 (recall@1 61.4% against 52.1%, significant); recall@5, recall@10, MRR and nDCG@10 do not
  differ significantly (80.5% against 81.7% at 5). Against ExactDocs' hybrid search with the same
  model (the recorded run, scored by chunk ID) only recall@10 differs significantly (84.6%
  against 89.9%).
- **Twice the context.** Its results hold 7,360 to 7,935 estimated tokens per question, against
  ExactDocs' 3,464, and 2,249 to 2,395 tokens up to the first hit, against 736. That bigger
  context also holds more of the cases' facts (92% to 94%, against 87%).
- **Changelogs are left out.** Its default exclusion patterns skip `changelog.md` and
  `changelog.mdx` (and hidden files), so it did not index Pydantic v1's and Zod v4's changelogs,
  and five answerable Zod v4 cases expect `changelog.mdx`. Without those five (262 answerable
  cases), recall@5 is 80.2% full-text and 82.1% with the embedding model, against ExactDocs'
  81.3%. The `version-change` questions, which lean on such pages, are where it trails most.
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
  were both scored from their text. The paired tests compare the two case by case. ExactDocs'
  recorded `bm25` and `hybrid:bge-small-en-v1.5` (scored by chunk ID, which agrees with the text
  scorer on 99.5% of decisions at `default`) are listed for reference.
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
- Run 2026-11-24T08:24:46+00:00: golden set 321 cases, fingerprint `sha256:7dd51c59057c279a`, projects starlette, pydantic, tanstack-query, zod, electron; ExactDocs commit `2fff1f699f034a8647f65ebf7bb8a723f9aeca64`, Python 3.14.6, Linux x86_64, 4 CPUs.
- `full-text`: no embedding model: full-text search only, what it does when no provider credentials are set. Environment: none.
- `bge-small-en-v1.5`: full-text and vector search, BAAI/bge-small-en-v1.5 served locally through an OpenAI-compatible endpoint (OPENAI_API_BASE). Environment: `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `OPENAI_API_BASE=<endpoint>/v1`, `OPENAI_API_KEY=local`.
  Embedding model BAAI/bge-small-en-v1.5 (revision `aa8f8b060edb`, 384 dimensions, stored at 512), served by retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched): indexing 6,263 texts, 2,466,665 tokens, 1,599 s of embedding (0 requests abandoned by the client); questions 321 texts, 5 s.
<!-- /bench -->

<!-- bench:grounded-docs -->
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
<!-- /bench -->
