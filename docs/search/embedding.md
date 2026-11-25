# Background embedding

!!! abstract "TL;DR"

    - With an embedding model set, every version is embedded in the background, resumably.
    - Each chunk is sent once; a library with AI off is never sent.
    - A new model starts a new space; searches answer BM25 until a version is covered.
    - `exactdocs ai estimate` prints what embedding will cost, without calling a model.

With an embedding model set, every version is embedded in the background: one `embed` job per
version, with a durable step per `batch_size` chunks that resumes after a restart. Jobs are queued
on start, after each import and whenever the model changes.

Each chunk is sent once, as its article title, heading path and text, even when many versions hold
it, and a library with AI off is never sent. Changing the model, its `dimensions` or the input
format starts a new embedding space, and every version is embedded again. Until a version is
covered by the new model, its searches answer BM25 with `fallback_reason: embedding_in_progress`;
two models' vectors are never mixed. The old space is dropped once the new one covers every
version.

Saving the embedding role's profile over REST re-queues what it changes. A batch the provider does
not answer for now (a timeout, a 429) is tried again a few times. On PostgreSQL the vectors go to
pgvector (see [PostgreSQL](../deployment/postgresql.md)); without its `vector` extension each embed
job is skipped with `vector_store_unavailable`.

To see what embedding will cost before you start, `exactdocs ai estimate` (where the server runs)
prints the chunks still to embed, an estimate of their tokens (4 characters per token, never a
tokenizer) and of the US dollars from the bundled price list, without calling any model.
`GET /api/v1/ai/embedding/estimate` is the same over REST.
