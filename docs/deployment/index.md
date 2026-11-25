# Deployment

!!! abstract "TL;DR"

    - One image (or `uvx exactdocs`) serves the web UI, the REST API and MCP from one process.
    - A small instance needs nothing else: SQLite in the data volume.
    - Pick the image variant by the models you want: none, over the network, or local.
    - A team can move to PostgreSQL and run several processes.

ExactDocs ships as one Docker image (and as `uvx exactdocs`) that serves the web UI, the REST API
and MCP from a single process. A small instance needs nothing else: the database is a SQLite file
in the data volume. A team can move the database to PostgreSQL and run several processes on it.

## Which page do I need

| Stage | Page | What it covers |
|---|---|---|
| Quick start | [Quick start](quick-start.md) | One hardened container, or `uvx` |
| Production | [Behind a reverse proxy](reverse-proxy.md) | Allowed hosts, trusted proxies, Cloudflare Access |
| Production | [Behind a corporate proxy](corporate-proxy.md) | Forward proxies, company CAs, git over SSH |
| Production | [PostgreSQL](postgresql.md) | Several processes on one database |
| Production | [Supabase](supabase.md) | PostgreSQL on a Supabase project |
| Operations | [Health checks](health-checks.md) | Liveness and readiness probes |
| Operations | [Backup and restore](backup.md) | Archives of a SQLite instance |
| Operations | [Upgrading](upgrading.md) | New versions, reindexing, index backends |
| Operations | [Observability](observability.md) | What leaves the server, OTLP, Prometheus |

Every setting named in this section is listed under [Configuration](../configuration/index.md).

## Image variants

All three variants are built from one Dockerfile, and all three start as a BM25 server until a
model role is configured.

| Tag | Holds | For |
|---|---|---|
| `:<version>`, `:latest` | BM25 on SQLite or PostgreSQL; no model, no ML library | most installs |
| `:<version>-ai`, `:latest-ai` | `exactdocs[ai]`: the hosted and self-hosted model providers, sqlite-vec, pgvector | [AI providers](../search/providers.md) over the network |
| `:<version>-local`, `:latest-local` | `exactdocs[ai,local]` and the two default [local models](../search/local-models.md), read-only in `/opt/exactdocs/models`<br/>(their licenses, MIT and Apache-2.0, are in its `NOTICE`) | air-gapped instances: hybrid search and reranking with no network |

The `uvx` equivalents are `uvx --from 'exactdocs[ai]' exactdocs serve` and
`uvx --from 'exactdocs[ai,local]' exactdocs serve` (followed by `exactdocs models pull`). Dev builds
carry the same suffixes (`:dev-ai`, `:0.4.0.dev1-local`).
