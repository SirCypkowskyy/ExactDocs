# Detailed setup

!!! abstract "TL;DR"

    - A step-by-step walk through a production-like instance, each step linking to its reference page.
    - The order: data and database, secret key, network, sign-in, models, telemetry, backups.
    - Every step is optional; skip the ones your instance does not need.

## 1. Data directory and database

- Keep `EXACTDOCS_DATA_DIR` on a volume. It holds the SQLite database, the generated secret key,
  `known_hosts`, fetch caches and `jobs.sqlite`.
- For several server processes, move the database to PostgreSQL with
  `EXACTDOCS_DATABASE_URL=postgresql://user:password@host:5432/exactdocs`
  (see [PostgreSQL](../deployment/postgresql.md)). Every process still has a data directory of its own.

Reference: [Storage and database](storage.md).

## 2. Secret key

- Generate one with `openssl rand -base64 32` and set `EXACTDOCS_SECRET_KEY`, so the key lives
  outside the data volume.
- On PostgreSQL this is required, with the same value in every process.
- Without the key, the stored credentials cannot be read.

Reference: [The secret key](security.md#the-secret-key).

## 3. Network

- `EXACTDOCS_ALLOWED_HOSTS`: the public host names.
- `EXACTDOCS_FORWARDED_ALLOW_IPS`: the reverse proxy's own address, and nothing wider.
- `EXACTDOCS_PUBLIC_URL`: the URL people use, without a path.
- `EXACTDOCS_HTTPS_PROXY`, `EXACTDOCS_NO_PROXY` and `EXACTDOCS_CA_BUNDLE` (or the standard
  variables) when the only way out is a forward proxy.

Reference: [Security](security.md), [Outbound connections](outbound.md);
how-to: [Behind a reverse proxy](../deployment/reverse-proxy.md),
[Behind a corporate proxy](../deployment/corporate-proxy.md).

## 4. Sign-in

- Put the providers in a TOML file named by `EXACTDOCS_CONFIG_FILE`, as `[auth.providers.<name>]`
  tables, and their client secrets in the environment or a `client_secret_file`.
- Register `<public_url>/api/v1/auth/<name>/callback` at each provider.
- Decide who gets in (`allowed_groups`, or `allow_any_user = true`) and who is an admin
  (`admin_groups`).
- Optionally limit who may create libraries with `[auth.library_creation]`.

Reference: [Sign-in and access](sign-in.md); a complete example is in
[Getting started](../getting-started.md#sign-in-through-an-identity-provider).

## 5. Models

- Configure provider profiles and the `embedding`, `reranker`, `llm` and `judge` roles (an `-ai`
  or `-local` image, or the `exactdocs[ai]` extra).
- Choose the default mode with `EXACTDOCS_AI__MODE`, for example `hybrid`.
- Set `[ai.budgets]` before you let models spend.

Reference: [Search and AI settings](ai.md); how it works:
[Search and AI models](../search/index.md); which setup to pick:
[Recommended defaults](../benchmark/defaults.md).

## 6. Telemetry and metrics

- `EXACTDOCS_TELEMETRY=otlp` with `OTEL_EXPORTER_OTLP_ENDPOINT` exports traces and metrics.
- `EXACTDOCS_METRICS=true` serves `/metrics`; add `EXACTDOCS_METRICS_TOKEN` when the port is
  reachable beyond a network you trust.

Reference: [Observability and usage counts](observability.md); what each exports:
[Observability](../deployment/observability.md).

## 7. Probes, backups and upgrades

- Point liveness at `/healthz` and readiness at `/readyz`
  ([Health checks](../deployment/health-checks.md)).
- Back up with `exactdocs backup` on SQLite, or `pg_dump` on PostgreSQL, and keep the secret key
  apart ([Backup and restore](../deployment/backup.md)).
- Read [Upgrading](../deployment/upgrading.md) before the first upgrade.
