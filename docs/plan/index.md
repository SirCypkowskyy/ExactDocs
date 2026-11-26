# Delivery plan

!!! abstract "TL;DR"
    - This plan turns the [user stories](../user-stories.md) into GitHub issues, grouped into
      12 epics and five milestones. It was filed on GitHub on 2026-11-04.
    - GitHub is now the source of truth for status. These pages keep the rationale.
    - MVP-1 is built and released (v0.2.0). As of 2026-11-25 every milestone has no open issues
      and all 12 epics are closed.
    - Each epic has its own page with its issues in build order. The
      [build order](build-order.md) gives the order across epics, and the
      [coverage matrix](coverage.md) maps every story to its issues.

The plan lives on GitHub as:

- the [milestones](https://github.com/SirCypkowskyy/ExactDocs/milestones)
- 12 epics (`type: epic`, #1-#12), with the features as sub-issues (#13-#115)
- "blocked by" links for the *Depends on* lines

It holds **110 feature issues** plus **12 epic tracking issues**:

- 103 filed on 2026-11-04 (#13-#115)
- 7 added for *Next: AI retrieval* in 2026-11 (#241-#246, #248)

| Milestone | Feature issues |
|---|---|
| MVP-1 | 46 |
| MVP-2 | 27 |
| Next: AI retrieval | 23[^ai-count] |
| Next: Teams & integrations | 11 |
| Next: Operations | 4 |

[^ai-count]: 14 planned, 7 added and 2 moved from Teams in 2026-11; see
    [E11 AI retrieval](e11-ai-retrieval.md).

!!! info "Status: MVP-1 is built (v0.2.0)"
    - The 46 MVP-1 issues are merged and released.
    - The acceptance checklists on the epic pages are the *plans* the issues were written from.
      The checkboxes are not ticked retroactively: GitHub is the source of truth.
    - Where the build deviated, the merged PR says why. The [as-built deviations](deviations.md)
      table collects the ones that matter.
    - For how the system works now, read [Architecture](../architecture/index.md) and
      [Flows](../flows/index.md).

!!! abstract "How to read this plan"
    - **Milestones** say *when*: what must be demonstrably true to close them.
    - **Epics** say *what area* of the product an issue belongs to. One epic spans milestones.
    - **Issues** are one PR each, 1-5 days (S/M/L).
        - IDs like `E3-06` are plan IDs: epic 3, issue 6.
        - Inside an epic, issues are listed in implementation order. The
          [MVP-1 build order](build-order.md) gives the order across epics.
        - A merged issue keeps the surviving ID and says what it absorbs (e.g. *(absorbs E7-01)*).
          A split issue gets suffixes (`E3-05a`, `E3-05b`). Absorbed IDs are not reused.
    - The [coverage matrix](coverage.md) maps every story ID to its issues.

## Pages in this section

| Page | What it holds |
|---|---|
| [Filing](filing.md) | How the issues were filed, and the architecture ground rules every issue follows |
| [Deviations from the plan](deviations.md) | What MVP-1 turned out differently, and why |
| [MVP-1 build order](build-order.md) | The critical path, side chains and parallel tracks |
| Epic pages, E1 to E12 | Every issue, as filed: context, expected behavior, criteria of success (see [Epics](#epics)) |
| [Coverage matrix](coverage.md) | Story ID → issues, and the deferred and cross-milestone notes |

## Milestones

Status from GitHub on 2026-11-25.

| Milestone | Goal | Epics | Status |
|---|---|---|---|
| [**MVP-1**](https://github.com/SirCypkowskyy/ExactDocs/milestone/1) | The main loop works end to end for one admin user with zero external services | E1-E10 | Built, v0.2.0<br/>0 open, 47 closed |
| [**MVP-2**](https://github.com/SirCypkowskyy/ExactDocs/milestone/2) | Convenience and polish on top of the loop | E3-E10 | 0 open, 34 closed |
| [**Next: AI retrieval**](https://github.com/SirCypkowskyy/ExactDocs/milestone/3) | Optional embedding, reranker and LLM endpoints upgrade retrieval, measured by an eval suite | E11 | 0 open, 34 closed |
| [**Next: Teams & integrations**](https://github.com/SirCypkowskyy/ExactDocs/milestone/4) | One shared instance for a team: PostgreSQL, OIDC, roles, declarative sources, webhooks, MCP Apps | E12 | 0 open, 13 closed |
| [**Next: Operations**](https://github.com/SirCypkowskyy/ExactDocs/milestone/5) | The instance can be monitored and backed up like any other service | E10 | 0 open, 4 closed |
| **Later** | Other sources and extras | - | Not planned yet; see [Later](#later) |

### Exit criteria

Each milestone closes when these are demonstrably true.

**MVP-1.** The main loop (add a library, public or private → choose docs → import → browse and
search → keep in sync) works in the web UI, over REST and over MCP (incl. the context7 tools); the
CLI client follows in MVP-2.

- Every MVP-1 issue is closed.
- The E10-03a smoke test passes (RUN-01): from a clean machine, one `docker run` with the fixture
  repository mounted, setup, add it via `file://` over REST, browse and search it over REST and
  MCP within five minutes.
- The E10-03b tests pass: `uvx exactdocs serve` starts, and the Playwright test runs
  setup → add → browse → search in a browser.

**MVP-2.** Every MVP-2 issue is closed and its scenarios pass:

- the CLI client with `login`, tokens, `add`, `libraries`, `version add`, `sync` and `remove`
  (E6-02, E6-03)
- distinct sync error codes and moved-tag detection (E9-02)
- settings edits that re-process every version (E9-04, E8-10a)
- import preview (E3-08, E8-11) and `context7.json` (E3-09)
- imported images and relative links (E3-10, E8-12)
- resumable DBOS imports (E3-11)
- renames (E3-12, E8-13)
- custom chunking (E4-05) and manual tags (E4-06, E8-14)
- cross-library search (E5-06, E8-15)
- ctx7-style CLI and REST (E6-04, E6-05)
- MCP resources (E7-08) and stale chunks with their new location (E7-09)
- `exactdocs config --client` (E7-10)
- auto-import of tags (E9-05), moved-tag re-import (E9-06) and a pinned default version (E9-07)
- upgrades without re-import (E10-04)

**Next: AI retrieval.**

- With an embedding endpoint, search is hybrid.
- With an LLM, HyDE and agentic mode work within budgets and fall back to BM25 with a reason.
- The eval suite reports recall@k, wrong-version rate, cost and latency per mode in CI.
- LLM and embedding modes are tested in CI with pydantic-ai `TestModel`/`FunctionModel` or
  recorded fixtures (no live endpoints).
- A BM25-only install still imports nothing from `exactdocs[ai]`.

**Next: Teams & integrations.**

- The ranking suite passes on ParadeDB.
- Two server processes share one database.
- OIDC users see only libraries shared with them in UI, REST and MCP.
- `sources plan/apply` is idempotent.
- A signed webhook syncs within 30 s.
- MCP Apps render in a supporting host, verified with a manual checklist there.

**Next: Operations.**

- `/healthz`, `/readyz`, a backup/restore round-trip, OTLP traces and Prometheus metrics are
  demonstrated.
- Query text is excluded by default, and nothing is sent anywhere but the operator's collector.

!!! note "Dependencies between the Next milestones"
    - Next milestones are independent and may run in parallel.
    - RET-07's metrics need E10-08, and MCP-08 needs ACL-01 (both called out in the issues).
    - Since 2026-11, E12-01 and E12-02 (PostgreSQL, ParadeDB) belong to *Next: AI retrieval*.
      The pgvector work is its own issue (E11-17), so E12-02 no longer waits for E11-03.

## Epics

Every epic issue (#1-#12) is closed on GitHub.

| Epic | Goal | Stories | Milestones |
|---|---|---|---|
| [**E1 Foundation & data model**](e1-foundation.md) | Persistent data dir and schema, IDs and default version, manifests over deduplicated content, version-scoped chunk IDs, the job worker and the fixture repo that later issues build on | RUN-05, IMP-05 (atomic swap), LIB-04 (IDs, SHA), Terms | MVP-1 |
| [**E2 Accounts & tokens**](e2-accounts.md) | A network-exposed instance is never open: first-run admin, sessions, API tokens | AUTH-01, AUTH-02 | MVP-1 |
| [**E3 Git import**](e3-git-import/index.md) | Any git URL, public or private, imported fast, atomically and with visible problems | LIB-01, -02, -03, -04, -05, -06, -07, -11,<br/>IMP-01, IMP-05, IMP-06 | MVP-1, MVP-2 |
| [**E4 Parsing, chunking & tags**](e4-parsing.md) | Safe parsing, heading-based chunks, tags from front matter, path rules and by hand | IMP-02, IMP-03, IMP-04,<br/>TAG-01, TAG-02, TAG-03 | MVP-1, MVP-2 |
| [**E5 Search**](e5-search.md) | BM25 behind one search port, identifier-aware, pinned to a version, proven by a ranking suite | SRCH-01, SRCH-02, SRCH-03,<br/>MCP-04, TAG-03 (search) | MVP-1, MVP-2 |
| [**E6 REST API & CLI**](e6-rest-cli.md) | `/api/v1` + OpenAPI as the single API; the CLI as its client | CLI-01, LIB-08, AUTH-02, C7-03, C7-04 | MVP-1, MVP-2 |
| [**E7 MCP & context7 parity**](e7-mcp.md) | Agents read docs over MCP, including drop-in context7 tools | MCP-01 … MCP-07, C7-01, C7-02 | MVP-1, MVP-2 |
| [**E8 Web UI**](e8-web-ui.md) | Setup, add and watch, browse and switch versions, read, search, manage | AUTH-01/02 (UI), BRW-01 … BRW-05,<br/>LIB-*, IMP-06, SRCH-*, TAG-* (UI) | MVP-1, MVP-2 |
| [**E9 Sync & lifecycle**](e9-sync.md) | Keep versions fresh, survive upstream failures, remove cleanly, edit settings safely | SYNC-01 … SYNC-04, LIB-09, LIB-10 | MVP-1, MVP-2 |
| [**E10 Run & operations**](e10-operations.md) | One-command start, small and private by construction, upgradable, observable | RUN-01 … RUN-04, OPS-01, OPS-02 | MVP-1, MVP-2,<br/>Next: Operations |
| [**E11 AI retrieval**](e11-ai-retrieval.md) | Opt-in hybrid, rerank, HyDE and agentic retrieval with budgets, guardrails and evals | RET-01 … RET-09 | Next: AI retrieval |
| [**E12 Teams & integrations**](e12-teams.md) | PostgreSQL, OIDC, local users, roles, sharing, audit, declarative sources, webhooks, MCP Apps | TEAM-01 … TEAM-03,<br/>ACL-01 … ACL-06, MCP-08 | Next: Teams & integrations |

### Issues per epic, in order

| Epic | MVP-1 | MVP-2 and Next |
|---|---|---|
| E1 | E1-01 … E1-06 | - |
| E2 | E2-01, E2-02, E2-03 | - |
| E3 | E3-01 … E3-04, E3-05a, E3-05b, E3-06, E3-07 | MVP-2: E3-08 … E3-12 |
| E4 | E4-01 … E4-03 | MVP-2: E4-05, E4-06[^e4-04] |
| E5 | E5-01 … E5-04 | MVP-2: E5-06[^e5-05] |
| E6 | E6-01 | MVP-2: E6-02 … E6-05 |
| E7 | E7-02 … E7-07[^e7-01] | MVP-2: E7-08, E7-09, E7-10 |
| E8 | E8-01 … E8-04, E8-06, E8-07, E8-09, E8-10b[^e8-merged] | MVP-2: E8-10a, E8-11 … E8-15 |
| E9 | E9-01, E9-03 | MVP-2: E9-02, E9-04 … E9-07 |
| E10 | E10-01, E10-02, E10-03a, E10-03b | MVP-2: E10-04<br/>Next: E10-05 … E10-08 |
| E11 | - | E11-01 … E11-14 |
| E12 | - | E12-01 … E12-04, E12-13, E12-05 … E12-12 |

[^e4-04]: E4-04 dissolved into E4-03 and E5-03.
[^e5-05]: E5-05 merged into E7-03.
[^e7-01]: E7-01 merged into E7-02.
[^e8-merged]: E8-05 merged into E8-04, E8-08 into E8-06.

## Later

Not planned as issues; revisit after Next.

| Idea | Why later |
|---|---|
| Import from `llms.txt` / `llms-full.txt` | A second source type; the git importer comes first |
| Crawl documentation websites | Needs a crawler, rate limiting and HTML-to-Markdown conversion |
| Package registries (PyPI, npm) and lockfiles | Requires a curated registry mapping packages to repos and paths |
| Prebuilt, signed index snapshots and a public registry | Depends on the registry and a stable index format |
| Backup LLM (model fallback), remote Monty sandbox worker | Only matters once agentic mode runs at scale |
| Pattern-based prompt-injection flags on imported docs | Report-only nice-to-have |
| AsciiDoc, Jupyter notebooks[^rst] | Markdown covers most repositories |

[^rst]: reStructuredText is done: Sphinx sources are imported since #435.
