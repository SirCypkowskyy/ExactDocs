# Observability

!!! abstract "TL;DR"

    - ExactDocs makes no outbound connection you did not configure, and a test checks it.
    - Traces and metrics go over OTLP with `EXACTDOCS_TELEMETRY=otlp`; query text stays out by default.
    - `EXACTDOCS_METRICS=true` serves Prometheus metrics at `/metrics`.
    - uvicorn's access log still holds full URLs: filter it in your log pipeline.

<figure class="xd-shot" markdown>

![The operator overview with counters for libraries, jobs, AI spend and reads, and charts of reads and AI spend per day](../assets/screenshots/overview-light.webp#only-light){ loading=lazy }
![The operator overview with counters for libraries, jobs, AI spend and reads, and charts of reads and AI spend per day](../assets/screenshots/overview-dark.webp#only-dark){ loading=lazy }

<figcaption>The operator overview: counters and daily charts for the whole instance.</figcaption>

</figure>

## What leaves the server

ExactDocs makes no outbound connections you did not configure: only your git hosts, your model
endpoints and, if you turn it on, your trace collector; through your proxy when you set one. There are no analytics and no update
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
- git follows an HTTP redirect from your git host. With a proxy configured
  ([Behind a corporate proxy](corporate-proxy.md)), traffic goes to that proxy, and only
  there: the test runs the loop again with the proxy variables naming a proxy on loopback and the
  repository under a name only that proxy knows, and finds every connection, git's included (in
  the network namespace, by the kernel), went through it.
- With telemetry off, a fresh process started with the defaults (and a collector named in
  `OTEL_*`) sets up no OpenTelemetry SDK provider. With telemetry on, the spans reach the collector
  and nothing else is contacted, and
  [`test_telemetry.py`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/tests/bootstrap/test_telemetry.py)
  checks that no exported byte holds the query text.

The web UI bundles its fonts, and `pnpm build` fails if the built HTML, CSS or any JS chunk names
another host ([`web/scripts/check-dist.mjs`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/web/scripts/check-dist.mjs)).

## Traces and metrics over OTLP

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
| `rerank`, `judge`, `agent` stages | the AI steps of a search; see [Search and AI models](../search/index.md) |
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

## Prometheus metrics

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
| `http_server_request_duration_seconds` (histogram), `http_server_active_requests` | `http_route` (the route template, such as `/api/v1/libraries/{owner}/{repo}/search`, or `/mcp`),<br/>`http_request_method`,<br/>`http_response_status_code`, `error_type` |
| `exactdocs_search_duration_seconds` (histogram) | `exactdocs_search` (`search_docs`, `search_all_libraries`, `query_docs`, `resolve_library_id`),<br/>`exactdocs_search_stage` (`total`, `version`/`versions`, `rank`, `chunks`),<br/>`exactdocs_retrieval_mode`, `error_type` |
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
