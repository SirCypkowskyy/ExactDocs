# ExactDocs

**Self-hosted, version-accurate documentation for AI coding agents.**
An MCP server that serves the right docs for the right library version, verbatim and with sources, from infrastructure you control.

> **Status: early development.** This README describes the target design. Items marked ✅ ship today; see the [Roadmap](#roadmap) for the rest.

---

## Why ExactDocs

Coding agents hallucinate APIs when their documentation is outdated, for the wrong version, or paraphrased by yet another model. ExactDocs is built around accuracy first:

- **Version is a hard filter, not a ranking hint.** If there is no match for `react@19.1`, you get "no result for this version", never a plausible answer from another one.
- **Verbatim excerpts, not summaries.** Every result is the original text with its source URL, version and commit SHA. No LLM sits in the query path.
- **Hybrid retrieval.** BM25 for exact identifiers (function names, flags, error codes) plus vector search for meaning, followed by an optional cross-encoder reranker.
- **Measured, not assumed.** Retrieval quality is tracked with a public eval suite that runs in CI on every supported database backend.
- **Self-hosted and private by default.** No telemetry, no phone-home. Your queries and your internal docs stay on your network.

## Features

- MCP server over Streamable HTTP and stdio, with read-only tools
- Version-pinned indexes built from Git tags, `llms.txt`, package registries or allowlisted crawls
- Private sources: internal wikis, ADRs, internal APIs and repos, indexed in separate namespaces
- Web UI (served by the same process) for sources, indexing status, tokens and users
- Authentication: local accounts, generic OIDC, or trusted proxy headers
- SQLite for a single user, PostgreSQL + pgvector for teams
- Durable ingestion workflows (resume after restart, rate limits, scheduled re-crawls) powered by [DBOS](https://docs.dbos.dev/)
- OpenTelemetry export (via Logfire SDK or any OTLP backend), **off by default**

## Quick start

Requires Docker.

```bash
docker run -d --name exactdocs \
  -p 3000:3000 \
  -v exactdocs-data:/data \
  ghcr.io/sircypkowskyy/exactdocs:latest
```

Open <http://localhost:3000>, create the admin account, and add your first library:

```bash
docker exec exactdocs exactdocs add https://github.com/react/react
```

Create an API token in the UI (**Settings → Tokens**), then point your agent at it.

### Connect your agent

Generic MCP client configuration (Streamable HTTP):

```json
{
  "mcpServers": {
    "exactdocs": {
      "url": "http://localhost:3000/mcp",
      "headers": { "Authorization": "Bearer <your-token>" }
    }
  }
}
```

`exactdocs config --client cursor|claude|vscode` prints a ready-to-paste snippet for popular clients.

Local stdio mode (no network port, single user):

```bash
uvx exactdocs serve --stdio
```

### Team deployment

One instance per team, backed by PostgreSQL:

```yaml
# docker-compose.yml
services:
  exactdocs:
    image: ghcr.io/sircypkowskyy/exactdocs:latest
    ports: ["3000:3000"]
    environment:
      EXACTDOCS_DATABASE_URL: postgresql://exactdocs:${DB_PASSWORD}@db:5432/exactdocs
      EXACTDOCS_AUTH_MODE: oidc
      EXACTDOCS_OIDC_ISSUER: https://sso.example.com/realms/dev
      EXACTDOCS_OIDC_CLIENT_ID: exactdocs
      EXACTDOCS_OIDC_CLIENT_SECRET: ${OIDC_SECRET}
    depends_on: [db]
  worker:
    image: ghcr.io/sircypkowskyy/exactdocs:latest
    command: ["exactdocs", "worker"]
    environment:
      EXACTDOCS_DATABASE_URL: postgresql://exactdocs:${DB_PASSWORD}@db:5432/exactdocs
    depends_on: [db]
  db:
    image: pgvector/pgvector:pg19
    environment:
      POSTGRES_USER: exactdocs
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: exactdocs
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes:
  pgdata:
```

Declare the libraries your team uses in a file kept in your own repo, and ExactDocs keeps them indexed:

```yaml
# exactdocs.sources.yaml
libraries:
  - name: react
    versions: ["19"]
    source: git+https://github.com/reactjs/react.dev
  - name: fastapi
    versions: ["0.115"]
    source: registry:pypi
private:
  - name: internal-platform-docs
    namespace: team
    source: git+ssh://git.example.com/platform/docs.git
```

## How it works

```
 Agent (Cursor, Claude Code, VS Code, ...)
        │  MCP (HTTP / stdio)
        ▼
┌──────────────────────────────────────────────┐
│ ExactDocs (one image)                        │
│  FastAPI ── FastMCP ── Web UI (static build) │
│        │                                     │
│  Retrieval: version filter → BM25 + vectors  │
│             → rerank → verbatim excerpts     │
│        │                                     │
│  Worker (DBOS): fetch → parse → chunk →      │
│                 embed → index                │
└───────────────┬──────────────────────────────┘
                ▼
      SQLite (FTS5 + sqlite-vec)
      or PostgreSQL + pgvector
```

**Query path:** resolve the library and version from the request or the project lockfile, filter by version, run hybrid search, rerank, return excerpts with source links.

**Ingestion path:** a durable workflow that survives restarts. Documents are parsed into structured chunks (headings, code blocks, signatures) and each chunk keeps its heading path as context.

### MCP tools

| Tool | Purpose |
|---|---|
| `resolve_library` | Map a name (and optionally a lockfile snippet) to a library and an indexed version |
| `search_docs` | Hybrid search within a library version; returns verbatim excerpts with sources |
| `get_page` | Fetch a full documentation page for a given version |
| `list_libraries` | List indexed libraries and versions visible to the token |

All tools are read-only. Compatibility aliases for common context7 tool names are planned (see [Roadmap](#roadmap)).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `EXACTDOCS_DATABASE_URL` | `sqlite:///data/exactdocs.db` | SQLite path or PostgreSQL URL |
| `EXACTDOCS_AUTH_MODE` | `local` | `local`, `oidc` or `proxy` (trusted headers) |
| `EXACTDOCS_OIDC_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET` | – | Required for `oidc` |
| `EXACTDOCS_TRUSTED_PROXIES` | – | Required for `proxy`: CIDRs allowed to set identity headers |
| `EXACTDOCS_EMBEDDING_MODEL` | bundled small model | Local ONNX model, or an OpenAI-compatible / Ollama endpoint |
| `EXACTDOCS_RERANKER` | `off` | Enable a cross-encoder reranker (better accuracy, more CPU) |
| `EXACTDOCS_CRAWL_ALLOWLIST` | – | Domains the crawler may fetch (SSRF protection) |
| `EXACTDOCS_TELEMETRY` | `off` | `off`, `console`, `otlp` or `logfire` |
| `EXACTDOCS_TELEMETRY_CAPTURE_QUERIES` | `false` | Include query text in telemetry |

## Security

- Read-only MCP tools; ingestion is separated from serving
- Documentation is treated as **untrusted input**: invisible Unicode is stripped and results are marked as external content to reduce prompt-injection risk
- Crawler restricted to an allowlist, with SSRF protections
- API tokens stored hashed, scoped to namespaces, with optional expiry
- Passwords hashed with argon2; session cookies with CSRF protection; lockout after repeated failed logins
- Container runs as non-root; releases are signed (cosign) and ship with an SBOM

Found a vulnerability? See [SECURITY.md](SECURITY.md).

## Privacy and network behavior

ExactDocs makes no outbound connections you did not configure.

| Connection | When | How to control |
|---|---|---|
| Documentation sources (Git, registries, crawled sites) | During ingestion | You choose the sources; crawler uses an allowlist |
| Embedding model download | First run, only if the model is not bundled | Use the bundled model or offline mode with a mounted model volume |
| OIDC provider | Only if `EXACTDOCS_AUTH_MODE=oidc` | Your own IdP |
| Telemetry | Only if `EXACTDOCS_TELEMETRY` is not `off` | See below |

No analytics, no update checks, no data sent to Anthropic, Pydantic or us.

### Observability

Telemetry is **disabled by default**, and sending data to Logfire's cloud is disabled even when telemetry is on, unless you explicitly choose `logfire`.

To send traces to your own OpenTelemetry collector:

```yaml
environment:
  EXACTDOCS_TELEMETRY: otlp
  OTEL_SERVICE_NAME: exactdocs
  OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318   # HTTP/protobuf, not gRPC
```

Query text is excluded from spans unless `EXACTDOCS_TELEMETRY_CAPTURE_QUERIES=true`.

## Evaluation

Accuracy claims are only worth something if you can reproduce them. The [`exactdocs-evals`](https://github.com/exactdocs/exactdocs-evals) repository contains:

- **Retrieval benchmarks:** recall@k, MRR, nDCG and the rate of wrong-version results, on hand-labeled questions about specific library versions
- **End-to-end agent evals:** does an agent using ExactDocs write code that is correct for the pinned version?
- **Security fixtures:** documentation pages containing prompt-injection attempts

Evals run in CI against both SQLite and PostgreSQL backends. Built on [pydantic-evals](https://github.com/pydantic/pydantic-ai).

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.14), Node 26 LTS, pnpm 12.

```bash
git clone https://github.com/SirCypkowskyy/ExactDocs && cd ExactDocs
uv sync
uv run exactdocs serve --reload             # backend on :3000
cd web && pnpm install && pnpm dev          # Vite dev server, proxies /api and /mcp to :3000
uv run pytest && uv run behave              # unit, architecture and acceptance tests
```

Stack: Python (FastAPI, FastMCP, DBOS), React (shadcn/ui, TanStack Router and Query), SQLite or PostgreSQL + pgvector. The production image serves the built frontend from the backend, so there is a single service to run.

Repository layout:

```
exactdocs/
├── packages/
│   ├── exactdocs/          # the app: one folder per domain + bootstrap (composition root)
│   └── exactdocs-kernel/   # shared kernel used by every domain
├── web/                    # React UI (vertical slices)
├── deploy/                 # Dockerfile, self-hosted runner scripts
├── docs/                   # architecture, releasing
└── .agents/skills/         # how agents work on issues, test and release
```

Read [docs/architecture.md](docs/architecture.md) (modular monolith, ports & adapters) and
[docs/releasing.md](docs/releasing.md) (branches, versions, tags) before contributing.

Related repositories:

- [`exactdocs-registry`](https://github.com/exactdocs/exactdocs-registry): curated catalog of libraries, sources and version mappings
- [`exactdocs-evals`](https://github.com/exactdocs/exactdocs-evals): accuracy benchmarks

## Roadmap

- [ ] MCP server, SQLite storage, ingestion from Git and `llms.txt` for 5–10 popular libraries
- [ ] CLI and one-command Docker start
- [ ] Eval suite with the first 50 labeled questions
- [ ] Web UI, local accounts and API tokens
- [ ] PostgreSQL + pgvector backend, DBOS workers
- [ ] OIDC and trusted-proxy authentication
- [ ] Library registry and prebuilt, signed index snapshots
- [ ] Context7-compatible tool aliases
- [ ] Helm chart

## Contributing

Contributions are welcome, especially new library entries in the registry and labeled questions for the eval suite. Please open an issue before large changes. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. Indexed documentation remains under the license of its original source; ExactDocs records each source's license in the registry.
