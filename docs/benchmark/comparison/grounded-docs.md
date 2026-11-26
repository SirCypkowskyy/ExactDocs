# How Grounded Docs was measured

!!! abstract "TL;DR"
    - The same files as the ExactDocs importer takes, at the same pinned commits; the same questions
      with 10 results; scored from the text by the same scorer.
    - Two configurations: full-text only, and with `bge-small-en-v1.5` served locally.
    - Latency is not compared; the recorded run's versions and settings are at the end.

- **Same documentation.** Every pinned version of every project was indexed from the files the
  ExactDocs importer takes at the pinned commit, byte for byte, as a local folder (`file://`), as
  the project's library at the version's name.
- **Same questions, same cut-off.** Each golden question went through Grounded Docs' `search_docs`
  MCP tool with the case's library and version and 10 results, the cut-off ExactDocs is measured
  at.
- **Same scorer.** Grounded Docs' results and ExactDocs' BM25 at `default`, asked in the same run,
  were both scored from their text, with the rules chunk-ID scoring uses: recall@k and MRR count
  the first hit on any section a case lists, section recall and nDCG@10 count each part once.
  ExactDocs' results are scored as its `search_docs` returns them, grouped by article: each group
  is one result, holding its chunks' text (#575). The paired tests compare the two case by case.
  ExactDocs' recorded `bm25` and
  `hybrid:bge-small-en-v1.5` (scored by chunk ID, which agrees with the text scorer on 99.8% of
  decisions at `default`) are listed for reference.
- **Its documented defaults.** Scraping, its default exclusion patterns, splitting, search and
  result assembly were left as they ship. Three settings were set:
    - telemetry off;
    - the corpus folder as the one folder it may read;
    - the embedding request timeout raised from 30 to 300 seconds, because the local CPU endpoint
      answers one request at a time and Grounded Docs sends several at once (it waits longer; it
      indexes and ranks the same).

    The crawl's depth limit was raised for the versions whose folders are deeper than its default
    of 3, so that every article was offered.
- **Same embedding model.** The vector configuration used `BAAI/bge-small-en-v1.5`, the model of
  ExactDocs' best local configuration, served from the same ONNX file through a local
  OpenAI-compatible endpoint, the way Grounded Docs reaches any local model. Grounded Docs stores
  this model's 384-dimension vectors padded with zeros to 512 (its table of known models says
  512), which changes no distance between two vectors.

!!! warning "What to keep in mind"

    - **Bigger results.** Each Grounded Docs result is the matching chunks with the context it
      assembles around them (parent sections, neighbouring and child sections), so its ten
      results hold more text than ExactDocs' ten chunks. A result that holds a section's text
      answers it, so compare recall with the context tokens per question and the tokens up to
      the first hit.
    - **Version-neutral text.** Most of a pinned version's text is the same in its other
      versions, so most results of both tools cannot be told apart by their text, and the
      wrong-version rate scored from text is a lower bound. Grounded Docs searches only the
      version it is asked for.
    - **Latency is not compared.** Grounded Docs answered through MCP over HTTP; ExactDocs' BM25
      latency is its search alone, in-process.

## The recorded run

<!-- bench:grounded-docs-run -->
- Grounded Docs 3.4.1 (npm `@arabold/docs-mcp-server`, integrity `sha512-IZQKYKs3p939Tt7N...`), Node.js v22.23.5; questions through its `search_docs` MCP tool with the case's library and version, 10 results.
- Run 2026-11-25T15:50:09+00:00: golden set 321 cases, fingerprint `sha256:a00997851150e3b0`, projects starlette, pydantic, tanstack-query, zod, electron; ExactDocs commit `bdefaa90e0630622c5d4c87d1bb7cb6ab764ad87`, Python 3.14.6, Linux x86_64, 4 CPUs.
- `full-text`: no embedding model: full-text search only, what it does when no provider credentials are set. Environment: none.
- `bge-small-en-v1.5`: full-text and vector search, BAAI/bge-small-en-v1.5 served locally through an OpenAI-compatible endpoint (OPENAI_API_BASE). Environment: `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `OPENAI_API_BASE=<endpoint>/v1`, `OPENAI_API_KEY=local`.
  Embedding model BAAI/bge-small-en-v1.5 (revision `aa8f8b060edb`, 384 dimensions, stored at 512), served by retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched): indexing 6,263 texts, 2,466,665 tokens, 1,599 s of embedding (0 requests abandoned by the client); questions 321 texts, 11 s.
<!-- /bench -->
