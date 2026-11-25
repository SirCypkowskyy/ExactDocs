# DuckDB

!!! abstract "TL;DR"

    - Keeps the search index, the vector index or both in one embedded file you can query yourself.
    - Needs no credentials and makes no outbound request.
    - Only one process may open the file: stop the server before `exactdocs index check` or `rebuild`.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__DUCKDB__<OPTION>`.

`duckdb` keeps the search index, the vector index or both in one embedded DuckDB database file
(#357): no server, and a file you can query yourself for analytics or your own retrieval.
Install the extra (`pip install 'exactdocs[duckdb]'`, or `uvx --from 'exactdocs[duckdb]'
exactdocs serve`); the published Docker images do not include it.

```toml
search_backend = "duckdb"
vector_backend = "duckdb"

[index_backends.duckdb]
path = "/data/index.duckdb"
```

| Option | Default | What it does |
|---|---|---|
| `path` | required | The database file.<br/>Its folder must exist; the file is made at the first start.<br/>Both indexes may share it (one process opens it once) |
| `threads` | every CPU | Threads DuckDB uses for a query or an index build |
| `memory_limit` | DuckDB's (80% of RAM) | DuckDB's memory limit, e.g. `2GB` |

- **No credentials.** The file holds the text of every imported version, private libraries'
  included: protect it as the database (file permissions, the same volume and backups). It
  holds derived data only, so a lost file is written again by `exactdocs index rebuild`.
- **Offline.** The full-text search extension (`fts`) is installed with the extra, from the
  `duckdb-extension-fts` wheel (DuckDB's signed binary, pinned to the same DuckDB release as
  `duckdb`), and loaded from that file; DuckDB checks its signature, and extension auto-install
  and auto-load are off. ExactDocs makes no outbound request for DuckDB, at start or later.
- **One process.** DuckDB lets one process write a file, and no other process may open it,
  even to read, while ExactDocs has it open. A second process is refused at start, naming the
  process holding it: run one server process on the file (`WEB_CONCURRENCY=1` on PostgreSQL;
  SQLite always runs one), and stop the server before `exactdocs index check` or
  `exactdocs index rebuild`. To query the file yourself, stop ExactDocs or query a copy made
  while it was stopped.
- **Tables.** `exactdocs_search` has one row per chunk of each version: `library`,
  `version_id` (`/owner/repo/<ref>`), `manifest_id`, `chunk_id`, `article_path`,
  `heading_path`, `content`, `tags`, and the tokens the full-text index reads (`fts_*`). Each
  embedding space has `exactdocs_vectors_<space id>` with the same columns but the text, and
  `vector FLOAT[<dimensions>]`. `fts_main_exactdocs_search` is the `fts` extension's index.
- **Search.** BM25 from the `fts` extension, with the heading, ancestor headings, text and
  identifier columns weighted as the database's own index weighs them. The `fts` index does not
  follow writes: a write marks it stale and the first search after it rebuilds it whole, which
  takes about 7 s per 100,000 chunks on 2 threads (0.7 s per 10,000); searches then take tens of
  milliseconds. After an import, the first search waits for that rebuild.
- **Vectors.** An exact scan with DuckDB's `array_cosine_distance`, limited to the searched
  versions: about 0.15 s for 20,000 chunks of 1,536 dimensions on 2 threads, growing with the
  chunks of the searched versions; a vector takes 4 bytes per dimension. The `vss` extension's
  HNSW index is not used: in DuckDB 2.0 keeping it in a database file is still experimental
  (`hnsw_enable_experimental_persistence`; DuckDB warns that a crash can lose or corrupt it). Hybrid search
  fuses BM25 and the vectors in ExactDocs (reciprocal rank fusion), as with the database.
