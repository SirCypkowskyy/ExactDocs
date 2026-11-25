# MongoDB

!!! abstract "TL;DR"

    - Either index, or both, with Atlas Search and Atlas Vector Search (Atlas, or 8.2+ with `mongot`).
    - Give ExactDocs its own user with `readWrite` on its database.
    - Native hybrid search uses `$rankFusion` on MongoDB 8.1 or later; older servers are fused by ExactDocs.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__MONGODB__<OPTION>`.

MongoDB with Atlas Search and Atlas Vector Search (an Atlas cluster, or MongoDB Community or
Enterprise 8.2+ with `mongot`, the search process) can hold the **search index**, the **vector
index**, or both (`EXACTDOCS_SEARCH_BACKEND=mongodb`, `EXACTDOCS_VECTOR_BACKEND=mongodb`, #363).
Its client is an optional extra, not in the images: `pip install 'exactdocs[mongodb]'` or
`uvx --from 'exactdocs[mongodb]' exactdocs serve` (with `ai` for hosted embedding models:
`exactdocs[ai,mongodb]`). It is tested against the `mongodb/mongodb-atlas-local:9.0.8` image
(MongoDB 9.0.8 with `mongot`; the client is `pymongo` 4.20.0, its async API). Native hybrid
search with one `$rankFusion` stage needs MongoDB 8.1 or later; on an older server ExactDocs
fuses the two searches itself.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "mongodb"
vector_backend = "mongodb"

[index_backends.mongodb]
url = "mongodb+srv://cluster0.example.mongodb.net/?retryWrites=true&w=majority"
username = "exactdocs"
database = "exactdocs"
collection = "chunks"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__MONGODB__PASSWORD=...   # or password_file in the TOML file
# or the whole connection string, password included, in a mounted secret:
#   url_file = "/run/secrets/mongodb-url"   (instead of url, username and password)
```

| Option | Default | Meaning |
|---|---|---|
| `url` | `url` or `url_file` required | The connection string, `mongodb://host[:port][,host...]/?options` or `mongodb+srv://host` (TLS on by default with `+srv`; add `tls=true` otherwise).<br/>It may not hold a password, nor a parameter whose name says password, secret or token |
| `url_file` | unset | A file holding the whole connection string, credentials included (a mounted secret), instead of `url` |
| `username` | unset | The database user, unless the connection string names one |
| `password` | unset | The user's password.<br/>From the environment only (`EXACTDOCS_INDEX_BACKENDS__MONGODB__PASSWORD`); the TOML file refuses it |
| `password_file` | unset | A file holding the password (a mounted secret), instead of `password` |
| `database` | `exactdocs` | The database ExactDocs writes to (letters, digits, `_` and `-`) |
| `collection` | `chunks` | The search index's collection; each embedding space's is `<collection>.space<id>`.<br/>Letters, digits, `_` and `-`.<br/>Give every ExactDocs instance that shares a database its own |
| `timeout` | `10` | Seconds one operation may take (server selection, connecting, and each command: the client's `timeoutMS`) |
| `index_timeout` | `120` | Seconds a write waits for a new search index to be queryable, and for the search indexes to return what it wrote (below); past it the write fails and its job is retried |
| `hybrid` | `true` | Native hybrid search (below). The vector index only; `false` keeps the words out of the spaces' collections |
| `vector_search` | `approximate` | `approximate` (HNSW, `numCandidates` 20 times the hits asked, at least 100) or `exact` (a full scan of the version's vectors: exact, slower on large versions) |

Both backends read the same table, so with both indexes in MongoDB they share the database.

## What ExactDocs creates

Each chunk of each version is one document (`_id` is its manifest
and chunk ID): in `<collection>` for the search index, in `<collection>.space<id>` for an
embedding space. Each carries `manifest_id`, `library`, `version_id`, `chunk_id`, `article_path`
and `tags`, and the words in three fields (`heading`, `path`, `body`: the section's heading, the
headings above it, its text, as every word whole and by its identifier parts, lower case, so
`retryPolicy` is `retrypolicy`, `retry` and `policy`). A space's documents carry the vector as
BSON float32. The first write to a collection creates it, with lookup indexes on `manifest_id`,
and its search indexes when they are missing, then waits until they are queryable:

- `exactdocs_text`, an Atlas Search index: the three word fields (`lucene.whitespace`, no
  stemming, no stop words), ranked with BM25 and weighted in each query as the database's own
  indexes weigh them (heading 20, the headings above 4, text 1), and the five ID fields as
  `token` fields;
- `exactdocs_vectors`, an Atlas Vector Search index on each space's collection: `vector`
  (cosine, the embedding model's dimensions) and the five ID fields as `filter` fields.

Every query filters on the asked versions' `manifest_id` (and the tags) inside MongoDB, before
ranking (`$search`'s `compound.filter`, `$vectorSearch`'s pre-filter), so another version's
chunks are never returned. A new embedding model makes a new space, so a new collection; the
retired space's collection is dropped with its indexes. A collection whose vector index has other
dimensions (another instance's) is never written to: the write fails naming it. A collection or
index dropped behind ExactDocs' back is created again on the next write (`exactdocs index
rebuild` fills it).

## Writes wait for the indexes

`mongot` follows each collection's change stream, so a write is
searchable a moment after MongoDB took it (about 0.3 s on the test image). Every write marks its
documents (`write_id`) and returns only once the search indexes return all of them (a delete:
once they return none), so a version is complete in the indexes when its import or embedding job
says so. On the test image, writing 10,000 chunks into both indexes took about a minute.

## Authentication and TLS

Give ExactDocs its own database user with the `readWrite` role on
its database: it creates its collections and their search indexes, and needs nothing else (the
tests sign in as such a user). Keep the password in the environment or a mounted file, or put
the whole connection string in `url_file`. A password that is refused stops
the start with `authentication failed` and the backend's name; no error or log line carries the
password. `mongodb+srv://` connection strings use TLS; for a `mongodb://` one outside a private
network, add `tls=true` (and `tlsCAFile=...` for a private CA).

## Native hybrid search

With `hybrid` on (the default), each space's documents also carry the
words (the same three fields, and an `exactdocs_text` index on that collection), and a hybrid
search of one version is a single `$rankFusion` stage: a `$search` and a `$vectorSearch`, both
filtered to the version and the tags, 50 deep (or the limit when higher), fused by MongoDB with
reciprocal rank fusion (`k` 60). The start asks the server whether it has `$rankFusion`; on one
without it, the backend runs the two searches itself and fuses them with ExactDocs' own
reciprocal rank fusion (the same weights). With `hybrid = false`, ExactDocs fuses its own search
index (MongoDB's or the database's) with MongoDB's nearest vectors. Turning it on later needs
`exactdocs index rebuild` to write the words of the documents already there (until then they are
found by their vector only). The search across libraries (`search_all_docs`) always fuses in
ExactDocs.

## Sizing

One document per chunk of each version (the same section in two versions is two
documents), so count the chunks of every indexed version. Measured on
`mongodb-atlas-local:9.0.8` (10,000 chunks of about 1,000 characters each, 768-dimension vectors,
`hybrid` on), per million chunks:

| What | Per million chunks |
|---|---|
| Search collection on disk (`collStats` `storageSize`; 2.4 GB uncompressed) | 0.9 GB |
| A space's collection on disk, 768 dimensions, with the words | 4.6 GB |
| `mongot`'s indexes on disk (both word indexes and the HNSW graph) | 5.9 GB |

A vector is 4 bytes per dimension in its document and again in the HNSW graph, which `mongot`
keeps in memory to search fast: give the search nodes (Atlas) or the `mongot` process about
4 bytes per dimension per chunk of memory, plus room for the word indexes (1,536-dimension
vectors, `text-embedding-3-small`: about 6 GB per million chunks for the graph alone). Leave room
for a rebuild, which writes a version's documents again.
