# Deployment

ExactDocs ships as one Docker image (and as `uvx exactdocs`) that serves the web UI, the REST API
and MCP from a single process. A small instance needs nothing else: the database is a SQLite file
in the data volume. A team can move the database to PostgreSQL and run several processes on it.

## Image variants

All three variants are built from one Dockerfile, and all three start as a BM25 server until a
model role is configured.

| Tag | Holds | For |
|---|---|---|
| `:<version>`, `:latest` | BM25 on SQLite or PostgreSQL; no model, no ML library | most installs |
| `:<version>-ai`, `:latest-ai` | `exactdocs[ai]`: the hosted and self-hosted model providers, sqlite-vec, pgvector | [AI providers](search.md#ai-providers-and-model-roles) over the network |
| `:<version>-local`, `:latest-local` | `exactdocs[ai,local]` and the two default [local models](search.md#local-models), read-only in `/opt/exactdocs/models` (their licenses, MIT and Apache-2.0, are in its `NOTICE`) | air-gapped instances: hybrid search and reranking with no network |

The `uvx` equivalents are `uvx --from 'exactdocs[ai]' exactdocs serve` and
`uvx --from 'exactdocs[ai,local]' exactdocs serve` (followed by `exactdocs models pull`). Dev builds
carry the same suffixes (`:dev-ai`, `:0.4.0.dev1-local`).

## A single container

This hardened setup works today, and CI runs the image this way. The image runs as UID 10001 and
needs nothing but `/data` and `/tmp` to be writable.

```yaml
# docker-compose.yml
services:
  exactdocs:
    image: ghcr.io/sircypkowskyy/exactdocs:latest
    ports: ["3000:3000"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { cpus: "2", memory: 1g }
    volumes: ["exactdocs-data:/data"]
volumes:
  exactdocs-data:
```

## Behind a reverse proxy

Set these:

- `EXACTDOCS_ALLOWED_HOSTS`: the public host name(s). The server answers only to localhost and the
  names listed here; this is its guard against DNS rebinding.
- `EXACTDOCS_FORWARDED_ALLOW_IPS`: the proxy's own address, so that `X-Forwarded-*` is trusted.
- `EXACTDOCS_SECURE_COOKIES=true`, if TLS ends at a proxy that does not forward
  `X-Forwarded-Proto` from a trusted address. An `https://` `EXACTDOCS_PUBLIC_URL` makes the
  cookies `Secure` too, so with one set you can leave this out.

If people sign in through an identity provider, also set `EXACTDOCS_PUBLIC_URL` to the address
they use, such as `https://docs.example.com` (no path). The redirect URI that ExactDocs sends to
the provider is built from it, never from the request's `Host` header, so it stays right behind
any proxy. The server refuses to start with a provider configured and no public URL (see
[Sign in through an identity provider](getting-started.md#sign-in-through-an-identity-provider)).

If the proxy is not listed in `EXACTDOCS_FORWARDED_ALLOW_IPS`, every client looks like the proxy,
and 5 failed sign-ins from anyone throttle everyone.

!!! warning "List only the proxy"
    Whatever `EXACTDOCS_FORWARDED_ALLOW_IPS` lists can choose the client address the server sees,
    through `X-Forwarded-For`. List only the proxy, not a range such as `172.16.0.0/12`, which
    covers every container on every Docker network of the host.

To pin the proxy's address, give it a fixed one on a network of its own:

```yaml
services:
  proxy:
    networks: { edge: { ipv4_address: 172.30.0.2 } }
  exactdocs:
    environment:
      EXACTDOCS_FORWARDED_ALLOW_IPS: "172.30.0.2"
    networks: [edge]
networks:
  edge:
    ipam: { config: [{ subnet: 172.30.0.0/24 }] }
```

## Behind Cloudflare Access

A common setup publishes ExactDocs through a Cloudflare Tunnel with an Access application in
front. ExactDocs can then trust the identity Access checked, so people do not sign in a second
time and MCP clients need only the Access service-token headers.

1. **Make the origin reachable only through the tunnel.** Run `cloudflared` next to ExactDocs and
   do not publish ExactDocs' port to the host or the internet (no `ports:` in Compose, a
   firewall in front of anything else). Anyone who can reach the origin directly can replay a
   stolen Access token; nobody can forge one, since its signature is checked.
2. **Create a self-hosted Access application** for the public host name. Copy its
   **Application Audience (AUD) tag** (application overview) and note your team domain
   (`https://<team>.cloudflareaccess.com`, under Zero Trust settings).
3. **Configure ExactDocs** (all fields: [Cloudflare Access](configuration.md#cloudflare-access)):

    ```yaml
    services:
      exactdocs:
        environment:
          EXACTDOCS_ALLOWED_HOSTS: "docs.acme.com"
          EXACTDOCS_PUBLIC_URL: "https://docs.acme.com"
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__TEAM_DOMAIN: "https://acme.cloudflareaccess.com"
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__AUDIENCE: '["<aud tag>"]'
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__ADMIN_EMAILS: '["ada@acme.com"]'
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__SERVICE_TOKENS: '{"<client id>.access": "ci-bot"}'
      cloudflared:
        image: cloudflare/cloudflared:latest
        command: tunnel --no-autoupdate run
        environment:
          TUNNEL_TOKEN: ${TUNNEL_TOKEN}
    ```

4. **For MCP clients and scripts**, create an Access **service token**, add a *Service Auth*
   policy for it to the application, create the account it acts as on the **Users** page (for
   example `ci-bot`, then give it library roles), and map the token's client ID to that account
   in `service_tokens`. See [MCP behind Cloudflare Access](mcp.md#behind-cloudflare-access).

What people see: after the Access login, the web UI opens signed in, with no sign-in form. The
**Account** page says the sign-in comes from Cloudflare Access, and **Sign out** goes to
`<team_domain>/cdn-cgi/access/logout`, which ends the Access session too (ending only the
ExactDocs session would sign the browser straight back in). The local admin from the setup keeps
working with its password, for example from inside the network.

## Health checks

Two probes answer `GET` and `HEAD` without sign-in, even before the first account exists, for
Docker, Kubernetes or a load balancer:

| Path | Answers | Use it for |
|---|---|---|
| `/healthz` | `200` while the process runs, whatever the database does, within about 0.3 s: `status`, `version`, `database_reachable` and, when the database answered in time, `schema_revision`, `search_index_format`, `reindex_required`, `search_engine` (`null` when unknown) and `vector_store_missing` (the extension hybrid search needs and cannot load once an embedding model is configured, `sqlite-vec` or `vector`; `null` otherwise) | liveness: restart the process when it stops answering |
| `/readyz` | `200 {"status": "ready"}` when the database file exists, answers within 2 s and is at this version's schema; else `503 {"status": "not_ready", "reason": ...}` | readiness: send traffic only while it is ready |

`/api/health` is an alias of `/healthz`, kept for existing clients. Neither probe creates a missing
database file (an existing empty one gets SQLite's header and WAL files on connect). To wait for a
starting instance, poll `/readyz`: liveness answers before the database does.

```yaml
livenessProbe:  {httpGet: {path: /healthz, port: 3000}, timeoutSeconds: 1, periodSeconds: 10}
readinessProbe: {httpGet: {path: /readyz, port: 3000}, timeoutSeconds: 3, periodSeconds: 10}
```

The probes answer whatever the `Host` header says, so a Kubernetes `httpGet` probe, which sends the
pod IP, needs no extra header. Only exact `GET` and `HEAD` requests on these three paths skip the
DNS-rebinding guard, and `/healthz` then answers just `{"status": "ok"}`. The version and the
database details go only to a `Host` the instance trusts (`localhost` or
`EXACTDOCS_ALLOWED_HOSTS`).

The Docker image's `HEALTHCHECK` asks `/readyz`, so `docker compose`'s
`depends_on: condition: service_healthy` waits for a usable database. Plain Docker only marks the
container unhealthy. Docker Swarm, or an autoheal sidecar, restarts an unhealthy container, so
there a database outage longer than a few checks turns into restarts. With SQLite on a local
volume, that is what you want: a restart reopens the file.

??? note "How a probe waits for a stuck database"
    A probe stops waiting for the database when its time budget is up, even while a statement still
    runs. That check finishes in the background, and later probes wait for it instead of starting
    another, so however often they are called, a stuck database holds at most one connection for
    each probe. A probe may therefore get the result of a check an earlier probe started.

    A stopping instance waits up to 2 s for such a check, then cancels it and waits up to 2 s more
    before it closes its database connections. A statement stuck in the driver's thread cannot be
    interrupted: if the check still runs after those 4 s, the instance logs a warning and stops
    without it, and that connection may be finalized, unclosed, later.

## Upgrading

On PostgreSQL, stop every process first (see [PostgreSQL](#postgresql)).

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

### External index backends

With `EXACTDOCS_SEARCH_BACKEND` or `EXACTDOCS_VECTOR_BACKEND` set to an external backend (see
[Configuration](configuration.md#search-and-ai)), the backend holds a copy of each version that
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

## Backup and restore

This section is about the SQLite database. On PostgreSQL, use `pg_dump` (see
[PostgreSQL](#postgresql)); `exactdocs backup` refuses a non-SQLite `EXACTDOCS_DATABASE_URL`.

`exactdocs backup` writes one archive of the instance while the server keeps serving. It holds:

- a consistent snapshot of the database, taken with SQLite's online backup API so writers are not
  stopped: libraries, versions, articles, images, settings, accounts and API tokens;
- DBOS's durable job steps (`jobs.sqlite`), so an import that was running resumes after a restore;
- `known_hosts`.

Run it where the server runs:

```bash
docker exec exactdocs exactdocs backup - > exactdocs-$(date +%F).tar.gz   # or a path in the volume
uvx exactdocs backup ~/exactdocs-backup.tar.gz
```

`exactdocs restore` puts an archive into a data directory that holds no instance yet (it refuses to
overwrite one), with the server stopped. It checks every file against the archive's checksums, then
migrates the schema: a backup from an older release is brought up to this version, and one from a
newer release is refused before anything is written. Then start the server as usual.

```bash
docker run --rm -v exactdocs-data:/data -v "$PWD:/backup:ro" \
  ghcr.io/sircypkowskyy/exactdocs:latest restore /backup/exactdocs-2026-11-07.tar.gz
uvx exactdocs restore ~/exactdocs-backup.tar.gz      # into EXACTDOCS_DATA_DIR
```

!!! warning "The secret key is not in the archive"
    Unless you pass `--include-secret-key`, the archive leaves the secret key out. Whoever holds the
    archive then cannot read the encrypted repository credentials in it, and the restored instance
    needs the original key to read them: set the same `EXACTDOCS_SECRET_KEY`, or copy the old
    `secret.key` into the new data directory (before or after the restore, but before `serve`).
    Without the key every library keeps serving its docs, and adding a version asks for its
    credential again (`credentials_required`).

    With `--include-secret-key` the archive opens those credentials by itself, so store it as
    carefully as the key.

Archives and restored files are created with mode `0600`; they also hold the password and token
hashes. Files a running server creates itself, such as `exactdocs.db`, are `0644` inside the `0700`
data directory, and a restored instance's are `0600`. Both keep other users out.

A backup stages its copies next to the archive (for `-`, in the data directory) before writing it,
so that file system needs room for about two copies of the database while it runs. A backup that
was killed leaves a `.exactdocs-backup-*` folder behind; the next backup removes those older than a
day. A restore checks each file's size against its manifest, and the free space (keeping 64 MiB to
spare), before it writes anything.

## PostgreSQL

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

### When a process or the database fails

- A process that dies with running jobs leaves them to the next process that starts or, after about
  30 s, to any running process, which resumes them at their last completed step. A process that
  starts after a crash waits 15 s before it resumes the jobs the crashed one left, and logs why.
- A database outage or failover of up to about 15 s is waited out.
- A longer outage, or another process taking over a process's executor slot meanwhile, makes that
  process stop taking jobs and stop itself (as `SIGTERM` does) within a few seconds, before anyone
  else can take its jobs over, so that no job runs twice. Run it with a restart policy:
  `restart: unless-stopped` as in the example below, or a Deployment in Kubernetes.

### Connecting

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

    Supabase's transaction pooler is refused at start, from its URL (see [Supabase](#supabase)).
    Any other one (a self-hosted PgBouncer on 6432, another provider's, or Supabase's named by its
    IP address) cannot be recognised from the URL. After migrating, each process sets a session
    value in one transaction and reads it back in the next, and logs a WARNING naming the session
    or direct connection to use if the value was lost. That probe can only warn, never prove a
    session: a transaction-mode pooler with one idle server connection keeps the value, so no
    warning is no guarantee. The process starts either way.

### Search on PostgreSQL

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

### Writes, sign-ins, backups and upgrades

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

### Example

Several processes on one PostgreSQL database, verified in CI (`deploy/compose.postgres.yaml`):

<!-- compose.postgres.yaml: start -->
```yaml
# ExactDocs on PostgreSQL: several server processes share one database (docs/deployment.md, "PostgreSQL").
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

## Supabase

ExactDocs runs on a [Supabase](https://supabase.com) project's database as PostgreSQL without
`pg_search`. It uses only the database: no Supabase SDK, Auth or Storage. Everything in
[PostgreSQL](#postgresql) applies. Search is PostgreSQL's full-text search
(`search_engine: postgres_fts`), which passes the same ranking suite as SQLite, and hybrid search
keeps its vectors in pgvector from the `extensions` schema. CI runs the scenarios below and the
ranking suite on the `supabase/postgres` image, over SSL, with the role this setup creates.

### 1. Set up a role and schemas

Run this once in the SQL editor, as `postgres`. ExactDocs gets a login role without `CREATEDB`, its
tables in the schema `exactdocs` and DBOS's in the schema `dbos` (the Data API exposes neither
unless you add it there), and pgvector's `vector` in `extensions`. The role cannot create that
extension itself, because Supabase lets only `postgres` do it.

<!-- supabase.sql: start -->
```sql
-- ExactDocs on Supabase (docs/deployment.md, "Supabase"): run once in the SQL editor, as `postgres`.
-- A login role of its own, without CREATEDB, owning one schema for ExactDocs' tables and one
-- for DBOS's. Neither schema is exposed by Supabase's Data API unless you add it there.
-- Then give the role a password of your own, in a statement of its own (docs/deployment.md, step 2).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE ROLE exactdocs LOGIN NOCREATEDB NOCREATEROLE; -- no password yet: it cannot sign in
GRANT exactdocs TO postgres; -- lets `postgres` hand the schemas to it (PostgreSQL 16 and newer)
CREATE SCHEMA exactdocs AUTHORIZATION exactdocs;
CREATE SCHEMA dbos AUTHORIZATION exactdocs;
GRANT USAGE ON SCHEMA extensions TO exactdocs; -- pgvector's type and operators
ALTER ROLE exactdocs SET search_path = exactdocs, extensions;
```
<!-- supabase.sql: end -->

### 2. Give the role a password

Do this in a statement of its own. The script sets no password, so the role cannot sign in until
you do, and a pasted script never leaves a known password behind. Generate one
(`openssl rand -hex 24`) and run, with it in place of the placeholder:

```sql
ALTER ROLE exactdocs PASSWORD '<the generated password>';
```

From `psql`, keep it out of your shell history with `\set password <the generated password>` and
then `ALTER ROLE exactdocs PASSWORD :'password';`.

### 3. Connect with a session

Never use the pooler's transaction mode: ExactDocs' jobs (DBOS's `LISTEN`, the executor slots'
advisory locks) and psycopg's prepared statements need the same session from one statement to the
next. A URL on port 6543 of a Supabase host (Supavisor's or the dedicated pooler's transaction
mode) is refused at start, with a message that says so. The pooler named by its IP address cannot
be recognised from the URL and only gets the start-up probe's WARNING (see
[PostgreSQL](#connecting)), which cannot catch every case. Use one of these:

| Connection | URL | Notes |
|---|---|---|
| Direct | `postgresql://exactdocs:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require` | IPv6 only unless the project has the IPv4 add-on: a host or Docker network without IPv6 cannot connect |
| Session pooler (Supavisor in session mode) | `postgresql://exactdocs.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require` | IPv4 and IPv6; the same host as the transaction pooler, on port 5432, with the project in the user name. Each ExactDocs process keeps a few connections open (a pool, its executor slot and DBOS's), so size the pooler's session limit for every process |

### 4. Keep `sslmode=require`

Use `sslmode=require` (or `verify-full` with Supabase's CA certificate), in the URL or in
`PGSSLMODE`. Without either on a Supabase host, the server logs a WARNING that the connection may
not be encrypted.

### 5. Start ExactDocs

Set `EXACTDOCS_SECRET_KEY` as for any PostgreSQL instance and start ExactDocs. `/api/health`
reports `search_engine: postgres_fts`, and with an embedding model configured,
`vector_store_missing` stays empty. Without `GRANT USAGE ON SCHEMA extensions`, the log says that
pgvector is in a schema the role may not use (and which `GRANT` fixes), `/api/health` names
`vector` in `vector_store_missing`, and hybrid search answers with BM25.

Back up with Supabase's backups or with `pg_dump -n exactdocs -n dbos`.

## Observability

### What leaves the server

ExactDocs makes no outbound connections you did not configure: only your git hosts, your model
endpoints and, if you turn it on, your trace collector. There are no analytics and no update
checks. The Prometheus endpoint, if you turn it on, waits to be scraped and sends nothing.

A test checks this:
[`test_no_outbound.py`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/tests/bootstrap/test_no_outbound.py).
An import over git and HTTP, REST search and both MCP search tools run with FastMCP's update check
forced off and no telemetry configured, then again with telemetry on and a collector on loopback,
in a process of their own. What that proves, exactly:

- Observed: every Python socket and name lookup goes through a guard that refuses anything but
  loopback. Where unprivileged user namespaces exist (`unshare -rn`), the same loop and a redirect
  to another host also run in a network namespace with only loopback, so the kernel itself blocks
  anything else, git included. Elsewhere that check is skipped.
- Only pinned: where it is skipped, git (a child process) is checked by what it was told. The only
  URL is the fixture server, the protocols are restricted, and no ssh is started.
- git follows an HTTP redirect from your git host and honours `HTTP(S)_PROXY` and `ALL_PROXY` when
  they are set, in which case traffic goes to that proxy. The test runs without proxy variables.
- With telemetry off, a fresh process started with the defaults (and a collector named in
  `OTEL_*`) sets up no OpenTelemetry SDK provider. With telemetry on, the spans reach the collector
  and nothing else is contacted, and
  [`test_telemetry.py`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/tests/bootstrap/test_telemetry.py)
  checks that no exported byte holds the query text.

The web UI bundles its fonts, and `pnpm build` fails if the built HTML, CSS or any JS chunk names
another host ([`web/scripts/check-dist.mjs`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/web/scripts/check-dist.mjs)).

### Traces and metrics over OTLP

With `EXACTDOCS_TELEMETRY=otlp` and `OTEL_EXPORTER_OTLP_ENDPOINT` pointing at your collector (for
example `http://otel-collector:4318`), ExactDocs exports OpenTelemetry traces and metrics over
OTLP/HTTP with the plain OpenTelemetry SDK. The other standard `OTEL_*` variables (headers, service
name, resource attributes, sampling) apply. Nothing is written to the console, because stdout
belongs to stdio MCP. When telemetry is off (the default), the SDK is not even imported, and
setting the `OTEL_*` variables alone exports nothing.

The metrics are the ones listed under [Prometheus metrics](#prometheus-metrics), under their
OpenTelemetry names (`http.server.request.duration`, `exactdocs.search.duration`,
`exactdocs.job.duration`...). The spans:

| Span | Where from |
|---|---|
| `GET /api/v1/libraries/{owner}/{repo}/search`, ... | every request (FastAPI's built-in OpenTelemetry), except the health checks |
| `tools/call search_docs`, ... | every MCP request, named after the tool (FastMCP) |
| `retrieval.search_docs`, `retrieval.search_all_libraries`, `retrieval.query_docs`, `retrieval.resolve_library_id` | every search, with `exactdocs.retrieval.mode`, library and ref |
| `retrieval.<search>.version`, `.rank`, `.chunks` (`.versions` for the cross-library ones) | each stage of a search: finding the version, ranking, loading the chunks |
| `rerank`, `judge`, `agent` stages | the AI steps of a search; see [Search and AI models](search.md) |
| `ingestion.import`, `ingestion.refresh` (a branch sync), `ingestion.reprocess`, `ingestion.rechunk`, `ingestion.retag`, `ingestion.collect` | every job, with its library and version |

Query text stays out unless you set `EXACTDOCS_TELEMETRY_QUERY_TEXT=true`:

- no span carries it;
- the values of `q`, `query`, `libraryName` and `url` (a repository URL may hold a token) in
  request URLs are replaced with `REDACTED`;
- an error keeps its exception type but not its message or stack trace, which can quote the input
  (a refused, over-long query is named in its validation error);
- MCP spans also lose FastMCP's `enduser.id` and `enduser.scope` (the calling token's client ID
  and scopes), which would tie the searches to a person.

LLM calls are traced without their prompts and answers (pydantic-ai's `include_content=False`).

!!! warning "Access logs are not covered"
    uvicorn's access log on stdout (`GET /api/v1/...?q=... 200`) holds the full URL, query text
    included, whatever the telemetry settings say. If your container logs are shipped somewhere,
    filter those lines (logger `uvicorn.access`) in your log pipeline.

### Prometheus metrics

With `EXACTDOCS_METRICS=true`, `GET /metrics` serves the Prometheus text format, from an
OpenTelemetry metric reader that only answers scrapes. When it is off (the default), there is no
`/metrics` (404) and `prometheus_client` is not imported. With `EXACTDOCS_TELEMETRY=otlp` as well,
it is a second reader on the same meter provider, and the collector gets the same metrics.

Point Prometheus at the address and Host name you serve, with the token in a file if you set
`EXACTDOCS_METRICS_TOKEN`:

```yaml
scrape_configs:
  - job_name: exactdocs
    static_configs: [{targets: ["exactdocs:3000"]}]   # the Host must be allowed (EXACTDOCS_ALLOWED_HOSTS)
    authorization:                                    # only with EXACTDOCS_METRICS_TOKEN
      credentials_file: /etc/prometheus/exactdocs-metrics-token
```

| Metric (Prometheus name) | Labels |
|---|---|
| `http_server_request_duration_seconds` (histogram), `http_server_active_requests` | `http_route` (the route template, such as `/api/v1/libraries/{owner}/{repo}/search`, or `/mcp`), `http_request_method`, `http_response_status_code`, `error_type` |
| `exactdocs_search_duration_seconds` (histogram) | `exactdocs_search` (`search_docs`, `search_all_libraries`, `query_docs`, `resolve_library_id`), `exactdocs_search_stage` (`total`, `version`/`versions`, `rank`, `chunks`), `exactdocs_retrieval_mode`, `error_type` |
| `exactdocs_job_duration_seconds` (histogram) | `exactdocs_job_kind`: `import`, `refresh` (a branch sync), `reprocess`, `rechunk`, `retag`, `collect`; `error_type` when it failed |
| `exactdocs_ai_fallbacks_total`, `exactdocs_ai_cache_hits_total` | searches a cheaper mode answered, by mode and reason; searches whose LLM step a cache answered, by cache and mode |
| `gen_ai_client_token_usage` and pydantic-ai's cost metrics | LLM usage: anything recorded through OpenTelemetry's global meter appears here |
| `process_*`, `python_*`, `target_info` | the process (memory, CPU, open files), the Python runtime, and the service name and version |

`/metrics` renders `prometheus_client`'s default registry on purpose: besides ExactDocs' own
metrics, it holds the process and Python runtime collectors. A dependency that registered its own
Prometheus collectors there would show up too; none does today. Scrapes and the health probes are
not counted as requests.

!!! warning "Who may scrape"
    `/metrics` takes no account sign-in, since Prometheus has none. The metrics carry nothing a user
    typed or owns (no query text, library, version, user name or token client ID, whatever
    `EXACTDOCS_TELEMETRY_QUERY_TEXT` says; requests are labelled with the route template, never the
    path). They do tell how busy the instance is, its error types, the process's memory and open
    files, and which Python and ExactDocs versions it runs.

    So set `EXACTDOCS_METRICS_TOKEN` whenever the port is reachable beyond a network you trust. A
    scrape without `Authorization: Bearer <token>` then gets 401 (compared in constant time).
    Without the token, anyone who reaches the port can scrape. The Host allowlist applies either
    way (an unknown `Host` gets 400), but it is a DNS-rebinding guard, not access control; blocking
    `/metrics` at your reverse proxy also works.
