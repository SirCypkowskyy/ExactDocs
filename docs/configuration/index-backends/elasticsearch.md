# Elasticsearch and OpenSearch

!!! abstract "TL;DR"

    - Either index, or both, in an Elasticsearch 8.x/9.x or OpenSearch 2.x/3.x cluster.
    - Sign in with an API key, a token, or a user and password; secrets come from the environment or a `*_file` option.
    - Native hybrid search needs Elasticsearch's RRF (Enterprise or trial) or OpenSearch's neural-search plugin; otherwise ExactDocs fuses.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__ELASTICSEARCH__<OPTION>`.

`EXACTDOCS_SEARCH_BACKEND=elasticsearch` (or `opensearch`) puts the full-text index in that
cluster, `EXACTDOCS_VECTOR_BACKEND=elasticsearch` (or `opensearch`) the vector index; either or
both. Install the client with the extra: `pip install 'exactdocs[elasticsearch]'` or
`'exactdocs[opensearch]'` (`uvx --from 'exactdocs[elasticsearch]' exactdocs serve`); the Docker
images do not include them. Elasticsearch 8.x and 9.x and OpenSearch 2.x and 3.x (Amazon
OpenSearch Service included) are supported; CI runs Elasticsearch 9.5 and OpenSearch 3.8. A
release without the native hybrid query gets hybrid search fused by ExactDocs (see below).

```toml
[index_backends.elasticsearch]   # or [index_backends.opensearch]
url = "https://search.internal:9200"   # several nodes: comma-separated
index_prefix = "exactdocs"
username = "exactdocs"
ca_certs = "/etc/exactdocs/search-ca.pem"
# the password comes from EXACTDOCS_INDEX_BACKENDS__ELASTICSEARCH__PASSWORD or password_file
```

| Option | Default | What it does |
|---|---|---|
| `url` | required | The cluster's URL (`http://` or `https://`); several nodes separated by commas |
| `index_prefix` | `exactdocs` | ExactDocs creates `<prefix>-search` and one `<prefix>-vectors-<space>` index per embedding space (and, on OpenSearch, the search pipeline `<prefix>-hybrid`).<br/>Lower case, digits, `_` and `-`.<br/>Instances sharing a cluster need different prefixes |
| `api_key` / `api_key_file` | unset | Elasticsearch only: an API key (the encoded value, or `id:key`) |
| `username`, `password` / `password_file` | unset | Basic auth (OpenSearch's internal users and Amazon OpenSearch Service's fine-grained access control too) |
| `token` / `token_file` | unset | A bearer token (an Elasticsearch service token, an OpenSearch JWT) |
| `ca_certs` | system CAs | A PEM file of the certificate authorities the cluster's TLS certificate is checked against |
| `verify_certs` | `true` | `false` skips the certificate check (never in production) |
| `request_timeout` | `30` | Seconds before a request gives up |
| `number_of_shards`, `number_of_replicas` | `1`, the cluster's | Of each index ExactDocs creates |
| `num_candidates` | `100` | The fewest HNSW candidates a kNN search considers (at least the `k` asked); more is slower and closer to an exact search.<br/>At most 10,000 |
| `refresh` | `wait_for` | A write returns once it is searchable; `true` refreshes at once (more segments; for tests and small instances) |

Sign in one way: an API key, a token, or a user and password. Secrets come from the environment
or a `*_file` option (Docker and Kubernetes secrets); the TOML file refuses them. The user needs
the index privileges `create_index`, `write`, `read`, `delete` and `view_index_metadata` on
`<prefix>-*` (Elasticsearch's `manage` on those indexes covers them), and, on OpenSearch, the
cluster permission to put the search pipeline (`cluster:admin/search/pipeline/put`); without it
hybrid search is fused by ExactDocs instead, as said below.

## Mappings and analysis

ExactDocs creates its indexes when they are missing, with strict
mappings: `manifest_id`, `library`, `version_id`, `chunk_id` and `tags` are `keyword` fields, and
every search filters by version inside the cluster, so another version's chunk never comes back.
The heading, path and text fields use an analyzer that keeps identifiers whole (`retry_policy`,
`v1.4.0`, `client.retry.timeout`, `--dry-run`), lower-cased and ASCII-folded; an `identifiers`
field holds their parts too (`retryPolicy` is also `retry` and `policy`), so `snake_case`,
`camelCase` and dotted names are found whole and by their parts, with the same field weights as
the database's own indexes; each word of a query counts once, in the field it scores best in, so
a section ranks as it does on the database. Vectors are `dense_vector` (Elasticsearch) or `knn_vector` with the
Lucene engine (OpenSearch) fields, cosine similarity, HNSW without quantisation.

## Native hybrid search

With the vector index in the cluster, hybrid search asks the cluster
once: Elasticsearch fuses BM25 and kNN with its RRF retriever, OpenSearch with a `hybrid` query
and a normalisation search pipeline (min-max, arithmetic mean, equal weights). Elasticsearch's
RRF needs an Enterprise (or trial) licence and OpenSearch's hybrid query the neural-search plugin
(in the default distribution); a cluster that refuses it gets the two halves asked separately and
fused by ExactDocs (reciprocal rank fusion, as with the database), and the server logs that once.

## Sizing

Each version is held apart (one document per chunk and version), so the indexes grow
with the versions you keep, not only with distinct content. A vector index needs about
`4 × dimensions` bytes per chunk for the vectors plus the HNSW graph (roughly another 10%), and
searches are fast while that fits in the nodes' memory outside the JVM heap (the page cache):
50,000 chunks of 1,024 dimensions are about 220 MB. One primary shard suffices for most
instances; give the JVM half the node's memory at most, as both engines advise (CI runs each
engine as a single node with a 512 MB heap).
