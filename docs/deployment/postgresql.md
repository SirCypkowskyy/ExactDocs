# PostgreSQL

!!! abstract "TL;DR"

    - PostgreSQL 14 or newer lets several server processes share one database.
    - Set `EXACTDOCS_DATABASE_URL` and the same `EXACTDOCS_SECRET_KEY` in every process.
    - Connect directly or through a session-mode pooler, never a transaction-mode one.
    - Upgrade with every process stopped.

A team's instance can keep everything in PostgreSQL 14 or newer (a UTF8 database, in any locale)
instead of the SQLite file, and then run several server processes on it: in one container
(`WEB_CONCURRENCY`), in several, or on several hosts behind a load balancer.

Every process serves the web UI, the API and MCP, and runs jobs. A job runs once, in whichever
process takes it first, and at most one job per library runs at a time.

```mermaid
flowchart LR
    lb["Load balancer"] --> p1["ExactDocs process"] & p2["ExactDocs process"] & p3["ExactDocs process"]
    p1 & p2 & p3 --> db[("PostgreSQL<br/>tables, DBOS job steps,<br/>pgvector, pg_search")]
    p1 -.-> d1["own data directory<br/>git work folders, known_hosts"]
    p2 -.-> d2["own data directory"]
    p3 -.-> d3["own data directory"]
```

## When a process or the database fails

- A process that dies with running jobs leaves them to the next process that starts or, after about
  30 s, to any running process, which resumes them at their last completed step. A process that
  starts after a crash waits 15 s before it resumes the jobs the crashed one left, and logs why.
- A database outage or failover of up to about 15 s is waited out.
- A longer outage, or another process taking over a process's executor slot meanwhile, makes that
  process stop taking jobs and stop itself (as `SIGTERM` does) within a few seconds, before anyone
  else can take its jobs over, so that no job runs twice. Run it with a restart policy:
  `restart: unless-stopped` as in the example below, or a Deployment in Kubernetes.

## Connecting

- Set `EXACTDOCS_DATABASE_URL=postgresql://user:password@host:5432/exactdocs`
  (`postgresql+psycopg://` means the same). Percent-encode special characters in the password.
- The role needs to own the database, or at least be able to create tables and a schema in it. It
  does not need `CREATEDB`: DBOS keeps its tables in the schema `dbos` of the same database
  (`EXACTDOCS_DBOS_SYSTEM_SCHEMA`), never in a database of its own.
- `EXACTDOCS_SECRET_KEY` is required, and must be the same in every process. Otherwise each
  process generates its own key and cannot open the credentials another one stored.
- Every process still has its own data directory, for its git work folders and `known_hosts`.
  Nothing in it has to be shared or backed up.

!!! warning "Connect with a session, not a transaction-mode pooler"
    Connect directly to PostgreSQL, or through a pooler in session mode (PgBouncer's
    `pool_mode = session`). A pooler in transaction mode is unsupported: it hands each transaction
    to any server connection, and ExactDocs' jobs (DBOS's `LISTEN`, the executor slots' advisory
    locks) and psycopg's prepared statements need the same session from one statement to the next,
    so jobs would fail at random.

    Supabase's transaction pooler is refused at start, from its URL (see [Supabase](supabase.md)).
    Any other one (a self-hosted PgBouncer on 6432, another provider's, or Supabase's named by its
    IP address) cannot be recognised from the URL. After migrating, each process sets a session
    value in one transaction and reads it back in the next, and logs a WARNING naming the session
    or direct connection to use if the value was lost. That probe can only warn, never prove a
    session: a transaction-mode pooler with one idle server connection keeps the value, so no
    warning is no guarantee. The process starts either way.

## Search on PostgreSQL

The search engine is chosen when a process starts, from what the database offers. `/healthz` names
the one in use in `search_engine`: `fts5` (SQLite), `pg_search` or `postgres_fts`.

- With ParadeDB's `pg_search` extension in the database (the ParadeDB image below installs it),
  search is BM25, as on SQLite. The first start builds its index (`retrieval_search_bm25`). That
  takes a while on a large instance, but it runs `CONCURRENTLY`, so the instance keeps serving and
  importing meanwhile. If it fails, the process logs a WARNING, uses full-text search and tries
  again at its next start. Later starts find the index.
- Without it, search uses PostgreSQL's full-text search (`tsvector`, the `simple` configuration,
  ranked with `ts_rank_cd`, with words cut as SQLite's index cuts them). The log says why: at INFO
  on a server without `pg_search` (managed PostgreSQL such as Supabase), or as a WARNING when the
  server has it but the database does not (`CREATE EXTENSION pg_search CASCADE` adds it).

Both engines pass the shared ranking suite, as SQLite does, and both read the same rows. Adding the
extension needs only a restart, not `exactdocs reindex`. Removing it needs
`DROP EXTENSION pg_search CASCADE` (the BM25 index depends on it), then a restart.

Hybrid search keeps its vectors in the same database with pgvector: one table per embedding model,
with a `vector(<dimensions>)` column, searched exactly (cosine distance, no index). Any number of
dimensions up to pgvector's 16,000 works, including those above the 2,000 an index would allow.

ExactDocs looks for the `vector` extension once per process when an embedding model is configured,
and creates it if it is not in the database yet. Creating it needs a superuser, since pgvector is
not a trusted extension. The ParadeDB image in the example already has it in every new database.
Elsewhere, run `CREATE EXTENSION vector;` as a superuser in the ExactDocs database (managed services
offer it too; on Supabase it goes to the schema `extensions`, which ExactDocs finds), then restart
ExactDocs. Without it, hybrid search answers with BM25 (`fallback_reason:
vector_store_unavailable`), the server logs why, and `/healthz` names the missing extension in
`vector_store_missing`.

## Writes, sign-ins, backups and upgrades

- Writes that must not interleave (storing and activating a version, indexing it) take turns across
  all processes, as on SQLite. Several processes therefore serve more readers but do not import
  faster. A writer that waits more than 30 s for its turn gives up with an error, as SQLite does
  after its own wait.
- The sign-in throttle's counts live in the database (`identity_failed_sign_ins`,
  `identity_known_sign_ins`), so failed sign-ins count the same on every process. They survive a
  restart, and old ones are deleted whenever a new one is written.
- Accounts of an identity provider are checked again with the provider by every process in turn:
  each one claims a batch of the identities that are due, so no identity is checked twice. A
  sign-in started on one process can finish on another, because the attempt is in the database.
- Back up with PostgreSQL's own tools: `pg_dump -Fc exactdocs > exactdocs.dump` (DBOS's job steps
  are in it too), plus `EXACTDOCS_SECRET_KEY`. `exactdocs backup` and `restore` copy a SQLite file
  only. Stop every ExactDocs process before a `pg_restore`, and start them once it is done.
- Upgrade with every process stopped. The new version migrates the schema when its first process
  starts, and older processes only check the schema when they start, so stop them all, then start
  the new version. This also matters when a release changes how jobs run (its notes say so): an
  older process would otherwise keep running jobs the new one cannot resume.

## Example

Several processes on one PostgreSQL database, verified in CI (`deploy/compose.postgres.yaml`):

<!-- compose.postgres.yaml: start -->
```yaml
# ExactDocs on PostgreSQL: several server processes share one database (docs/deployment/postgresql.md).
#   export POSTGRES_PASSWORD=$(openssl rand -hex 24) EXACTDOCS_SECRET_KEY=$(openssl rand -base64 32)
#   docker compose -f compose.postgres.yaml up -d
services:
  db:
    restart: unless-stopped
    # PostgreSQL 17 with pg_search and pgvector; any PostgreSQL 14 or newer works as well.
    image: paradedb/paradedb:0.26.3-pg17@sha256:950f68abebc78e28fd2ecfc8ed915aa29d07b5dd8cba25b2f513ca4e211dda70
    environment:
      POSTGRES_USER: exactdocs
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
      POSTGRES_DB: exactdocs
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U exactdocs -d exactdocs"]
      interval: 2s
      retries: 30
    volumes: ["exactdocs-db:/var/lib/postgresql/data"]
  exactdocs:
    # A process whose executor slot another one took stops itself; this brings it back.
    restart: unless-stopped
    image: ${EXACTDOCS_IMAGE:-ghcr.io/sircypkowskyy/exactdocs:latest}
    depends_on:
      db: { condition: service_healthy }
    environment:
      EXACTDOCS_DATABASE_URL: postgresql://exactdocs:${POSTGRES_PASSWORD}@db:5432/exactdocs
      EXACTDOCS_SECRET_KEY: ${EXACTDOCS_SECRET_KEY:?set EXACTDOCS_SECRET_KEY}
      WEB_CONCURRENCY: "2" # server processes; on PostgreSQL every one serves and runs jobs
      # Sign-in through an OIDC provider (docs/getting-started.md, "Sign in through an identity
      # provider"): the provider in the TOML file ([auth.providers.corp]), its secret from the env.
      # EXACTDOCS_PUBLIC_URL: https://docs.example.com
      # EXACTDOCS_CONFIG_FILE: /run/exactdocs.toml
      # EXACTDOCS_AUTH__PROVIDERS__CORP__CLIENT_SECRET: ${CORP_CLIENT_SECRET}
    ports: ["127.0.0.1:3000:3000"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    volumes: ["exactdocs-data:/data"]
volumes:
  exactdocs-db:
  exactdocs-data:
```
<!-- compose.postgres.yaml: end -->
