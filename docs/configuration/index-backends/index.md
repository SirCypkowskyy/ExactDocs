# External index backends

!!! abstract "TL;DR"

    - By default the database holds both indexes; a backend can hold a copy of the search index, the vector index or both.
    - Options go under `[index_backends.<name>]` or `EXACTDOCS_INDEX_BACKENDS__<NAME>__<OPTION>`; keys only from the environment or a `*_file` option.
    - After switching, or after the backend lost data, run `exactdocs index rebuild`.

`EXACTDOCS_SEARCH_BACKEND` and `EXACTDOCS_VECTOR_BACKEND` move an index out of the database (see
[External index backends](../../architecture.md#external-index-backends)). Each backend is configured
under `[index_backends.<name>]` in the TOML file, or `EXACTDOCS_INDEX_BACKENDS__<NAME>__<OPTION>`;
keys and tokens only from the environment or a `*_file` option. After switching, or after the
backend lost data, run `exactdocs index rebuild` ([Deployment](../../deployment/upgrading.md#external-index-backends)).

| Backend | Search index | Vector index |
|---|---|---|
| [Azure AI Search](azure-search.md) | yes | yes |
| [Chroma](chroma.md) | | yes |
| [DuckDB](duckdb.md) | yes | yes |
| [Elasticsearch and OpenSearch](elasticsearch.md) | yes | yes |
| [LanceDB](lancedb.md) | yes | yes |
| [libSQL](libsql.md) | yes | yes |
| [Milvus](milvus.md) | | yes |
| [MongoDB](mongodb.md) | yes | yes |
| [Pinecone](pinecone.md) | | yes |
| [Qdrant](qdrant.md) | | yes |
| [Redis](redis.md) | yes | yes |
