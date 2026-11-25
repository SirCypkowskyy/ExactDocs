# Azure AI Search

!!! abstract "TL;DR"

    - Holds the search index, the vector index or both; install the `azure-search` extra.
    - Authenticates with an admin key or Entra ID (two roles on the service).
    - Native hybrid search is on by default; a `semantic_configuration` lets Azure's semantic ranker rerank.
    - Writes return only once the index counts them.

!!! tip "Environment variables"
    Every option below can also be set as `EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__<OPTION>`.

Azure AI Search can hold the **search index**, the **vector index**, or both
(`EXACTDOCS_SEARCH_BACKEND=azure_search`, `EXACTDOCS_VECTOR_BACKEND=azure_search`, #353). Its
client is an optional extra, not in the images: `pip install 'exactdocs[azure-search]'` or
`uvx --from 'exactdocs[azure-search]' exactdocs serve` (with `ai` for hosted embedding models:
`exactdocs[ai,azure-search]`). It uses `azure-search-documents` 12.0.0 (the `2026-04-01` REST
API) over azure-core's requests transport, and `azure-identity` for Entra ID.

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE)
search_backend = "azure_search"
vector_backend = "azure_search"

[index_backends.azure_search]
endpoint = "https://contoso-docs.search.windows.net"
index = "exactdocs"
```

```bash
# An admin key, from the environment (or api_key_file in the TOML file, a mounted secret):
export EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__API_KEY=...
# Or Entra ID: no key, and auth = "default" (DefaultAzureCredential) or "managed_identity".
```

| Option | Default | Meaning |
|---|---|---|
| `endpoint` | required | The service's URL, `https://<service>.search.windows.net` (HTTPS only, no path) |
| `index` | `exactdocs` | The search index's name; each embedding space's index is `<index>-space<id>`.<br/>Lower-case letters, digits and single dashes, 2 to 100 characters.<br/>Give every ExactDocs instance that shares a service its own |
| `auth` | `api_key` with a key, else `default` | `api_key`: an admin key.<br/>`default`: Entra ID through `DefaultAzureCredential` (the `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_CLIENT_SECRET` or workload identity variables, a managed identity, the Azure CLI's sign-in).<br/>`managed_identity`: the system-assigned managed identity, or the user-assigned one `client_id` names |
| `api_key` | unset | An admin key.<br/>From the environment only (`EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__API_KEY`); the TOML file refuses it |
| `api_key_file` | unset | A file holding the admin key (a mounted secret), instead of `api_key` |
| `client_id` | unset | The client ID of a user-assigned managed identity (`auth = "managed_identity"` or `"default"`) |
| `audience` | unset | The Entra ID audience of a sovereign cloud (e.g. `https://search.azure.us`); unset: the public cloud |
| `timeout` | `10` | Seconds to connect, and to read each answer.<br/>Requests the service throttles or fails are retried twice by the SDK, then by the job |
| `index_timeout` | `60` | Seconds a write waits for the index to return what it wrote (below); past it the write fails and its job is retried |
| `hybrid` | `true` | Native hybrid search (below). The vector index only; `false` keeps the words out of the spaces' indexes |
| `vector_search` | `approximate` | `approximate` (HNSW) or `exact` (every vector of the asked versions: exhaustive k-nearest-neighbours, exact and slower on large versions) |
| `semantic_configuration` | unset | The name of a semantic configuration: Azure's **semantic ranker** reranks the hybrid searches that ask for reranking (below).<br/>Letters, digits, `_` and `-`, up to 128 characters; needs `hybrid = true`.<br/>Unset: the semantic ranker is never used |

Both backends read the same table, so with both indexes in Azure AI Search they share the
service.

## What ExactDocs creates

Each chunk of each version is one document, keyed by its manifest
and chunk IDs: in `<index>` for the search index, in `<index>-space<id>` for an embedding space.
Each carries `manifest_id`, `library`, `version_id`, `chunk_id` (filterable; `manifest_id` and
`library` facetable, for the drift check), `article_path`, `tags` (a filterable collection), and
the words in three searchable fields (`heading`, `path`, `body`: the section's heading, the
headings above it, its text, as every word whole and by its identifier parts, lower case, so
`retryPolicy` is `retrypolicy`, `retry` and `policy`). They use the `whitespace` analyzer, so
`retry_policy` and `--dry-run` stay whole tokens (a language analyzer would split them and stem
the rest), and the index ranks with BM25 and a scoring profile, `exactdocs`, that weighs them as
the database's own indexes do (heading 20, the headings above 4, text 1). A space's documents
also carry `vector` (`Collection(Edm.Single)`, the embedding model's dimensions, an HNSW profile
comparing by cosine; not retrievable or stored, to save room). The search index is created when
the server starts and it is missing; a space's index on the space's first write. An index of
that name that exists with another schema (a field of another type, another analyzer, vectors of
other dimensions, no `exactdocs` scoring profile) is never written to: the start, or the write,
fails naming the index and what differs; delete it or set another `index`, then run
`exactdocs index rebuild`. A new embedding model makes a new space, so a new index; the retired
space's index is deleted. An index deleted behind ExactDocs' back is created again on the next
write (`exactdocs index rebuild` fills it).

Every query filters on the asked versions' `manifest_id` (and the tags) with an OData filter
inside Azure AI Search, before ranking (vector queries are pre-filtered), so another version's
chunks are never returned. A query's words are its terms, each escaped for the full Lucene
syntax, so a query is never parsed as syntax, and BM25 statistics are global, so the same chunk
in two versions scores the same.

## Writes wait for the index

Azure AI Search indexes in near real time: a document is
searchable about a second after the service took it. Every write marks its documents
(`write_id`) and returns only once the index counts all of them (a delete: none of them), so a
version is complete in the index when its import or embedding job says so.

## Authentication

With a key, use an admin key (a query key cannot write); keep it in the
environment or a mounted file. With Entra ID, enable role-based access on the service (API access
control *Role-based access control* or *Both*) and give ExactDocs' identity two roles on it:
**Search Service Contributor** (it creates and deletes its indexes) and **Search Index Data
Contributor** (it writes and queries documents). Tokens come from the sync `azure-identity`
credentials, run in a thread, about once an hour. A refused key or identity stops the start with
`authentication failed` and the backend's name; no error or log line carries the key (azure-core
redacts the `api-key` header in its own logs).

## Native hybrid search

With `hybrid` on (the default), each space's documents also carry the
words (the same three fields), and a hybrid search of one version is one Azure hybrid query: the
words (BM25, weighted) and the vector query (at least the 50 nearest), both filtered
to the version and the tags, fused by Azure with reciprocal rank fusion. With `hybrid = false`,
ExactDocs fuses its own search index (Azure AI Search's or the database's) with the nearest
vectors itself. Turning it on later needs `exactdocs index rebuild` to write the words of the
documents already there. The search across libraries (`search_all_docs`) always fuses in
ExactDocs.

## Semantic ranker

Azure's semantic ranker (#473) can rerank hybrid searches instead of
ExactDocs' own reranker. Name a semantic configuration:

```toml
[index_backends.azure_search]
endpoint = "https://contoso-docs.search.windows.net"
semantic_configuration = "exactdocs-semantic"   # any name; ExactDocs makes it
```

and keep a reranker configured (`EXACTDOCS_AI__RERANKER__MODEL`, or a library's own): reranking
is asked for as it always is, by the reranker role ([Reranker](../../search/reranking.md#reranker)). A hybrid
search (`hybrid`, and `hybrid_hyde`'s native query) of a library that reranks is then one Azure
request: the same hybrid query (the words, the vector, the filters to the version and the tags,
before ranking), with `semanticConfiguration` and the query's own text as `semanticQuery`. Azure
reranks its best 50 results; the result says `reranked: true`, its scores are the ranker's (0 to
4), and ExactDocs' reranker is not called for that search (no cross-encoder or judge call, nothing
recorded against ExactDocs' budgets; a budget that already turned the search's reranking off,
`llm_budget_reached`, turns Azure's off too). Searches the semantic ranker does not answer are reranked
as before by ExactDocs' reranker: `bm25` and `vector` searches, the search across libraries, and
any hybrid search Azure could not rerank (the ranker over capacity: Azure answers in the hybrid
order, `semanticErrorHandling = partial`; or the request refused, such as the Free plan's
monthly requests used up: ExactDocs logs a warning and asks the hybrid query alone). Without a
reranker configured nothing reranks, as today; without `semantic_configuration` the semantic
ranker is never used.

With the option, each space's documents also carry two plain-text fields the ranker reads,
`title` (the section's headings, `Guide / Retries`) and `content` (its text, as written),
searchable and retrievable as a semantic configuration needs but never searched by BM25 nor
returned; the configuration ranks by them (`title` as its title field, `content` as its content
field). A new space's index is made with them. An existing space's index without them gets them
added in place (Azure adds fields and semantic configurations without a rebuild, and ExactDocs
logs a warning): run `exactdocs index rebuild` once, so the documents written before carry the
text. A configuration of that name over other fields, or a `title` / `content` field of another
kind, is a schema mismatch: the write fails naming the index and what differs.

## Setting it up

The semantic ranker needs a region that offers it. Every service starts on
its **Free** plan (any tier), which allows a monthly number of semantic requests (1,000 at the
time of writing); once they are used up, semantic queries are refused until the next month.
The **Standard** plan (the Basic tier or higher) bills each semantic request beyond the free
ones, per 1,000 requests: see [Azure AI Search pricing](https://azure.microsoft.com/pricing/details/search/).
Choose the plan in the portal (**Settings** > **Premium features** > **Semantic ranker**) or with
the management API's `semanticSearch` property (`free` or `standard`). **What it costs:** every
reranked hybrid search is one semantic request (a search that does not ask for reranking, or is
not a native hybrid search, makes none), and the `content` field stores each chunk's text once
more in every space's index (about what the chunks' text takes; see *Sizing*). The semantic
ranker reads each document's first 2,000 or so tokens across `title` and `content`, more than
ExactDocs' chunks hold.

## Sizing

One document per chunk of each version (the same section in two versions is two
documents), so count the chunks of every indexed version. A vector takes 4 bytes per dimension
in the vector index (1,536 dimensions, `text-embedding-3-small`: about 6 GB per million chunks,
plus the HNSW graph's links), which counts against the tier's vector index quota per partition;
the words and fields take about what the chunks' text does. Each embedding space is an index of
its own and, while a new model is embedding, the old space's index is still there: with the
search index that makes three indexes, the Free tier's limit. Check the tier's storage, vector
index and index count limits before indexing many versions, and leave room for a rebuild.

## Testing against a real service

There is no emulator: CI runs the contract suites against an
in-process fake of the REST API, plugged in as the SDK's transport. The manual workflow
**Azure AI Search (real service)** (`.github/workflows/azure-search.yml`, *Run workflow*) runs
the same suites against a real service. It needs a GitHub environment `azure-search`, the
repository variable `AZURE_SEARCH_ENDPOINT` and, for `auth: api_key`, the environment secret
`AZURE_SEARCH_API_KEY` (an admin key); for `auth: entra`, the repository variables
`AZURE_CLIENT_ID` and `AZURE_TENANT_ID` of an app registration (or user-assigned identity) with a
federated credential for `repo:<owner>/<repo>:environment:azure-search` and both roles above.
Each test writes to indexes of its own (`exactdocs-test-<random>`) and deletes them, so a Free
tier service will do. The `azure_search_semantic` cases run with a semantic configuration, so the
service's region must offer the semantic ranker (its Free plan's requests are plenty). Locally:

```bash
EXACTDOCS_TEST_AZURE_SEARCH_URL=https://<service>.search.windows.net \
EXACTDOCS_TEST_AZURE_SEARCH_KEY=<admin key> \
  uv run pytest --integration packages/exactdocs/tests/retrieval -k "azure_search and not fake"
```

(Without `EXACTDOCS_TEST_AZURE_SEARCH_KEY`, the tests sign in with `DefaultAzureCredential`,
e.g. after `az login`. The real service's cases are integration tests: `--integration` turns them
on, see [Fast and integration tests](../../releasing.md#fast-and-integration-tests).)
