# Redis

!!! abstract "TL;DR"

    - Either index, or both, with Redis 8's Query Engine; native hybrid needs Redis 8.4 or later.
    - One server or a primary with replicas: not a Redis Cluster.
    - Everything is in memory: about 27 GB per million chunks with both indexes, 1,536 dimensions and `hybrid`.
    - Set `maxmemory` with `noeviction`.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__REDIS__<OPTION>`.

[Redis](https://redis.io) 8 or later, whose Query Engine (formerly RediSearch) indexes text and
vectors in memory, can hold the **search index**, the **vector index**, or both
(`EXACTDOCS_SEARCH_BACKEND=redis`, `EXACTDOCS_VECTOR_BACKEND=redis`, #364). Its client is an
optional extra, not in the images: `pip install 'exactdocs[redis]'` or
`uvx --from 'exactdocs[redis]' exactdocs serve` (with `ai` for hosted embedding models:
`exactdocs[ai,redis]`). It is tested against the official `redis:8.10.3` image (the client is
`redis` 8.1.0, redis-py). Redis Stack 7.4 and managed Redis with the Query Engine work the same
way; native hybrid search needs Redis 8.4 or later. One Redis server (or a primary with
replicas): the community Query Engine does not search across the shards of a Redis Cluster.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "redis"
vector_backend = "redis"

[index_backends.redis]
url = "rediss://redis.internal:6380"
prefix = "exactdocs"
username = "exactdocs"
tls_ca_file = "/run/secrets/redis-ca.pem"
hybrid = true
```

```bash
export EXACTDOCS_INDEX_BACKENDS__REDIS__PASSWORD=...   # or password_file in the TOML file
```

| Option | Default | Meaning |
|---|---|---|
| `url` | required | The server, `redis://host[:port]`, or `rediss://` for TLS (port 6379 when none is given).<br/>It may not hold a user or password, nor a database other than 0 (the Query Engine indexes database 0 only) |
| `prefix` | `exactdocs` | Names the indexes and keys: the search index is `<prefix>:search`, each embedding space's `<prefix>:space<id>`, each over the hashes whose keys start with its name.<br/>Letters, digits, `_` and `-`.<br/>Give every ExactDocs instance that shares a server its own |
| `username` | unset | The ACL user (Redis 6 or later); unset, the `default` user |
| `password` | unset | The user's password, sent with `AUTH`.<br/>From the environment only (`EXACTDOCS_INDEX_BACKENDS__REDIS__PASSWORD`); the TOML file refuses it |
| `password_file` | unset | A file holding the password (a mounted secret), instead of `password` |
| `tls_ca_file` | unset | With `rediss://`: the CA certificate the server's certificate is checked against (unset: the system's trusted CAs).<br/>The certificate and the host name are always checked |
| `tls_cert_file`, `tls_key_file` | unset | With `rediss://`: a client certificate and its key, for a server that asks for one (`tls-auth-clients yes`) |
| `timeout` | `10` | Seconds one command may take, also each query's `TIMEOUT` (a query that runs out fails instead of answering with part of its results) |
| `hybrid` | `false` | Native hybrid search: Redis ranks the words and the vector in one `FT.HYBRID` query (below).<br/>The vector index only |
| `vector_algorithm` | `hnsw` | `hnsw` (approximate, fast on large versions) or `flat` (exact, brute force) |

Both backends read the same table, so with both indexes in Redis they share the server and the
prefix.

## What ExactDocs creates

Each chunk of each version is one hash: `<prefix>:search:<manifest>:<chunk>`
in the search index, `<prefix>:space<id>:<manifest>:<chunk>` in a space's. The first write
creates the index with `FT.CREATE` when it is missing: `manifest_id`, `library`, `version_id`,
`chunk_id` and `tags` as `TAG` fields (case-sensitive), the words in three `TEXT` fields weighted
as the database's own indexes weigh them (the section's heading 20, the headings above it 4, its
text 1; no stemming, no stop words, every word whole and by its identifier parts, so
`retryPolicy` is `retrypolicy`, `retry` and `policy`), ranked with BM25 (`BM25STD`). A space's
index adds a `VECTOR` field (`FLOAT32`, cosine) whose dimensions are the embedding model's; a new
model makes a new space, so a new index, and the retired space's index is dropped with its
hashes (`FT.DROPINDEX ... DD`). Every query filters on the asked versions' `manifest_id` (and the
tags) inside Redis, before ranking, so another version's chunks are never returned. An index
dropped behind ExactDocs' back is created again on the next write (`exactdocs index rebuild`
fills it); an index of the same name whose vectors have other dimensions (another instance's) is
never written to, and the write fails naming it. Deleting a chunk or a version leaves its terms
in the index's statistics until the Query Engine's garbage collector cleans them (after
`search-fork-gc-clean-threshold` deletions, 100 by default), so BM25 scores can shift a little
after a rebuild; the order of the hits holds.

## Authentication and TLS

Give ExactDocs its own ACL user, limited to its keys (the rights
below are what it needs, and what the tests sign in with):

```text
ACL SETUSER exactdocs on >PASSWORD ~exactdocs:* +@read +@write +@search +@transaction +ping +info
```

Keep the password in the environment or a mounted file. A password that is refused stops the start with
`authentication failed` and the backend's name; no error or log line carries the password. Use
`rediss://` for anything but a server on loopback or a private network you trust: the password
and every chunk travel in the clear otherwise.

## Native hybrid search

With `hybrid = true`, each hash of a space also carries the chunk's
words (the same three `TEXT` fields), and a hybrid search of one version is a single `FT.HYBRID`
query: a BM25 search and a KNN search (`K` 50), both filtered to the version and the tags,
fused by Redis with reciprocal rank fusion (`k` 60). The start checks the server has `FT.HYBRID`
(Redis 8.4 or later). Off, ExactDocs fuses its own search index (Redis' or the database's) with
Redis' nearest vectors itself. Turning it on later needs `exactdocs index rebuild` to write the
words of the hashes already there (until then they are found by their vector only). The search
across libraries (`search_all_docs`) always fuses in ExactDocs.

## Sizing

Redis holds everything in memory: one hash per chunk of each version (the same
section in two versions is two hashes), so count the chunks of every indexed version. Measured
on `redis:8.10.3` (`used_memory`, 20,000 chunks of about 1,000 characters of text each),
per million chunks:

| Index | Memory per million chunks |
|---|---|
| Search (`<prefix>:search`) | 5.6 GB |
| Vectors, 384 dimensions | 5.0 GB |
| Vectors, 768 dimensions | 8.6 GB |
| Vectors, 1,536 dimensions (`text-embedding-3-small`) | 15.9 GB |
| Vectors with `hybrid = true` | add 5 GB (the words) |

A vector takes 4 bytes per dimension twice (in its hash and in the index), plus about 2 KB for
the HNSW graph, the tags and the key; the words take about 5 times the chunk's text (the hash
holds the tokens, the index their postings, without positions), so longer chunks cost more. Both
indexes in Redis with 1,536-dimension vectors and `hybrid = true`: about 27 GB per million chunks. Leave room for Redis' own overhead and for a rebuild,
which writes a version's hashes again before the old ones are collected; set `maxmemory` with
the `noeviction` policy, so a full server refuses writes (the job fails and is retried) instead
of evicting entries without saying so.
