# Chroma

!!! abstract "TL;DR"

    - Holds the vector index, on a Chroma server, Chroma Cloud or an embedded directory.
    - Two extras: `chroma` (HTTP only) or `chroma-local` (adds the embedded client).
    - ExactDocs sends its own vectors; Chroma runs no model.
    - The embedded directory belongs to one process: stop the server before `exactdocs index rebuild`.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__CHROMA__<OPTION>`.

[Chroma](https://www.trychroma.com), as a server, as Chroma Cloud or embedded in a local
directory, can hold the **vector index** (`EXACTDOCS_VECTOR_BACKEND=chroma`, #361). Its client is
an optional extra, not in the images, in two flavours that install the same `chromadb` module
(pick one):

- `exactdocs[chroma]`: the HTTP-only client (`chromadb-client`), for a Chroma server or Chroma
  Cloud (`url`). No ONNX runtime, no tokenizer, no model.
- `exactdocs[chroma-local]`: the full `chromadb` package, which adds the embedded persistent
  client (`path`); it also speaks HTTP. It pulls more (Chroma's server parts, `onnxruntime`,
  `tokenizers`), none of which ExactDocs uses.

`pip install 'exactdocs[chroma]'` or `uvx --from 'exactdocs[chroma]' exactdocs serve` (combine it
with `ai` for hosted embedding models: `exactdocs[ai,chroma]`). It is tested against
`chromadb/chroma:1.5.9` (the clients are 1.5.9); use a server of the same minor version.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE): a server, or Chroma Cloud
vector_backend = "chroma"

[index_backends.chroma]
url = "https://api.trychroma.com"   # or http://chroma.internal:8000
tenant = "3f8c..."                  # Chroma Cloud: your tenant and database
database = "exactdocs"
collection = "exactdocs"
```

```bash
export EXACTDOCS_INDEX_BACKENDS__CHROMA__TOKEN=ck-...   # or token_file in the TOML file
```

```toml
# embedded: one directory, read and written by this ExactDocs process only
vector_backend = "chroma"

[index_backends.chroma]
path = "/var/lib/exactdocs/chroma"
```

| Option | Default | Meaning |
|---|---|---|
| `url` | one of `url` / `path` | A Chroma server or Chroma Cloud, `http(s)://host[:port]` (port 8000, or 443 with `https`, when none is given; no path) |
| `path` | one of `url` / `path` | The embedded persistent client's directory (created when missing); needs `exactdocs[chroma-local]` |
| `collection` | `exactdocs` | The collections' prefix: each embedding space is the collection `<collection>_space<id>`.<br/>Give every ExactDocs instance that shares a Chroma database its own |
| `tenant` | `default_tenant` | The Chroma tenant (Chroma Cloud: yours) |
| `database` | `default_database` | The Chroma database in that tenant (Chroma Cloud: one you created) |
| `token` | unset | A Chroma Cloud API key, or the token a proxy in front of a server checks.<br/>From the environment only (`EXACTDOCS_INDEX_BACKENDS__CHROMA__TOKEN`); the TOML file refuses it |
| `token_file` | unset | A file holding the token (a mounted secret), instead of `token` |
| `token_header` | `x-chroma-token` | Where the token is sent: `x-chroma-token` (Chroma Cloud's header) or `authorization` (`Authorization: Bearer <token>`, for a proxy) |
| `timeout` | `30` | Seconds one call to Chroma may take |

## What ExactDocs creates

On the first write to an embedding space, the collection
`<collection>_space<id>`, with cosine distance and **no embedding function**: ExactDocs sends the
vectors its own embedding model made and never any text to embed, so Chroma runs no model and
downloads none. The collection's metadata records the space's dimensions
(`exactdocs_dimensions`) and model; a collection of that name without it (not made by ExactDocs)
or with other dimensions (another instance's) is never written to, and the write fails naming
it. A collection dropped behind ExactDocs' back is created again on the next write. Each record
is one chunk of one version, with the metadata `manifest_id`, `library`, `version_id`,
`chunk_id`, `article_path`, `headings` and one `tag:<tag>` key (`true`) per tag of its article;
every search filters on the asked versions' `manifest_id` (and tags) in Chroma, before ranking,
so another version's chunks are never returned. The metadata holds no lists on purpose: in
Chroma 1.5.9 a record's list metadata can read back, and over HTTP be filtered by, another
record's lists. A new embedding model makes a new space, so a new collection; the retired
space's collection is dropped. Hybrid search fuses ExactDocs' BM25 index with Chroma's nearest
vectors in ExactDocs, as with the database.

## Authentication

Chroma Cloud takes its API key as `token` (sent as `x-chroma-token`), with
your `tenant` and `database`. A self-hosted Chroma server does not check a token itself: keep it
on a private network, or put it behind a reverse proxy that does (`token_header =
"authorization"`). Use `https` for anything but loopback or a private network. A token that is
missing or refused stops the start with the backend's name and what the server answered; no
error or log line carries the token.

## Embedded mode

The directory belongs to one process: the server. `exactdocs index check` and
`exactdocs index rebuild` open it too, so run them while the server is stopped (or use a Chroma
server). Several ExactDocs server processes (PostgreSQL with replicas) need a
Chroma server (`url`).

## Sizing

Chroma holds one record per chunk of each version (the same section in two versions
is two records), so count the chunks of every indexed version. A collection's HNSW index is kept
in memory: 4 bytes per dimension per record (1536 dimensions: about 6 KB; 100,000 chunks: about
600 MB), plus the graph (roughly 10 to 20 % more); the metadata, a few hundred bytes per record,
is on disk. The drift check (at start and every 5 minutes) reads the records' metadata a
thousand at a time: 100 requests per 100,000 records.
