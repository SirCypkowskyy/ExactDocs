# Advanced

!!! abstract "TL;DR"

    - Options most instances never touch: ExactDocs' own database on a libSQL server, rotating the secret key, and tuning knobs.
    - A libSQL database lets several processes and hosts share one SQLite-style database, with some limits.
    - Rotating the secret key takes the new key in `EXACTDOCS_SECRET_KEY` and the old one in `EXACTDOCS_SECRET_KEY_PREVIOUS`.

## ExactDocs' own database on libSQL

ExactDocs' own database can live on a **libSQL server** (`sqld`, self-hosted, or a Turso
database) instead of a SQLite file (#474), so several ExactDocs processes and hosts share one
SQLite-style database:

```bash
pip install 'exactdocs[libsql-database]'     # or: uvx --from 'exactdocs[libsql-database]' exactdocs serve
export EXACTDOCS_DATABASE_URL='libsql://exactdocs-acme.turso.io?authToken=...'
# a sqld on loopback or a private network, without TLS:
export EXACTDOCS_DATABASE_URL='libsql://sqld:8080?tls=0&authToken=...'
```

The URL names the server only (no path): `libsql://host[:port]`, over HTTPS unless `tls=0`, with
its token (a JWT: a Turso database token, or one signed with the key given to `sqld
--auth-jwt-key-file`) as `authToken`, as Turso writes it; a server without authentication takes
none. Log lines and errors never show the token. The extra installs Turso's `turso-serverless`
driver (pure Python, no dependency, so every platform); it is not in the images. ExactDocs runs
SQLite's own SQLAlchemy dialect over it (`sqlite+libsql`, in `bootstrap/libsql_database.py`),
each connection on a thread of its own as aiosqlite does, so every table, revision and query is
SQLite's: the schema is migrated on start, and the search index is SQLite's FTS5. Tested against
`ghcr.io/tursodatabase/libsql-server:v0.24.33`; CI runs the persistence contract tests' SQLite
cases on it, and a scenario with two server processes.

### Several processes

Each process (and host) has a data directory of its own and uses the
server for everything in the database. Writes take turns on the server: a transaction that asks
for `BEGIN IMMEDIATE` (the first admin, activations, the search index) waits for the one before
it, as on a file. Processes starting together migrate one after the other.

**What differs from a SQLite file:**

- **Vectors use libSQL's own functions.** The vector store keeps the same tables and BLOBs as on
  SQLite and searches them exactly, with libSQL's `vector_distance_cos` instead of `sqlite-vec`,
  which a server cannot load (`/api/health` names its requirement `libSQL vectors`). For an
  approximate index on libSQL, add the [libSQL backend](index-backends/libsql.md) on the same server.
- **No read-only access.** A libSQL server refuses `PRAGMA query_only` and has no authorizer, so
  `serve --stdio` (and the commands that open the database read-only) refuse it: run `exactdocs
  serve` and connect over HTTP (`/mcp`).
- **`exactdocs backup` refuses it**: use the server's backups (a Turso database's point-in-time
  restore, or copies of `sqld`'s data directory).
- **Jobs stay with their process.** DBOS keeps each process's running jobs in `jobs.sqlite` in its
  data directory, as on a file: a job runs on the process that took it, and every process sees
  its state in the database. One server process per data directory, as on a file.
- **The server keeps its own settings.** It refuses `journal_mode`, `busy_timeout`,
  `synchronous`, `ANALYZE` and other PRAGMAs that set something; ExactDocs only switches
  `foreign_keys` on for each connection (the server's default too). Without `ANALYZE` the query
  planner has no statistics, so it may pick another of a table's indexes than on a file (the
  answers are the same).
- **Streams expire.** The server drops a connection's stream after a few seconds idle (`sqld`:
  10 s). A statement outside a transaction is then sent again; a transaction left idle that long
  is rolled back by the server and fails.
- **Every statement is a round trip.** One HTTP request each (about 2 ms on loopback): a first
  migration takes about a second, and an import is slower than on a local file, more so the
  farther the server.
- `REGEXP` is not available (ExactDocs does not use it), and an infinite float cannot be sent.
- A **local libSQL file** is not a database option: it is the same format as SQLite, so use
  `sqlite:///path` (libSQL's local file is for the [search and vector backend](index-backends/libsql.md)).

## Rotating the secret key

1. Put the new key in `EXACTDOCS_SECRET_KEY` and the old one in `EXACTDOCS_SECRET_KEY_PREVIOUS`.
2. Credentials sealed with the old key still open, and each one is sealed with the new key
   whenever it is sent again.
3. Remove `EXACTDOCS_SECRET_KEY_PREVIOUS` once they all have been.

HyDE's and the agentic cache's answers are keyed with the current key only, so after a rotation
every cached answer is a miss (the LLM is asked again) until the TTL prunes the old rows.

## Tuning knobs

Settings that are rarely changed, with the reference row that describes each:

| Setting | Default | Described on |
|---|---|---|
| `EXACTDOCS_IMPORT_BATCH_FILES` | `100` | [Server and imports](server.md#server-and-imports) |
| `EXACTDOCS_JOB_POLL_SECONDS` | `1` | [Server and imports](server.md#server-and-imports) |
| `EXACTDOCS_AUTO_SYNC_SCHEDULE` | `0 * * * * *` | [Server and imports](server.md#server-and-imports) |
| `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET` | `10000` | [Server and imports](server.md#server-and-imports) |
| `EXACTDOCS_DBOS_SYSTEM_SCHEMA` | `dbos` | [Storage and database](storage.md) |
| `EXACTDOCS_MODELS_DIR` | `<data dir>/models` | [Storage and database](storage.md) |
| `EXACTDOCS_SECURE_COOKIES` | `false` | [Security and the secret key](security.md) |
| `EXACTDOCS_AUTH__REVALIDATE_POLL_SECONDS` | `300` | [Linking providers to an account](sign-in/index.md#linking-providers-to-an-account) |
| `EXACTDOCS_AI__HYDE__CACHE_TTL` | `P30D` | [Search and AI settings](ai.md) |
| `EXACTDOCS_AI__USE_INSTANCE_PROXY` | `false` | [Outbound connections](outbound.md) |
| `EXACTDOCS_USAGE__RETENTION_MONTHS` | `13` | [Usage counts and leaderboards](observability.md#usage-counts-and-leaderboards) |
