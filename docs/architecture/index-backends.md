# External index backends

!!! abstract "TL;DR"

    - By default every index lives in ExactDocs' own database. `EXACTDOCS_SEARCH_BACKEND` and
      `EXACTDOCS_VECTOR_BACKEND` move the search or vector index to one of twelve external backends
      (#352, epic E14).
    - The database stays the source of truth: a backend holds derived data that
      `exactdocs index rebuild` can always write again.
    - A backend holds one entry per chunk and version, and every hit is checked against the
      manifests asked for, so a lagging backend never leaks a stale chunk.
    - Writes are retried, then fail the job, never silently. A drift check compares each backend
      with the database.

By default every index lives in ExactDocs' own database (SQLite FTS5 and sqlite-vec, or PostgreSQL
full-text search, pg_search and pgvector). `EXACTDOCS_SEARCH_BACKEND` and `EXACTDOCS_VECTOR_BACKEND`
move the search index or the vector index to an external backend (#352). Epic E14 built twelve
backends on it, each with its options in
[Configuration](../configuration.md#external-index-backends).

## The rules

- **Derived data.** The database stays the source of truth. It keeps:
    - every chunk;
    - its search entries (the database's own index is still written, so switching back needs no
      reindex);
    - every vector (an embedding is paid once; the backend holds a copy).

    Anything a backend holds can be thrown away and written again by `exactdocs index rebuild`,
    without importing or embedding anything again.
- **Version isolation.** A backend holds one entry per chunk row of each version, never one shared
  by several versions. An `IndexEntry` is: manifest ID, library, version, chunk ID, article path,
  headings, text, tags and, for vectors, the vector.
    - Every search names the manifests it may look at.
    - The domain also drops any hit of another manifest and any chunk the database no longer has,
      so a backend that lags behind a removal never leaks a stale chunk.
- **Optional extras.** A backend's client library is an optional extra
  (`pip install 'exactdocs[<extra>]'`), imported only by its adapter module, and that module only
  when an operator names the backend (`bootstrap/index_backends.py` imports it by name).
    - An architecture test (`tests/architecture/test_index_backends.py`) checks that nothing else
      imports the extra's packages.
    - A missing extra, invalid options, or a backend that does not answer at start stop the instance
      with a message naming the backend.

## The extension point

Retrieval declares the backend ports in `ports/driven.py`:

| Port | What a backend implements |
|---|---|
| `IndexBackend` | `name`, `open()` (connect and check, at start), `close()` |
| `SearchBackend` | `put(manifest, entries)` (add or replace, page by page), `delete(manifest_ids)`,<br/>`held(library)` (versions and entry counts, for the drift check),<br/>`search(manifest_ids, query, tag_filter, limit)` and `count(...)`[^textquery] |
| `VectorBackend` | `put(space, manifest, entries)`, `remove(space, manifest, chunk_ids)`, `delete(manifest_ids)`,<br/>`drop_space(space)`, `held(space, library)`,<br/>`nearest(space, manifest_ids, vector, tag_filter, limit)` with cosine distances |
| `NativeHybrid` (optional) | `hybrid(space, manifest_ids, query, vector, tag_filter, limit)`[^hybrid] |
| `NativeRerank` (optional, #473) | `hybrid_reranked(space, manifest_ids, query, vector, tag_filter, limit)` → `NativeRanking`[^rerank] |

[^textquery]: The query comes as its text and its terms (`TextQuery`), never as syntax.

[^hybrid]: A vector backend that ranks words and vectors together itself. `RetrievalModule.build`
    checks for it (a `runtime_checkable` Protocol), and `HybridPipeline` then asks the backend once
    instead of fusing BM25 and the vectors with reciprocal rank fusion.

[^rerank]: `NativeRanking` holds the hits, and how many of the first ones the backend's own ranker
    reordered. It is for a `NativeHybrid` backend that also reranks with a ranker of its own (Azure
    AI Search's semantic ranker); see [Native rerank](#native-rerank-473) below.

### Native rerank (#473)

- `RetrievalModule.build` checks for `NativeRerank` like `NativeHybrid`.
- `HybridPipeline` asks it instead of `hybrid` when the search asks for reranking (the rerank flag,
  `PipelineRequest.rerank`: a reranker is configured for the library).
- An answer it reranked (`reranked` > 0) says so (`reranked: true`), and `RetrievalModes.rerank`
  leaves it as it is.
- One it could not rerank (`reranked` 0) is reranked by ExactDocs' reranker.
- The filters to the version still apply: the backend filters before ranking, and the domain drops
  any other manifest's hit.
- Backends without it keep today's behaviour: ExactDocs' own reranker, or none.

### Wrappers the use cases see

The domain wraps the ports so that the use cases see the ports they always did:

- `ExternalSearchIndex` implements `SearchIndex`: the backend ranks; snippets are cut from the stored
  chunks.
- `ExternalVectorIndex` implements `VectorIndex`: the database's store keeps spaces, coverage and
  vectors, and `nearest` asks the backend. A backend that does not answer is
  `VectorStoreUnavailableError`, so hybrid answers with BM25 and says why.

### Keeping backends in step

`ExternalIndexes` keeps the backends in step:

| Event | What the backends get |
|---|---|
| an **import** | the version, written after its chunks are stored, with the vectors its chunks already have in every space in use[^copied] |
| an **embedding batch** | its vectors, copied to every version holding the chunks *before* the store takes them |
| a **re-tag** | the entries of the articles it changed, rewritten |
| a **removal or collection** | the version deleted from the backends *before* the database deletes its chunks |
| a retired **space** | dropped |

[^copied]: A blob shared with an embedded version is never embedded again, but its vectors are
    copied.

- **Retries.** Each write is tried `EXTERNAL_WRITE_ATTEMPTS` times with doubling waits while the
  backend does not answer, inside the job step that made it. Then `IndexBackendUnavailableError`
  fails that job, never silently.
- **The order above makes the job's own retry write it again:**
    - a failed import leaves the version unpublished (re-running the import writes it);
    - a failed embedding batch leaves its chunks without a stored vector (the next start or import
      queues the version again);
    - a failed removal leaves the chunks for the next collection job.
- **Drift.** `CheckExternalIndexes` compares each backend with the database, version by version,
  and names what is `missing`, `incomplete` or `orphaned` (held after the database removed it).
    - A server runs it at start and every `INDEX_DRIFT_CHECK_SECONDS` (`DriftWatch`) and logs what
      drifted.
    - `/healthz` reports the count (`index_versions_missing`). Drift never fails `/readyz`, so a
      lost version does not take the instance out of rotation.
    - `exactdocs index check` lists them and exits 1.
- **Rebuild.** `RebuildExternalIndexes` (`exactdocs index rebuild [--library] [--version]`) writes
  the versions again from the database, page by page (`ChunkRepository.page`, the store's vectors
  through `StoredVectors`). Without a scope it also deletes the orphans and the retired spaces'
  copies. It is safe while serving and to repeat.

## The backends

| Name | Indexes | Extra | Native hybrid |
|---|---|---|---|
| `memory` | search, vectors | none | yes (RRF of term counts and cosine) |
| `azure_search` | search, vectors | `azure-search` | with `hybrid` (on by default): one Azure hybrid query (RRF);<br/>with `semantic_configuration` also `NativeRerank`[^azure-rerank] |
| `chroma` | vectors | `chroma` (HTTP only),<br/>`chroma-local` (embedded too) | no: ExactDocs fuses BM25 and Chroma's nearest vectors |
| `duckdb` | search, vectors | `duckdb` | no (ExactDocs fuses with RRF) |
| `elasticsearch` | search, vectors | `elasticsearch` | yes: the RRF retriever |
| `lancedb` | search, vectors | `lancedb` | yes: LanceDB's BM25 and exact cosine halves fused by its RRF reranker |
| `libsql` | search, vectors | `libsql` (a local file only) | no (ExactDocs fuses) |
| `milvus` | vectors | `milvus` (server),<br/>`milvus-lite` (Lite too) | yes, unless `hybrid = false`: a BM25 function's sparse vector and the dense vector<br/>in one request, fused by Milvus' RRF ranker |
| `mongodb` | search, vectors | `mongodb` | with `hybrid` (on by default): one `$rankFusion` stage (MongoDB 8.1+),<br/>else `$search` and `$vectorSearch` fused in ExactDocs (RRF) |
| `opensearch` | search, vectors | `opensearch` | yes: a `hybrid` query and a normalisation pipeline |
| `pinecone` | vectors | `pinecone` | with `hybrid = true` on a `dotproduct` index: one sparse-dense query |
| `qdrant` | vectors | `qdrant` | with `hybrid = true`: BM25-weighted sparse and dense prefetches fused by Qdrant (RRF) |
| `redis` | search, vectors | `redis` | with `hybrid = true`: one `FT.HYBRID` query (BM25 and KNN fused by Redis, RRF) |

[^azure-rerank]: A reranked search is that query reranked by Azure's semantic ranker
    (`semanticQuery`), the configuration made over plain-text `title` / `content` fields.

### Adapters

Each adapter is a module in `retrieval/adapters/driven/`.

??? info "`memory`: `memory_index.py`"

    In process, tests only.

??? info "`azure_search`: `azure_search_index.py`"

    - A document per chunk and version, in `<index>` and one `<index>-space<id>` per space, made
      when missing (a schema mismatch is refused, naming the index).
    - The words in three `whitespace`-analysed fields ranked with BM25 and a weighting scoring
      profile; an HNSW cosine vector field of the model's dimensions.
    - `manifest_id` / `library` / `version_id` / `chunk_id` / `tags` filterable (OData, vectors
      pre-filtered).
    - Writes return once the index counts them. API key or Entra ID.
    - No emulator: CI runs it on an in-process fake of the REST API, a manual workflow on a real
      service ([Configuration](../configuration.md#azure-ai-search)).

??? info "`chroma`: `chroma_index.py`"

    - A collection per space (cosine, no embedding function: ExactDocs passes its vectors).
    - Scalar metadata `manifest_id` / `library` / one `tag:<tag>` key per tag, filtered in Chroma
      before ranking.
    - The HTTP client (a server, Chroma Cloud) or the embedded persistent client, synchronous, in
      worker threads ([Configuration](../configuration.md#chroma)).

??? info "`duckdb`: `duckdb_index.py`"

    - One embedded database file (#357).
    - BM25 from the `fts` extension, loaded from the installed `duckdb-extension-fts` wheel, never
      downloaded.
    - Vectors scanned exactly with `array_cosine_distance` (no `vss`: HNSW persistence is still
      experimental).
    - One process per file; a second is refused at open
      ([Configuration](../configuration.md#duckdb)).

??? info "`elasticsearch` and `opensearch`: `elasticsearch_index.py`, `opensearch_index.py` over `elastic_index.py`"

    See [Elasticsearch and OpenSearch](#elasticsearch-and-opensearch) below and
    [Configuration](../configuration.md#elasticsearch-and-opensearch).

??? info "`lancedb`: `lancedb_index.py`"

    - Embedded, a directory or an object-store URI.
    - A table for search and one per space, filtered on `manifest_id` before ranking.
    - Writers on a local directory take turns on a `flock`; an object store needs
      `single_writer = true` ([Configuration](../configuration.md#lancedb)).

??? info "`libsql`: `libsql_index.py`"

    - FTS5 with SQLite's columns and `bm25()` weights.
    - A table per space with an `F32_BLOB` column and a `libsql_vector_idx` index read by
      `vector_top_k`, filtered to the asked versions (an exact scan when they are too small a share
      of the space).
    - A server over its HTTP API, or a local file ([Configuration](../configuration.md#libsql)).

??? info "`milvus`: `milvus_index.py`"

    - A collection per space (cosine, `AUTOINDEX`).
    - Scalar fields `manifest_id` / `library` / `version_id` with inverted indexes and an array of
      tags, filtered in Milvus before ranking.
    - A server or Zilliz Cloud, or Milvus Lite on a local `.db` directory; the synchronous client, in
      worker threads ([Configuration](../configuration.md#milvus)).

??? info "`mongodb`: `mongodb_index.py`"

    - A document per chunk and version, in `<collection>` and one `<collection>.space<id>` per
      space.
    - An Atlas Search index (`$search`, BM25 on three weighted fields) and an Atlas Vector Search
      index (`$vectorSearch`, cosine), made when missing.
    - `manifest_id` / `library` / `version_id` / `chunk_id` / `tags` as `token` and `filter` fields.
    - Writes return once the indexes return them ([Configuration](../configuration.md#mongodb)).

??? info "`pinecone`: `pinecone_index.py`"

    - A serverless index, one namespace per instance.
    - Metadata filters on space, manifest and tags in every query.
    - Vector IDs `<manifest>#<space>#<chunk>`, so a version is deleted by listing its ID prefix
      (serverless indexes cannot delete by filter).
    - The SDK's HTTP client, no gRPC or protobuf ([Configuration](../configuration.md#pinecone)).

??? info "`qdrant`: `qdrant_index.py`"

    A collection per space, payload-indexed `manifest_id` / `library` / `tags`
    ([Configuration](../configuration.md#qdrant)).

??? info "`redis`: `redis_index.py`"

    - Redis 8's Query Engine, a hash per chunk and version.
    - Indexes made with `FT.CREATE` (`<prefix>:search`, `<prefix>:space<id>`).
    - `manifest_id` / `library` / `version_id` / `tags` as `TAG` fields
      ([Configuration](../configuration.md#redis)).

## Adding a backend

1. One adapter module in `retrieval/adapters/driven/` (the reference is `memory_index.py`; it holds
   nothing across a restart and is for tests).
2. Its extra in `packages/exactdocs/pyproject.toml`.
3. One `IndexBackendKind` in `INDEX_BACKENDS` (`bootstrap/constants.py`: name, module, the factory
   function of each index it can hold, the extra and its packages).
4. One `BackendCase` in `tests/fixtures/index_backends.py`.

The shared contract suites then run on it:

- `tests/retrieval/test_search_index.py` and `test_vector_index.py`: the `SearchIndex` and
  `VectorIndex` contracts every database adapter passes, through the domain's wrappers. They cover
  put, delete and collect per version, version and library filters, top-k ordering, empty results
  and unknown versions.
- `test_index_backends.py`: the backend ports themselves, native hybrid and native rerank included
  when implemented.

A factory takes the options of `[index_backends.<name>]`
(`EXACTDOCS_INDEX_BACKENDS__<NAME>__<OPTION>`) and raises `ValueError` for invalid ones. Secrets
come from the environment or `*_file` options.

## Elasticsearch and OpenSearch

Elasticsearch and OpenSearch (#354) answer the same REST API for everything ExactDocs asks, so:

- `elastic_index.py` builds the requests and reads the answers once, behind an `Engine` (one request
  in, its JSON out) that each engine's module implements with its client;
- where the engines differ (the vector field, the kNN query, the hybrid query), the engine's name
  decides;
- it imports neither client.

Options, analysis and sizing: [Configuration](../configuration.md#elasticsearch-and-opensearch).
