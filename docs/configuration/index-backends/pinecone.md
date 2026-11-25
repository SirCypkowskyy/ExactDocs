# Pinecone

!!! abstract "TL;DR"

    - Vectors only, in a serverless dense index (`cosine`, or `dotproduct` for `hybrid`).
    - Give each instance its own `namespace` to share an index.
    - The drift check lists IDs: about one read request per 100 vectors each time.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__PINECONE__<OPTION>`.

Vectors only (`EXACTDOCS_VECTOR_BACKEND=pinecone`), extra `pinecone` (#362). Full-text search
stays in the database, or in another backend.

```toml
[index_backends.pinecone]
host = "https://docs-abc1234.svc.aped-4627-b74a.pinecone.io"  # or: index = "docs"
namespace = "exactdocs-prod"
hybrid = true
```

```bash
EXACTDOCS_VECTOR_BACKEND=pinecone
EXACTDOCS_INDEX_BACKENDS__PINECONE__API_KEY=pcsk_...   # or ..._API_KEY_FILE=/run/secrets/pinecone
```

| Option | Default | What it does |
|---|---|---|
| `host` | | The index's host, as the Pinecone console shows it. Set it or `index` |
| `index` | | The index's name instead; the host is looked up once at start |
| `api_key` / `api_key_file` | | The API key, from the environment or a file (Docker or Kubernetes secrets); the TOML file refuses `api_key`.<br/>It is sent to Pinecone only, never logged |
| `namespace` | `exactdocs` | The namespace this instance keeps its vectors in.<br/>Give each instance its own and they can share one index without mixing data |
| `hybrid` | `false` | Also store a sparse vector of each chunk's words, so `hybrid` searches are one sparse-dense query in Pinecone instead of ExactDocs fusing BM25 and the vectors.<br/>Needs a `dotproduct` index |
| `hybrid_alpha` | `0.5` | The vector half's weight in a hybrid query, 0 to 1 (the words get the rest) |
| `timeout` | `30` | Seconds one request may take |

## The index

Create a serverless dense index (Pinecone's `list` and delete-by-ID are what the
adapter uses; pod indexes cannot list IDs) with the `cosine` or `dotproduct` metric
(`dotproduct` for `hybrid`), and a dimension at least the embedding model's. A model with fewer
dimensions is padded with zeros, which leaves cosine unchanged, so a model change to a smaller
one needs no new index; a larger one does (the embedding job fails, naming the dimensions). The
start fails, naming the backend, when the index cannot be reached, the key is refused, or its
metric does not fit.

## What is stored

One vector per chunk of each version and embedding space, with the
version's manifest ID, its library, the space and the article's tags as metadata (no text). A
vector's ID is `<manifest>#<space>#<chunk>`: a version is deleted by listing its ID prefix,
since serverless indexes do not delete by metadata filter. Every query filters on the space and
the versions searched, so nothing of another version is returned.

## Sizing and cost

Storage is one vector per chunk per version (a blob shared by two versions
is two vectors), at the index's dimension, plus a few dozen bytes of metadata; with `hybrid`, a
sparse vector of up to 1000 terms too. A query reads the namespace, filtered: Pinecone bills it
by the namespace's size. The drift check (at start and every 5 minutes, and
`exactdocs index check`) lists the namespace's IDs, 100 per request, so it costs about one read
request per 100 vectors each time; for millions of vectors, prefer an instance that does not
serve (`exactdocs index check` from a job) or accept the reads. Writes go 100 vectors per
request and are retried by the job that made them.

## Trying it locally

Pinecone Local's single-index image emulates an index (amd64 only, kept
in memory, sparse values ignored, so `hybrid` cannot be tried on it):

```bash
docker run -d --name pinecone -p 5081:5081 -e PORT=5081 -e INDEX_TYPE=serverless \
  -e VECTOR_TYPE=dense -e DIMENSION=1536 -e METRIC=dotproduct \
  ghcr.io/pinecone-io/pinecone-index:v1.0.0.rc0@sha256:d60708292452e1e1d0740da86f653706a73b3682f302e1f0c18908f59e7ec7e0
EXACTDOCS_VECTOR_BACKEND=pinecone EXACTDOCS_INDEX_BACKENDS__PINECONE__HOST=http://localhost:5081 \
  EXACTDOCS_INDEX_BACKENDS__PINECONE__API_KEY=pclocal exactdocs serve
```

The contract tests run on it with `EXACTDOCS_TEST_PINECONE_URL=http://localhost:5081` (an index of
at least 256 dimensions) and `--integration` (they are integration tests). CI's integration job runs them on Pinecone Local (the image above, 256 dimensions,
`dotproduct`), which ignores sparse values; the manual **Pinecone** workflow runs them, hybrid
included, against a real index (repository secret `PINECONE_API_KEY`, its host as the workflow's
input). CI never calls Pinecone itself.
