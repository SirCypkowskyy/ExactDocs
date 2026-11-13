---
name: testing
description: Use when deciding what and how to test in ExactDocs, writing pytest, behave, architecture or web tests, or verifying a change before a PR.
---

# Testing

## The layers and where they live

| Layer | Tool | Location | What it proves | Speed |
|---|---|---|---|---|
| Acceptance | **behave** (Gherkin) | `packages/exactdocs/features/*.feature`, steps in `features/steps/` | the issue's *Expected behavior*, through the public HTTP API | fast (in-process) |
| Unit | pytest | `packages/exactdocs/tests/<domain>/` | use cases and models: business rules, edge cases | very fast |
| Integration | pytest + httpx `ASGITransport` / FastMCP `Client` | `packages/exactdocs/tests/bootstrap/` | wiring, HTTP status mapping, MCP tool schema and annotations | fast |
| Adapter contract | pytest, parametrized over adapters | `packages/exactdocs/tests/<domain>/` | every driven adapter (memory, sqlite, postgres) behaves the same | slower for DBs |
| Architecture | pytest + **ArchUnitPython** | `packages/exactdocs/tests/architecture/` | boundaries in `docs/architecture.md` | fast |
| Web | vitest + Testing Library | `web/src/**/*.test.tsx` | components and query logic of a feature | fast |
| Retrieval eval | Pydantic Evals, `just eval` | `packages/exactdocs/evals/` (tests in `tests/evals/`) | recall, wrong-version rate, latency and cost per retrieval mode; gates in docs/evals.md | seconds |

## Rules of thumb

- **Start from behavior.** Each criterion of success maps to at least one behave scenario or test.
  Scenarios use domain language (no URLs or JSON in `.feature` files; that goes in steps).
- **Test use cases, not adapters' internals.** Build the domain with `XModule.build(...)` and
  in-memory adapters. Test doubles are plain classes matching the Protocol; no `Mock`
  for ports and no inheritance (see `FakeVersions` in `tests/retrieval/`).
- **Assert outcomes, not calls.** Check returned DTOs and raised errors, not which methods were called.
- **Version is a hard filter**: anything touching retrieval gets a "wrong version gets nothing" test.
- **Retrieval ranking or a new mode**: run `just eval`; the wrong-version rate must stay 0 and BM25's
  recall@5 within 2 points of `evals/retrieval_eval/baseline.json` (refresh it with
  `--write-baseline` when ranking improves). A query added to `expected-queries.yaml` is added to
  the eval dataset too.
- **Import and search tests use the fixture docs repository** (`packages/exactdocs/tests/fixtures/docs-repo/`):
  pytest fixture `docs_repo`, behave `context.fixture_repo`; read its README before changing content.
- **A bug fix starts with a failing test** that reproduces the issue.
- **New driven adapter** (e.g. SQLite repository): add it to the adapter contract test so it runs
  the same cases as the in-memory one.
- **New domain**: the architecture tests discover it automatically; make sure they pass and that
  `test_domain_has_the_standard_module_set` is green.
- **One run per container.** `Container.running()` refuses a second concurrent run, and the app's
  lifespan is such a run. A test that needs the MCP session manager runs the container through the
  app only: `app.router.lifespan_context(app)` in the test body, or `serving(app)` from
  `tests/fixtures/app_lifespan.py` in an async fixture. Don't also wrap it in `container.running()`.
- **No unbounded waits in tests.** A behave scenario that hangs (cleanups included) fails after
  `BEHAVE_SCENARIO_TIMEOUT` seconds (default 300) with every thread's stack (`environment.py`);
  still give a step's own waits a timeout, and end a `SlowDatabase` stall (`release()`) before the
  app stops.
- Async tests need no decorator (`asyncio_mode = "auto"`). Warnings are errors (`filterwarnings = error`).
- **Close every SQLite connection a test opens**, or the garbage collector finalizes it during a
  later test, which then fails with "unclosed database". An autouse guard
  (`tests/fixtures/sqlite_guard.py`) fails the test itself when a connection it opened is still open
  at teardown. `with sqlite3.connect()` does not close: use `contextlib.closing`. A container built
  but never run must have its engine disposed (`await container.engine.dispose()`). The guard only
  tracks connections opened during the test, and waits up to 2 s for them to close (DBOS closes an
  executor thread's connection a moment after `DBOS.destroy`). An engine owned by a session- or
  module-scoped fixture but used lazily by a test is flagged at the end of the first test that
  uses it: open (warm) its connection in the fixture itself, or dispose it after each test.
- **The same goes for PostgreSQL** (psycopg, sync or async): `tests/fixtures/psycopg_guard.py`
  fails the test that leaves one open ("was deleted while still open" otherwise lands in a later
  test), naming the database and where the connection was opened. A pooled connection returned
  after its engine was disposed stays open in a plain `QueuePool`; DBOS's system database uses
  `ClosingQueuePool` for that reason.

## MCP tool snapshot

`packages/exactdocs/tests/bootstrap/snapshots/mcp_tools.json` is the public contract of the MCP
tools (descriptions, annotations, input and output schemas). A failing diff is a contract change:
review it, then refresh with `UPDATE_SNAPSHOTS=1 uv run pytest packages/exactdocs/tests/bootstrap/test_mcp_browse.py`.
A dependency bump can also change it; check that the diff is only generated noise.

## Commands

```bash
uv run pytest                                    # everything
uv run pytest packages/exactdocs/tests/catalog   # one domain
uv run pytest -k version                         # by name
uv run pytest --cov=exactdocs --cov-report=term-missing
uv run behave                                    # all scenarios
uv run behave packages/exactdocs/features/search.feature -n "hard filter"
uv run pytest packages/exactdocs/tests/architecture -q
cd web && pnpm test                              # vitest
```

## Before saying "done"

Run the full check list from the **working-on-issues** skill and paste the summary lines
(`N passed`, `N scenarios passed`) into the PR's "How it was tested". Never claim a check passed
without running it.
