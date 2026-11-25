# libSQL

!!! abstract "TL;DR"

    - Either index, or both, on a libSQL server (`sqld`, Turso) or in a local file.
    - A server needs no extra; a local file needs the `libsql` extra.
    - `compress_neighbors` defaults to `float1bit`: small and fast to write, with no recall loss we could measure.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__LIBSQL__<OPTION>`.

[libSQL](https://github.com/tursodatabase/libsql), the open-source fork of SQLite behind Turso, can
hold the **search index**, the **vector index**, or both (`EXACTDOCS_SEARCH_BACKEND=libsql`,
`EXACTDOCS_VECTOR_BACKEND=libsql`, #358): full-text search with FTS5, as on SQLite, and vectors
in libSQL's native vector type and index (`F32_BLOB`, `libsql_vector_idx`, `vector_top_k`), with
no extension to load. It runs in one of two places, named by `url`:

- **A libSQL server** (`sqld`, self-hosted, or a Turso database): `libsql://`, `https://` or
  `http://`. ExactDocs talks to its HTTP API with its own HTTP client, so nothing more is
  installed: the images can use it as they are. Tested against
  `ghcr.io/tursodatabase/libsql-server:v0.24.33`.
- **A local file**: `file:<path>` (or a path). libSQL then runs inside ExactDocs, through the
  `libsql` package: `pip install 'exactdocs[libsql]'` or
  `uvx --from 'exactdocs[libsql]' exactdocs serve`. It is not in the images. Its latest release
  (0.1.11) has a Python 3.14 wheel for Linux x86_64 only; elsewhere pip builds it from source,
  which needs a Rust toolchain.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "libsql"
vector_backend = "libsql"

[index_backends.libsql]
url = "libsql://exactdocs-acme.turso.io"   # or "http://sqld:8080", or "file:/data/index.db"
prefix = "exactdocs"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__LIBSQL__AUTH_TOKEN=...   # or auth_token_file in the TOML file
```

| Option | Default | Meaning |
|---|---|---|
| `url` | required | `libsql://host[:port]` (HTTPS; add `?tls=0` for plain HTTP), `https://host[:port]`, `http://host[:port]`, or a local file: `file:<path>`, `file://<path>` or a path.<br/>A server URL names the server only: no path, user or password |
| `auth_token` | unset | The server's token (a JWT: a Turso database token, or one signed with the key given to `sqld --auth-jwt-key-file` / `SQLD_AUTH_JWT_KEY`), sent as `Authorization: Bearer`.<br/>From the environment only (`EXACTDOCS_INDEX_BACKENDS__LIBSQL__AUTH_TOKEN`); the TOML file refuses it.<br/>Not for a local file |
| `auth_token_file` | unset | A file holding the token (a mounted secret), instead of `auth_token` |
| `prefix` | `exactdocs` | What every table ExactDocs creates starts with (letters, digits and `_`, at most 40).<br/>Give every ExactDocs instance that shares a libSQL database its own |
| `timeout` | `10` | Seconds one request to a server may take |
| `compress_neighbors` | `float1bit` | How the vector index stores the vectors of a node's neighbours: `float1bit`, `float8`, `float16`, `floatb16` or `float32` (sizing below).<br/>Set when a space's table is created: changing it later needs the space dropped (a new embedding model) or the tables dropped and `exactdocs index rebuild` |
| `max_neighbors` | libSQL's | The most neighbours of a node in the vector index (libSQL's default grows with the square root of the dimensions).<br/>Fewer: a smaller, faster to write, less exact index |

## What ExactDocs creates

For the search index, `<prefix>_search_entries` (one row per chunk of
each version: manifest ID, chunk ID, library, tags) and `<prefix>_search`, its FTS5 table with
the columns, tokenizer (`unicode61 tokenchars '-_.'`) and `bm25()` column weights of ExactDocs'
SQLite index. For the vector index, `<prefix>_spaces` (the embedding spaces and their
dimensions) and, on the first write to a space, `<prefix>_space_<id>`: the chunks of each
version with their vectors in an `F32_BLOB(<dimensions>)` column, and the vector index
`<prefix>_space_<id>_ann` (cosine). A new embedding model makes a new space, so a new table; the
retired space's table is dropped. A space of the same ID with other dimensions (another instance
with the same `prefix`) is never written to: the write fails naming it.

## Searches

Every search names the versions it may look at, in SQL: never a chunk of another
version. Full-text search ranks with FTS5's `bm25()`, as ExactDocs' SQLite index does; its
statistics are over libSQL's entries (one per chunk of each version, where the database holds
one per distinct section), so two hits whose scores are close may come in the other order. A
vector search asks the vector index (`vector_top_k`) for enough neighbours that the asked
versions' share of the space fills the limit (twice that many, at most 2,000), keeps theirs and
orders them by their exact cosine distance; when the versions are too small a share of the space
for that (or a tag filter keeps too few of them), it compares every vector of those versions
instead, which is exact and cheap for a version's few thousand chunks. Hybrid search fuses
libSQL's two halves in ExactDocs (reciprocal rank fusion), as with the database.

## Several processes

A libSQL server is what several ExactDocs processes or hosts share (with
PostgreSQL, or this same libSQL server, as their database): each write is one transaction, which the server runs one after
the other. A local file is for one host: processes there may share it (WAL, and a writer
waits up to 5 seconds for another's lock), but never put it on a network filesystem. Embedded
replicas (a local copy synced from a server) are not used.

## Authentication

Use `https` (or `libsql://`) for anything but a server on loopback or a
private network: the token goes with every request. A missing or refused token stops the start
with `HTTP 401` and the backend's name; no error or log line carries the token.

## Sizing

libSQL holds one row per chunk of each version (the same section in two versions is
two rows), so count the chunks of every indexed version. The search index keeps a copy of each
chunk's text and its FTS5 index, as ExactDocs' SQLite index does. A vector takes 4 bytes per dimension,
but the vector index takes much more: each node keeps its neighbours' vectors, compressed by
`compress_neighbors`. The index only proposes candidates (their exact distances rank them), so
the default, one bit per dimension, costs no recall we could measure and is several times smaller
and faster to write. Measured on a local file (x86_64, libSQL's default `max_neighbors`):

| Dimensions | `compress_neighbors` | Disk per chunk | Write per chunk |
|---|---|---|---|
| 384 | `float1bit` (default) | about 7 KiB | about 2 ms |
| 384 | `float8` | about 28 KiB | about 4 ms |
| 1536 | `float1bit` (default) | about 40 KiB | about 5 ms |
| 1536 | `float8` | about 200 KiB | about 40 ms |
| 1536 | `float32` | about 320 KiB | about 50 ms |

Recall@10 of the index's 20 candidates, ranked by exact distance, was 0.99 to 1.00 with
`float1bit` and `float8` (384 dimensions, 3,000 clustered test vectors; `float1bit` with 1536 too). So 100,000 chunks of a 1536-dimension model take about
4 GB and a rebuild writes them in roughly ten minutes (one writer); with `float8`, five times
that. `max_neighbors` lower than libSQL's default makes the index smaller again (384 dimensions,
`float8`, 32 neighbours: about 18 KiB a chunk). One bit per dimension needs many dimensions to
tell vectors apart: for a model of fewer than about 256, use `float8`.
