# E10 Run & operations

!!! abstract "TL;DR"
    - **Goal:** One-command start, small and private by construction, upgradable, observable.
    - **Stories:** RUN-01 to RUN-04, OPS-01, OPS-02
    - **Milestones:** MVP-1, MVP-2, Next: Operations
    - **Issues, in build order:** E10-01, E10-02, E10-03a, E10-03b, E10-10; MVP-2: E10-04, E10-09; Next: E10-05 to E10-08
    - **Status:** the epic ([#10](https://github.com/SirCypkowskyy/ExactDocs/issues/10)) is closed; GitHub holds the current issue bodies.

## E10 · MVP-1

### E10-01 · feat: ExactDocs makes no outbound connections except the ones the user configured

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend`<br/>`area: infra` | CI / release / infra | RUN-03 | E3-05a, E5-03, E7-04, E7-06 | M |

**Context.** Docs and queries are private. "No phone-home" must be proven by a test, not promised
in a README.

**Expected behavior**

```gherkin
Scenario: The whole loop works with outbound traffic blocked
  Given outbound connections are blocked except to a local git server
  When a library is imported, searched and read over MCP
  Then every step succeeds
  And no connection to any other host was attempted
```

**Criteria of success**

- [ ] integration test with a socket guard (allow only 127.0.0.1 / the fixture HTTP git server) covering import, REST search, MCP `search_docs`, `query-docs`
- [ ] `FASTMCP_CHECK_FOR_UPDATES=off` asserted; no telemetry configured by default
- [ ] runs in CI
- [ ] docs: README *Privacy and observability* links to the test

### E10-02 · feat: the package and image stay small and model-free

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: infra` | CI / release / infra | RUN-02 | E4-02 | S |

**Context.** Many machines only ever use BM25; they should not download models or ML libraries.

**Expected behavior**

```gherkin
Scenario: The release artifacts contain no models
  When CI builds the wheel and the image
  Then neither contains model weight files
  And starting the server imports no ML client library
```

**Criteria of success**

- [ ] CI check: no `*.safetensors`, `*.bin`, `*.onnx`, `*.gguf`, `*.pt` in wheel or image; size budgets reported and enforced: wheel ≤ 5 MB (without `[ai]`), image ≤ 375 MB uncompressed (300 MB first planned; the floor is the `python:3.14-slim` base, git/ssh and the 167 MB virtualenv, and dropping 57 MB of `.pyc` would slow every start of a read-only container; see docs/releasing.md)
- [ ] test: after app start, `sys.modules` has no `torch`, `transformers`, `sentence_transformers`, `pydantic_ai`
- [ ] dependency review: Chonkie dropped in #27 (needs HF Hub/network); `ML_PACKAGES` in `deploy/check_artifacts.py` lists what must stay out of the default install

### E10-03a · feat: one `docker run` starts ExactDocs and a library is searchable within five minutes

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: infra`<br/>`area: backend` | CI / release / infra, docs | RUN-01, Decisions *Data location*, *Git* | E1-06, E2-03, E7-07, E10-02 | L |

**Context.** Nobody adopts a tool that takes an afternoon to set up. This is the MVP-1 exit test.
It needs only the image, `curl` and the fixture repository, so it depends neither on GitHub nor
on this repository being public.

**Expected behavior**

```gherkin
Scenario: From a clean machine to a searchable library
  Given a clean machine with Docker and no models or API keys
  And the fixture repository is mounted into the container
  When the smoke job runs the documented "docker run" command, creates the admin and adds "file:///fixture/docs-repo" over REST
  Then the library is browsable and searchable over REST, and "query-docs" answers over MCP, within five minutes
```

**Criteria of success**

- [ ] image: `git` installed, `EXACTDOCS_DATA_DIR=/data`, volume, non-root user, built web UI included
- [ ] CI smoke job (shell and `curl` only): build the fixture (E1-06), start the image with it mounted read-only at `/fixture/docs-repo`, `POST /api/v1/setup`, sign in, `POST /api/v1/tokens`, `POST /api/v1/libraries` with `file:///fixture/docs-repo` and `docs/`, poll `GET /api/v1/jobs/{id}`, list and read an article, search a known term over REST, call MCP `query-docs` over HTTP with the token; total time recorded and asserted < 5 min
- [ ] the job needs no network access beyond the runner (no GitHub)
- [ ] docs: README *Quick start* shows the same steps, with a repository URL in place of the mounted fixture

### E10-03b · feat: `uvx exactdocs serve` starts ExactDocs, and the whole loop works in a real browser

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: infra`<br/>`area: web` | CI / release / infra, web UI | RUN-01 | E8-04, E8-07, E8-09, E10-02 | M |

**Context.** `uvx` is the other one-command start, and only a real browser proves that the UI
pieces, built against mocked API types, work together on a real server.

**Expected behavior**

```gherkin
Scenario: Without git, uvx start fails fast
  Given a machine without "git" on its PATH
  When the user runs "uvx exactdocs serve"
  Then start fails with a message saying that git is required

Scenario: The whole loop in a real browser
  Given a fresh instance
  When a user completes setup, adds the fixture repository, opens an article and searches a known term
  Then the article renders and the search result opens its section
```

**Criteria of success**

- [ ] `exactdocs serve` fails fast with a clear message when `git` is missing
- [ ] CI `uvx` smoke job: install the built wheel (with the built web UI) with `uvx`, run `exactdocs serve`, check `/api/health`; on a runner without `git` on `PATH`, start fails with that message
- [ ] Playwright end-to-end test (one test, in CI against a server started from the built wheel): setup → add the fixture repository (fixture HTTP git server) → browse an article → search a known term
- [ ] docs: README *Quick start* has the `uvx` variant

### E10-10 · chore: the Docker image caches dependencies across source changes and is hardened and scanned

| Milestone | Labels | Area | Stories | Depends on | Size | Issue |
|---|---|---|---|---|---|---|
| MVP-1 | `type: chore`<br/>`status: ready`<br/>`area: infra` | CI / release / infra | RUN-01, RUN-02, RUN-03, LIB-05, IMP-01 | - (coordinate with E10-02, E10-03a) | L | [#124](https://github.com/SirCypkowskyy/ExactDocs/issues/124) |

**Context.** The layer cache is invalidated by every release and by README/test edits, and the image is not hardened; MVP-1 also needs `git` and `openssh-client` in the runtime.

- [ ] caching: `VERSION` below the dependency layers; dependency layer built only from `uv.lock` (`uv export --frozen`); only `packages/*/src` + metadata copied (no tests); pnpm pinned and installed before any `COPY`, `pnpm fetch` then `install --offline`; source-only changes show dependency layers `CACHED`
- [ ] hardening: base images pinned by digest (Dependabot), runtime with only `git`, `openssh-client`, `ca-certificates`, `tini` (PID 1), no pip/setuptools, no setuid bits, read-only app files, only `/data` and `/tmp` writable; amd64 apt layer built under QEMU for that stage only
- [ ] CI: hadolint, Trivy/Grype gate on fixable CRITICAL/HIGH, smoke test with `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges` incl. a `file://` import; size budget kept
- [ ] docs: hardened compose example in README; scan gate in `docs/releasing.md`

## E10 · MVP-2

### E10-04 · feat: upgrades migrate automatically, and re-indexing is one command when needed

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend`<br/>`area: infra` | CI / release / infra | RUN-04, CLI-01 (`reindex`) | E1-01, E5-02 | M |

**Context.** Updating must not mean re-importing everything.

```gherkin
Scenario: Upgrading keeps the libraries
  Given an instance with libraries created by the previous release
  When the new release starts
  Then the database is migrated and the libraries are served unchanged

Scenario: Re-indexing while serving
  When the operator runs "exactdocs reindex"
  Then a new index is built while the old one keeps answering, then swapped
```

- [ ] CI upgrade test: data dir from the previous release tag → current release
- [ ] index format version stored; `exactdocs reindex` (local) rebuilds and swaps
- [ ] release notes template has a "requires reindex" section (`docs/releasing.md`)

### E10-09 · docs: project docs describe MVP-1 as built, with all diagrams in Mermaid

| Milestone | Labels | Area | Stories | Depends on | Size | Issue |
|---|---|---|---|---|---|---|
| MVP-2 | `type: docs`<br/>`status: triage` | docs | - (documentation) | MVP-1 complete | L | [#123](https://github.com/SirCypkowskyy/ExactDocs/issues/123) |

**Context.** The ASCII diagrams in README, `docs/architecture.md` and `web/README.md` are hard to maintain and cannot show flows; the docs must describe the system as built.

- [ ] Mermaid enabled in `zensical.toml` (superfences custom fence) and validated in CI (`deploy/mermaid-check`: every diagram is parsed with the `mermaid` package, and ASCII art fails the build)
- [ ] every ASCII diagram replaced by Mermaid (README *How it works*, architecture domains and bridges, web slices)
- [ ] new diagrams: data model (ER), import flow, query flow, retrieval modes, auth, branching and releases (`gitGraph`), CI/CD and runners
- [ ] README, architecture, releasing, index and CONTRIBUTING reflect MVP-1 as built; planned features labelled as planned; strict docs build passes

## E10 · Next: Operations

### E10-05 · feat: orchestrators see whether ExactDocs is alive and ready to serve

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| Next: Operations | `type: feature`<br/>`status: triage`<br/>`area: backend`<br/>`area: infra` | CI / release / infra | OPS-02 | E1-01 | S |

```gherkin
Scenario: Readiness follows the database
  When the database is unreachable
  Then "/healthz" reports up and "/readyz" reports not ready
```

- [ ] `/healthz`, `/readyz` (database reachable) unauthenticated, excluded from traces; Docker `HEALTHCHECK`
- [ ] `/api/health` stays as an alias of `/healthz` (existing clients and E2-03's exemption list keep working)

### E10-06 · feat: operators back up and restore an instance with one command

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| Next: Operations | `type: feature`<br/>`status: triage`<br/>`area: backend` | CI / release / infra | OPS-02, CLI-01 (`backup`, `restore`) | E10-05 | M |

**Context.** The instance becomes something the team depends on.

```gherkin
Scenario: Backup and restore round-trip
  Given an instance with libraries, versions, settings, accounts and tokens
  When the operator runs "exactdocs backup" and restores it into an empty data dir
  Then the restored instance serves the same libraries and accepts the same tokens
```

- [ ] local commands; consistent SQLite snapshot while serving (online backup API); PostgreSQL via `pg_dump` documented
- [ ] round-trip test; secret key handling documented

### E10-07 · feat: operators see ExactDocs traces in their own collector, without query text

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| Next: Operations | `type: feature`<br/>`status: triage`<br/>`area: backend` | CI / release / infra | OPS-01, RUN-03, RET-04 (tool-call spans), Decisions *Telemetry* | E10-01 | M |

**Context.** Operators monitor ExactDocs with the same stack as everything else, without leaking queries.

```gherkin
Scenario: Traces go only to the configured collector, without query text
  Given telemetry is "otlp" with a local collector
  When a user searches "retry_policy"
  Then the collector receives request and search spans
  And no span contains "retry_policy"
```

- [ ] the OpenTelemetry SDK set up only when `EXACTDOCS_TELEMETRY=otlp`, no console output (was `logfire.configure(send_to_logfire=False, console=False)`; Logfire dropped in #87); FastAPI built-in OpenTelemetry; health checks excluded
- [ ] spans for import, sync, search (per mode and stage); query text only with an explicit opt-in
- [ ] one span per MCP tool call (FastMCP); pydantic-ai instrumentation with `include_content=False`, nested in `run_code`, moved to E11-10
- [ ] RUN-03 test extended: only the collector is contacted

### E10-08 · feat: operators scrape ExactDocs metrics with Prometheus

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| Next: Operations | `type: feature`<br/>`status: triage`<br/>`area: backend` | CI / release / infra | OPS-01, RET-07 (LLM-usage metrics) | E10-07 | S |

```gherkin
Scenario: Metrics are exposed when enabled
  Given "EXACTDOCS_METRICS" is on
  When Prometheus scrapes "/metrics"
  Then it gets request, search, import, sync and LLM-usage metrics
```

- [ ] Prometheus via an additional OpenTelemetry metric reader; off by default; `/metrics` behind the host allowlist
