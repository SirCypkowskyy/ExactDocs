# Weaviate

!!! abstract "TL;DR"

    - Holds the search index, the vector index or both, self-hosted or Weaviate Cloud.
    - Needs both the REST and the gRPC port; ExactDocs computes every vector (no Weaviate vectorizer).
    - A hybrid search of one version is one Weaviate hybrid query (`alpha`, `fusion`).

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__WEAVIATE__<OPTION>`.

[Weaviate](https://weaviate.io), self-hosted or Weaviate Cloud, can hold the **search index**, the
**vector index**, or both (`EXACTDOCS_SEARCH_BACKEND=weaviate`, `EXACTDOCS_VECTOR_BACKEND=weaviate`,
#359). Its client (`weaviate-client` v4) is an optional extra, not in the images:
`pip install 'exactdocs[weaviate]'` or `uvx --from 'exactdocs[weaviate]' exactdocs serve` (combine
it with `ai` for hosted embedding models: `exactdocs[ai,weaviate]`). It is tested against
`cr.weaviate.io/semitechnologies/weaviate:1.40.7` (the client is `weaviate-client` 4.25.0); the
client needs Weaviate 1.27 or later, and both the REST and the gRPC port.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "weaviate"
vector_backend = "weaviate"

[index_backends.weaviate]
url = "https://weaviate.internal.example.com"
grpc_url = "https://weaviate-grpc.internal.example.com:443"
collection = "ExactDocs"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__WEAVIATE__API_KEY=...   # or api_key_file in the TOML file
```

| Option | Default | Meaning |
|---|---|---|
| `url` | required | The REST endpoint, `http(s)://host[:port]` (port 8080 for `http`, 443 for `https` when none is given) |
| `grpc_url` | the `url` host, port 50051 | The gRPC endpoint, `http(s)://host[:port]` (`https` is TLS). For a Weaviate Cloud `url` (`*.weaviate.cloud`) it defaults to its `grpc-<host>:443` |
| `collection` | `ExactDocs` | The collections' prefix (a letter, then letters, digits and `_`; Weaviate makes the first letter upper case): the search index is `<collection>_search`, each embedding space `<collection>_space<id>`. Give every ExactDocs instance that shares a server its own |
| `api_key` | unset | The API key (a Weaviate Cloud key, or one of a self-hosted server's `AUTHENTICATION_APIKEY_ALLOWED_KEYS`), sent as a bearer token. From the environment only (`EXACTDOCS_INDEX_BACKENDS__WEAVIATE__API_KEY`); the TOML file refuses it |
| `api_key_file` | unset | A file holding the API key (a mounted secret), instead of `api_key` |
| `timeout` | `10` | Seconds one call may take, the client's own retries included; then the call fails as the backend being unavailable |
| `alpha` | `0.5` | Native hybrid: how much the vector counts against the words (0: BM25 alone, 1: the vector alone) |
| `fusion` | `relative_score` | Native hybrid: how Weaviate fuses the two rankings, `relative_score` or `ranked` (reciprocal ranks) |

## What ExactDocs creates

On the first write to an index, its collection, when it is missing (and
again on a later write, should it have been dropped): a self-provided named vector `default` (no
vectorizer: ExactDocs computes every vector, with the embedding model you configured; the search
collection's is a flat index left empty, a space's an HNSW index with cosine distance), no
stop words, and the properties `manifest_id`, `library`, `version_id`, `chunk_id`, `article_path`,
`tags` (filterable, whole values) and `heading`, `path`, `body` (the section's heading, its
ancestor headings and its text, split as every ExactDocs index splits identifiers, BM25-searchable,
boosted 20, 4 and 1). Each object is one chunk of one version; every query filters on the asked
versions' `manifest_id` (and the tags) in Weaviate, before ranking, so another version's chunks are
never returned. A new embedding model makes a new space, so a new collection; the retired space's
collection is dropped.

## No model provider

ExactDocs never asks Weaviate to vectorize, and its collections name no
vectorizer, reranker or generative module. Run the server without them, so that no module can call
a provider even when someone else creates a collection: `DEFAULT_VECTORIZER_MODULE=none`,
`API_BASED_MODULES_DISABLED=true` (Weaviate otherwise enables its API-based modules by default) and
no `ENABLE_MODULES`. `AUTOSCHEMA_ENABLED=false` keeps a write from making a collection with
Weaviate's own types. Connecting never asks pypi.org for the latest client, as the client otherwise
does: ExactDocs talks to your server only.

```bash
docker run -d -p 8080:8080 -p 50051:50051 \
  -e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=false -e AUTHENTICATION_APIKEY_ENABLED=true \
  -e AUTHENTICATION_APIKEY_ALLOWED_KEYS=change-me -e AUTHENTICATION_APIKEY_USERS=exactdocs \
  -e DEFAULT_VECTORIZER_MODULE=none -e API_BASED_MODULES_DISABLED=true \
  -e AUTOSCHEMA_ENABLED=false -e PERSISTENCE_DATA_PATH=/var/lib/weaviate \
  -v weaviate-data:/var/lib/weaviate cr.weaviate.io/semitechnologies/weaviate:1.40.7
```

## Authentication and proxies

Use `https` (and a TLS `grpc_url`) for anything but a server on loopback: the
key goes with every request. A key that is missing or refused stops the start with `HTTP 401` and
the backend's name; a gRPC port that does not answer, with "its gRPC API does not answer (check
grpc_url)". No error or log line carries the key.

REST and gRPC go through the outbound proxy unless `NO_PROXY` lists their host
([Corporate proxy](../../deployment/corporate-proxy.md)). The CA bundle is trusted by the gRPC
channel only: the client's REST transport keeps certifi's bundle and takes no other.

## Native hybrid search

With Weaviate as the vector backend, a hybrid search of one version is a
single Weaviate hybrid query: BM25 over the version's `heading`, `path` and `body` and the nearest
vectors, both filtered to the version, fused by Weaviate (`fusion`, weighted by `alpha`). The
objects of a space carry the chunk's words for that, whichever backend holds the search index. The
search across libraries (`search_all_docs`) always fuses in ExactDocs.

## Scores

Weaviate's BM25 statistics still count deleted objects until it compacts its segments,
so after a removal or a rebuild that writes a version again, the same search ranks the same chunks
with scores a few percent apart. The hits and their order are what to compare.

## Sizing

Weaviate holds one object per chunk of each version (the same section in two versions
is two objects), in the search collection and again in each space's collection, so count the
chunks of every indexed version. A space's HNSW index keeps each vector in memory: 4 bytes per
dimension (1536 dimensions: about 6 KB; 100,000 chunks: about 600 MB), plus the graph (roughly
10 to 20 % more, `maxConnections` 32). Each object adds its words (about the chunk's text again,
pre-split) and the inverted index of them on disk, and a few hundred bytes of properties. Filtered
searches over fewer objects than Weaviate's `flatSearchCutoff` (40,000) are exact. Weaviate's own
quantization (PQ, BQ, SQ) and compression settings can be set on the collections it created;
ExactDocs leaves them alone.
