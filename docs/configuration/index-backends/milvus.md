# Milvus

!!! abstract "TL;DR"

    - Holds the vector index on a Milvus server, Zilliz Cloud or Milvus Lite.
    - Native hybrid search is on by default; Milvus fuses BM25 and the vectors.
    - Milvus Lite locks its directory: one process only.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__MILVUS__<OPTION>`.

[Milvus](https://milvus.io), as a server, as Zilliz Cloud (its managed service) or as Milvus Lite
in a local directory, can hold the **vector index** (`EXACTDOCS_VECTOR_BACKEND=milvus`, #360), and
answer hybrid searches itself. Its client is an optional extra, not in the images:

- `exactdocs[milvus]`: `pymilvus`, for a Milvus server or Zilliz Cloud (`uri = "http(s)://..."`).
- `exactdocs[milvus-lite]`: `pymilvus` and `milvus-lite`, which adds Milvus Lite, the embedded
  engine, on a local `.db` directory (`uri = "/path/name.db"`). It is pure Python on `faiss-cpu`
  and `pyarrow`, with wheels for Linux x86_64 and ARM64 and macOS.

`pip install 'exactdocs[milvus]'` or `uvx --from 'exactdocs[milvus]' exactdocs serve` (combine it
with `ai` for hosted embedding models: `exactdocs[ai,milvus]`). It is tested against the
`milvusdb/milvus:v3.0.5` standalone server (pymilvus 3.0.2) and Milvus Lite 3.2.2; use a Milvus
3.0 server.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE): a server, or Zilliz Cloud
vector_backend = "milvus"

[index_backends.milvus]
uri = "http://milvus.internal:19530"   # or https://in03-....zillizcloud.com
collection = "exactdocs"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__MILVUS__TOKEN=root:Milvus   # or token_file in the TOML file
```

```toml
# Milvus Lite: one directory, read and written by this ExactDocs process only
vector_backend = "milvus"

[index_backends.milvus]
uri = "/var/lib/exactdocs/milvus.db"
```

| Option | Default | Meaning |
|---|---|---|
| `uri` | required | A Milvus server or Zilliz Cloud (`http://host:19530`, `https://...`),<br/>or a Milvus Lite directory: a path ending in `.db` (made absolute; its parent is created when missing; needs `exactdocs[milvus-lite]`) |
| `collection` | `exactdocs` | The collections' prefix: each embedding space is the collection `<collection>_space<id>`.<br/>Give every ExactDocs instance that shares a Milvus database its own |
| `db_name` | the default database | The Milvus database the collections are in |
| `token` | unset | A server's `user:password` or a Zilliz Cloud API key.<br/>From the environment only (`EXACTDOCS_INDEX_BACKENDS__MILVUS__TOKEN`); the TOML file refuses it.<br/>Milvus Lite takes none |
| `token_file` | unset | A file holding the token (a mounted secret), instead of `token` |
| `hybrid` | `true` | Native hybrid search: Milvus keeps each chunk's words for BM25 and fuses BM25 and the vectors itself (RRF).<br/>`false` keeps vectors only, and ExactDocs fuses its own BM25 index with Milvus' nearest vectors |
| `consistency_level` | `Strong` | The consistency new collections get: `Strong` (a search sees every earlier write), `Bounded`, `Session` or `Eventually` (faster searches; a version just written may be missed for a moment) |
| `timeout` | `30` | Seconds one call to Milvus may take |

## What ExactDocs creates

On the first write to an embedding space, the collection
`<collection>_space<id>`, with the space's dimensions and cosine similarity (`AUTOINDEX`: Milvus
picks the index). Each row is one chunk of one version, keyed by a hash of the manifest and chunk
IDs, with the fields `manifest_id`, `library`, `version_id` (each with a scalar `INVERTED`
index), `chunk_id`, `article_path` and `tags` (an `INVERTED` index too on a server; Milvus Lite
has no array index); every search filters on the asked versions' `manifest_id` (and tags) in
Milvus, before ranking, so another version's chunks are never returned. With `hybrid`, a row also
keeps its headings and text as words in an analyzed `text` field (standard tokenizer, lower case;
cut at a word past 64 KB), which a BM25 function turns into the sparse vector `sparse`; a hybrid
search is one request, a BM25 half and a dense half, both filtered to the version, fused by
Milvus' RRF ranker (k = 60, as ExactDocs' own fusion). Collections are made once: with
`hybrid` switched on for collections made without it, hybrid searches answer with BM25 alone
(`vector_store_unavailable`); drop the collections and run `exactdocs index rebuild`. A new embedding model makes a new space,
so a new collection; the retired space's collection is dropped.

## Authentication

A Milvus server with authentication on takes `user:password` as `token`
(`root:Milvus` until you change it), Zilliz Cloud its API key. Use `https` for anything but
loopback or a private network. A server that cannot be reached, or refuses the token, stops the
start with the backend's name and Milvus' error code; no error or log line carries the token.

## Milvus Lite

The engine runs inside the ExactDocs process, which locks the directory: another
process cannot open it ("Open local milvus failed"). `exactdocs index check` and
`exactdocs index rebuild` open it too, so run them while the server is stopped (or use a Milvus
server). Several ExactDocs server processes (PostgreSQL with replicas) need a Milvus server.

## Sizing

Milvus holds one row per chunk of each version (the same section in two versions is
two rows), so count the chunks of every indexed version. A loaded collection keeps its vectors in
memory: 4 bytes per dimension per row (1536 dimensions: about 6 KB; 100,000 chunks: about 600 MB),
plus the index (roughly 10 to 20 % more for HNSW). `hybrid` adds the chunk's words (about the
size of its text) and the BM25 sparse index (a few hundred bytes per chunk); `hybrid = false`
saves both. The drift check (at start and every 5 minutes) is one grouped count per collection on
a server; Milvus Lite reads the rows' version keys a thousand at a time.
