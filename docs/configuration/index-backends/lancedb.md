# LanceDB

!!! abstract "TL;DR"

    - An embedded database in a local directory or object storage, holding either index or both.
    - A local directory is safe with several writers; an object store needs `single_writer = true`.
    - Object-store credentials come from the store's standard environment variables, never the TOML file.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__LANCEDB__<OPTION>`.

[LanceDB](https://lancedb.com) is an embedded vector database: it keeps Lance files in a local
directory or in object storage (S3, GCS, Azure Blob), with no server to run. It can hold the
**search index**, the **vector index**, or both (`EXACTDOCS_SEARCH_BACKEND=lancedb`,
`EXACTDOCS_VECTOR_BACKEND=lancedb`, #356), and serves hybrid search natively. Its client is an
optional extra, not in the images (with `pyarrow` it takes about 350 MB installed):
`pip install 'exactdocs[lancedb]'` or `uvx --from 'exactdocs[lancedb]' exactdocs serve` (with
`ai` for hosted embedding models: `exactdocs[ai,lancedb]`). It is pinned to `lancedb` 0.41.0,
which has wheels for x86_64 and ARM64 Linux and for macOS on Apple silicon. It suits a
single-node ExactDocs that wants its vectors outside SQLite, or kept in object storage.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "lancedb"
vector_backend = "lancedb"

[index_backends.lancedb]
uri = "/var/lib/exactdocs/lancedb"
```

| Option | Default | Meaning |
|---|---|---|
| `uri` | required | An absolute directory (`/var/lib/exactdocs/lancedb`, `file:///...`), created if missing,<br/>or an object-store URI LanceDB takes: `s3://bucket/path`, `gs://bucket/path`, `az://container/path` (without user info or a `?` query: credentials never go in the URI) |
| `table_prefix` | `exactdocs` | The tables' prefix (lower-case letters, digits, `_`): the search index is `<prefix>_chunks`, each embedding space `<prefix>_space_<id>`.<br/>Give every ExactDocs instance that shares a URI its own |
| `storage_options` | none | A table of LanceDB storage options for an object store, such as `region`, `endpoint` (S3-compatible stores like MinIO) or `allow_http`.<br/>Credentials are refused here (below) |
| `single_writer` | `false` | Required (`true`) for an object-store URI: you state that exactly one ExactDocs process writes it (below) |
| `lock_timeout_seconds` | `30` | How long a write waits while another process writes the same directory; then the write fails and its job retries it |
| `read_consistency_seconds` | `0` | How stale a read may be.<br/>`0` looks for other processes' writes (such as `exactdocs index rebuild`) on every search; on an object store a few seconds saves a request per search |

## Object storage and credentials

LanceDB reads an object store's credentials from that store's
standard environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
`AWS_SESSION_TOKEN` (or an instance role), `GOOGLE_APPLICATION_CREDENTIALS` (or workload
identity), `AZURE_STORAGE_ACCOUNT_NAME` and `AZURE_STORAGE_ACCOUNT_KEY`. Set them for the server
process; a `storage_options` entry whose name holds `key`, `secret`, `token`, `password`,
`credential` or `sas` is refused at start, so no credential sits in the TOML file. Errors name the
error type only.

```toml
[index_backends.lancedb]
uri = "s3://docs-bucket/exactdocs"
single_writer = true

[index_backends.lancedb.storage_options]
region = "eu-central-1"
```

## Several processes writing

Two processes upserting into one LanceDB table at the same time
leave duplicate rows (each commit is atomic, but neither sees the rows the other is adding).
ExactDocs therefore never lets them write at once:

- **A local directory is safe with several writers.** Every write takes an exclusive lock on
  `.exactdocs-write.lock` in the directory (`flock`), so the server, its jobs and an
  `exactdocs index rebuild` run alongside it take turns; searches never wait. The lock holds
  between processes of one machine (or containers sharing the volume on one host); do not
  share the directory between machines over NFS or SMB, where the lock is not reliable.
- **An object store is refused unless you declare one writer.** It has no lock ExactDocs can
  take, so a URI like `s3://...` stops the start with a message saying why, until you set
  `single_writer = true`. That states that exactly one ExactDocs process writes the URI: no
  replicas (one server, SQLite or PostgreSQL), and `exactdocs index rebuild` only while that
  server is stopped. Several replicas need a server backend instead.

## What ExactDocs creates

The search table on the first import, and a space's table on the
first vector written to it, each with a bitmap index on `manifest_id` and full-text indexes on
three word columns: the section's heading, its ancestors' headings and its text, split as every
ExactDocs index splits identifiers (`retryPolicy` is `retrypolicy`, `retry` and `policy`). A row
is one chunk of one version: `manifest_id`, `library`, `version_id`, `chunk_id`, `article_path`,
`tags`, the word columns and, in a space's table, the vector (float32, the space's dimensions).
Every search filters on the asked versions' `manifest_id` (and tags) inside LanceDB, before
ranking, so another version's chunks are never returned. A new embedding model makes a new space,
so a new table; the retired space's table is dropped. A space table of other dimensions under
the same prefix (another instance's) is never written to, and the write fails naming it.

## Search and native hybrid search

Keyword search is LanceDB's BM25 over the three columns,
weighted as the database's own index weighs them (heading 20, ancestors 4, text 1). Vector search
is exact: cosine distance over every vector of the asked version, so results do not depend on an
approximate index. A hybrid search asks LanceDB for both halves, the best 50 of each, filtered to
the version, and fuses them with LanceDB's reciprocal rank fusion reranker (`k` 60). The search
across libraries (`search_all_docs`) fuses in ExactDocs. Rows written are searched at once; a
process adds them to the full-text indexes and compacts the table two seconds after its last
write (or every 10,000 rows, and when it stops).

## Sizing

LanceDB holds one row per chunk of each version (the same section in two versions is
two rows), on disk; memory is the operating system's page cache. A vector takes 4 bytes per
dimension (1,536 dimensions: about 6 KB; 100,000 chunks: about 600 MB), and the text columns and
their full-text indexes about twice the chunks' text. Measured on 4 CPU cores with a version of
20,000 chunks at 1,536 dimensions: a vector search about 55 ms (it reads that version's vectors,
about 120 MB, so its time grows with the version's size), a keyword search about 5 ms, a hybrid
search about 60 ms. LanceDB keeps the files of replaced table versions for 7 days before it
deletes them, so right after an import or a rebuild the directory can hold two to three times the
live data (382 MB for that version, both indexes). For versions of several hundred thousand
chunks, or several ExactDocs replicas, prefer a server backend with an approximate index.
