# Upgrading

!!! abstract "TL;DR"

    - Start the new version on the same data directory; the schema is migrated on start.
    - On PostgreSQL, stop every process first.
    - A release that says **Requires reindex** needs `exactdocs reindex`, which runs while the server serves.
    - External index backends are rebuilt from the database with `exactdocs index rebuild`.

On PostgreSQL, stop every process first (see [PostgreSQL](postgresql.md)).

Start the new version on the same data directory: `docker pull` and recreate the container, or run
`uvx --refresh exactdocs serve`. The database is migrated on start and every library keeps serving;
nothing is imported again. CI proves this for each change, starting from the previous release's
data directory.

When a release changes how the search index is built, its notes have a **Requires reindex**
section, the server logs a warning, and `/api/health` reports `"reindex_required": true`. Search
keeps answering as before until you run, where the server runs (it opens the data directory):

```bash
docker exec exactdocs exactdocs reindex     # or: uvx exactdocs reindex
```

It builds the new index from the stored chunks next to the one that answers, then swaps them in one
step, so the server keeps serving throughout. Running it when nothing changed is harmless.

## External index backends

With `EXACTDOCS_SEARCH_BACKEND` or `EXACTDOCS_VECTOR_BACKEND` set to an external backend (see
[Configuration](../configuration/ai.md)), the backend holds a copy of each version that
the database can always write again. The server compares the two at start and every five
minutes, logs what drifted, and `/healthz` reports how many versions did
(`index_versions_missing`). After the backend lost data (a reset, a deleted index), or when you
move an index to a backend for the first time, run where the server runs:

```bash
docker exec exactdocs exactdocs index check     # names what is missing; exits 1 if anything is
docker exec exactdocs exactdocs index rebuild   # or --library /owner/repo [--version v1.2.0]
```

The rebuild writes every version from the stored chunks and vectors (nothing is imported or
embedded again) while the server keeps serving, and deletes the versions the database no longer
has. A backend that does not answer at start stops the server, naming it.

A backend's client is an optional extra that the images do not carry: install ExactDocs with it
(`pip install 'exactdocs[lancedb]'`, `uvx --from 'exactdocs[lancedb]' exactdocs serve`), or in
an image of your own that installs that extra. **LanceDB** is embedded, so the server and the
command line both open its directory: on a local directory they take turns writing (a lock file in
it), so the rebuild above is safe while serving; with an object-store URI (`single_writer = true`)
stop the server before `exactdocs index rebuild`. See [LanceDB](../configuration/index-backends/lancedb.md).

A **DuckDB** file is the exception to "while the server keeps serving": it is open in one process
only, so stop the server, run `exactdocs index check` or `rebuild`, and start it again (the
command is refused, naming the server's process, while it runs). See
[DuckDB](../configuration/index-backends/duckdb.md).
