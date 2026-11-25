# Persistence: one data directory, one database

!!! abstract "TL;DR"

    - Everything ExactDocs stores lives in the **data directory**: one SQLite database (SQLAlchemy
      Core, async, no ORM) plus DBOS's `jobs.sqlite`. Back up the directory as a whole.
    - `EXACTDOCS_DATABASE_URL` can point at **PostgreSQL** (several server processes share it) or
      a **libSQL** server instead, with the same adapters.
    - Each domain owns its tables, prefixed with its name. Foreign keys never cross domains.
    - One Alembic history, owned by `bootstrap`, runs at start.

## The data directory and SQLite

Everything ExactDocs stores lives in the **data directory**: `EXACTDOCS_DATA_DIR`, which the Docker
image sets to `/data`, else the platform user-data directory (so `uvx` and stdio MCP share it).

`bootstrap/database.py`:

- creates it, and refuses to start if it is not writable;
- opens one SQLite file in it (`EXACTDOCS_DATABASE_URL` overrides the path);
- uses SQLAlchemy **Core**, async, no ORM, on aiosqlite, in WAL mode with a busy timeout and
  `foreign_keys=ON`.

Next to it, DBOS keeps the durable state of running jobs in `jobs.sqlite` (its own schema and
migrations; see [Background jobs](jobs.md)).

!!! tip "Back up the data directory as a whole"

    The database and `jobs.sqlite` belong together.

## PostgreSQL (#103)

`EXACTDOCS_DATABASE_URL=postgresql+psycopg://...` (or `postgresql://`) puts every table in a
PostgreSQL 14+ database instead, through psycopg 3 async (already in the image as a DBOS
dependency), so several server processes can share it. The data directory then only holds each
process's git work folders and `known_hosts`.

What changes:

### The same adapters

- The SQLAlchemy Core adapters in `adapters/driven/sqlite.py` run on both dialects.
- The little that differs is chosen from the engine's dialect: `ON CONFLICT` inserts through the
  dialect's `insert`, JSON tag lists through `json_each` or `json_array_elements_text`.
- Only search has adapters of its own (`postgres_fts.py` and `pg_search.py`, below).
- The adapter contract tests run every SQL adapter on both.

### Turn-taking

- A transaction that asks for `begin_immediate` (SQLite's `BEGIN IMMEDIATE`, one writer at a time)
  takes a transaction-level advisory lock (`WRITE_LOCK`) on PostgreSQL. The read-then-write
  transactions that rely on it (the first admin, activations, the search index) keep that guarantee
  across processes.
- A turn waits at most `WRITE_LOCK_TIMEOUT_MS` (30 s, `SET LOCAL lock_timeout`), then fails with
  `WriteTurnTimeoutError`, as SQLite gives up after `BUSY_TIMEOUT_MS`.
- `migrate()` runs in one transaction under another advisory lock: processes starting together
  migrate one after the other.

!!! warning "The trade-off is SQLite's single writer"

    Every such transaction of every process takes turns on one key, so more processes serve more
    reads but do not import faster. Per-library keys (the transactions mostly touch one library)
    are the way to lift that when it matters.

### Text compares like SQLite's

- After migrating, every `text` column of ExactDocs' tables gets the "C" collation (code-point
  order, as SQLite's `BINARY`), whatever the database's locale, so listings sort the same on both.
- Revisions keep creating plain `Text` columns; the column keeps its exact type (`format_type`).
- A column a generated column or a view reads cannot change type, so such a column is created with
  `Text(collation="C")` in its revision (as `0c4e8a2f6b19` does).

### One Alembic history

The revisions run on both:

- `render_as_batch` is SQLite's only;
- partial indexes carry `postgresql_where` next to `sqlite_where`;
- the FTS5 steps are skipped on PostgreSQL, and `0c4e8a2f6b19` creates PostgreSQL's search table
  instead (a no-op on SQLite).

### Search: PostgreSQL full-text search

`retrieval.adapters.driven.postgres_fts`:

- `retrieval_search` keeps FTS5's four columns per chunk (a cascading foreign key replaces the
  delete trigger) and a generated `tsvector` with the `simple` configuration, labels A to D for
  heading, path, text and identifiers.
- Ranking: `ts_rank_cd` over FTS5's weights scaled to 0..1 and length normalisation 1, plus the
  rank of the query's identifiers (`retry_policy`) matched as whole words, as BM25 weighs a rare
  whole token high. Snippets come from `ts_headline`.
- Every column passes through the SQL function `retrieval_search_words` first, so PostgreSQL's
  parser cuts words as FTS5's `tokenchars '-_.'` does (`/v1/tokens` holds `tokens`, an underscore
  stays inside a word).
    - Its word characters are spelled out (ASCII letters and digits, every non-ASCII character),
      never `[[:alnum:]]`, which follows `LC_CTYPE` and under `C` knows only ASCII. The suites run
      on a `C`-locale database too.
    - In such a database `lower()` folds only ASCII, so an upper-case non-ASCII word is matched
      through the (casefolded) identifiers column.
- It is not BM25, but the shared ranking suite (`tests/retrieval/ranking`) passes on it with no
  listed difference.
- `exactdocs reindex` rebuilds it the same way as FTS5's (`retrieval_search_next`, then a swap in
  one transaction).

### BM25 with `pg_search` (#104)

`retrieval.adapters.driven.pg_search`: when the database has ParadeDB's extension, a BM25 index
(`retrieval_search_bm25`) over the same `retrieval_search` columns answers instead.

- **Tokenizer.** It cuts words as FTS5 does: a regular expression for ASCII letters and digits,
  every non-ASCII character and `-_.`, lower-cased and ASCII-folded; the identifiers column by
  whitespace.
- **Scoring.** Every term is an alternative; each field's BM25 score is boosted and the fields'
  scores add up. The query's whole identifiers count twice (only queries that have one run that
  second group of clauses).
- **Boosts** are derived from FTS5's column weights `w`, as `w * (k1 + 1) / (w + k1)` with FTS5's
  `k1 = 1.2`:

    | Field | Boost |
    |---|---|
    | heading | 2.08 |
    | path | 1.69 |
    | text | 1 |
    | identifiers | 0.17 |

    FTS5 multiplies a column's term count by `w` before BM25 saturates it, so that is what one
    occurrence there scores against one in the text, while Tantivy multiplies each field's whole
    score (with the field's own IDF and length) by its boost. FTS5's raw 20 for a heading would let
    any word of a short heading win.
- **Tests.** The ranking suite and the retrieval eval's BM25 gates run on it in CI (the eval with
  `--expect-engine pg_search`).
- **Scans.** Each search turns pg_search's join and aggregate scans off (`SET LOCAL`): they never
  apply to these joins and would log a warning per query. Indexing a chunk set does the same for its
  anti-join (`PostgresSearchIndex.write_settings`, set by bootstrap for the table pg_search reads).
- **Writes.** The adapter writes and rebuilds the rows through `postgres_fts` (structurally, as its
  `table`), and `exactdocs reindex` indexes `retrieval_search_next` with BM25 before the swap.
- **Snippets** are `ts_headline`'s, as without `pg_search`.

### The engine is chosen at start

`bootstrap/search_engine.py`: once the schema is migrated, `Container.running()` asks whether the
extension is installed and builds the BM25 index if no valid one exists.

- **The build.** `CREATE INDEX CONCURRENTLY` on an autocommit connection, so writers carry on,
  under a session advisory lock that the other starting processes poll (`pg_try_advisory_lock`; a
  statement waiting for the lock would hold a snapshot the concurrent build waits for).
- **Failures.** An invalid index a dead build left is dropped and built again. A build that fails
  (a deadlock, a cancel, a full disk) drops what it left, and the process falls back with a WARNING
  instead of failing to start.
- **`exactdocs reindex`** takes the same lock around its whole rebuild, so it never races a
  starting process's build. It first renames an index left under `retrieval_search_next_bm25` by
  a rebuild that died between its swap and its rename.
- **Read-only.** A read-only `serve --stdio` never builds it and falls back.
- **Fallback.** Without the extension, or without the index in a read-only process, full-text
  search answers and the log says why (a WARNING when the server could do better: the extension is
  available, or the index is only missing). The table and its `tsvector` stay in both cases, so
  the extension can come and go with a restart.
- **Reporting.** `SearchIndexState.engine` names the engine in use; `/healthz` reports it as
  `search_engine`.

### Other differences

- **Jobs and locks across processes:** see
  [Several processes on PostgreSQL](jobs.md#several-processes-on-postgresql).
- **Backup** is PostgreSQL's own (`pg_dump`): `exactdocs backup`/`restore` refuse it.
- `EXACTDOCS_SECRET_KEY` is required: one key for every process, or credentials one stored could
  not be opened by another.

## Tables and migrations

- **Each domain owns its tables**, prefixed with its name (`catalog_libraries`, `retrieval_...`).
  Foreign keys only between tables of the same domain; another domain's IDs are held by value and
  its tables are never read.
- **One Alembic history, owned by `bootstrap`** (`bootstrap/migrations/versions`), run on start
  (`Container.running()`) and reported by `/api/health` as `schema_revision`.
    - A domain's revision is plain `op.create_table(...)`, not an import of the adapter's `Table`
      objects, so old revisions never change.
    - Use `op.batch_alter_table` to change an existing table,
      `op.execute("CREATE VIRTUAL TABLE ... USING fts5(...)")` for FTS5.
    - `migrate()` runs the revisions in one `BEGIN IMMEDIATE` transaction with `foreign_keys`
      off[^fk-off]. It fails, rolling back, if `PRAGMA foreign_key_check` finds a violation before
      the commit.
- **Processes starting together on one SQLite file** take turns first on an exclusive `flock` of
  `exactdocs.db-migration.lock`, next to the database.
    - A process waits there for as long as another one's migration takes (SQLite's own
      `BUSY_TIMEOUT_MS`, 5 s, is too short on a busy machine, #320), and the kernel drops the lock
      of a process that dies.
    - A waiter logs a warning naming the lock file and its holder (pid and host, written into the
      file) after 5 s and then every minute.
    - A lock file it cannot open stops startup naming it.

[^fk-off]: A batch alteration recreates the table, and with the pragma on SQLite would
    cascade-delete the rows of tables that reference it.

The catalog's tables for versions, logos, manual tags and renames are described in
[Version storage](versions.md); the vector store and AI spend in
[Vectors, embedding and budgets](embeddings.md); all tables in the [Data model](data-model.md).

## Backup and restore (E10-06), SQLite only

`bootstrap/backup.py`, behind the local `exactdocs backup` / `restore` commands. No domain is
involved: it works on the files the bootstrap owns.

A backup is a gzipped tar of:

- `manifest.json`: format, version, schema revision, a SHA-256 and size per member;
- the database, copied with SQLite's online backup API in one step (one read transaction's view;
  WAL writers carry on);
- `jobs.sqlite`, copied the same way *before* it (a resumed import may redo a step the database
  recorded, never skip one);
- `known_hosts`;
- `secret.key`, only on request.

A restore reads only those member names. Before moving any file into place it refuses:

- a revision this build's Alembic history does not know;
- a data directory that holds any trace of an instance (database, `-wal`, `-shm`, `jobs.sqlite`);
- a member whose size differs from its manifest or does not fit in the free space;
- any checksum mismatch.

Then `migrate()` brings an older schema to head.

## Search index format and `exactdocs reindex` (E10-04)

- `retrieval_search_format` holds the format the FTS5 table was built in (`FORMAT` in
  `retrieval.adapters.driven.sqlite_fts`), read through the `SearchIndexMaintenance` port
  (`GetSearchIndexState`, `RebuildSearchIndex`).
- A change to how entries are made from chunks bumps `FORMAT`. The old index keeps answering, and
  `/api/health` reports `reindex_required` until the operator runs `exactdocs reindex` (local).
- The rebuild:
    1. fills `retrieval_search_next` from `retrieval_chunks`, 500 chunks per write transaction
       (readers never wait in WAL mode), with a trigger that removes chunks deleted meanwhile;
    2. then, in one `BEGIN IMMEDIATE` transaction, adds what was indexed since it began, drops the
       old table and renames the new one over it.
- A rebuild that died leaves its table behind; the next one starts over.
- A change of the table's columns stays an Alembic revision that rebuilds it on start (as
  `a91c4e7b3d02` did).

See *Upgrades* in [Releasing](../releasing.md).

## Adding a table, adapters and tests

- **Adding a table:** `just migration "add jobs table"`, fill in `upgrade()`/`downgrade()`, set
  `down_revision` to the current head if you rebased over another revision (a test fails if the
  history ever has two heads), then write the adapter.
- **Adapters** live in `adapters/driven/sqlite.py`, take the `AsyncEngine` and describe their tables
  with Core `Table` objects (`catalog.adapters.driven.sqlite` is the reference).
    - They run in the same adapter contract test as the in-memory adapter.
    - SQLAlchemy, Alembic and aiosqlite are imported only by driven adapters and `bootstrap`
      (architecture test).
- **Tests** build a container on an empty temporary data directory (`tests/conftest.py` points
  `EXACTDOCS_DATA_DIR` at one for every test) and seed data through the repository, so the catalog
  starts empty in production.

## libSQL (#474)

`EXACTDOCS_DATABASE_URL=libsql://host?authToken=...` puts the database on a libSQL server (`sqld`,
or Turso) with no change to any adapter.

- `bootstrap/libsql_database.py` registers `sqlite+libsql`: SQLite's async dialect over Turso's
  `turso-serverless` DB-API driver (SQL over HTTP; the `libsql-database` extra, imported only
  there), run on a thread per connection through aiosqlite's `Connection` as `sqlite3` is.
- The engine's dialect is `sqlite`, so every SQLite adapter, revision and query applies.
- `is_libsql(engine)` tells it apart where something differs:
    - the vector store searches with libSQL's `vector_distance_cos` instead of loading sqlite-vec
      (`SqliteVectorIndex(native=True)`);
    - no PRAGMA but `foreign_keys` is set;
    - read-only access and `exactdocs backup` are refused.
- The driver's errors become `sqlite3`'s, and a statement outside a transaction is sent again once
  when the server had dropped the idle stream.
- CI's integration job runs the persistence contract tests' SQLite cases on a `sqld` server, and
  the libSQL database's own server tests, several processes migrating and writing it at once among
  them (`EXACTDOCS_TEST_LIBSQL_DATABASE_URL` with `--integration`, its own step;
  [Fast and integration tests](../releasing.md#fast-and-integration-tests)).

See *ExactDocs' own database on libSQL* in [Configuration](../configuration.md) for what an
operator sees.
