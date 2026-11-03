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

## Rules of thumb

- **Start from behavior.** Each criterion of success maps to at least one behave scenario or test.
  Scenarios use domain language (no URLs or JSON in `.feature` files; that goes in steps).
- **Test use cases, not adapters' internals.** Build the domain with `XModule.build(...)` and
  in-memory adapters. Test doubles are plain classes matching the Protocol; no `Mock`
  for ports and no inheritance (see `FakeIndexedVersions` in `tests/retrieval/`).
- **Assert outcomes, not calls.** Check returned DTOs and raised errors, not which methods were called.
- **Version is a hard filter**: anything touching retrieval gets a "wrong version gets nothing" test.
- **A bug fix starts with a failing test** that reproduces the issue.
- **New driven adapter** (e.g. SQLite repository): add it to the adapter contract test so it runs
  the same cases as the in-memory one.
- **New domain**: the architecture tests discover it automatically; make sure they pass and that
  `test_domain_has_the_standard_module_set` is green.
- Async tests need no decorator (`asyncio_mode = "auto"`). Warnings are errors (`filterwarnings = error`).

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
