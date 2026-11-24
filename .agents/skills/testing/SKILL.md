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
| Adapter contract | pytest, parametrized over adapters | `packages/exactdocs/tests/<domain>/` | every driven adapter (memory, sqlite, postgres) behaves the same; the PostgreSQL and server cases are integration tests (below) | slower for DBs |
| Service integration | pytest marker `integration`, behave tag `@integration` | next to the code they test | PostgreSQL, PgBouncer, Supabase, libSQL and every search or vector server, the local models; off by default (below) | minutes, needs containers |
| Architecture | pytest + **ArchUnitPython** | `packages/exactdocs/tests/architecture/` | boundaries in `docs/architecture.md` | fast |
| Web | vitest + Testing Library | `web/src/**/*.test.tsx` | components and query logic of a feature | fast |
| Retrieval eval | Pydantic Evals, `just eval` | `packages/exactdocs/evals/` (tests in `tests/evals/`; the end-to-end ones are marked `eval`) | recall, wrong-version rate, latency and cost per retrieval mode; gates in docs/evals.md; runs on releases, not in CI | minutes |
| Ingestion benchmark | `just ingestion-bench` (needs the golden corpus cache) | `packages/exactdocs/evals/retrieval_eval/ingestion*.py` (tests in `tests/evals/test_ingestion.py`) | coverage, cut blocks, chunk sizes and heading paths per chunking configuration, with BM25 recall; `--check` against `evals/results/ingestion.json`; runs on releases, not in CI | about a minute per configuration |
| Retrieval benchmark | `just retrieval-bench` (golden corpus cache; local models from `exactdocs models pull`) | `packages/exactdocs/evals/retrieval_eval/retrieval_bench*.py` (tests in `tests/evals/test_retrieval_bench.py`, `retrieval_bench.feature`) | recall, MRR, nDCG@10, wrong version, unanswerable handling, latency and cost of every mode, model and reranker at every chunking configuration, with the default per budget; BM25 at `default` is checked on releases; hosted models only through the manual real-providers workflow | a minute model-free; hours with every local model |
| Text scorer | `just text-bench --offline` (golden corpus cache) | `packages/exactdocs/evals/retrieval_eval/text_match.py`, `text_bench*.py` (tests in `tests/evals/test_text_match.py`, `test_text_bench.py`, `text_scorer.feature`) | scores any tool's text results with the retrieval benchmark's metrics; the calibration checks it agrees with chunk-ID scoring on ≥ 98% of decisions on BM25's results at `default`; by hand, not in CI | about two minutes per chunking |
| Grounded Docs run | `just grounded-bench --offline` (Node.js 22, golden corpus cache, `BAAI/bge-small-en-v1.5` pulled) | `packages/exactdocs/evals/retrieval_eval/grounded_docs*.py`, `openai_embeddings.py` (tests in `tests/evals/test_grounded_docs.py`, `test_openai_embeddings.py`, `grounded_docs.feature`, replaying recorded responses) | a pinned Grounded Docs indexes the golden corpus and answers the golden set, scored from its text next to ExactDocs' BM25, with paired tests; by hand or the manual `grounded-bench.yml`, never in CI | minutes full-text; about an hour with the embedding model |

## Rules of thumb

- **Start from behavior.** Each criterion of success maps to at least one behave scenario or test.
  Scenarios use domain language (no URLs or JSON in `.feature` files; that goes in steps).
- **Test use cases, not adapters' internals.** Build the domain with `XModule.build(...)` and
  in-memory adapters. Test doubles are plain classes matching the Protocol; no `Mock`
  for ports and no inheritance (see `FakeVersions` in `tests/retrieval/`).
- **Assert outcomes, not calls.** Check returned DTOs and raised errors, not which methods were called.
- **Version is a hard filter**: anything touching retrieval gets a "wrong version gets nothing" test.
- **Retrieval ranking or a new mode**: run `just eval` and `uv run pytest -m eval` before the PR.
  CI does not run them; the release does, and a failing gate stops it. The wrong-version rate must
  stay 0 and BM25's recall@5 within 2 points of `evals/retrieval_eval/baseline.json` (refresh it
  with `--write-baseline` when ranking improves). A query added to `expected-queries.yaml` is added to
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
- A test that imports the fixture and runs the retrieval eval suite end to end gets
  `@pytest.mark.eval` (deselected by default, run at release; docs/evals.md).
- **A test that needs a container, a service, the network or a download is an integration test**
  (#507): deselected by default, so `uv run pytest` and `uv run behave` need nothing but the
  checkout, and the run ends saying how many it left out. Mark it from what it takes, in
  `tests/fixtures/integration.py`: PostgreSQL through `on_postgres` / `SQL_BACKENDS` /
  `SEARCH_BACKENDS` and an index backend through its `BackendCase(marks=integration.<NAME>)` are
  marked for you; anything else gets `@integration.POSTGRES`, `pytestmark = integration.REDIS`,
  `integration.needs("EXACTDOCS_TEST_<NAME>_URL")` ... (the variables it reads). A behave scenario
  gets `@integration` and its service's tag (`@postgres`, `@qdrant` ...; `SERVICES` in
  `features/environment.py`, which refuses a service tag without `@integration`). Never a bare
  `skipif` on a missing variable: with the switch on, a test whose variable is unset is skipped
  naming it, and CI's fast jobs point every variable at a dead port, so an unmarked test that
  reaches a service fails there.
- **Pull request CI runs the fast suite only**, in parallel shards (pytest by `pytest-split`,
  behave by feature file, balanced by `.test_durations` and `.behave_durations`; refresh them with
  `just test-durations` / `just bdd-durations` when many tests were added or became slower). The integration jobs run on a PR labelled `run integration`, on a manual CI run with
  the input `integration`, and in every release ([docs/releasing.md](../../../docs/releasing.md#fast-and-integration-tests)).
  Add the label when the change touches an adapter on a server, PostgreSQL, the Dockerfile,
  the wheel or the end-to-end flow.
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
  test), naming the database and where the connection was opened, and closes the leaked ones so
  the warning does not follow into the next test. A pooled connection returned after its engine
  was disposed stays open in a plain `QueuePool`; DBOS's system database uses `ClosingQueuePool`
  for that reason. It does not cover a checkout that *starts* after the dispose (see its
  docstring).

## MCP tool snapshot

`packages/exactdocs/tests/bootstrap/snapshots/mcp_tools.json` is the public contract of the MCP
tools (descriptions, annotations, input and output schemas). A failing diff is a contract change:
review it, then refresh with `UPDATE_SNAPSHOTS=1 uv run pytest packages/exactdocs/tests/bootstrap/test_mcp_browse.py`.
A dependency bump can also change it; check that the diff is only generated noise.

## Commands

```bash
uv run pytest                                    # everything but the eval and integration tests
uv run pytest -m eval                            # the retrieval eval suite end to end
uv run pytest --integration                      # with the integration tests (or EXACTDOCS_INTEGRATION=1;
just test-integration -m integration             #   just test-integration): only them, here
EXACTDOCS_INTEGRATION=1 uv run behave            # with the @integration scenarios (just bdd-integration)
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
