# Observability and usage counts

!!! abstract "TL;DR"

    - Telemetry is off by default; `EXACTDOCS_TELEMETRY=otlp` exports traces and metrics to your collector.
    - Query text stays out of traces unless `EXACTDOCS_TELEMETRY_QUERY_TEXT=true`.
    - `EXACTDOCS_METRICS=true` serves `/metrics`; set `EXACTDOCS_METRICS_TOKEN` when the port is reachable beyond a network you trust.
    - Usage is counted per day, never with a query or text; the people leaderboard is off by default.

## Observability

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_TELEMETRY` | `off` | `otlp` exports traces and metrics over OTLP/HTTP to your OpenTelemetry collector, named by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `..._METRICS_ENDPOINT`).<br/>A signal with no endpoint, or with `OTEL_TRACES_EXPORTER` / `OTEL_METRICS_EXPORTER` set to `none`, is not exported |
| `EXACTDOCS_TELEMETRY_QUERY_TEXT` | `false` | Keep the text of search queries in the traces.<br/>When off, it is left out of every span and redacted from request URLs |
| `EXACTDOCS_METRICS` | `false` | `true` serves Prometheus metrics at `/metrics` (requests, searches, imports, syncs, AI usage), behind the Host allowlist.<br/>`serve` only, not `--stdio` |
| `EXACTDOCS_METRICS_TOKEN` | unset | A bearer token that `/metrics` requires (`Authorization: Bearer <token>`, else 401).<br/>Unset, a scrape needs no credentials.<br/>Surrounding whitespace and newlines are trimmed, as Prometheus trims its `credentials_file`.<br/>Set it whenever the port is reachable beyond a network you trust |

[Observability](../deployment/observability.md) explains what each of these exports.

## Usage counts and leaderboards

ExactDocs counts reads, searches and agent answers per UTC day, account, API token, library and
operation (#510): counts only, never a query, a path or any text. Operators read them at
`GET /api/v1/stats/usage`, everyone their own at `GET /api/v1/account/usage`, and the leaderboards
at `GET /api/v1/stats/leaderboard` (see [REST API](../rest-api/usage.md)). Per-person usage is monitoring
data under the GDPR, hence the opt-in for people and the bounded retention. The `[usage]` table
of the TOML file takes the same settings.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_USAGE__PEOPLE_LEADERBOARD` | `false` | Turn the people leaderboard on.<br/>Even then it ranks, and operators' usage reports name, only people who opted in (the `leaderboard_opt_in` interface preference, off by default); everyone else counts in totals only.<br/>Off, nobody is shown by name to anyone, operators included.<br/>The libraries leaderboard is always on |
| `EXACTDOCS_USAGE__RETENTION_MONTHS` | `13` | How many months of daily counts are kept (1 to 120).<br/>Every night the days before it are deleted: 13 keeps a year and the month before it |

<figure class="xd-shot" markdown>

![The leaderboard ranking libraries by searches this month, with the note that people are not ranked on this instance](../assets/screenshots/leaderboard-light.webp#only-light){ loading=lazy }
![The leaderboard ranking libraries by searches this month, with the note that people are not ranked on this instance](../assets/screenshots/leaderboard-dark.webp#only-dark){ loading=lazy }

<figcaption>The leaderboard by searches this month. This instance does not rank people.</figcaption>

</figure>
