# Supabase

!!! abstract "TL;DR"

    - ExactDocs runs on a Supabase database as PostgreSQL without `pg_search`, using only the database.
    - Create a role and two schemas once, then give the role a password.
    - Use the direct connection or the session pooler, with `sslmode=require`; port 6543 is refused.

ExactDocs runs on a [Supabase](https://supabase.com) project's database as PostgreSQL without
`pg_search`. It uses only the database: no Supabase SDK, Auth or Storage. Everything in
[PostgreSQL](postgresql.md) applies. Search is PostgreSQL's full-text search
(`search_engine: postgres_fts`), which passes the same ranking suite as SQLite, and hybrid search
keeps its vectors in pgvector from the `extensions` schema. CI runs the scenarios below and the
ranking suite on the `supabase/postgres` image, over SSL, with the role this setup creates.

## 1. Set up a role and schemas

Run this once in the SQL editor, as `postgres`. ExactDocs gets a login role without `CREATEDB`, its
tables in the schema `exactdocs` and DBOS's in the schema `dbos` (the Data API exposes neither
unless you add it there), and pgvector's `vector` in `extensions`. The role cannot create that
extension itself, because Supabase lets only `postgres` do it.

<!-- supabase.sql: start -->
```sql
-- ExactDocs on Supabase (docs/deployment/supabase.md): run once in the SQL editor, as `postgres`.
-- A login role of its own, without CREATEDB, owning one schema for ExactDocs' tables and one
-- for DBOS's. Neither schema is exposed by Supabase's Data API unless you add it there.
-- Then give the role a password of your own, in a statement of its own (docs/deployment/supabase.md, step 2).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE ROLE exactdocs LOGIN NOCREATEDB NOCREATEROLE; -- no password yet: it cannot sign in
GRANT exactdocs TO postgres; -- lets `postgres` hand the schemas to it (PostgreSQL 16 and newer)
CREATE SCHEMA exactdocs AUTHORIZATION exactdocs;
CREATE SCHEMA dbos AUTHORIZATION exactdocs;
GRANT USAGE ON SCHEMA extensions TO exactdocs; -- pgvector's type and operators
ALTER ROLE exactdocs SET search_path = exactdocs, extensions;
```
<!-- supabase.sql: end -->

## 2. Give the role a password

Do this in a statement of its own. The script sets no password, so the role cannot sign in until
you do, and a pasted script never leaves a known password behind. Generate one
(`openssl rand -hex 24`) and run, with it in place of the placeholder:

```sql
ALTER ROLE exactdocs PASSWORD '<the generated password>';
```

From `psql`, keep it out of your shell history with `\set password <the generated password>` and
then `ALTER ROLE exactdocs PASSWORD :'password';`.

## 3. Connect with a session

Never use the pooler's transaction mode: ExactDocs' jobs (DBOS's `LISTEN`, the executor slots'
advisory locks) and psycopg's prepared statements need the same session from one statement to the
next. A URL on port 6543 of a Supabase host (Supavisor's or the dedicated pooler's transaction
mode) is refused at start, with a message that says so. The pooler named by its IP address cannot
be recognised from the URL and only gets the start-up probe's WARNING (see
[PostgreSQL](postgresql.md#connecting)), which cannot catch every case. Use one of these:

| Connection | URL | Notes |
|---|---|---|
| Direct | `postgresql://exactdocs:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require` | IPv6 only unless the project has the IPv4 add-on:<br/>a host or Docker network without IPv6 cannot connect |
| Session pooler (Supavisor in session mode) | `postgresql://exactdocs.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require` | IPv4 and IPv6.<br/>The same host as the transaction pooler, on port 5432, with the project in the user name.<br/>Each ExactDocs process keeps a few connections open (a pool, its executor slot and DBOS's), so size the pooler's session limit for every process |

## 4. Keep `sslmode=require`

Use `sslmode=require` (or `verify-full` with Supabase's CA certificate), in the URL or in
`PGSSLMODE`. Without either on a Supabase host, the server logs a WARNING that the connection may
not be encrypted.

## 5. Start ExactDocs

Set `EXACTDOCS_SECRET_KEY` as for any PostgreSQL instance and start ExactDocs. `/api/health`
reports `search_engine: postgres_fts`, and with an embedding model configured,
`vector_store_missing` stays empty. Without `GRANT USAGE ON SCHEMA extensions`, the log says that
pgvector is in a schema the role may not use (and which `GRANT` fixes), `/api/health` names
`vector` in `vector_store_missing`, and hybrid search answers with BM25.

Back up with Supabase's backups or with `pg_dump -n exactdocs -n dbos`.
