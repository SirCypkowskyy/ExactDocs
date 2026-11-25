# Telemetry

!!! abstract "TL;DR"

    - Off by default, and then nothing is set up: only the OpenTelemetry *API* is imported, which
      records nothing.
    - `EXACTDOCS_TELEMETRY=otlp` exports traces and metrics over OTLP/HTTP; `EXACTDOCS_METRICS`
      adds a Prometheus `GET /metrics` route.
    - Query text, exception messages, prompts and model output are scrubbed before export.
      Metric attributes never name the query, library, version or caller.

Off by default, and then nothing is set up: only the OpenTelemetry *API* is imported (FastAPI,
FastMCP and DBOS use it too), which records nothing without an SDK.

With `EXACTDOCS_TELEMETRY=otlp` or `EXACTDOCS_METRICS`, `bootstrap/telemetry.py:start_telemetry`
(called by `create_app` and `serve --stdio`) loads `bootstrap/otel_sdk.py`, which sets up the plain
OpenTelemetry SDK:

- for OTLP, a tracer and a meter provider exporting over OTLP/HTTP to the collector the
  `OTEL_EXPORTER_OTLP_*` variables name, never to the console;
- for metrics, a Prometheus reader on the meter provider.

A process's providers are set once and cannot be replaced, so each test that turns telemetry on runs
in a process of its own.

!!! note "Why not Logfire"

    The Telemetry decision named Logfire as the SDK. It was dropped in #87: its pydantic plugin
    loaded into every process, crashed on a malformed `pyproject.toml` in the working directory and
    could export validated input, and the image had no room for its 9 MB.

## Requests

FastAPI's built-in OpenTelemetry (`FastAPI(telemetry=...)`, not `instrument_fastapi`, which records
request arguments), with the health checks excluded and `auto_configure` off.

## Scrubbing

Unless the operator opted in to query text, spans pass `ScrubbingExporter` on their way out:

- the query-text values in `url.query` become `REDACTED`;
- exception events and error statuses lose their message and stack trace (a pydantic
  `ValidationError` quotes its `input_value`), keeping the exception type;
- FastMCP's `enduser.id` and `enduser.scope` (who called) are dropped.

Model spans always lose `PROMPT_SPAN_ATTRIBUTES`, even with the query text opted in
(`without_prompts`). This is the second guard after pydantic-ai's `include_content=False`. The
attributes are:

- `gen_ai.input.messages`, `gen_ai.output.messages` and any other `gen_ai.*.messages`;
- `gen_ai.system_instructions`;
- tool-call arguments and results, under the current and the older attribute names;
- an agent run's `pydantic_ai.all_messages` and `final_result`.

Health and readiness probes (`PROBE_PATHS`) get no request span.

## Search

Retrieval declares a driven port, `SearchTracer`.

- Each search use case opens a span for the search and one per stage, in its mode:
    - `version`;
    - `rank`, and inside it `embed_query` for hybrid and `agent` for agentic (whose pydantic-ai spans
      nest below it);
    - `rerank` when a reranker is configured, or `judge` when the LLM judge reranks;
    - `chunks`.
- The query text is a separate argument, so the adapter (`adapters/driven/opentelemetry.py`) can
  leave it out.
- Without a tracer the use cases get `UntracedSearches`, which records nothing.

## Jobs

Bootstrap wraps every job handler in `TracedJobHandler` (`ingestion.<kind>` spans); ingestion's code
is unchanged. MCP tool calls get FastMCP's own spans.

## Metrics

The same adapters time what they span:

| Metric | Recorded by | Attributes |
|---|---|---|
| `exactdocs.search.duration` | `OpenTelemetrySearchTracer` | search, stage, mode |
| `exactdocs.job.duration` | `TracedJobHandler` | job kind |
| `exactdocs.ai.fallbacks` | `OpenTelemetrySearchTracer.fallback`, for each search a cheaper mode answered | mode, reason |
| `exactdocs.ai.cache_hits` | `OpenTelemetrySearchTracer.cache_hit`, for each search whose LLM step a cache answered | cache (`agentic_answer` or `hyde_answer`), mode |
| request metrics | FastAPI | |

- Their attributes are bounded and anonymous: never the query, library, version or caller, so no
  opt-in changes them.
- Both adapters are wired when either `EXACTDOCS_TELEMETRY=otlp` or `EXACTDOCS_METRICS` is on.

## Prometheus

With `EXACTDOCS_METRICS`, `start_telemetry(..., scraped=True)` (from `create_app`; stdio MCP has no
HTTP to serve it):

- adds a `PrometheusMetricReader` to the meter provider, beside the OTLP reader when that is on too;
- and `create_app` mounts `GET /metrics` (`build_metrics_router`), which renders
  `prometheus_client`'s default registry (chosen for its process and runtime collectors).

Access:

- The route sits behind the Host check and takes no account sign-in (Prometheus has none; the
  metrics hold nothing user-specific).
- `EXACTDOCS_METRICS_TOKEN`, when set, makes it require that bearer token (`hmac.compare_digest`,
  401 otherwise).
- The reader sends nothing.
- Scrapes, like the probes, get no request span or metric (`UNTRACED_PATHS`).
- Off, the route does not exist and `prometheus_client` is not imported.

Any library that records through OpenTelemetry's global meter shows up without more wiring. One
example is pydantic-ai's `gen_ai.client.token.usage` and `operation.cost`, recorded by every chat
model and embedder the `ModelFactory` builds (instrumented with `include_content=False`, labelled by
provider, model, operation and token type).
