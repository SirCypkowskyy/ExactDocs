# Health

!!! abstract "TL;DR"
    - The probes sit outside `/api/v1` and answer `GET` and `HEAD` without sign-in.
    - `GET /healthz` (alias `GET /api/health`) is liveness: 200 while the process runs, with
      database and search details.
    - `GET /readyz` is readiness: 200 when the database answers at this version's schema
      revision, else 503.
    - Only exact `GET`/`HEAD` requests on these paths skip the `Host` check.

## Endpoints

| Method | Path | Purpose | Caller |
|---|---|---|---|
| `GET`, `HEAD` | `/healthz` | liveness | none |
| `GET`, `HEAD` | `/api/health` | alias of `/healthz` | none |
| `GET`, `HEAD` | `/readyz` | readiness | none |

## `GET /healthz`

Answers 200 while the process runs, giving the database about 0.3 s for its details.

| Field | Meaning |
|---|---|
| `status` | |
| `version` | |
| `database_reachable` | `false` when the database did not answer in time |
| `schema_revision` | the database's |
| `search_index_format` | the format the search index was built in;<br/>`null` if none is recorded |
| `reindex_required` | `true` when that format is older than this version's or not recorded,<br/>until `exactdocs reindex` has run (search keeps answering meanwhile) |
| `search_engine` | the engine that answers searches, below |
| `vector_store_missing` | once an embedding model is configured, the extension the vector store needs<br/>and cannot load (`sqlite-vec` on SQLite, `vector` on PostgreSQL), else `null` |

| `search_engine` | Engine |
|---|---|
| `fts5` | SQLite |
| `pg_search` | ParadeDB's BM25 on PostgreSQL |
| `postgres_fts` | PostgreSQL full-text search, when the database has no `pg_search` |

- When the database did not answer in time, `database_reachable` is `false` and the database
  fields are `null`.
- A request whose `Host` the instance does not trust gets only `{"status": "ok"}`.

## `GET /readyz`

| Answer | When |
|---|---|
| 200 `{"status": "ready"}` | the database file exists, answers within 2 s and is at this version's schema revision |
| 503 `{"status": "not_ready", "reason": ...}` | otherwise, with a fixed sentence |

Both probes keep their budget while a database statement is still running.

!!! note "`Host` check"
    Only exact `GET`/`HEAD` requests on these paths skip the `Host` check
    ([Deployment](../deployment/health-checks.md)).
