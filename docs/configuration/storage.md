# Storage and database

!!! abstract "TL;DR"

    - Everything lives in the data directory unless `EXACTDOCS_DATABASE_URL` says otherwise.
    - The database is a SQLite file by default; PostgreSQL and a libSQL server are the alternatives.
    - The schema is migrated on start.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_DATA_DIR` | `/data` in the Docker image, else the platform's user-data directory | Where ExactDocs keeps everything: the SQLite database, the generated secret key, `known_hosts`, fetch caches and `jobs.sqlite` (the durable steps of running imports).<br/>On PostgreSQL only `known_hosts` and fetch caches live here.<br/>Created if missing; the server refuses to start, naming the path, if it is not writable.<br/>`uvx` and stdio MCP use the same default path |
| `EXACTDOCS_DATABASE_URL` | `exactdocs.db` in the data directory | A SQLite file, such as `sqlite:////srv/exactdocs.db` (opened in WAL mode),<br/>a PostgreSQL database, `postgresql://user:password@host:5432/exactdocs` (psycopg 3; see [PostgreSQL](../deployment/postgresql.md)),<br/>or a libSQL server, `libsql://host?authToken=...` (the `libsql-database` extra; see [ExactDocs' own database on libSQL](advanced.md#exactdocs-own-database-on-libsql)).<br/>The schema is migrated on start, and `/api/health` reports its revision |
| `EXACTDOCS_DBOS_SYSTEM_SCHEMA` | `dbos` | PostgreSQL only: the schema of the same database where DBOS keeps the durable steps of jobs.<br/>SQLite keeps them in `<data dir>/jobs.sqlite` |
| `EXACTDOCS_MODELS_DIR` | `<data dir>/models` | Where local models live; see [Local models](../search/local-models.md) |

ExactDocs' own database can also live on a libSQL server: see [ExactDocs' own database on libSQL](advanced.md#exactdocs-own-database-on-libsql).
