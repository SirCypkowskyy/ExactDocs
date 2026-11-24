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

<!-- grounded-summary -->

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
<!-- /bench -->

### Results

<!-- bench:grounded-docs -->
<!-- /bench -->
