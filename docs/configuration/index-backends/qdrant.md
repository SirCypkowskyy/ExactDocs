# Qdrant

!!! abstract "TL;DR"

    - Holds the vector index, self-hosted or Qdrant Cloud.
    - `hybrid = true` lets Qdrant rank words and vector in one query.
    - `on_disk` and `quantization` trade RAM for speed.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__QDRANT__<OPTION>`.

[Qdrant](https://qdrant.tech), self-hosted or Qdrant Cloud, can hold the **vector index**
(`EXACTDOCS_VECTOR_BACKEND=qdrant`, #355). Its client is an optional extra, not in the images:
`pip install 'exactdocs[qdrant]'` or `uvx --from 'exactdocs[qdrant]' exactdocs serve` (combine it
with `ai` for hosted embedding models: `exactdocs[ai,qdrant]`). It is tested against
`qdrant/qdrant:v1.20.0` (the client is `qdrant-client` 1.20.0); use a server of the same minor
version or the one next to it.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
vector_backend = "qdrant"

[index_backends.qdrant]
url = "https://xyz-example.eu-central.aws.cloud.qdrant.io:6333"
collection = "exactdocs"
hybrid = true
```

```bash
export EXACTDOCS_INDEX_BACKENDS__QDRANT__API_KEY=...   # or api_key_file in the TOML file
```

| Option | Default | Meaning |
|---|---|---|
| `url` | required | The server's REST endpoint, `http(s)://host[:port]` (port 6333 when none is given) |
| `collection` | `exactdocs` | The collections' prefix: each embedding space is the collection `<collection>_space<id>`.<br/>Give every ExactDocs instance that shares a server its own |
| `api_key` | unset | The API key (a Qdrant Cloud database key, or a self-hosted server's `service.api_key`), sent as the `api-key` header.<br/>From the environment only (`EXACTDOCS_INDEX_BACKENDS__QDRANT__API_KEY`); the TOML file refuses it |
| `api_key_file` | unset | A file holding the API key (a mounted secret), instead of `api_key` |
| `timeout` | `10` | Seconds one request may take |
| `hybrid` | `false` | Native hybrid search: Qdrant ranks the words and the vector in one query (below) |
| `on_disk` | `false` | Keep the vectors memory-mapped from disk instead of in RAM |
| `quantization` | `none` | `scalar`: also keep an int8 copy of each vector in RAM, 4 times smaller, which searches use first |

## What ExactDocs creates

On the first write to an embedding space, the collection
`<collection>_space<id>`: a dense vector `dense` with the embedding model's dimensions and cosine
distance, a sparse vector `words` (with Qdrant's IDF modifier), and keyword payload indexes on
`manifest_id` (as the tenant key), `library` and `tags`. A collection dropped behind ExactDocs'
back is created again on the next write, and missing payload indexes on the first write after a
start; a collection of the same name with vectors of other dimensions (another
instance's) is never written to, and the write fails naming it. Each point is one chunk of one
version, with the payload `manifest_id`, `library`, `version_id`, `chunk_id`, `article_path`,
`heading_path` and `tags`; every search filters on the asked versions' `manifest_id` (and tags) in
Qdrant, before ranking, so another version's chunks are never returned. A new embedding model
makes a new space, so a new collection; the retired space's collection is dropped.

## Authentication

Use `https` for anything but a server on loopback: the key is sent with every
request (the client warns about a key over `http`). A key that is missing or refused stops the
start with `HTTP 401` or `403` and the backend's name; no error or log line carries the key.

## Native hybrid search

With `hybrid = true`, each point also carries its words as a sparse
vector: BM25 term weights (`k1` 1.2, `b` 0.75, headings counting 3 times), split as every ExactDocs
index splits identifiers (`retryPolicy` is `retrypolicy`, `retry` and `policy`), with the IDF that
Qdrant computes over the collection. A hybrid search of one version is then a single Qdrant query
whose two prefetches (words and vector, both filtered to the version) are fused with reciprocal
rank fusion (`k` 60). Off, ExactDocs fuses its own BM25 index with Qdrant's nearest vectors, as
with the database. Turning it on later needs `exactdocs index rebuild` to write the words of the
points already there (until then they are found by their vector only). The search across
libraries (`search_all_docs`) always fuses in ExactDocs.

## Sizing

Qdrant holds one point per chunk of each version (the same section in two versions is
two points), so count the chunks of every indexed version. In RAM, each point's vector takes
4 bytes per dimension (1536 dimensions: about 6 KB; 100,000 chunks: about 600 MB), plus the HNSW
graph (roughly 10 to 20 % more) and a few hundred bytes of payload. `quantization = "scalar"`
adds a quarter of that in RAM and, with `on_disk = true`, leaves the full vectors on disk. With
`hybrid`, the sparse vectors add about 8 bytes per distinct word of a chunk.
