# Delivery plan

This plan turns the [user stories](user-stories.md) into **GitHub issues** (Feature format),
grouped into **epics** and **milestones**. It is **filed on GitHub** (2026-11-04): the
[milestones](https://github.com/SirCypkowskyy/ExactDocs/milestones), 12 epics (`type: epic`,
#1-#12) with the features as sub-issues (#13-#115), and "blocked by" links for the *Depends on*
lines. GitHub is now the source of truth for status; this page keeps the rationale.

It holds **103 feature issues** plus **12 epic tracking issues**:

| Milestone | Feature issues |
|---|---|
| MVP-1 | 46 |
| MVP-2 | 27 |
| Next: AI retrieval | 14 |
| Next: Teams & integrations | 13 |
| Next: Operations | 4 |

!!! abstract "How to read this plan"
    - **Milestones** say *when* (what must be demonstrably true to close them).
    - **Epics** say *what area* of the product an issue belongs to; one epic spans milestones.
    - **Issues** are one PR each (1-5 days (S/M/L)). IDs like `E3-06` are plan IDs: epic 3,
      issue 6. Inside an epic, issues are listed in implementation order; the
      [MVP-1 build order](#mvp-1-build-order) gives the order across epics. A merged issue keeps
      the surviving ID and says what it absorbs (e.g. *(absorbs E7-01)*); a split issue gets
      suffixes (`E3-05a`, `E3-05b`). Absorbed IDs are not reused.
    - The [coverage matrix](#coverage-matrix) maps every story ID to its issues.

## Filing

Each issue below is ready to paste into the **Feature** form (`.github/ISSUE_TEMPLATE/feature.yml`):

| Plan field | Issue form |
|---|---|
| Title (`feat: ...`) | Title, unchanged; drop the plan ID, add it as the first line of *Notes* (`Plan: E3-06`) |
| Context | *Context* (business context); add the story IDs, e.g. `Stories: LIB-01, LIB-04` |
| Expected behavior | *Expected behavior*: backend Gherkin becomes the behave scenario as written; E8 (web) Gherkin becomes vitest tests; foundation issues list testable statements verified by pytest (see the ground rules) |
| Criteria of success | *Criteria of success*: checkbox list as-is |
| Area | *Area* dropdown values |
| Notes, Depends on | *Notes*: hints (citing the [Decisions](user-stories.md#decisions)), out-of-scope, `Depends on #<n>` once the dependencies have issue numbers |

Labels: one type (`type: feature`, or `type: chore` for E1-06 and E6-01), one status, and one or
more of `area: backend`, `area: web`, `area: infra`. The status in each issue's *Labels* line is
the status it gets **after promotion**. **Every issue is filed as `status: triage`**; after review
round 3, all MVP-1 issues and the 12 epics are promoted to `status: ready` in bulk; MVP-2 and Next
issues are promoted when their milestone starts.

**Record every created number** in `filed.tsv` (plan ID, issue number), since later steps look
dependencies and epics up there, and **pause about 1 s between write calls** (GitHub's secondary
rate limits):

```bash
url=$(gh issue create --title "feat: <outcome>" … --body-file body.md)
echo "E3-06 ${url##*/}" >> filed.tsv
sleep 1
```

Filing steps, in this order:

1. **Milestones.** Create the five milestones (goal from the [Milestones](#milestones) table as
   description):

    ```bash
    gh api repos/{owner}/{repo}/milestones -f title="MVP-1" \
      -f description="The main loop works end to end for one admin user with zero external services."
    # repeat for "MVP-2", "Next: AI retrieval", "Next: Teams & integrations", "Next: Operations"
    ```

2. **Label.** `type: epic` is in `.github/labels.yml`; apply it with
   `.agents/skills/working-on-issues/scripts/sync-labels.sh`.
3. **Epics.** File the 12 epic tracking issues, titled `epic: E<n> <name>` (e.g.
   `epic: E3 Git import`), each with the epic's goal and stories from the [Epics](#epics) table,
   labels `type: epic` and `status: triage`, no milestone (an epic spans milestones). Record
   each epic's number in `filed.tsv` under its epic ID (`E3`), for step 5:

    ```bash
    url=$(gh issue create --title "epic: E3 Git import" --label "type: epic" --label "status: triage" --body-file epic.md)
    echo "E3 ${url##*/}" >> filed.tsv; sleep 1
    ```

    Once its features are filed (step 4), edit each epic's body to add a task list of them
    (`- [ ] #<n>`, one line per feature) as a fallback view of the sub-issues.
4. **Features, in topological build order** (not page order), so every dependency already has a
   number. `body.md` uses the form's headings: `### Context`, `### Expected behavior`,
   `### Criteria of success`, `### Area`, `### Notes`. For MVP-1:

    E1-01, E1-06, E5-01, E6-01, E4-01, E1-02, E1-05, E2-01, E1-03, E2-02, E1-04, E3-01, E2-03,
    E3-02, E4-02, E5-02, E3-03, E4-03, E3-05a, E3-05b, E3-06, E3-07, E3-04, E5-03, E5-04, E7-02,
    E7-03, E7-04, E7-05, E7-06, E7-07, E9-01, E9-03, E8-01, E8-02, E8-03, E8-04, E8-06, E8-07,
    E8-09, E8-10b, E10-01, E10-02, E10-03a, E10-03b.

    Then the other milestones in this order (dependencies on earlier milestones are already
    filed):

    - **MVP-2:** E6-02, E6-03, E9-02, E9-04, E3-08, E3-09, E3-10, E3-11, E3-12, E4-05, E4-06,
      E5-06, E6-05, E6-04, E7-08, E7-09, E7-10, E8-10a, E8-11, E8-12, E8-13, E8-14, E8-15, E9-05,
      E9-06, E9-07, E10-04.
    - **Next: Operations:** E10-05, E10-06, E10-07, E10-08.
    - **Next: AI retrieval:** E11-01, E11-02, E11-03, E11-04, E11-05, E11-06, E11-08, E11-07,
      E11-09, E11-10, E11-11, E11-12, E11-13, E11-14.
    - **Next: Teams & integrations:** E12-01, E12-02, E12-03, E12-04, E12-13, E12-05, E12-06,
      E12-07, E12-08, E12-09, E12-10, E12-11, E12-12.

    ```bash
    url=$(gh issue create --title "feat: <outcome>" --milestone "MVP-1" \
      --label "type: feature" --label "status: triage" --label "area: backend" \
      --body-file body.md)
    echo "E3-06 ${url##*/}" >> filed.tsv; sleep 1
    ```

5. **Sub-issues.** Link each feature as a GitHub sub-issue of its epic (the API takes the
   issue's database `id`, not its number):

    ```bash
    child_id=$(gh api repos/{owner}/{repo}/issues/<feature-number> --jq .id)
    gh api repos/{owner}/{repo}/issues/<epic-number>/sub_issues -F sub_issue_id="$child_id"
    ```

6. **Blocked by.** First check once that the dependencies API is available:
   `gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by`. If it returns 404, skip
   this step and rely on the `Depends on #<n>` lines and the epic task lists. Otherwise, for
   every *Depends on*, add a GitHub "blocked by" relationship in addition to the
   `Depends on #<n>` line in *Notes*. Add "blocked by" only for whole-issue dependencies: skip
   E11-08 → E10-08 (metrics only), E12-02 → E11-03 (pgvector part only) and E12-01 ('MVP-1').

    ```bash
    blocker_id=$(gh api repos/{owner}/{repo}/issues/<dependency-number> --jq .id)
    gh api repos/{owner}/{repo}/issues/<feature-number>/dependencies/blocked_by -F issue_id="$blocker_id"
    ```

7. **Promotion.** After review round 3, promote every MVP-1 issue and every epic to
   `status: ready` in bulk:

    ```bash
    { gh issue list --milestone "MVP-1" --label "status: triage" --limit 200 --json number --jq '.[].number'
      gh issue list --label "type: epic" --label "status: triage" --limit 50 --json number --jq '.[].number'; } |
      xargs -I{} sh -c 'gh issue edit {} --remove-label "status: triage" --add-label "status: ready"; sleep 1'
    ```

Sizes: **S** ≤ 1 day, **M** 1-3 days, **L** 3-5 days. Anything bigger is split.

MVP-1 issues are written in full. MVP-2 and Next issues use a compact form: the paragraph is the
*Context*, the Gherkin block the *Expected behavior*, and the checklist the *Criteria of success*;
they are completed (tests, docs) when promoted to `status: ready`. E6-02, E6-03, E9-02, E9-04
and E8-10a moved from MVP-1 to MVP-2 in review round 2 and keep their full form. Every issue
implicitly includes "`just check` passes" and "architecture tests green".

!!! note "Architecture ground rules used by every issue"
    Work goes through each domain's standard modules (`models`, `dtos`, `ports/driving`,
    `ports/driven`, `use_cases`, `module`, `adapters/...`; see [Architecture](architecture.md)).
    The plan adds two domains next to `catalog` and `retrieval`, matching the form's *Area* values:

    | Domain | Owns |
    |---|---|
    | `identity` | the admin account, sessions, API tokens |
    | `catalog` | libraries, versions, settings (paths, tag rules, chunking), manifests, article content, default version |
    | `ingestion` | git access, credentials, jobs and the worker, parsing, chunking, import/sync use cases; applies catalog settings |
    | `retrieval` | chunk sets, version-scoped chunk IDs, the search port and its adapters, `search_docs`, `read_chunk`, `resolve-library-id`, `query-docs` |

    Domains talk only through driven ports implemented by bridges in `bootstrap/bridges.py`.
    **Bridges are one-way: retrieval → catalog, ingestion → catalog / retrieval.** Catalog calls
    no other domain, and nothing calls ingestion. There are **no cross-domain foreign keys**:
    a domain holds another domain's IDs (e.g. manifest IDs) by value.

    Persistence (Decisions *Persistence*): SQLAlchemy Core (async, no ORM) with aiosqlite; one
    Alembic history owned by `bootstrap` (`render_as_batch=True`; FTS5 tables via `op.execute`);
    tables prefixed per domain (`catalog_`, `retrieval_`, ...); a domain never reads another
    domain's tables.

    Every use case gets its REST route under `/api/v1` in the same PR (REST is the only API of the
    UI and the CLI). Routes that need a ref and an article path take both as query parameters
    (`?ref=` and `?path=`; Decisions *Refs containing `/`*).

    **How issues are verified.** Foundation issues (E1-*, E4-02, E5-01, E5-02) are verified by
    pytest contract and integration tests; their *Expected behavior* lists testable statements,
    not behave scenarios. Every other backend acceptance scenario is a behave scenario that runs
    through REST or MCP, never through internals. Before E3-05a merges, *Given* steps seed
    fixture-shaped versions through the catalog and retrieval driving ports (`StoreManifest`,
    `IndexManifest`, `ActivateManifest`) with a shared step; *When* and *Then* go through REST
    or MCP. E8 (web) Gherkin maps to vitest tests against
    mocked API responses. One Playwright end-to-end test (setup → add fixture → browse → search)
    runs in CI with E10-03b.

## Milestones

| Milestone | Goal | Exit criteria (demonstrably true) | Epics |
|---|---|---|---|
| **MVP-1** | The main loop (add a library, public or private → choose docs → import → browse and search → keep in sync) works end to end for one admin user with zero external services, in the web UI, over REST and over MCP (incl. the context7 tools); the CLI client follows in MVP-2. | Every MVP-1 issue is closed, the E10-03a smoke test passes (from a clean machine, one `docker run` with the fixture repository mounted, setup, add it via `file://` over REST, browse and search it over REST and MCP within five minutes, RUN-01) and the E10-03b tests pass (`uvx exactdocs serve` starts; the Playwright test runs setup → add → browse → search in a browser). | E1-E10 |
| **MVP-2** | Convenience and polish on top of the loop. | Every MVP-2 issue is closed and its scenarios pass: the CLI client with `login`, tokens, `add`, `libraries`, `version add`, `sync` and `remove` (E6-02, E6-03), distinct sync error codes and moved-tag detection (E9-02), settings edits that re-process every version (E9-04, E8-10a), import preview (E3-08, E8-11), `context7.json` (E3-09), imported images and relative links (E3-10, E8-12), resumable DBOS imports (E3-11), renames (E3-12, E8-13), custom chunking (E4-05), manual tags (E4-06, E8-14), cross-library search (E5-06, E8-15), ctx7-style CLI and REST (E6-04, E6-05), MCP resources (E7-08), stale chunks with their new location (E7-09), `exactdocs config --client` (E7-10), auto-import of tags (E9-05), moved-tag re-import (E9-06), pinned default version (E9-07), upgrades without re-import (E10-04). | E3-E10 |
| **Next: AI retrieval** | Optional embedding, reranker and LLM endpoints upgrade retrieval, measured by an eval suite. | With an embedding endpoint search is hybrid; with an LLM, HyDE and agentic mode work within budgets and fall back to BM25 with a reason; the eval suite reports recall@k, wrong-version rate, cost and latency per mode in CI; LLM and embedding modes are tested in CI with pydantic-ai `TestModel`/`FunctionModel` or recorded fixtures (no live endpoints); a BM25-only install still imports nothing from `exactdocs[ai]`. | E11 |
| **Next: Teams & integrations** | One shared instance for a team: PostgreSQL, OIDC, roles, declarative sources, webhooks, MCP Apps. | Ranking suite passes on ParadeDB; two server processes share one database; OIDC users see only libraries shared with them in UI, REST and MCP; `sources plan/apply` is idempotent; a signed webhook syncs within 30 s; MCP Apps render in a supporting host, verified with a manual checklist there. | E12 |
| **Next: Operations** | The instance can be monitored and backed up like any other service. | `/healthz`, `/readyz`, backup/restore round-trip, OTLP traces and Prometheus metrics demonstrated, with query text excluded by default and nothing sent to Logfire's cloud. | E10 |
| **Later** | Other sources and extras. | Not planned yet; see [Later](#later). | - |

Next milestones are independent and may run in parallel; RET-07's metrics need E10-08,
MCP-08 needs ACL-01, and E12-02's pgvector part needs E11-03 (all called out in the issues).

## Epics

| Epic | Goal | Stories | Milestones | Issues (in order) |
|---|---|---|---|---|
| **E1 Foundation & data model** | Persistent data dir and schema, IDs and default version, manifests over deduplicated content, version-scoped chunk IDs, the job worker and the fixture repo that later issues build on. | RUN-05, IMP-05 (atomic swap), LIB-04 (IDs, SHA), Terms | MVP-1 | E1-01 … E1-06 |
| **E2 Accounts & tokens** | A network-exposed instance is never open: first-run admin, sessions, API tokens. | AUTH-01, AUTH-02 | MVP-1 | E2-01, E2-02, E2-03 |
| **E3 Git import** | Any git URL, public or private, imported fast, atomically and with visible problems. | LIB-01, -02, -03, -04, -05, -06, -07, -11, IMP-01, IMP-05, IMP-06 | MVP-1, MVP-2 | E3-01 … E3-04, E3-05a, E3-05b, E3-06, E3-07; MVP-2: E3-08 … E3-12 |
| **E4 Parsing, chunking & tags** | Safe parsing, heading-based chunks, tags from front matter, path rules and by hand. | IMP-02, IMP-03, IMP-04, TAG-01, TAG-02, TAG-03 | MVP-1, MVP-2 | E4-01 … E4-03; MVP-2: E4-05, E4-06 (E4-04 dissolved into E4-03 and E5-03) |
| **E5 Search** | BM25 behind one search port, identifier-aware, pinned to a version, proven by a ranking suite. | SRCH-01, SRCH-02, SRCH-03, MCP-04, TAG-03 (search) | MVP-1, MVP-2 | E5-01 … E5-04; MVP-2: E5-06 (E5-05 merged into E7-03) |
| **E6 REST API & CLI** | `/api/v1` + OpenAPI as the single API; the CLI as its client. | CLI-01, LIB-08, AUTH-02, C7-03, C7-04 | MVP-1, MVP-2 | E6-01; MVP-2: E6-02 … E6-05 |
| **E7 MCP & context7 parity** | Agents read docs over MCP, including drop-in context7 tools. | MCP-01 … MCP-07, C7-01, C7-02 | MVP-1, MVP-2 | E7-02 … E7-07 (E7-01 merged into E7-02); MVP-2: E7-08, E7-09, E7-10 |
| **E8 Web UI** | Setup, add and watch, browse and switch versions, read, search, manage. | AUTH-01/02 (UI), BRW-01 … BRW-05, LIB-*, IMP-06, SRCH-*, TAG-* (UI) | MVP-1, MVP-2 | E8-01 … E8-04, E8-06, E8-07, E8-09, E8-10b (E8-05 merged into E8-04, E8-08 into E8-06); MVP-2: E8-10a, E8-11 … E8-15 |
| **E9 Sync & lifecycle** | Keep versions fresh, survive upstream failures, remove cleanly, edit settings safely. | SYNC-01 … SYNC-04, LIB-09, LIB-10 | MVP-1, MVP-2 | E9-01, E9-03; MVP-2: E9-02, E9-04 … E9-07 |
| **E10 Run & operations** | One-command start, small and private by construction, upgradable, observable. | RUN-01 … RUN-04, OPS-01, OPS-02 | MVP-1, MVP-2, Next: Operations | E10-01, E10-02, E10-03a, E10-03b; MVP-2: E10-04; Next: E10-05 … E10-08 |
| **E11 AI retrieval** | Opt-in hybrid, rerank, HyDE and agentic retrieval with budgets, guardrails and evals. | RET-01 … RET-09 | Next: AI retrieval | E11-01 … E11-14 |
| **E12 Teams & integrations** | PostgreSQL, OIDC, local users, roles, sharing, audit, declarative sources, webhooks, MCP Apps. | TEAM-01 … TEAM-03, ACL-01 … ACL-06, MCP-08 | Next: Teams & integrations | E12-01 … E12-04, E12-13, E12-05 … E12-12 |

## MVP-1 build order

The order is built around the **critical path**, the longest dependency chain; a slip on it
moves the MVP-1 date:

**E1-01 → E1-02 → E1-03 → E1-04 → E4-02 → E3-05a → E3-06 → E7-05 → E7-06 → E7-07 → E10-03a**

Counted by size (S=1, M=2.5, L=4.5 days) over the *Depends on* lines, the path is **28.5 days**
long. Prerequisites that must be merged before their step on the path: E4-01 and E1-06 before
E4-02; E1-05, E3-03 and E4-03 before E3-05a; E7-02 and E5-03 before E7-05; E7-03 and E7-04
before E7-07; E2-03 and E10-02 before E10-03a. Side chains:

- **Just as critical (zero slack):** E1-02 → E3-01 → E3-02 → E3-03 → E3-05a and
  E3-02 → E4-03 → E3-05a both reach E3-05a on day 12.5, like E4-02.
- **Near-critical:** E1-04 → E5-02 → E5-03 → E7-05 and E4-03 → E7-02 → E7-05 (1 day of slack);
  E7-02 → E7-03 → E7-07 (1.5 days; E7-03 is L since it absorbed E5-05).
- **Web:** web issues are built against the mocked OpenAPI types, so their backend dependencies
  gate merging, not starting. Even counted as hard dependencies, the longest web chain
  E3-07 → E3-04 → E8-04 → E10-03b ends on day 27.5 (1 day of slack); E9-01 → E8-10b ends on
  day 26.5.

MVP-1 totals 45 issues (8 S, 30 M, 7 L): **59-133 person-days** at the low and high ends of
the sizes (S=1, M=1-3, L=3-5), 114.5 at the S=1, M=2.5, L=4.5 point estimate. Everything else
runs beside the path:

| Track | Issues (in order) | Starts | Demonstrable result |
|---|---|---|---|
| Critical path | E1-01, E1-02, E1-03, E1-04, E4-02, E3-05a, E3-06, E7-05, E7-06, E7-07, E10-03a | day 1 | Migrated SQLite in the data dir → IDs and default version → manifests → chunk sets → chunker → atomic import → README defaults → `resolve-library-id` → `query-docs` → stdio → five-minute smoke demo |
| Day 1, in parallel | E1-06, E5-01, E6-01, E4-01 | day 1 | Fixture repo builds in tests; identifier tokenizer; `/api/v1` conventions and OpenAPI; safe parser |
| Jobs | E1-05 | after E1-01 | Jobs persist and restart cleanly |
| Identity | E2-01, E2-02, E2-03 | E2-01 after E1-01 + E6-01 | Nothing reachable before setup; sessions and tokens guard REST and MCP |
| Git importer | E3-01, E3-02, E3-03, E4-03; E3-04 after E3-07 | E3-01 after E1-02 | Libraries created from any git URL, public or private; a sparse, shallow fetch lands in a temp dir; tags and tag filters on listings |
| Import follow-ups | E3-05b, E3-07 | after E3-05a | Skipped files with reasons; a second version |
| Search & MCP | E5-02, E5-03, E5-04; E7-02, E7-03, E7-04 | E5-02 after E1-04 + E5-01; E7-02 after E1-03 + E4-03 | FTS5 and version-pinned search; ranking suite green; MCP browse, read and search tools |
| Sync & lifecycle | E9-01, E9-03 | E9-01 after E3-05a + E7-03 | Re-sync (incl. stale chunk IDs and a failed sync keeping the last good version), removal + GC |
| Web | E8-01, E8-02, E8-03, E8-04, E8-06, E8-07, E8-09, E8-10b | E8-01 after E2-02, built against the mocked OpenAPI types; each UI issue merges once its endpoints exist | The whole loop in the browser, incl. tokens and private repositories |
| Run it | E10-02, E10-01, E10-03b | E10-02 after E4-02; E10-01 after E7-06; E10-03b after the web issues (E10-03a ends the critical path) | Size budgets, privacy test, `docker run` smoke, `uvx` smoke and the browser end-to-end test (MVP-1 exit) |

---

## E1 Foundation & data model

### E1-01 · feat: ExactDocs keeps its data in one data directory with a migrated SQLite database

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / catalog · **Stories** RUN-01 (data location) · **Depends on** - · **Size** M

**Context.** Today the catalog is an in-memory demo, so nothing survives a restart. Every later
story (imports, tokens, sync) needs durable storage in the place the Decisions table promises:
`/data` in Docker, the platform user-data directory for `uvx`, the same path for stdio MCP.

**Expected behavior** (pytest integration tests)

- Starting the app on an empty data directory creates the database there at the Alembic head
  revision.
- A library stored before a restart (new app instance on the same data dir) is listed after it.
- A non-writable data directory makes start fail with a message naming the path.
- The same `LibraryRepository` contract cases pass on the memory and the SQLite adapter.

**Criteria of success**

- [ ] data dir from `EXACTDOCS_DATA_DIR`, else `/data` in the image, else the platform user-data dir; created if missing; a non-writable dir fails start with a clear message
- [ ] `EXACTDOCS_DATABASE_URL` overrides the SQLite path in the data directory
- [ ] SQLite opened in WAL mode with foreign keys (within a domain only) and a busy timeout; schema migrations run on start; `/api/health` reports the schema revision
- [ ] SQLAlchemy Core (async, no ORM) on aiosqlite; one Alembic history owned by `bootstrap`, `render_as_batch=True`; FTS5 tables created via `op.execute`
- [ ] SQLite `LibraryRepository` adapter; the adapter contract test runs the same cases on memory and SQLite
- [ ] the container wires SQLite; the demo catalog exists only as test data (behave `Background`)
- [ ] architecture tests green (database libraries only in `adapters/driven` and `bootstrap`)
- [ ] docs: README *Configuration* lists `EXACTDOCS_DATA_DIR` and `EXACTDOCS_DATABASE_URL`

**Notes.** Decisions *Persistence*: one database, each domain owns its tables (prefixed
`catalog_`, `retrieval_`, ...), never reads another domain's tables, and has no foreign keys to
them.

### E1-02 · feat: libraries and versions are addressed by context7-style IDs with a predictable default version

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / catalog · **Stories** LIB-04, Terms (Library ID, Version, Default version) · **Depends on** E1-01 · **Size** M

**Context.** Agents and users address docs as `/owner/repo` or `/owner/repo/<ref>`, exactly like
context7. If the ID parsing or the default-version rule is fuzzy, an agent gets docs for the wrong
version, which is the one thing ExactDocs promises never to do.

**Expected behavior** (pytest unit and contract tests)

- Parsing `/acme/payments/v1.4.0` gives library `/acme/payments` and ref `v1.4.0`; parsing
  `/acme/payments/release/1.4` gives ref `release/1.4` (everything after two segments is the ref).
- `/Acme/Payments` resolves to the stored `/acme/payments`; refs stay case-sensitive (`V1.4.0` is
  not `v1.4.0`); an ID segment outside `[a-z0-9._-]` (after lower-casing) is a validation error.
- With versions `v1.3.0`, `v1.4.0`, `v1.5.0-rc.1` and branch `main`, `/acme/payments` resolves to
  `v1.4.0`, and the response states `v1.4.0` (default-version rule table test).
- A unique short SHA (≥ 7 chars) finds its commit version; an ambiguous prefix is a validation
  error.

**Criteria of success**

- [ ] models: `LibraryId` (exactly two segments, each `[a-z0-9._-]+`, stored lower-case, matched case-insensitively), `VersionRef` (case-sensitive), `RefKind` (tag, branch, commit), `Version` with commit SHA, `Library` with title, description, source URL, host kind and settings (include/exclude paths, tag rules, chunking config)
- [ ] default version per Terms: highest stable semver tag (pre-releases excluded), else default-branch version, else most recently imported; unit-tested as a table
- [ ] a commit version is also found by a unique short SHA (≥ 7 chars); an ambiguous prefix is a validation error
- [ ] REST: `GET /api/v1/libraries`, `/libraries/{owner}/{repo}`, `/libraries/{owner}/{repo}/versions/{ref:path}` (ref always last); unknown → `404 not_found`
- [ ] existing behave features (`catalog.feature`, `search.feature`) move from the `/reactjs/react.dev 19.1` demo to fixture-shaped data
- [ ] unit + adapter contract tests (memory, SQLite)

**Notes.** Pinning (LIB-10) is MVP-2 (E9-07); keep a nullable `pinned_version` column now.
Decided: library IDs are stored lower-case and matched case-insensitively; refs stay
case-sensitive; ID charset `[a-z0-9._-]` per segment.

### E1-03 · feat: each version is a manifest over deduplicated article content, activated atomically

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / catalog · **Stories** IMP-05 (atomic swap), LIB-04 (commit SHA per version), Decisions *Version storage* · **Depends on** E1-02 · **Size** M

**Context.** Libraries get many tags and frequent re-syncs. Storing each version as a manifest
over shared, content-addressed files keeps that cheap, and activating a manifest in one step is
what guarantees readers never see half a version.

**Expected behavior** (pytest contract tests, memory and SQLite)

- With `/acme/payments/main` active at commit `aaa111` and a manifest for `bbb222` stored but not
  activated, `GetArticle("guide/install.md")` returns the `aaa111` content.
- After `ActivateManifest(bbb222)`, the same call returns the `bbb222` content and the version
  reports commit `bbb222`.
- A failure injected during activation leaves `aaa111` active.
- When `v1.3.0` and `v1.4.0` contain the same blob of `guide/install.md`, the content store holds
  it once.

**Criteria of success**

- [ ] `Manifest`: entries (article path, blob SHA, title, tags, front matter, size), commit SHA, state (pending, active, superseded)
- [ ] article content store keyed by git blob SHA; writes are idempotent
- [ ] driving ports `StoreManifest`, `ActivateManifest` (one transaction flips the version's active manifest and commit SHA), `ListArticles` (path prefix, `limit` + `cursor`), `GetArticle` (version + path), `DiscardPendingManifests`, `CollectGarbage`
- [ ] a failure during activation leaves the previous manifest active (test)
- [ ] REST: `GET /api/v1/libraries/{owner}/{repo}/articles?ref=<ref>&path_prefix=...` (tree) and `GET .../article?ref=<ref>&path=<path>` (one article); no `ref` means the default version
- [ ] architecture test for bridge direction: bridges in `bootstrap/bridges.py` go only retrieval → catalog and ingestion → catalog / retrieval, with no cycles (see [Architecture](architecture.md#bridges-are-one-way))
- [ ] unit + adapter contract tests (memory, SQLite)

**Notes.** The catalog knows nothing about chunks and holds no foreign keys to other domains;
other domains keep manifest IDs by value. Pending-manifest discard and GC are per domain and
triggered by ingestion through bridges (the import job's recovery hook in E3-05a, GC in E9-03). Superseded manifests are kept for a grace
period (configurable) so stale chunk IDs can be recognized (E7-03), then collected. Routes follow
Decisions *Refs containing `/`*: a route that needs both a ref and an article path takes `?ref=`
and `?path=`.

### E1-04 · feat: chunks are stored once per content and addressed by version-scoped chunk IDs

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / retrieval · **Stories** Terms (Chunk), Decisions *Version storage*, MCP-04, IMP-02 (chunk IDs) · **Depends on** E1-03 · **Size** M

**Context.** Search results must be addressable (`read_chunk`, neighbors) and must stay valid
across a branch re-sync when the section did not change. Chunk IDs scoped to one version make
`read_chunk` unambiguous, while deduplicated chunk content keeps many versions cheap.

**Expected behavior** (pytest contract tests, memory and SQLite)

- `/acme/payments/main` indexed at `aaa111`, then re-indexed at `bbb222` where only
  `guide/install.md` changed: every chunk of `guide/auth.md` has the same chunk ID in both
  manifests.
- When `v1.3.0` and `v1.4.0` contain the same blob of `guide/install.md`, its chunk set is stored
  once, and its chunks have a different chunk ID in each version.
- `IndexManifest` called twice with the same input stores nothing new.
- The `ChunkId` golden test pins the hash of a known input.

**Criteria of success**

- [ ] `ChunkSet` keyed by (blob SHA, chunking-config hash): ordered chunks with heading path, occurrence index, content, content hash, anchor, code-block languages
- [ ] `ChunkId` = hash(version ID, article path, heading path, occurrence index, content hash), a pure function with a golden test
- [ ] per-manifest chunk rows: chunk ID, article path, `position`/`total`, `prev_chunk_id`/`next_chunk_id`, a copy of the article's tags
- [ ] driving ports `IndexManifest` (idempotent), `DiscardPendingManifests`, `CollectGarbage`; driven port `ActiveManifests` implemented by a bridge to the catalog
- [ ] contract tests (memory, SQLite), including the dedup case

**Notes.** Atomicity without a cross-domain transaction: chunk rows are written for the *new*
manifest ID first (invisible), then the catalog activates the manifest (E1-03); retrieval always
scopes queries to the version's active manifest ID. Manifest IDs are held by value (no foreign
key to catalog tables). Retrieval's pending-manifest discard and GC are triggered by ingestion
through a bridge, like the catalog's; chunk rows of superseded manifests stay for the same grace
period as the manifests.

### E1-05 · feat: imports and other long tasks run as background jobs with visible progress

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** IMP-05 (restart cleanly), IMP-06 (progress), Decisions *Background jobs* · **Depends on** E1-01 · **Size** M

**Context.** Imports of large repos take time; a request must not block on them, and a restart
must not leave a library stuck "importing" forever. Users need to see how far a job got.

**Expected behavior** (pytest unit and integration tests)

- A job over 10 files that has finished 4 reports `done=4, total=10` through
  `GET /api/v1/jobs/{id}`.
- A job left `running` when the app stopped is re-queued on the next start and runs from the
  beginning, after the recovery hook registered for its job kind ran (tested with a fake job
  kind whose hook records the call).
- Two jobs for the same library never run at the same time.

**Criteria of success**

- [ ] new `ingestion` domain with the standard module set; architecture tests green
- [ ] `Job`: kind, library/version target, state (queued, running, succeeded, failed), done/total, per-file problems (path, reason), error, timestamps
- [ ] in-process worker started in the app lifespan, at most one job per library at a time
- [ ] a recovery hook per job kind: on start, each `running` job's hook runs (no-op by default), then the job is re-queued; the import's hook (pending-manifest discard) is registered by E3-05a
- [ ] REST: `GET /api/v1/jobs/{id}`, `GET /api/v1/libraries/{owner}/{repo}/jobs`
- [ ] unit tests with the kernel clock; integration test for restart recovery
- [ ] docs: `docs/architecture.md` lists the `ingestion` domain

**Notes.** DBOS replaces the worker behind the same port in MVP-2 (E3-11). The worker is a
driving adapter (`ingestion/adapters/driving/worker.py`).

### E1-06 · feat: a versioned fixture docs repository backs every import and search test

**Milestone** MVP-1 · **Labels** `type: chore` `status: ready` `area: infra` `area: backend` · **Area** CI / release / infra · **Stories** RUN-05 · **Depends on** - · **Size** M

**Context.** Search quality, chunking and version isolation can only be asserted against stable,
known content. A real git repository with tags and a branch makes import, sync and ranking tests
reproducible on every machine and in CI.

**Expected behavior** (pytest tests on the built fixture)

- The built repository has tags `v1.3.0` and `v1.4.0` and a branch `next`, with the same commit
  SHAs on every machine (golden SHAs asserted).
- The identifier `retry_policy` occurs only in `v1.4.0`.
- Both fixture git servers (`file://` and smart HTTP on 127.0.0.1) serve `git ls-remote` for it.

**Criteria of success**

- [ ] `tests/fixtures/docs-repo/` holds per-commit trees; a pytest fixture and a behave hook build them into a git repo with fixed author and dates (stable SHAs)
- [ ] content: code blocks, tables, front matter (title, tags, description), MDX with JSX, both admonition syntaxes, `snake_case`, `camelCase`, `--flag`, `pkg.mod.fn`, a root README, a file renamed between tags, one Latin-1 file that decodes by detected encoding, one truly undecodable file, a binary file, an oversized file (> 2 MiB), an `AGENTS.md`
- [ ] `expected-queries.yaml`: query → expected top section (article path + heading path) per version
- [ ] fixture git servers: `file://` and smart HTTP on 127.0.0.1 (`git http-backend`) for network tests
- [ ] fixture README explains how to add content without breaking expected SHAs

**Notes.** Article paths are repo-relative: the scenario shorthand `guide/install.md` means
`docs/guide/install.md` in the fixture (`docs/api/auth.md` and `docs/guide/auth.md` both exist,
and `--path docs/` and `docs/archive/**` need the prefix). The suite is used by E4-02, E5-04, E3-05a, E3-05b, E9-01, E10-01, E10-03a (mounted
into the container), E10-03b and RET-09 (E11-02).

---

#### E1 · MVP-2

### E1-07 · chore: Python conventions for constants, docstrings and data classes are enforced automatically

**Milestone** MVP-2 · **Labels** `type: chore` `status: triage` `area: backend` · **Area** backend (all Python packages) · **Stories** - (engineering quality) · **Depends on** - · **Size** L · **Issue** [#121](https://github.com/SirCypkowskyy/ExactDocs/issues/121)

**Context.** Many agents write code in parallel; conventions must be checked by CI, not reviewers.

- [ ] constants only in `constants.py` or a `constants/` package (`__init__.py` re-exporting private topic modules like `_auth.py`, `_identity.py`); each typed `Final[...]` with an attribute docstring
- [ ] private by default: non-API modules, functions, classes and constants are `_private`; public APIs re-exported via `__init__.py`
- [ ] every function and method, private ones included, has a Google-style docstring with `Args:` and `Returns:` (and `Raises:`) whenever it has them; ruff `convention = "google"`, DOC201/DOC501 re-enabled
- [ ] every dataclass is `frozen=True, slots=True, kw_only=True` unless marked `# conventions: allow-... -- <reason>`; every dataclass and pydantic field has an attribute docstring; pydantic models use `use_attribute_docstrings=True`
- [ ] enforced by an AST checker in `tests/architecture/test_conventions.py` with good/bad fixtures per rule; existing code brought into compliance; rules documented in `docs/architecture.md`

## E2 Accounts & tokens

### E2-01 · feat: a fresh instance only offers setup until the first admin account exists

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / identity · **Stories** AUTH-01 · **Depends on** E1-01, E6-01 · **Size** M

**Context.** Even a single-user instance on a network port must not be open to anyone. Until an
admin exists, the only thing a visitor may do is create that admin, in the UI or locally with
`exactdocs admin create`.

**Expected behavior**

```gherkin
Scenario: Everything but setup is refused before the first account exists
  Given a fresh instance
  When a client lists the libraries over the REST API
  Then the request is refused with "setup_required"

Scenario: Creating the admin from the command line
  Given a fresh instance
  When the operator runs "exactdocs admin create" with a username and password
  Then the admin can sign in
  And the setup endpoint is no longer available
```

**Criteria of success**

- [ ] new `identity` domain (standard module set) with `Account` (username, password hash, `role` column: `admin` for the first account); passwords hashed with a memory-hard KDF (argon2id), never stored or logged in clear
- [ ] `POST /api/v1/setup` works only while no account exists (then `409`); every other `/api/v1` route answers `403 setup_required` until then (`GET /api/v1/session`, `/api/health`, `openapi.json` and SPA assets excepted)
- [ ] `exactdocs admin create` (local command: opens the database directly, prompts for the password)
- [ ] unit tests (identity use cases), behave `setup.feature`, integration test for the guard
- [ ] docs: README *Quick start* matches the flow; `docs/architecture.md` lists the `identity` domain; remove `auth_mode` from `settings.py` and `EXACTDOCS_AUTH_MODE`/OIDC from the README and compose example (OIDC returns with E12-03)

**Notes.** One admin only (Decisions *Users and tenancy*); the `role` column keeps room for more
local users (ACL-06, E12-13) and roles (Next). The setup page itself is E8-01.

### E2-02 · feat: the admin signs in to the web UI with an expiring, HttpOnly session

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / identity · **Stories** AUTH-01 · **Depends on** E2-01 · **Size** M

**Context.** The browser UI needs a login that cannot be stolen by script or replayed cross-site,
and a way back in when the password is lost, without opening any remote recovery path.

**Expected behavior**

```gherkin
Scenario: Signing in and out
  Given an admin account exists
  When the admin signs in with the right password
  Then the UI session is active
  When the admin signs out
  Then the libraries are no longer reachable with that session

Scenario: A session cookie never authenticates MCP
  Given the admin is signed in to the UI
  When the browser calls the MCP endpoint with the session cookie only
  Then the call is refused as unauthenticated
```

**Criteria of success**

- [ ] `POST /api/v1/session` (login), `DELETE /api/v1/session` (logout), `GET /api/v1/session` (current state: `setup_required`, signed out, or signed in as whom; used by the UI, E8-01); server-side sessions with idle expiry after 7 days and absolute expiry after 30 days
- [ ] cookie is HttpOnly, SameSite=Lax, `Secure` behind HTTPS; wrong password and unknown user give the same error
- [ ] state-changing requests keep the existing Origin check (403 for a foreign `Origin`); test for login and logout
- [ ] `/mcp` ignores cookies (integration test)
- [ ] `exactdocs admin reset-password` (local) sets a new password and ends all sessions
- [ ] behave `login.feature`; unit tests for expiry with the kernel clock

**Notes.** Decisions *Web UI auth*, *Host and origin checks*. Login rate limiting is out of scope
(follow-up if needed).

### E2-03 · feat: API tokens give agents, the CLI and REST clients access

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / identity, MCP tools · **Stories** AUTH-02 · **Depends on** E2-02 · **Size** M

**Context.** Agents (MCP over HTTP), the CLI and scripts cannot use a browser session; they need
revocable credentials that are never stored in a readable form.

**Expected behavior**

```gherkin
Scenario: A token works once created and stops working once revoked
  Given the admin created a token named "laptop"
  Then the token value is shown once
  And an MCP client with that token can list the libraries
  When the admin revokes "laptop"
  Then the same MCP client is refused

Scenario: An expired token is refused
  Given a token that expired yesterday
  When a REST client uses it
  Then the request is refused as unauthenticated
```

**Criteria of success**

- [ ] tokens: high-entropy, recognizable prefix, stored hashed, optional expiry, name, created and last-used time
- [ ] REST: `POST/GET/DELETE /api/v1/tokens`; the value is returned only by `POST`
- [ ] REST auth dependency accepts session cookie or `Authorization: Bearer`; every route requires one except: `POST /api/v1/setup`, `/api/v1/session` (login, logout, state), `/api/health`, `openapi.json` and the SPA assets (test lists the exemptions)
- [ ] MCP over HTTP uses a FastMCP `TokenVerifier` backed by the identity domain; the token acts as its user
- [ ] unit tests, behave `tokens.feature`, MCP integration test with FastMCP `Client`
- [ ] docs: README *Connect your agent*

**Notes.** Decisions *MCP auth*. In MVP-1 tokens are managed in the UI (E8-02); CLI
`token create|list|revoke` and `exactdocs login` (with its exempt `POST /api/v1/tokens/login`)
are MVP-2 (E6-03, E6-02);
stdio MCP needs no token (E7-07).

---

## E3 Git import

### E3-01 · feat: pasting a git URL validates the repository and proposes a library ID

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** LIB-01 · **Depends on** E1-02 · **Size** M

**Context.** Docs live on GitHub, Bitbucket, GitLab, Gitea and self-hosted servers. A user should
paste any git URL and learn immediately whether it works, before anything is saved, with a
sensible library ID proposed.

**Expected behavior**

```gherkin
Scenario Outline: Common git URLs are accepted with a default ID
  When a user checks the repository URL "<url>"
  Then it is accepted with the proposed library ID "<id>"
  Examples:
    | url                                           | id                 |
    | https://github.com/acme/payments              | /acme/payments     |
    | https://bitbucket.org/acme/billing            | /acme/billing      |
    | https://gitlab.com/acme/platform/sub/docs     | /acme/docs         |
    | https://git.example.com/acme/handbook.git     | /acme/handbook     |
    | git@git.example.com:acme/payments.git         | /acme/payments     |
    | file://<fixtures>/fixture/docs-repo           | /fixture/docs-repo |
    | http://127.0.0.1:<port>/fixture/docs-repo.git | /fixture/docs-repo |

Scenario: A taken ID asks for another one
  Given library "/acme/payments" exists from GitHub
  When a user checks "https://bitbucket.org/acme/payments"
  Then the user is asked to choose another library ID
```

**Criteria of success**

- [ ] URL parser for HTTPS and SSH (`git@host:org/repo.git`, `ssh://`), plus `file://` and plain HTTP (used by the fixture servers and the smoke test; default ID from the last two path segments), host kind (GitHub, GitLab, Bitbucket, Gitea, other) for source links; the step fills `<fixtures>` and `<port>` from the running fixture servers
- [ ] default ID per Terms: owner (top-level group for nested GitLab groups) + repo name; collision → `409 library_id_taken`
- [ ] reachability check with `git ls-remote` (system git) and a 15 s timeout; "not a git repo", "unreachable" and "auth required" are distinct errors
- [ ] REST: `POST /api/v1/repositories/check` returns host kind, proposed ID, default branch (E3-04 adds the SSH host-key fingerprint)
- [ ] unit tests (parser table), integration test against the fixture HTTP git server

**Notes.** Decisions *Git*: no git hosting APIs, only `git`. A missing `git` binary is reported
clearly at start (also covered by E10-03b).

### E3-02 · feat: a library is created with its doc selection and a ref resolved to a commit

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion, backend / catalog · **Stories** LIB-02, LIB-04 · **Depends on** E3-01, E1-05 · **Size** M

**Context.** A repo holds far more than docs, and docs must match the code version a user works
with. Creating a library means choosing paths and a ref; the ref is pinned to a commit SHA so
everything later can say exactly what was imported.

**Expected behavior**

```gherkin
Scenario: Without a ref the default branch is imported
  When a user adds the fixture repository with paths "docs/" and no ref
  Then the library has a version for the default branch
  And that version records the branch head commit SHA

# Verified here by the pure-function table test; the scenario runs in E3-05a's `import.feature`.
Scenario: Exclusions win over inclusions
  When a user adds the fixture repository with paths "docs/**" and exclusion "docs/archive/**"
  Then no article under "docs/archive/" is imported
```

**Criteria of success**

- [ ] `AddLibrary` use case: URL, optional ID, ref, include/exclude patterns; empty selection means `**/*.{md,mdx}`; only `.md`/`.mdx` files are articles; exclusions win
- [ ] ref resolution via `ls-remote`: tag, branch, full or short commit SHA; unknown ref → `422 unknown_ref`
- [ ] the library is stored and an import job queued (job ID returned); `POST /api/v1/libraries`
- [ ] `GET /api/v1/repositories/refs?url=...` lists tags and branches for the UI picker
- [ ] pattern matching is a pure function with a table test (folders, globs, exclusions)
- [ ] behave `add_library.feature` against the fixture repo

**Notes.** The selection belongs to the library (Decisions *Library settings*). Import itself is
E3-05a.

### E3-03 · feat: imports fetch only the chosen ref and paths

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** IMP-01 · **Depends on** E3-02 · **Size** M

**Context.** Large monorepos must not take minutes or gigabytes to import. Fetching one ref,
without history, and only the selected paths keeps imports fast and the data dir small.

**Expected behavior**

```gherkin
Scenario: Only the selected paths of one ref are fetched
  Given the fixture repository has history and files outside "docs/"
  When "docs/" at "v1.4.0" is fetched
  Then the working copy contains "docs/" and the root README only
  And no commit older than "v1.4.0" was fetched
```

**Criteria of success**

- [ ] driven port `GitGateway` with a system-`git` adapter: blobless (`--filter=blob:none`), shallow (`--depth 1`), sparse checkout (non-cone patterns from the selection plus the root README); commits fetched by SHA
- [ ] each fetch uses its own temp dir under the data dir, removed afterwards (also on failure)
- [ ] git runs with a timeout, no interactive prompts (`GIT_TERMINAL_PROMPT=0`), no global/system config influence
- [ ] integration test on the fixture HTTP server asserts the object count / no history
- [ ] docs: README states the `git` requirement for `uvx`

**Notes.** Decisions *Git*. Referenced images are MVP-2 (E3-10).

### E3-04 · feat: private repositories import with an encrypted access token or SSH deploy key

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** LIB-05 · **Depends on** E3-03, E3-07 · **Size** M

**Context.** Most internal docs are private. Users must be able to give ExactDocs a token or deploy
key without it ever being shown again, logged, or sent to another host.

**Expected behavior**

```gherkin
Scenario: A private repository imports with a token
  Given the fixture HTTP git server requires a token
  When a user adds it with that token
  Then the library imports
  And the token is never returned by the API

Scenario: Losing the secret key keeps the docs
  Given a private library was imported
  When ExactDocs restarts with a different secret key
  Then the library is still readable
  And adding a version to it fails with "credentials_required"
```

**Criteria of success**

- [ ] credentials encrypted with a key from `EXACTDOCS_SECRET_KEY`, generated into the data dir on first run if unset (file mode 0600)
- [ ] HTTPS tokens passed through a credential helper/`GIT_ASKPASS` env, never in the URL or argv; SSH keys via a temp key file and `GIT_SSH_COMMAND`, deleted after use
- [ ] credentials sent only to the library's host (redirects to other hosts fail)
- [ ] SSH host keys: `StrictHostKeyChecking=accept-new`, `UserKnownHostsFile=<data>/known_hosts`, `GlobalKnownHostsFile=/dev/null`; the published GitHub, GitLab and Bitbucket host keys are pre-seeded; `POST /api/v1/repositories/check` returns the host-key fingerprint; a changed key is a hard error `host_key_changed` (unit tests for the SSH options and for mapping ssh's "host key changed" failure to that error)
- [ ] a log-capture test proves secrets never appear in logs or error messages
- [ ] undecryptable credentials → library error `credentials_required`, docs keep being served
- [ ] docs: README *Configuration* (`EXACTDOCS_SECRET_KEY`, the known-hosts file)

**Notes.** Decided SSH host-key policy: trust on first use for unknown hosts, pinned keys for
the big three hosts, never silently accept a changed key.

### E3-05a · feat: an import publishes a complete version or nothing

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** IMP-05, LIB-04 (SHA carried) · **Depends on** E1-03, E1-04, E1-05, E3-03, E4-01, E4-02, E4-03 · **Size** L

**Context.** Readers must never see half a version. This issue wires fetch, parse, chunk and tag
into one job that publishes atomically and reuses everything already stored.

**Expected behavior**

```gherkin
Scenario: An import publishes the whole version at once
  When "docs/" of the fixture repository at "v1.3.0" is imported
  Then "/fixture/docs-repo/v1.3.0" lists every selected article
  And every article and chunk carries the commit SHA of "v1.3.0"

Scenario: A failed import leaves the previous state served
  Given "/fixture/docs-repo/next" is imported
  When a re-import of "next" fails before activation
  Then "/fixture/docs-repo/next" still serves the previous commit
```

**Criteria of success**

- [ ] `ImportVersion` use case: fetch → enumerate → decode → parse → tag → chunk → store blobs and chunk sets → `IndexManifest` → `ActivateManifest`
- [ ] progress done/total updated per file
- [ ] a crash before activation leaves the previous state served (test with a failing fake gateway); the pending manifest is discarded in catalog and retrieval through bridges
- [ ] registers the pending-manifest discard (catalog and retrieval `DiscardPendingManifests`) as the import job kind's recovery hook (E1-05), so a restart discards it before the job re-runs (integration test)
- [ ] blobs already stored are not re-parsed or re-chunked (dedup test: importing `v1.4.0` after `v1.3.0` chunks only changed blobs)
- [ ] files over the size cap (default 2 MiB, configurable) are not read into memory (the skip reason and listing come with E3-05b)
- [ ] behave `import.feature` on the fixture repo (publish, version isolation, failed import, E3-02's exclusion scenario, E4-03's tag-combination scenario)

**Notes.** Bridges: ingestion → catalog (`StoreManifest`, `ActivateManifest`,
`DiscardPendingManifests`), ingestion → retrieval (`IndexManifest`, `DiscardPendingManifests`).
`IndexManifest` already feeds the FTS5 index (E5-02), so imported versions are searchable.

### E3-05b · feat: one bad file never fails an import, and the job lists every skipped file with its reason

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** IMP-06 (incl. decoding) · **Depends on** E3-05a · **Size** M

**Context.** One bad file must not cost a user the whole import, and users need to know whether
everything they selected made it in, and why not.

**Expected behavior**

```gherkin
Scenario: One bad file does not fail the import
  When the fixture repository is imported with its binary, oversized and undecodable files
  Then the import succeeds
  And the job lists the skipped files with reasons "binary", "too large" and "undecodable"

Scenario: A Latin-1 file is decoded, not skipped
  When the fixture repository is imported
  Then its Latin-1 article is imported with its accented characters intact
```

**Criteria of success**

- [ ] decode: UTF-8, else the detected encoding, else skip as `undecodable`
- [ ] skip reasons: `too_large` (default cap 2 MiB per file, configurable), `binary`, `undecodable`; malformed front matter imports the article and lists a problem (E4-01)
- [ ] per-file problems (path, reason) stored on the job (E1-05) and returned by `GET /api/v1/jobs/{id}`
- [ ] behave scenarios on the fixture repo

**Notes.** The UI list is in E8-04.

### E3-06 · feat: libraries get a title and description from the root README

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion, backend / catalog · **Stories** LIB-07 · **Depends on** E3-05a · **Size** S

**Context.** Agents pick libraries by title and description in `resolve-library-id`. Users should
get good defaults without typing, and be able to fix them.

**Expected behavior**

```gherkin
Scenario: Defaults come from the root README even outside the selection
  When the fixture repository is added with paths "docs/"
  Then its title is the README's first heading
  And its description is the README's first paragraph

Scenario: The user can edit them
  When the user changes the title to "Payments SDK"
  Then "list_libraries" shows "Payments SDK"
```

**Criteria of success**

- [ ] root README always fetched (E3-03) and parsed for first heading and first paragraph; fallback: repo name, empty description
- [ ] user edits are kept across re-imports (a set flag per field)
- [ ] `PATCH /api/v1/libraries/{owner}/{repo}` for title and description
- [ ] unit tests (README extraction table), behave scenario

**Notes.** `context7.json` precedence is MVP-2 (E3-09). The UI edit is E8-10b.

### E3-07 · feat: users add another version to an existing library

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** LIB-11 · **Depends on** E3-05a · **Size** S

**Context.** Teams work on projects pinned to different releases and need `v1.3.0` next to
`v1.4.0`, imported with exactly the same settings so versions stay comparable.

**Expected behavior**

```gherkin
Scenario: A second version uses the library's settings
  Given "/fixture/docs-repo" is imported at "v1.4.0"
  When the user adds version "v1.3.0"
  Then both versions are listed
  And "v1.3.0" contains only articles matching the library's paths
```

**Criteria of success**

- [ ] `AddVersion` use case: same ref validation as LIB-04; uses the library's paths, tag rules and chunking; duplicate ref → `409`
- [ ] `POST /api/v1/libraries/{owner}/{repo}/versions`
- [ ] default version recomputed after the import (test: adding `v1.5.0` moves the default)
- [ ] behave scenario on the fixture repo

**Notes.** UI in E8-10b; CLI `exactdocs version add` is MVP-2 (E6-03).

#### E3 · MVP-2

### E3-08 · feat: users preview the matching files before importing

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** LIB-03 · **Depends on** E3-03 · **Size** M

**Context.** A wrong glob is only noticed after a long import. A dry run shows count, size and the
file tree first, without storing anything.

```gherkin
Scenario: A dry run lists files without storing anything
  When a user previews the fixture repository at "v1.4.0" with paths "docs/**"
  Then the matching files are listed with their count and total size
  And no library, version or job exists afterwards
```

- [ ] `POST /api/v1/repositories/preview` (URL, ref, patterns, optional credentials) fetches the tree only (no blobs beyond sizes) and returns paths, sizes, totals
- [ ] `exactdocs add --dry-run` prints the same list
- [ ] behave scenario; test that the database is unchanged

### E3-09 · feat: a repository's `context7.json` pre-fills the library

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** LIB-06, LIB-07 (MVP-2), C7-02 (MVP-2 rules) · **Depends on** E3-02, E7-06 · **Size** M

**Context.** Many projects already describe their docs for context7; users should not repeat it.

```gherkin
Scenario: context7.json pre-fills the selection and rules
  Given the fixture repository has a context7.json with folders "docs" and rules "Use v2 client"
  When a user adds it
  Then title, description and paths are pre-filled and still editable
  And "query-docs" for the library includes the rule "Use v2 client"
```

- [ ] parses `projectTitle`, `description`, `folders`, `excludeFolders`, `excludeFiles`, `rules`, `previousVersions`; invalid file → warning, ignored
- [ ] `context7.json` values take precedence over README defaults (LIB-07), user edits over both
- [ ] `previousVersions` offered for import (REST field + UI list in E8-11)
- [ ] `rules` stored on the library and returned by `query-docs`
- [ ] fixture repo gains a `context7.json` on branch `next`

### E3-10 · feat: images referenced by imported articles are imported too

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** LIB-02 (MVP-2), IMP-01 (MVP-2) · **Depends on** E3-05a · **Size** M

**Context.** Private-repo images do not load from the git host, and offline instances should
render diagrams too.

```gherkin
Scenario: A referenced image is served from ExactDocs
  Given an imported article references "img/flow.png" in the repository
  When the article is read
  Then the image is served by ExactDocs at the imported commit
```

- [ ] relative image references collected at parse time; sparse checkout adds them; per-image (default 2 MiB, as E3-05b) and per-version size caps, oversize listed as skipped
- [ ] images stored by blob SHA (dedup) and served by `GET /api/v1/libraries/{owner}/{repo}/asset?ref=&path=` with the correct content type; SVG served with a restrictive CSP
- [ ] tests on the fixture repo

### E3-11 · feat: a killed import resumes where it stopped

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** IMP-05 (MVP-2), Decisions *Background jobs* · **Depends on** E3-05a · **Size** L

**Context.** Large imports should not restart from zero after a crash or deploy.

```gherkin
Scenario: A killed worker resumes without duplicates
  Given an import of 200 files was killed after 120 files
  When ExactDocs starts again
  Then the import finishes from file 121
  And the version has each article exactly once
```

- [ ] DBOS durable workflow replaces the in-process worker behind the job port (steps: fetch, per-batch parse/chunk, publish)
- [ ] steps idempotent (content-addressed writes); the test kills the process mid-import
- [ ] DBOS used only in `ingestion/adapters` and `bootstrap`; architecture tests green

### E3-12 · feat: renames between versions are detected from git

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** supports TAG-01 (MVP-2), BRW-04 (MVP-2), MCP-04 (MVP-2) · **Depends on** E3-05a · **Size** M

**Context.** Manual tags, the version switcher and stale-chunk hints should follow a file that was
moved, not lose it.

```gherkin
Scenario: A renamed article is linked across versions
  Given "guide/setup.md" in "v1.3.0" was renamed to "guide/install.md" in "v1.4.0"
  Then the rename map of "v1.4.0" maps "guide/setup.md" to "guide/install.md"
```

- [ ] on import, `git diff -M --name-status` against the previous version's commit (fetched shallowly) gives a rename map stored with the manifest
- [ ] catalog port `ResolveRenamedPath(version, old_path)`; tests on the fixture rename

---

## E4 Parsing, chunking & tags

### E4-01 · feat: articles are parsed safely: front matter, MDX as inert text, invisible characters removed

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** IMP-04, Terms (Verbatim), MCP-07 (import part) · **Depends on** - · **Size** M

**Context.** Doc sites use front matter and MDX. Titles must be right, JSX must never run, and a
doc file must not smuggle invisible instructions (zero-width, bidi) to an agent.

**Expected behavior**

```gherkin
Scenario: The article title follows front matter, then H1, then file name
  Then the title of "guide/install.md" is its front-matter title
  And the title of "guide/auth.md" is its first H1
  And the title of "notes.md" is "notes"

Scenario: Hidden characters are removed on import
  Given an article contains a zero-width space and a bidi override
  When it is imported
  Then the stored Markdown contains neither
  And is otherwise byte-identical to the source
```

**Criteria of success**

- [ ] pure parser in `ingestion/models`: front matter (YAML safe load; `title`, `tags`, `description`, others kept as metadata), title rule, body without front matter
- [ ] invisible control characters (zero-width, bidi controls) removed; nothing else changed (verbatim test)
- [ ] `.mdx` treated as Markdown; JSX blocks kept as text (rendered as inert code by the UI, E8-07); imports/exports never evaluated
- [ ] malformed front matter → article imported, problem listed (IMP-06)
- [ ] table-driven unit tests over fixture files

**Notes.** Front matter is hidden in the rendered view (E8-07) and returned as metadata by
`read_article` (E7-03). The parser is pure and starts on day 1: whichever of E1-05 and E4-01
merges first creates the `ingestion` package. The parser and sanitizer carry a version constant
that feeds the chunking-config hash (E4-02).

### E4-02 · feat: articles are split into heading-based chunks that never split code blocks or tables

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** IMP-02, RUN-02 (no ML extras), Decisions *Chunker* · **Depends on** E4-01, E1-04, E1-06 · **Size** M

**Context.** Header-based chunks are the best retrieval unit for documentation; a result that
cuts a code block in half is useless to an agent.

**Expected behavior** (pytest guarantee tests against the `Chunker` port, on fixture articles)

- Chunking `guide/install.md` yields a chunk with heading path `Guide > Install > Docker`.
- No fenced code block or table of any fixture article is split between two chunks.
- Text before the first heading is kept in a chunk of its own.
- Two headings with the same text get occurrence indexes 0 and 1.
- Changing the parser/sanitizer version constant changes the chunking-config hash.

**Criteria of success**

- [ ] driven port `Chunker`; default adapter on markdown-it-py (issue #27: Chonkie's Markdown recipe needs the HF Hub and network, which breaks RUN-02)
- [ ] each chunk: heading path, occurrence index (repeated headings), position, content, content hash, GitHub-style anchor, code-block languages
- [ ] chunking-config hash computed from the effective config plus the parser/sanitizer version (E4-01), so a parser fix re-chunks instead of reusing stale chunk sets (default config now; IMP-03 in MVP-2)
- [ ] guarantee tests on the fixture repo run against the port (heading paths, never-split code/tables, text before the first heading kept), so any chunker adapter must pass them
- [ ] dependency `markdown-it-py` added to `pyproject.toml`; no dependency that pulls ML models (RUN-02, see issue #27)

**Notes.** Chunk IDs are computed by retrieval (E1-04), not by the chunker.

### E4-03 · feat: articles carry tags from front matter and path rules, and listings filter by them

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion, backend / catalog · **Stories** TAG-01 (MVP-1), TAG-02, TAG-03 (listing) · **Depends on** E4-01, E3-02, E1-03 · **Size** M

**Context.** Most repos have no front matter but a meaningful folder layout; users slice docs by
topic (API reference, ADRs) across folders, and "only the API reference" is a common need for both
users and agents browsing a version.

**Expected behavior**

```gherkin
# Verified here by the pure-function table test; the scenario runs in E3-05a's `import.feature`.
Scenario: Front-matter and path-rule tags combine
  Given the library has the tag rule "docs/api/** -> api"
  And "docs/api/auth.md" has front-matter tags "auth"
  When the library is imported
  Then "docs/api/auth.md" is tagged "api" and "auth"

Scenario: Listing with an any-of filter
  When an agent lists articles with any of tags "adr, api"
  Then only articles tagged "adr" or "api" are listed
```

**Criteria of success**

- [ ] tag rules (glob → tag) stored in library settings and set only through `AddLibrary` (`POST /api/v1/libraries` accepts them); editing them later is `PUT /api/v1/libraries/{owner}/{repo}/settings`, owned by E9-04 (MVP-2)
- [ ] tags normalized (lower-case, trimmed, deduplicated); applied on every import
- [ ] tags stored on manifest entries and copied to chunk rows
- [ ] catalog `TagFilter` value object (`any` / `all`) in the catalog DTOs; `ListArticles` applies it before pagination; REST query params `tags` and `tags_match=any|all`
- [ ] unit tests (rule matching, filter), behave scenarios

**Notes.** Absorbs the listing half of the dissolved E4-04; the search half is in E5-03. Each
domain has its own `TagFilter`; bridges map between them. MCP (E7-02) and UI (E8-06) expose it.

#### E4 · MVP-2

### E4-05 · feat: chunking can be customized per library without re-cloning

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** IMP-03, LIB-09 (chunking) · **Depends on** E9-04 · **Size** M

**Context.** Some docs have huge sections, others one-line headings; one default does not fit all.

```gherkin
Scenario: Changing the split level re-chunks without fetching
  Given "/fixture/docs-repo" is imported with default chunking
  When the user sets the split level to "h2"
  Then every version is re-chunked from stored content without a git fetch
  And the previous chunks are served until the swap
```

- [ ] settings: split level (`h1`…`h6`), min/max size with merging of tiny sections, chunker choice among supported Chonkie chunkers; validated
- [ ] new config hash → new chunk sets from stored blobs; manifests re-indexed and swapped (E1-04)
- [ ] guarantee tests (E4-02) pass for every supported setting

### E4-06 · feat: users tag articles by hand, and manual tags follow renames

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / catalog · **Stories** TAG-01 (MVP-2), TAG-02 (combine) · **Depends on** E3-12, E4-03 · **Size** M

**Context.** Some topics are not visible in paths or front matter; users want to add them once for
all versions.

```gherkin
Scenario: A manual tag applies to all versions and follows a rename
  Given the user tagged "guide/setup.md" with "onboarding"
  Then "guide/setup.md" in "v1.3.0" is tagged "onboarding"
  And "guide/install.md" in "v1.4.0" (its renamed successor) is tagged "onboarding"
```

- [ ] manual tags per library keyed by article path; rename map (E3-12) carries them forward
- [ ] `PUT/DELETE /api/v1/libraries/{owner}/{repo}/tags?path=` ; chunk-row tag copies refreshed without re-chunking
- [ ] unit + behave tests; UI in E8-14

---

## E5 Search

### E5-01 · feat: identifiers are searchable whole and by their parts

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / retrieval · **Stories** SRCH-01, Decisions *Identifier tokenizer* · **Depends on** - · **Size** S

**Context.** Developers search for `retryPolicy`, `max_retries`, `--dry-run` or `pkg.mod.fn`.
Standard tokenizers either glue or shred these; both the whole identifier and its parts must match.

**Expected behavior** (pytest table-driven unit tests)

Tokenizing each identifier for indexing yields both the whole token and its parts:

| identifier | whole | parts |
|---|---|---|
| `retryPolicy` | `retrypolicy` | `retry policy` |
| `max_retries` | `max_retries` | `max retries` |
| `--dry-run` | `--dry-run` | `dry run` |
| `pkg.mod.fn` | `pkg.mod.fn` | `pkg mod fn` |
| `HTTPServer` | `httpserver` | `http server` |

The same function applied to a query yields the same tokens as applied to the indexed text.

**Criteria of success**

- [ ] pure function in `retrieval/models` producing the extra indexed column text, applied to both chunk text and queries
- [ ] handles acronyms (`HTTPServer` → `http server`), digits, Unicode letters
- [ ] table-driven unit tests; the same function will feed pg_search (E12-02)

### E5-02 · feat: BM25 search runs on SQLite FTS5 behind one search port

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / retrieval · **Stories** SRCH-01, SRCH-02, Decisions *BM25 engine* · **Depends on** E1-04, E5-01 · **Size** L

**Context.** Search must work with nothing configured and run identically on SQLite now and
ParadeDB later; one port with a shared contract keeps the engines interchangeable.

**Expected behavior** (pytest port contract tests, memory reference and FTS5)

- With two manifests indexed through `IndexManifest` (test chunk sets shaped like fixture
  `v1.3.0` and `v1.4.0`; no import needed), `search(<v1.3.0 manifest>, "retry_policy")`
  returns no hit.
- `search(<v1.4.0 manifest>, "retry_policy")` returns the defining section first, with a snippet
  and highlight offsets.
- Queries containing `"`, `NEAR`, `*` or `(` are matched as text and never raise an FTS5 syntax
  error.
- A chunk set shared by two manifests is indexed once and found from both.

**Criteria of success**

- [ ] driven port `SearchIndex`: `index(chunk_set)`, `search(manifest_id, query, tag_filter, limit)` → hits (chunk ID, score, snippet with highlight offsets)
- [ ] FTS5 adapter: content-addressed table over chunk sets (text, heading path, identifier column), scoped by the active manifest's chunk rows; snippets via `snippet()` with safe escaping
- [ ] queries are escaped (no FTS5 syntax injection: quotes, `NEAR`, `*`) — test
- [ ] indexing hooked into `IndexManifest` (E1-04); removal hook for GC (E9-03)
- [ ] port contract test (memory reference implementation + FTS5)

**Notes.** BM25 statistics are global over deduplicated content (not per version); acceptable,
and the ranking suite (E5-04) guards it.

### E5-03 · feat: search answers within the selected version, with locations and neighbors

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / retrieval · **Stories** SRCH-01, SRCH-02, MCP-04, MCP-05 (result shape), TAG-03 (search), BRW-03 (source links) · **Depends on** E5-02, E1-03 · **Size** M

**Context.** An answer from another version is worse than none. Every result must say exactly
where it comes from and how it was found, so an agent can read around it and trust it.

**Expected behavior**

```gherkin
Scenario: No results in the selected version, even if another version matches
  When a user searches "/fixture/docs-repo/v1.3.0" for "retry_policy"
  Then the result is explicitly empty for version "v1.3.0"
  And no result from "v1.4.0" is returned

Scenario: A result carries its location
  When a user searches "/fixture/docs-repo/v1.4.0" for "retry_policy"
  Then each result has chunk ID, article path, heading path, position of total, previous and next chunk IDs, commit SHA and a source link to the section anchor
  And the response states retrieval mode "bm25", not reranked, and its coverage

Scenario: Search with an all-of tag filter
  When a user searches "token" in "/fixture/docs-repo/v1.4.0" with all of tags "api, auth"
  Then every result is tagged "api" and "auth"
```

**Criteria of success**

- [ ] `SearchDocs` use case rewritten on the new model: library + optional ref (default version), query, tag filter, limit; unknown version → `not_found`, known version without hits → empty result
- [ ] retrieval's own `TagFilter` (`any` / `all`) applied before ranking; search-port contract test: filtered top-k is computed after filtering
- [ ] result shape (one for every future mode): chunks as above + `version`, `retrieval_mode`, `reranked`, `coverage` (candidates considered, reranked, complete/cut short), optional `fallback_reason`
- [ ] source link at the commit SHA and section anchor for GitHub, GitLab, Bitbucket, Gitea; none for unknown hosts
- [ ] REST `GET /api/v1/libraries/{owner}/{repo}/search?ref=&q=&tags=&tags_match=any|all`
- [ ] behave `search.feature` rewritten on the fixture repo with "wrong version gets nothing" and the tag filter

**Notes.** Absorbs the search half of the dissolved E4-04 (the listing half is in E4-03).
Background seeds `/fixture/docs-repo` v1.3.0/v1.4.0 through the driving ports (ground rules).

### E5-04 · feat: a shared ranking suite proves exact identifiers find their defining section first

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` `area: infra` · **Area** backend / retrieval, CI / release / infra · **Stories** SRCH-01, RUN-05 · **Depends on** E5-03, E1-06, E3-05a · **Size** M

**Context.** Ranking regressions are silent. A suite written against the search port, driven by
the fixture's expected-queries table, keeps BM25 honest now and proves PostgreSQL parity later.

**Expected behavior**

```gherkin
Scenario: Every expected query ranks its section first
  Given the fixture repository is imported at "v1.3.0" and "v1.4.0"
  When each query of the expected-queries table is searched in its version
  Then its expected section is the top result
```

**Criteria of success**

- [ ] `tests/retrieval/ranking/` parametrized over search adapters (FTS5 now; ParadeDB in E12-02)
- [ ] covers all four identifier shapes, a phrase query, a tag-filtered query and the version-isolation cases
- [ ] runs in `just check` and CI; failures print the actual top-5
- [ ] docs: how to add a query to the table (fixture README)

#### E5 · MVP-2

### E5-06 · feat: users search all libraries at once and see which library answers

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / retrieval · **Stories** SRCH-03 · **Depends on** E5-03 · **Size** M

**Context.** Users don't always know which library documents something.

```gherkin
Scenario: Results across libraries with a library facet
  Given two libraries are imported
  When a user searches all libraries for "token"
  Then results come from each library's default version
  And each result names its library and version, with counts per library
```

- [ ] `SearchAllLibraries` use case: union over default versions' active manifests, facet counts per library
- [ ] `GET /api/v1/search?q=&library=`; selecting a library narrows to it
- [ ] version-isolation test: a non-default version never appears

---

## E6 REST API & CLI

### E6-01 · feat: the REST API is versioned under `/api/v1` with a published OpenAPI description

**Milestone** MVP-1 · **Labels** `type: chore` `status: ready` `area: backend` · **Area** backend / catalog, docs · **Stories** Decisions *REST API*, *Refs containing `/`* · **Depends on** - · **Size** S

**Context.** The UI and the CLI must behave identically and work against remote instances; that
is only possible if both use one documented API with stable conventions from the first endpoint.

**Expected behavior**

```gherkin
Scenario: The API describes itself
  When a client fetches the OpenAPI description
  Then every "/api/v1" operation has a stable operation ID and documented error responses

Scenario: Errors have one shape
  When a client requests an unknown library
  Then the response status is 404 with error code "not_found" and a message
```

**Criteria of success**

- [ ] `/api/v1/openapi.json` published; operation IDs stable (`<tag>-<name>`), tags per domain
- [ ] one error envelope (`error`, `detail`) for every `DomainError`; validation errors mapped to `422` with field details
- [ ] list endpoints share `limit` + opaque `cursor` pagination
- [ ] route rule: `/libraries/{owner}/{repo}/...`, a ref only as the last path segment (`{ref:path}`) or as a query parameter; a route that needs a ref and an article path takes `?ref=` and `?path=`
- [ ] web: typed client generated from the OpenAPI file (`openapi-typescript`) in `web/src/shared/lib`, with a CI check that it is up to date
- [ ] integration tests for the envelope and pagination helper

#### E6 · MVP-2

### E6-02 · feat: the CLI is a client of the REST API and `exactdocs login` stores its credentials

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / identity · **Stories** CLI-01, AUTH-02 (login) · **Depends on** E2-03, E6-01 · **Size** M

**Context.** Users script their setup and run the CLI against remote instances; the CLI must not
reach into the database behind the server's back.

**Expected behavior**

```gherkin
Scenario: Logging in stores a named token
  Given a running instance with an admin account
  When the user runs "exactdocs login <url>" with the admin's username and password
  Then the CLI config holds the server URL and a new token named after the machine
  And "exactdocs libraries" works without further flags

Scenario: An existing token can be used instead
  When the user runs "exactdocs login <url> --token <token>"
  Then no new token is created
```

**Criteria of success**

- [ ] REST `POST /api/v1/tokens/login` (username, password, token name) issues a token; the auth-exemption test (E2-03) includes `POST /api/v1/tokens/login`
- [ ] config resolution: flags > `EXACTDOCS_URL`/`EXACTDOCS_TOKEN` env > config file in the platform config dir (mode 0600)
- [ ] shared CLI HTTP client (`httpx2`) with error mapping to non-zero exit codes and readable messages
- [ ] local commands stay local: `serve`, `admin create`, `admin reset-password`; an architecture/unit test lists every command and asserts the rest use only the REST client
- [ ] tests against an in-process server (ASGI transport)
- [ ] docs: README *Quick start*

### E6-03 · feat: users add, list, sync and remove libraries and manage tokens from the CLI

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion, backend / identity · **Stories** LIB-08, LIB-11 (CLI), AUTH-02 (CLI), CLI-01, SYNC-01 (CLI) · **Depends on** E6-02, E3-07, E3-04, E9-01, E9-03 · **Size** M

**Context.** A CLI action and the same UI action must produce identical results, so scripted
setups and the UI never drift.

**Expected behavior**

```gherkin
Scenario: Adding a library from the CLI
  When the user runs "exactdocs add <fixture-url> --id /fixture/docs-repo --ref v1.4.0 --path docs/"
  Then "exactdocs libraries" lists "/fixture/docs-repo" with version "v1.4.0"
  And the REST API returns the same library as for a library added in the UI
```

**Criteria of success**

- [ ] `exactdocs add <git-url> [--id] [--ref] [--path ...] [--exclude ...] [--token|--ssh-key] [--wait]`
- [ ] `exactdocs libraries`, `exactdocs version add <library> <ref>`, `exactdocs token create|list|revoke`
- [ ] `exactdocs sync <library> [--wait]` (E9-01's REST route) and `exactdocs remove <library>[/<ref>]` (E9-03's `DELETE` routes)
- [ ] `--json` output for scripting; human tables otherwise
- [ ] parity test: the same command via CLI and via the REST calls the UI makes yields equal stored libraries
- [ ] docs: README CLI examples verified by a test (doctest-style or behave)

**Notes.** `--token|--ssh-key` need the credential handling of E3-04.

### E6-04 · feat: CLI commands mirror `ctx7`

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / retrieval · **Stories** C7-03 · **Depends on** E6-05 · **Size** S

**Context.** Users want to check from the terminal what their agent would get.

```gherkin
Scenario: The CLI shows what the agent gets
  When the user runs "exactdocs docs /fixture/docs-repo retry policy"
  Then the output equals the text of "query-docs" for the same arguments
```

- [ ] `exactdocs library <name> <query>` and `exactdocs docs <libraryId> <query>` call the C7-04 endpoints
- [ ] equality test against the MCP tool results

### E6-05 · feat: integrations get context7's library search and docs over REST

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / retrieval · **Stories** C7-04 · **Depends on** E7-05, E7-06 · **Size** S

**Context.** Not every integration speaks MCP.

```gherkin
Scenario: REST returns the same docs as MCP
  When a client with an API token calls the docs endpoint for "/fixture/docs-repo/v1.4.0" and "retry policy"
  Then the payload equals the "query-docs" payload
```

- [ ] `GET /api/v1/c7/search?libraryName=&query=` and `GET /api/v1/c7/docs?libraryId=&query=&language=`, documented in OpenAPI
- [ ] same use cases and tokens as MCP; equality tests

---

## E7 MCP & context7 parity

### E7-02 · feat: agents list libraries and browse a version's article tree, marked as untrusted content (absorbs E7-01)

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** MCP tools, backend / catalog · **Stories** MCP-01, MCP-02, MCP-07, TAG-03 (MCP), RUN-03 (update check off), Terms (Version in responses), Decisions *MCP endpoint* · **Depends on** E1-03, E4-03 · **Size** L

**Context.** Agents navigate docs like humans: overview first, then the relevant article. They
must see what exists, which version is default, and page through big trees. A doc file can also
contain instructions aimed at the user's agent, so every result must tell the agent that the text
is external content, in a place every client actually reads.

**Expected behavior**

```gherkin
Scenario: Listing libraries
  When an agent calls "list_libraries"
  Then "/fixture/docs-repo" is listed with title, description, tags and versions with commit SHAs
  And "v1.4.0" is marked as the default version

Scenario: Paging through a version's articles
  When an agent calls "list_articles" for "/fixture/docs-repo" with limit 2
  Then it gets 2 articles of the default version and a cursor
  When it calls again with that cursor
  Then it gets the next articles

Scenario: ExactDocs tools carry the notice in structured content
  When an agent calls "list_articles"
  Then its structured result has a "notice" field and the version used
```

**Criteria of success**

- [ ] `list_libraries(limit?, cursor?)` (default limit 20): ID, title, description, source URL, tags, `refs` (ref, kind, commit SHA, default flag; at most 50 per library, plus `version_count`)
- [ ] `list_articles(library, ref?, path_prefix?, tags?, tags_match?, limit?, cursor?)` (`ref` like `search_docs`; blank means the default version): path, title, tags, size; tags filter as TAG-03 (catalog `TagFilter`, E4-03)
- [ ] each domain's result DTO carries a `notice` field whose text is the kernel `NOTICE` constant (a reviewed kernel addition, see [Architecture](architecture.md#bridges-are-one-way)); no shared MCP helper module (the context7 two-block `ToolResult` lives in retrieval's MCP adapter, E7-05)
- [ ] all tools annotated read-only; `mask_error_details=True` kept; `DomainError`s pass as tool errors (existing middleware) — test both paths
- [ ] `FASTMCP_CHECK_FOR_UPDATES=off` set in code; stdio banner off — test
- [ ] tool schemas snapshot-tested; behave `mcp_browse.feature` (MCP steps via FastMCP `Client`)

**Notes.** MCP over HTTP is guarded by the token verifier from E2-03; tests that run before it
lands use an unauthenticated in-process FastMCP `Client`.

### E7-03 · feat: agents and REST clients read whole articles and single chunks verbatim, and old chunk IDs say they are stale (absorbs E5-05)

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** MCP tools, backend / retrieval · **Stories** MCP-03, MCP-04 (`read_chunk`, `stale_chunk`), IMP-04 (front matter as metadata) · **Depends on** E7-02, E5-03 · **Size** L

**Context.** Once an agent knows where the answer is, it wants the whole article, unescaped, with
proof of where it came from; a typo in a path should point to the right file. A matching section
often needs its neighbor, and after a re-sync an agent holding an old chunk ID must learn it is
stale rather than get a confusing "not found" or wrong text.

**Expected behavior**

```gherkin
Scenario: Reading an article
  When an agent reads "guide/install.md" of "/fixture/docs-repo/v1.4.0"
  Then the Markdown arrives as a plain text block, identical to the imported file
  And the structured content has its front matter, commit SHA and source link

Scenario: A wrong path suggests close matches
  When an agent reads "guide/instal.md"
  Then the tool error lists "guide/install.md" as a close match

Scenario: Reading a neighbor chunk
  Given a search result for "retry_policy" in "/fixture/docs-repo/v1.4.0"
  When the agent reads its next chunk ID
  Then it gets that chunk verbatim with its location and the IDs of its own neighbors
```

**Criteria of success**

- [ ] `ReadChunk` use case (retrieval): verbatim content, location fields as in search results
- [ ] IDs in a superseded manifest of the same version but not in the active one → `stale_chunk` (domain error); unknown IDs → `not_found` (pytest with a superseded manifest stored through the ports; the behave scenario over a real re-sync is in E9-01)
- [ ] REST `GET /api/v1/chunks/{chunk_id}` and the article route of E1-03 (`?ref=&path=`)
- [ ] MCP `read_article(library, version?, path)` and `read_chunk(chunk_id)`: text block + structured content (metadata, commit SHA, link, version, notice)
- [ ] `stale_chunk` and `not_found` surface as tool errors with messages
- [ ] close matches (edit distance / same basename), at most 5
- [ ] unit, integration and behave tests

**Notes.** The new location in the `stale_chunk` error is MVP-2 (E7-09). Chunk IDs of superseded
manifests are kept as tombstones when GC (E9-03) removes the manifests after their grace period.

### E7-04 · feat: agents search one version with `search_docs`

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** MCP tools, backend / retrieval · **Stories** MCP-05, MCP-04, TAG-03 (MCP) · **Depends on** E7-02, E5-03 · **Size** S

**Context.** Agents should get the best results the instance can give and know how they were
found, so they can tell "nothing exists" from "not everything was checked".

**Expected behavior**

```gherkin
Scenario: Searching a version with nothing configured
  When an agent calls "search_docs" for "/fixture/docs-repo/v1.3.0" and "retry_policy"
  Then the result is explicitly empty for "v1.3.0" with retrieval mode "bm25"

Scenario: Asking for a mode that is not configured
  When an agent calls "search_docs" with mode "hybrid"
  Then the tool error lists the available modes "bm25"
```

**Criteria of success**

- [ ] `search_docs(library, version?, query, tags?, mode?)` returns the E5-03 shape + notice (retrieval DTO field, E7-02)
- [ ] `mode` validated against available modes (only `bm25` in MVP-1)
- [ ] behave `mcp_search.feature` incl. wrong-version case

### E7-05 · feat: `resolve-library-id` finds library IDs like context7 does

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** MCP tools, backend / retrieval · **Stories** C7-01, MCP-07 (context7 tools), LIB-07 (titles used for matching) · **Depends on** E7-02, E3-06, E5-03 · **Size** M

**Context.** Every context7-style prompt starts with `resolve-library-id`; ExactDocs must answer it
with the same tool name and arguments so switching is a URL change.

**Expected behavior**

```gherkin
Background:
  Given the fixture repository is imported as "/acme/payments" at "v1.3.0"
  And the fixture repository is imported as "/acme/payments-sdk" at "v1.4.0"

Scenario: A library name resolves to its ID
  Given the fixture repository is also imported as "/fixture/docs-repo"
  When an agent calls "resolve-library-id" with libraryName "docs repo" and query "retry policy"
  Then "/fixture/docs-repo" is the first match with its title, description, versions, article and chunk counts

Scenario: The query changes the order
  Given only "/acme/payments-sdk" documents "retry_policy" in its default version
  When an agent calls "resolve-library-id" with libraryName "payments" and query "retry_policy"
  Then "/acme/payments-sdk" is ranked first
  When the agent calls it with libraryName "payments" and query "invoices"
  Then "/acme/payments" is ranked first

Scenario: context7-compatible tools keep their payload shape
  When an agent calls "resolve-library-id"
  Then the result has two text blocks: the notice with the version, then the payload
  And the tool has no output schema
```

**Criteria of success**

- [ ] `ResolveLibraryId` use case in **retrieval**: reads libraries through a bridge to catalog's `ListLibraries` and matches the name in memory (ID, title, description; no catalog FTS); `query` re-ranks by matching docs (hits in each candidate's default version, retrieval's own search)
- [ ] context7-shaped text payload (ID, title, description, versions, counts) in a two-block `ToolResult` (notice from the kernel constant, then the payload) built in retrieval's MCP adapter and reused by E7-06
- [ ] contract test: tool name and argument schema are a superset of a vendored context7 schema in `tests/contracts/context7/` pinned to a context7 version, with a README on how to update it deliberately

**Notes.** The bridge goes retrieval → catalog (one-way rule); catalog never calls retrieval.

### E7-06 · feat: `query-docs` returns version-exact documentation within a size budget

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** MCP tools, backend / retrieval · **Stories** C7-02 · **Depends on** E7-05, E5-03 · **Size** M

**Context.** The second call of every context7-style prompt. It must never answer from another
version and must stay small enough for the agent's context.

**Expected behavior**

```gherkin
Scenario: An exact version answers only from that version
  When an agent calls "query-docs" with libraryId "/fixture/docs-repo/v1.3.0" and query "retry_policy"
  Then no text that exists only in "v1.4.0" is returned

Scenario: The response stays within the budget
  Given the size budget is 2000 tokens
  When an agent calls "query-docs" with a broad query
  Then the payload is at most 8000 characters
```

**Criteria of success**

- [ ] `QueryDocs` use case (retrieval): `/owner/repo` → default version, `/owner/repo/<ref>` → exactly that version; instance retrieval mode
- [ ] `language` ranks chunks with code blocks in that language first (from E4-02 code languages)
- [ ] budget (default ~10k tokens = characters / 4, setting `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET`) enforced in the use case, whole chunks only; no response-limiting middleware
- [ ] replay test: a recorded context7 session (both tools, real arguments) in `tests/contracts/context7/` runs without errors
- [ ] docs: README *MCP tools*

**Notes.** Library `rules` are MVP-2 (E3-09); per-library mode is Next (E11-01).

### E7-07 · feat: `exactdocs serve --stdio` serves MCP from the local database without a token

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** MCP tools · **Stories** AUTH-02 (stdio), Decisions *stdio MCP*, *Data location* · **Depends on** E7-02, E7-03, E7-04, E7-06 · **Size** S

**Context.** Local setups run the agent and ExactDocs on one machine without a network port; the
stdio server must be safe next to a running HTTP server.

**Expected behavior**

```gherkin
Scenario: stdio MCP reads the same libraries as the server
  Given "/fixture/docs-repo" was imported by a running server
  When an agent starts "exactdocs serve --stdio"
  Then "list_libraries" lists "/fixture/docs-repo" without any token
```

**Criteria of success**

- [ ] stdio builds the read-only tool set over the same data dir; SQLite opened read-only (WAL), no worker, no migrations
- [ ] read-only WAL tested both next to a running HTTP server and with the HTTP server stopped
- [ ] works before any account exists; stdio needs the database to exist (created by the first `exactdocs serve` or `admin create`): a missing database is a clear error on stderr naming the path
- [ ] docs: README states that stdio needs an existing database
- [ ] nothing written to stdout except MCP frames (test)
- [ ] docs: README *Connect your agent*

#### E7 · MVP-2

### E7-08 · feat: articles are exposed as MCP resources

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** MCP tools · **Stories** MCP-03 (MVP-2) · **Depends on** E7-03 · **Size** S

**Context.** Some clients browse resources rather than call tools.

```gherkin
Scenario: Reading an article as a resource
  When a client reads "exactdocs://fixture/docs-repo/guide/install.md?ref=v1.4.0"
  Then it gets the same Markdown as "read_article"
```

- [ ] resource template `exactdocs://{owner}/{repo}/{path*}{?ref}`; no ref → default version
- [ ] equality test with `read_article`

### E7-09 · feat: a stale chunk error points to the section's new location

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** MCP tools, backend / retrieval · **Stories** MCP-04 (MVP-2) · **Depends on** E7-03, E3-12 · **Size** S

**Context.** After a re-sync, an agent holding an old chunk ID should be able to continue, not
start its search over.

```gherkin
Scenario: The stale error carries the new chunk ID
  Given a section moved within its article during a re-sync
  When an agent reads its old chunk ID
  Then the "stale_chunk" error includes the new chunk ID and heading path
```

- [ ] match by heading path (and rename map for moved articles); no match → error without location
- [ ] unit + MCP tests

### E7-10 · feat: users get a ready-to-paste MCP config and agents get a usage skill

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** MCP tools · **Stories** MCP-06 · **Depends on** E6-02 · **Size** S

**Context.** Hand-written JSON is where setups break.

```gherkin
Scenario: A working snippet for Claude Code
  When the user runs "exactdocs config --client claude"
  Then a JSON snippet with the server URL and a newly created token is printed
  And an MCP client configured with it can list libraries
```

- [ ] clients `claude`, `cursor`, `vscode`; token created via REST (AUTH-02)
- [ ] a short "how to use ExactDocs" skill offered over MCP for clients that load skills
- [ ] snippet validity test per client

---

## E8 Web UI

All UI issues: features in `web/src/features/<feature>/` (vertical slices, see
[Architecture](architecture.md#web-client-vertical-slices)), data only through the generated
`/api/v1` client (E6-01), vitest + Testing Library tests per feature, fallow and Biome boundary
rules green. Each Gherkin scenario maps to a vitest test against mocked API responses (built from
the generated OpenAPI types, so UI work can start before the endpoints exist) and is checked once
manually against `just dev`; the Playwright end-to-end test of the whole loop is in E10-03b.

### E8-01 · feat: the web UI has setup, sign-in and sign-out

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** AUTH-01 · **Depends on** E2-02, E6-01 · **Size** M

**Context.** The first thing a new user sees decides whether the instance is safe: a fresh
instance must show only setup, and everything else must sit behind sign-in.

**Expected behavior**

```gherkin
Scenario: A fresh instance shows only the setup page
  Given no account exists
  When a user opens any page
  Then the setup page is shown
  When the user creates the admin account
  Then the user is signed in and sees the home page

Scenario: An expired session returns to sign-in
  Given the admin's session expired
  When the admin opens a library
  Then the sign-in page is shown and returns to that library after sign-in
```

**Criteria of success**

- [ ] `features/auth`: setup page, sign-in page, sign-out action, session state from `GET /api/v1/session`
- [ ] router guard: `setup_required` → setup; `401` → sign-in with a return URL (same-origin paths only)
- [ ] app shell (header with libraries, settings, sign-out) in `app/`
- [ ] vitest for guard logic and forms (validation, error messages)

### E8-02 · feat: users create, list and revoke API tokens in the UI

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** AUTH-02 · **Depends on** E8-01, E2-03 · **Size** S

**Context.** Connecting an agent should not require the CLI; the token must be easy to copy once
and impossible to see again.

**Expected behavior**

```gherkin
Scenario: A new token is shown once
  When the admin creates a token "laptop" expiring in 30 days under Settings → Tokens
  Then its value is shown once with a copy button
  And after closing the dialog only its name, expiry and last use are listed
```

**Criteria of success**

- [ ] `features/tokens`: list, create (name, optional expiry), revoke with confirmation
- [ ] the value never enters the query cache or local storage (test)
- [ ] vitest for the dialog and list

**Notes.** A ready-to-paste MCP config belongs to MCP-06 (E7-10, MVP-2), not here.

### E8-03 · feat: the home page lists libraries with versions, freshness and sync errors

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** BRW-05, SYNC-04 (error shown) · **Depends on** E8-01, E1-02, E1-05 · **Size** M

**Context.** Users need to see what is available and how fresh it is, and spot a failing sync
before their agent gives stale answers.

**Expected behavior**

```gherkin
Scenario: Libraries with their status
  Given "/fixture/docs-repo" has versions "v1.3.0" and "v1.4.0" and its last sync failed
  When the user opens the home page
  Then the library shows its URL, refs with commit SHAs, article count, tags and last sync time
  And the sync error is shown with its reason
```

**Criteria of success**

- [ ] extend `features/libraries` (existing skeleton) to the real `/api/v1/libraries` shape
- [ ] last job status and error per library come from `GET /api/v1/libraries/{owner}/{repo}/jobs` (a separate query; catalog's `/libraries` carries no job state)
- [ ] empty state links to "Add library"; running imports show progress (E8-04)
- [ ] vitest for table rows, error badge and empty state

### E8-04 · feat: users add a library from the UI and watch its import, including skipped files (absorbs E8-05)

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** LIB-01, LIB-02, LIB-04, LIB-05, LIB-07, IMP-06, TAG-02 (rules set when adding) · **Depends on** E8-03, E3-01, E3-02, E3-04, E3-05b, E4-03 · **Size** L

**Context.** Adding a library is the start of the main loop; it must catch a bad URL, a taken ID
or a wrong ref before anything is saved. Afterwards users need to know whether everything they
selected made it in, and why not.

**Expected behavior**

```gherkin
Scenario: Adding a library step by step
  When the user pastes the fixture repository URL
  Then the URL is checked and the ID "/fixture/docs-repo" is proposed
  When the user picks tag "v1.4.0" from the ref list and enters paths "docs/"
  And submits
  Then the import starts and its progress page opens

Scenario: A taken ID must be changed
  Given "/fixture/docs-repo" exists
  When the user pastes another URL that proposes "/fixture/docs-repo"
  Then submitting is blocked until another ID is entered

Scenario: Progress and problems
  Given an import of the fixture repository is running
  Then the job page shows files done of total, updating while it runs
  When it finishes
  Then skipped files are listed with "binary", "too large" or "undecodable"
```

**Criteria of success**

- [ ] `features/add-library`: URL check, editable ID, ref picker (tags, branches, free commit SHA), include/exclude paths, path tag rules (glob → tag; editing them later is MVP-2, E8-10a), optional token or SSH key (write-only fields; SSH host-key fingerprint shown from the check), title/description shown after the first import
- [ ] server errors mapped to field errors (`library_id_taken`, `unknown_ref`, `auth_required`, `host_key_changed`)
- [ ] `features/jobs`: polling `GET /api/v1/jobs/{id}` until finished (TanStack Query `refetchInterval`), problems table
- [ ] vitest for the form flow; vitest with fake timers for the job page

### E8-06 · feat: users browse a version as a file tree, switch versions on the same article, and open the exact commit (absorbs E8-08)

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** BRW-01 (tree), BRW-03, BRW-04, TAG-01 (shown), TAG-03 (tree filter) · **Depends on** E8-03, E1-03, E4-03 · **Size** L

**Context.** Reading the docs is the point. The tree should mirror the repo, users sometimes need
the surrounding code at the exact imported commit, not the branch head, and they work on projects
pinned to different versions and compare them often.

**Expected behavior**

```gherkin
Scenario: Tree, article and source link
  When the user opens "/fixture/docs-repo" version "v1.4.0"
  Then the tree mirrors the repository paths and shows article titles and tags
  When the user opens "guide/install.md"
  Then a "View on GitHub" link points at the file at the commit SHA of "v1.4.0"

Scenario: Filtering the tree by tag
  When the user filters the tree by tag "api"
  Then only articles tagged "api" and their folders remain

Scenario: Switching keeps the path when it exists
  Given the user reads "guide/auth.md" in "v1.4.0"
  When the user switches to "v1.3.0"
  Then "guide/auth.md" of "v1.3.0" is shown
  And when the article does not exist there, the version's root is shown with a notice
```

**Criteria of success**

- [ ] routes `/libraries/$owner/$repo` with `?version=` and `?path=` search params (refs and paths never in path segments)
- [ ] `features/browse`: tree (lazy folders for large trees), article page (title, tags, front matter hidden, source link by host kind)
- [ ] version picker lists imported refs with kind and marks the default
- [ ] vitest for tree building, tag filter and the version fallback logic

### E8-07 · feat: articles render with code highlighting, tables, admonitions and inert MDX

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** BRW-01, IMP-04 (MDX inert) · **Depends on** E8-06 · **Size** M

**Context.** Documentation written for MkDocs or GitHub must look right, and nothing in an
imported file may execute in the user's browser.

**Expected behavior**

```gherkin
Scenario: Both admonition syntaxes render
  When the user opens an article with "!!! note" and "> [!NOTE]" blocks
  Then both render as notes

Scenario: MDX components never run
  When the user opens an MDX article with a "<Tabs>" component
  Then the component is shown as code
```

**Criteria of success**

- [ ] Markdown renderer (proposal: `react-markdown` + `remark-gfm` + custom admonition plugins + a highlighter) with raw HTML disabled or sanitized
- [ ] headings get the same anchors as chunk anchors (E4-02) so search links land on sections
- [ ] images: the git host's raw URL at the commit for public repos, alt text for private ones
- [ ] vitest snapshots on fixture articles; an XSS test (script tags, `javascript:` links, event handlers)

### E8-09 · feat: users search a version with highlighted snippets and tag filters

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** SRCH-01, SRCH-02, TAG-03 (UI search) · **Depends on** E8-06, E5-03 · **Size** M

**Context.** Users often know a term but not where it is documented, and must never get an
answer from a version they did not select.

**Expected behavior**

```gherkin
Scenario: No results in this version
  When the user searches "retry_policy" in "v1.3.0"
  Then "No results in v1.3.0" is shown

Scenario: A result opens the section
  When the user searches "retry_policy" in "v1.4.0"
  Then results show article, heading path and a highlighted snippet
  And opening a result scrolls to that section
```

**Criteria of success**

- [ ] `features/search`: query box in the library view, tag filter (any/all), result list
- [ ] snippet highlights rendered from offsets, never as HTML from the server
- [ ] vitest for empty state, highlighting and navigation

### E8-10b · feat: users edit a library's title, add versions, re-sync and remove in the UI

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: web` · **Area** web UI · **Stories** LIB-07 (edit), LIB-11, SYNC-01, SYNC-03 · **Depends on** E8-06, E3-06, E3-07, E9-01, E9-03 · **Size** M

**Context.** The loop does not end at import, and in MVP-1 the UI is the only client: users fix
titles, add releases, refresh branches and remove what is stale there. Removal must be hard to
do by accident.

**Expected behavior**

```gherkin
Scenario: Editing the title
  When the user changes the title of "/fixture/docs-repo" to "Payments SDK"
  Then the home page lists "Payments SDK"

Scenario: Adding a version
  When the user adds version "v1.3.0" to "/fixture/docs-repo"
  Then its import starts and "v1.3.0" appears in the version picker when done

Scenario: Re-syncing a branch
  When the user clicks "Re-sync" on "/fixture/docs-repo"
  Then a sync job starts and its progress is shown

Scenario: Removing a version asks for confirmation
  When the user removes version "v1.3.0" and confirms with the version name
  Then "v1.3.0" is no longer listed
```

**Criteria of success**

- [ ] `features/library-settings`: title/description edit (`PATCH`, E3-06), add version (ref picker reused from E8-04)
- [ ] re-sync action with job progress (the job view of E8-04); remove version/library with typed confirmation
- [ ] vitest for the forms, actions and confirmations

**Notes.** Editing paths and tag rules is MVP-2 (E8-10a).

#### E8 · MVP-2

### E8-10a · feat: users edit a library's paths and tag rules in the UI

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: web` · **Area** web UI · **Stories** LIB-09, TAG-02 (edit rules) · **Depends on** E8-06, E9-04 · **Size** S

**Context.** The first selection is rarely perfect; users fix paths and tag rules without the
CLI.

**Expected behavior**

```gherkin
Scenario: Saving new paths warns about re-processing
  When the user adds the exclusion "docs/archive/**" in the library settings
  Then a warning says every version will be re-processed
  When the user confirms
  Then a re-processing job starts and its progress is shown
```

**Criteria of success**

- [ ] `features/library-settings` gains paths and tag rules; saving warns that every version is re-processed (`PUT …/settings`, E9-04)
- [ ] vitest for the form and the warning

### E8-11 · feat: the add-library form previews the matching files

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: web` · **Area** web UI · **Stories** LIB-03, LIB-06 (`previousVersions` offered) · **Depends on** E3-08, E3-09 · **Size** S

**Context.** Fix a wrong pattern before waiting for an import.

```gherkin
Scenario: Preview before import
  When the user enters URL, ref and paths and clicks "Preview"
  Then the matching tree is shown with file count and total size
```

- [ ] preview tree with counts; `context7.json` pre-fill and `previousVersions` checkboxes shown
- [ ] vitest

### E8-12 · feat: relative links and images work inside ExactDocs

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: web` · **Area** web UI · **Stories** BRW-02, BRW-01 (MVP-2 images) · **Depends on** E3-10, E8-07 · **Size** M

**Context.** Docs written for GitHub link to each other with relative paths.

```gherkin
Scenario: A relative link opens the imported article at its heading
  When the user clicks "[setup](../setup.md#docker)"
  Then the imported "setup.md" opens at "Docker" in the same version
  And links to files outside the selection open on the git host at the commit
```

- [ ] link resolver (pure function, table-tested) for relative paths, anchors, outside-selection files
- [ ] images from the imported copies (E3-10)

### E8-13 · feat: the version switcher follows renamed articles

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: web` · **Area** web UI · **Stories** BRW-04 (MVP-2) · **Depends on** E3-12, E8-06 · **Size** S

```gherkin
Scenario: Switching to a version where the article was renamed
  Given the user reads "guide/setup.md" in "v1.3.0"
  When the user switches to "v1.4.0"
  Then "guide/install.md" opens
```

- [ ] picker asks the rename map before falling back to the root; vitest

### E8-14 · feat: users tag articles by hand in the UI

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: web` · **Area** web UI · **Stories** TAG-01 (MVP-2) · **Depends on** E4-06 · **Size** S

```gherkin
Scenario: Adding a manual tag
  When the user adds the tag "onboarding" to "guide/install.md"
  Then the tag shows on the article and in the tree for every version
```

- [ ] tag editor on the article page distinguishing front-matter, rule and manual tags; vitest

### E8-15 · feat: one search box across all libraries

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: web` · **Area** web UI · **Stories** SRCH-03 · **Depends on** E5-06 · **Size** S

```gherkin
Scenario: Narrowing a global search to one library
  When the user searches "token" from the header
  Then results are grouped by library with counts
  When the user selects "/fixture/docs-repo"
  Then only its default version's results remain
```

- [ ] global search page with library facet; vitest

---

## E9 Sync & lifecycle

### E9-01 · feat: a branch version re-syncs on demand and re-processes only what changed

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** SYNC-01, LIB-04 (branch keeps its ID), MCP-04 (`stale_chunk`), SYNC-04 (last good version kept, error on the job) · **Depends on** E3-05a, E7-03 · **Size** M

**Context.** Docs change; users want the latest state of a branch with one click, without paying
for a full re-import every time, and an upstream problem must never take their docs away.

**Expected behavior**

```gherkin
Scenario: Nothing to do when the head did not move
  Given "/fixture/docs-repo/next" is imported at the branch head
  When the user syncs the library
  Then no import runs and the version is reported up to date

Scenario: Only changed articles are re-chunked
  Given a commit changed "guide/install.md" on branch "next"
  When the user syncs "/fixture/docs-repo"
  Then only "guide/install.md" is re-chunked
  And the version keeps its ID with the new commit SHA

Scenario: A changed section's old chunk ID is stale
  Given an agent holds the chunk ID of a section of "/fixture/docs-repo/next"
  And the branch was re-synced after that section changed
  When the agent reads that chunk ID
  Then it gets the error "stale_chunk"

Scenario: A failed sync keeps the last good version
  Given "/fixture/docs-repo/next" is imported
  And the fixture HTTP git server no longer serves the repository
  When the user syncs the library
  Then "/fixture/docs-repo/next" still serves the previous commit
  And the sync job is failed with its reason
```

**Criteria of success**

- [ ] `SyncLibrary` use case: for each branch version, `ls-remote` the head; import only if moved
- [ ] unchanged blobs reuse chunk sets (assert by counters on the job)
- [ ] `POST /api/v1/libraries/{owner}/{repo}/sync` (the CLI command is MVP-2, E6-03)
- [ ] a failed sync (any upstream error) leaves the last good version served and records the error on the job (shown on the home page by E8-03); distinct error codes and moved tags are MVP-2 (E9-02)
- [ ] behave `sync.feature` on the fixture branch, including the stale-chunk scenario (moved here from the former E5-05; `read_chunk` is E7-03)

### E9-03 · feat: removing a version or library removes it everywhere and frees its content

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` · **Area** backend / ingestion · **Stories** SYNC-03 · **Depends on** E3-05a, E5-02, E7-04 · **Size** M

**Context.** Stale docs found by a user or an agent are worse than none; removed content must
disappear from every surface and from disk.

**Expected behavior**

```gherkin
Scenario: A removed version is gone everywhere
  When the user removes version "v1.3.0" of "/fixture/docs-repo"
  Then it does not appear in browse, search, list_libraries or search_docs
  And content used only by "v1.3.0" is garbage-collected
  And content shared with "v1.4.0" is kept
```

**Criteria of success**

- [ ] `RemoveVersion` / `RemoveLibrary` use cases; `DELETE` REST routes (the CLI command is MVP-2, E6-03)
- [ ] use cases live in ingestion and call catalog and retrieval through bridges
- [ ] GC job run by ingestion, calling each domain's `CollectGarbage` through bridges: superseded manifests past their grace period, blobs, chunk sets and FTS rows not referenced by any manifest are deleted; chunk IDs kept as tombstones (E7-03); credentials of a removed library deleted
- [ ] default version recomputed after removal
- [ ] behave scenario over REST and MCP; GC unit tests on shared content

#### E9 · MVP-2

### E9-02 · feat: sync failures get distinct error codes, and moved tags are reported

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** SYNC-04 (error codes, moved tags) · **Depends on** E9-01, E6-03 · **Size** M

**Context.** An upstream problem (repo deleted or private, credential expired, branch deleted, tag
moved) must never take a team's docs away, and users need to know which one it was. E9-01 keeps
the last good version and records the error; this issue makes the reason precise.

**Expected behavior**

```gherkin
Scenario Outline: Upstream failures keep serving docs
  Given "/fixture/docs-repo" is imported
  And <problem>
  When the library is synced
  Then the last good version is still served
  And the library shows the error "<code>"
  Examples:
    | problem                           | code             |
    | the repository was deleted        | repo_unreachable |
    | the credential expired            | auth_failed      |
    | branch "next" was deleted         | ref_deleted      |
    | tag "v1.4.0" now points elsewhere | tag_moved        |
```

**Criteria of success**

- [ ] error codes stored on the sync job with time and message (shown by E8-03 through `GET …/jobs`)
- [ ] `exactdocs sync` exits non-zero with the reason
- [ ] sync checks tag versions for moved tags; a moved tag is reported, never silently re-imported
- [ ] behave scenarios using the fixture HTTP server (delete repo, rotate token, delete branch, move tag)

### E9-04 · feat: editing a library's paths or tag rules re-processes every version safely

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** LIB-09, TAG-02 (edit rules) · **Depends on** E9-01, E4-03 · **Size** M

**Context.** The first selection is rarely perfect. Settings belong to the library, so every
version must follow, while users keep reading the old state until the new one is complete.

**Expected behavior**

```gherkin
Scenario: Adding an exclusion re-processes every version
  Given "/fixture/docs-repo" has versions "v1.3.0" and "v1.4.0"
  When the user adds the exclusion "docs/archive/**"
  Then a job re-processes both versions
  And until it finishes, both versions still list "docs/archive/" articles
  And afterwards neither does
```

**Criteria of success**

- [ ] `UpdateLibrarySettings` use case: validated paths and tag rules; one job re-processes all versions at their recorded commit SHAs (re-fetch when paths changed, tag-only changes re-use stored blobs)
- [ ] each version swapped atomically (E1-03)
- [ ] `PUT /api/v1/libraries/{owner}/{repo}/settings`; behave scenario

**Notes.** Owns `PUT …/settings` (in MVP-1 paths and tag rules are set only when adding,
E3-02 and E4-03). Chunking settings (re-chunk only) come with E4-05. Branch versions are
re-processed at their current commit, not synced.

### E9-05 · feat: new tags are imported automatically and branches re-synced on a schedule

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` · **Area** backend / ingestion · **Stories** SYNC-02 · **Depends on** E9-01, E3-11 · **Size** M

**Context.** Users don't want to add every release by hand.

```gherkin
Scenario: A new matching tag becomes a version, old ones are pruned
  Given "/fixture/docs-repo" auto-imports tags "v*" keeping the last 2
  When tag "v1.5.0" is pushed and the scheduled check runs
  Then "v1.5.0" is imported
  And the oldest auto-imported version is removed
  And manually imported versions are kept
```

- [ ] per-library tag pattern, retention N, branch sync interval; scheduler (DBOS scheduled workflow)
- [ ] `auto` vs `manual` origin on versions; retention only removes `auto`
- [ ] tests with the kernel clock

### E9-06 · feat: a moved tag can be re-imported after confirmation

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` `area: web` · **Area** backend / ingestion, web UI · **Stories** SYNC-04 (MVP-2) · **Depends on** E9-02 · **Size** S

```gherkin
Scenario: Confirming a moved tag
  Given tag "v1.4.0" was reported as moved
  When the user confirms the re-import
  Then "v1.4.0" is re-imported at its new commit and the error clears
```

- [ ] `POST /api/v1/libraries/{owner}/{repo}/versions/reimport` with body `{ref}` (the ref cannot be followed by a path segment); UI button on the error; CLI `--confirm`

### E9-07 · feat: library owners pin the default version

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` `area: web` · **Area** backend / catalog, web UI · **Stories** LIB-10 · **Depends on** E1-02, E8-06 · **Size** S

**Context.** The newest tag is not always the one a team uses.

```gherkin
Scenario: A pinned default stays when a higher tag arrives
  Given the default of "/fixture/docs-repo" is pinned to "v1.3.0"
  When "v1.5.0" is imported
  Then "/fixture/docs-repo" still answers with "v1.3.0"
  And list_libraries shows the default as pinned
```

- [ ] pin/unpin use case + REST; unpinned follows the *Default version* rule
- [ ] UI pin action in the version picker; `list_libraries` field `default_pinned`

---

## E10 Run & operations

### E10-01 · feat: ExactDocs makes no outbound connections except the ones the user configured

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: backend` `area: infra` · **Area** CI / release / infra · **Stories** RUN-03 · **Depends on** E3-05a, E5-03, E7-04, E7-06 · **Size** M

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

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: infra` · **Area** CI / release / infra · **Stories** RUN-02 · **Depends on** E4-02 · **Size** S

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

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: infra` `area: backend` · **Area** CI / release / infra, docs · **Stories** RUN-01, Decisions *Data location*, *Git* · **Depends on** E1-06, E2-03, E7-07, E10-02 · **Size** L

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

**Milestone** MVP-1 · **Labels** `type: feature` `status: ready` `area: infra` `area: web` · **Area** CI / release / infra, web UI · **Stories** RUN-01 · **Depends on** E8-04, E8-07, E8-09, E10-02 · **Size** M

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

**Milestone** MVP-1 · **Labels** `type: chore` `status: ready` `area: infra` · **Area** CI / release / infra · **Stories** RUN-01, RUN-02, RUN-03, LIB-05, IMP-01 · **Depends on** - (coordinate with E10-02, E10-03a) · **Size** L · **Issue** [#124](https://github.com/SirCypkowskyy/ExactDocs/issues/124)

**Context.** The layer cache is invalidated by every release and by README/test edits, and the image is not hardened; MVP-1 also needs `git` and `openssh-client` in the runtime.

- [ ] caching: `VERSION` below the dependency layers; dependency layer built only from `uv.lock` (`uv export --frozen`); only `packages/*/src` + metadata copied (no tests); pnpm pinned and installed before any `COPY`, `pnpm fetch` then `install --offline`; source-only changes show dependency layers `CACHED`
- [ ] hardening: base images pinned by digest (Dependabot), runtime with only `git`, `openssh-client`, `ca-certificates`, `tini` (PID 1), no pip/setuptools, no setuid bits, read-only app files, only `/data` and `/tmp` writable; amd64 apt layer built under QEMU for that stage only
- [ ] CI: hadolint, Trivy/Grype gate on fixable CRITICAL/HIGH, smoke test with `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges` incl. a `file://` import; size budget kept
- [ ] docs: hardened compose example in README; scan gate in `docs/releasing.md`

#### E10 · MVP-2

### E10-04 · feat: upgrades migrate automatically, and re-indexing is one command when needed

**Milestone** MVP-2 · **Labels** `type: feature` `status: triage` `area: backend` `area: infra` · **Area** CI / release / infra · **Stories** RUN-04, CLI-01 (`reindex`) · **Depends on** E1-01, E5-02 · **Size** M

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

**Milestone** MVP-2 · **Labels** `type: docs` `status: triage` · **Area** docs · **Stories** - (documentation) · **Depends on** MVP-1 complete · **Size** L · **Issue** [#123](https://github.com/SirCypkowskyy/ExactDocs/issues/123)

**Context.** The ASCII diagrams in README, `docs/architecture.md` and `web/README.md` are hard to maintain and cannot show flows; the docs must describe the system as built.

- [ ] Mermaid enabled in `zensical.toml` (superfences custom fence) and validated in CI (mermaid-cli parse/render)
- [ ] every ASCII diagram replaced by Mermaid (README *How it works*, architecture domains and bridges, web slices)
- [ ] new diagrams: data model (ER), import flow, query flow, retrieval modes, auth, branching and releases (`gitGraph`), CI/CD and runners
- [ ] README, architecture, releasing, index and CONTRIBUTING reflect MVP-1 as built; planned features labelled as planned; strict docs build passes

#### E10 · Next: Operations

### E10-05 · feat: orchestrators see whether ExactDocs is alive and ready to serve

**Milestone** Next: Operations · **Labels** `type: feature` `status: triage` `area: backend` `area: infra` · **Area** CI / release / infra · **Stories** OPS-02 · **Depends on** E1-01 · **Size** S

```gherkin
Scenario: Readiness follows the database
  When the database is unreachable
  Then "/healthz" reports up and "/readyz" reports not ready
```

- [ ] `/healthz`, `/readyz` (database reachable) unauthenticated, excluded from traces; Docker `HEALTHCHECK`
- [ ] `/api/health` stays as an alias of `/healthz` (existing clients and E2-03's exemption list keep working)

### E10-06 · feat: operators back up and restore an instance with one command

**Milestone** Next: Operations · **Labels** `type: feature` `status: triage` `area: backend` · **Area** CI / release / infra · **Stories** OPS-02, CLI-01 (`backup`, `restore`) · **Depends on** E10-05 · **Size** M

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

**Milestone** Next: Operations · **Labels** `type: feature` `status: triage` `area: backend` · **Area** CI / release / infra · **Stories** OPS-01, RUN-03, RET-04 (tool-call spans), Decisions *Telemetry* · **Depends on** E10-01 · **Size** M

**Context.** Operators monitor ExactDocs with the same stack as everything else, without leaking queries.

```gherkin
Scenario: Traces go only to the configured collector, without query text
  Given telemetry is "otlp" with a local collector
  When a user searches "retry_policy"
  Then the collector receives request and search spans
  And no span contains "retry_policy"
```

- [ ] `logfire.configure(send_to_logfire=False, console=False)` only when `EXACTDOCS_TELEMETRY=otlp`; FastAPI built-in OpenTelemetry; health checks excluded
- [ ] spans for import, sync, search (per mode and stage); query text only with an explicit opt-in
- [ ] pydantic-ai instrumentation with `include_content=False`; one span per tool call (nested in `run_code` once E11-10 exists)
- [ ] RUN-03 test extended: only the collector is contacted

### E10-08 · feat: operators scrape ExactDocs metrics with Prometheus

**Milestone** Next: Operations · **Labels** `type: feature` `status: triage` `area: backend` · **Area** CI / release / infra · **Stories** OPS-01, RET-07 (LLM-usage metrics) · **Depends on** E10-07 · **Size** S

```gherkin
Scenario: Metrics are exposed when enabled
  Given "EXACTDOCS_METRICS" is on
  When Prometheus scrapes "/metrics"
  Then it gets request, search, import, sync and LLM-usage metrics
```

- [ ] Prometheus via an additional OpenTelemetry metric reader; off by default; `/metrics` behind the host allowlist

---

## E11 AI retrieval

All E11 issues: milestone **Next: AI retrieval**, labels `type: feature` `status: triage`
`area: backend`, Area *backend / retrieval* (E11-14: `area: web`, Area *web UI*). Code lives in retrieval adapters
and is imported only through the `exactdocs[ai]` extra (Decisions *Agent stack*); every model
call uses `httpx2`; every mode returns the MCP-05 result shape and has a "wrong version gets
nothing" test.

### E11-01 · feat: the retrieval mode is chosen per call, library and instance, from what is configured

**Stories** RET-06 (backend), MCP-05 (mode), RUN-02, C7-02 (library mode) · **Depends on** E7-04 · **Size** M

**Context.** One size does not fit every documentation set, and asking for an unavailable mode
must fail clearly.

```gherkin
Scenario: Precedence is call, then library, then instance
  Given the instance mode is "bm25" and the library's mode is "hybrid"
  When an agent searches with mode "bm25"
  Then the result says retrieval mode "bm25"
```

- [ ] `RetrievalPipeline` port with a registry of available modes from configuration; library setting validated against it
- [ ] `exactdocs[ai]` extra with pinned matching `pydantic-ai-slim` + `pydantic-ai-harness[codemode]`; a test proves nothing from it is imported when no model is configured

### E11-02 · feat: a retrieval eval suite compares modes on the fixture libraries

**Stories** RET-09, RUN-05 · **Depends on** E11-01, E5-04 · **Size** M

**Context.** Modes must be compared before one becomes a default.

```gherkin
Scenario: The suite reports per-mode metrics
  When the eval suite runs with only BM25 available
  Then it reports recall@k, wrong-version rate, cost and latency for "bm25"
```

- [ ] Pydantic Evals dataset from the fixture's expected queries plus questions; runs in CI for BM25, and for other modes when endpoints are provided
- [ ] wrong-version rate computed from returned results (the agentic trace check is added by E11-11)

### E11-03 · feat: an embedding endpoint embeds every version in the background

**Stories** RET-01 · **Depends on** E11-01 · **Size** M

**Context.** Semantic search with a model of the operator's choice, without blocking BM25.

```gherkin
Scenario: Changing the model re-embeds instead of mixing vectors
  Given chunks were embedded with model "a"
  When the operator switches to model "b"
  Then all chunks are re-embedded with "b" in the background while BM25 answers
```

- [ ] `pydantic_ai.Embedder` adapter (OpenAI-compatible, Ollama, TEI...), own batching, `EmbeddingSettings(dimensions=…)`, model + dimensions stored per vector
- [ ] vectors keyed by chunk content (dedup); background job per version
- [ ] SQLite vector storage (Decisions *Vector storage*): float32 BLOBs, brute-force cosine scoped to the active manifest, behind a `VectorIndex` port; numpy only in the `[ai]` extra; pgvector on PostgreSQL (E12-02)

### E11-04 · feat: search becomes hybrid (BM25 + vectors fused with RRF)

**Stories** RET-01 · **Depends on** E11-03 · **Size** M

```gherkin
Scenario: Hybrid search when an embedding model is configured
  Given every chunk of "v1.4.0" is embedded
  When an agent searches "how do I retry failed calls"
  Then the result says retrieval mode "hybrid"
  And no chunk from another version is returned
```

- [ ] vector search scoped to the active manifest; RRF fusion; `coverage` counts both halves
- [ ] versions not yet embedded answer with BM25 and `fallback_reason`

### E11-05 · feat: a cross-encoder reranker reorders the top candidates

**Stories** RET-02 · **Depends on** E11-01 · **Size** M

```gherkin
Scenario: A reranker timeout never fails the search
  Given a reranker endpoint that times out
  When an agent searches
  Then results arrive in the unreranked order with "reranked: false" and a fallback reason
```

- [ ] Cohere-compatible / Jina / TEI adapter; top N (default 32) reranked; errors logged and fallen back

### E11-06 · feat: an LLM endpoint enables HyDE for hybrid search

**Stories** RET-03 · **Depends on** E11-04 · **Size** M

**Context.** Companies route LLM traffic through their own gateways; HyDE improves the vector half.

```gherkin
Scenario: HyDE is the default with embeddings and an LLM
  Given an embedding model and an LLM are configured
  When an agent searches without a mode
  Then the result says retrieval mode "hybrid_hyde"
  And a repeated query for the same version reuses the cached hypothetical answer
```

- [ ] `OpenAICompatibleProvider`; proxy on the transport; exactly one retry layer; overall `request_timeout`; key stored as a secret
- [ ] extra HTTP headers and extra model parameters configurable (RET-03), headers sent on every LLM call (test with a mock gateway); header values treated as secrets in logs
- [ ] HyDE = `Agent(output_type=str)` output embedded; cache per (query, version)

### E11-07 · feat: a judge model can rerank candidates

**Stories** RET-02 · **Depends on** E11-05, E11-06, E11-08 · **Size** M

```gherkin
Scenario: The judge only rates candidates it was given
  When the judge model returns a chunk ID it was not given
  Then the output validator rejects it and the search falls back to the unreranked order
```

- [ ] one call rates all candidates (`list[...]` output, bounded score), per-call timeout, counted against RET-07 budgets

### E11-08 · feat: LLM usage is limited by budgets and rate limits

**Stories** RET-07 · **Depends on** E11-06; metrics with E10-08 · **Size** L

**Context.** HyDE and agentic retrieval cost money.

```gherkin
Scenario: Reaching the daily budget falls back to the non-LLM pipeline
  Given the instance's daily token budget is used up
  When an agent searches in "hybrid_hyde" mode
  Then the result says retrieval mode "hybrid" with fallback reason "llm_budget_reached"
```

- [ ] harness `SpendLimits` per instance, library and user; spend store = `retrieval_` tables in the shared database (Alembic), so it works on SQLite and PostgreSQL
- [ ] requests per minute per token via FastMCP `SlidingWindowRateLimitingMiddleware`
- [ ] usage via pydantic-ai `gen_ai.client.token.usage` and cost metrics (exported by E10-08)

### E11-09 · feat: agents read article outlines with `article_outline`

**Stories** RET-04 · **Depends on** E7-03 · **Size** S

```gherkin
Scenario: An outline lists headings only
  When an agent calls "article_outline" for "guide/install.md" of "v1.4.0"
  Then it gets the heading tree with chunk IDs and no body text
```

- [ ] MCP tool + REST route, typed return model; reused by the agent (E11-10)

### E11-10 · feat: agentic retrieval browses the tree in Code Mode and justifies its answer

**Stories** RET-04 · **Depends on** E11-09, E11-08 · **Size** L

**Context.** Some questions need reasoning over structure, not keyword or vector similarity.

```gherkin
Scenario: Agentic mode returns justified articles from the pinned version
  Given an LLM is configured and agentic mode is on
  When an agent searches "/fixture/docs-repo/v1.4.0" in mode "agentic"
  Then results carry a justification and the explored path
  And every result belongs to "v1.4.0"
```

- [ ] pydantic-ai agent with harness Code Mode: read tools (`list_articles`, `article_outline`, `read_article`, `read_chunk`, `search_docs`) only inside sandboxed `run_code` (Monty, never IPython), typed returns
- [ ] bounded by `max_tool_calls`, Monty resource limits, `UsageLimits`; exceeding ends the run and falls back to BM25 with the reason
- [ ] pydantic-ai instrumentation with `include_content=False`; one span per tool call, nested in `run_code` (exported by E10-07 when telemetry is on)

### E11-11 · feat: agentic retrieval only sees what the caller may see and stops on loops

**Stories** RET-04, RET-09 (agentic trace check) · **Depends on** E11-10 · **Size** M

```gherkin
Scenario: The output guardrail rejects foreign articles
  When the agent proposes an article that is not in the pinned version
  Then the guardrail rejects it and it is not returned
```

- [ ] caller access scope passed as `deps`, never as model-visible tool arguments
- [ ] output guardrail (pinned version, visibility); loop detection falls back to BM25 with the reason
- [ ] eval trace check in the E11-02 suite proves agentic runs stayed within the requested version (the only place this check lives)

### E11-12 · feat: similar agentic questions are answered from a cache

**Stories** RET-05 · **Depends on** E11-10 · **Size** M

```gherkin
Scenario: A similar question hits the cache
  Given "how do I configure retries" was answered agentically for "v1.4.0"
  When an agent asks "how to configure retry behaviour" for "v1.4.0"
  Then the cached result is returned with "cache_hit: true"
```

- [ ] similarity by hybrid search over past questions (BM25 without embeddings), configurable threshold; invalidated on re-sync

### E11-13 · feat: the repository's `AGENTS.md` / `CLAUDE.md` guide agentic retrieval

**Stories** RET-08 · **Depends on** E11-10, E3-05a · **Size** M

```gherkin
Scenario: Instruction files are untrusted notes by default
  Given the library's repository has an AGENTS.md describing its docs layout
  And the owner enabled repo guidance without marking the library trusted
  When the agent opens a directory
  Then the file reaches it as a user-channel note, not as system instructions
```

- [ ] importer keeps instruction files per version even outside the selection; off by default
- [ ] harness Repo Context over a read-only, database-backed workspace; system instructions only for trusted libraries

### E11-14 · feat: the UI shows each library's effective retrieval pipeline and LLM usage

**Stories** RET-06 (UI), RET-07 (UI) · **Depends on** E11-01, E11-08 · **Size** M · **Labels** `area: web` · **Area** web UI

```gherkin
Scenario: The effective pipeline is visible
  Given an embedding model is configured
  When the user opens a library's settings
  Then the effective pipeline "hybrid" is shown and only configured modes can be chosen
```

- [ ] library retrieval-mode setting, instance usage page (tokens, cost, budget left); vitest

---

## E12 Teams & integrations

All E12 issues: milestone **Next: Teams & integrations**, labels `type: feature`
`status: triage` and the area noted.

### E12-01 · feat: a shared instance runs on PostgreSQL with several server processes

**Stories** TEAM-01 · **Area** backend / catalog, CI · `area: backend` `area: infra` · **Depends on** MVP-1 · **Size** L

**Context.** The whole team should work on the same libraries.

```gherkin
Scenario: Two processes share one PostgreSQL database
  Given two ExactDocs processes use the same PostgreSQL database
  When a library is imported through the first
  Then the second serves it, and the import ran exactly once
```

- [ ] PostgreSQL adapters for every repository, run by the existing adapter contract tests in CI (ParadeDB image)
- [ ] job claiming safe across processes (`FOR UPDATE SKIP LOCKED`, or DBOS from E3-11)
- [ ] migrations for both databases; docker-compose example in README verified in CI

### E12-02 · feat: the ranking suite passes on ParadeDB as on SQLite

**Stories** TEAM-01, SRCH-01, RET-01 (pgvector) · **Area** backend / retrieval · `area: backend` · **Depends on** E12-01, E5-04, E11-03 (pgvector part only) · **Size** M

```gherkin
Scenario: The same ranking on both engines
  When the ranking suite runs on ParadeDB
  Then every expected query ranks its section first, as on SQLite
```

- [ ] `pg_search` adapter of the search port with the same identifier column (E5-01)
- [ ] pgvector adapter of the `VectorIndex` port (E11-03); can land after the BM25 part if E11-03 is not merged yet

### E12-03 · feat: users sign in through OIDC with groups from the identity provider

**Stories** ACL-01 · **Area** backend / identity, web UI · `area: backend` `area: web` · **Depends on** E12-01 · **Size** L

```gherkin
Scenario: Groups follow the identity provider on every sign-in
  Given the IdP puts "alice" in group "payments"
  When "alice" signs in through OIDC
  Then she is a member of ExactDocs group "payments"
  And when the IdP removes her from it, her next sign-in removes her membership
```

- [ ] OIDC and local accounts coexist: OIDC sign-in is offered when OIDC is configured, local sign-in stays available (no `AUTH_MODE` switch); group claim mapping; the local admin keeps working as break-glass
- [ ] OIDC settings documented in the README and compose example; whether OIDC is offered follows "OIDC configured or not" (`EXACTDOCS_AUTH_MODE` stays removed, E2-01)
- [ ] tests against a mock OIDC provider

### E12-04 · feat: MCP clients connect with OAuth as well as API tokens

**Stories** ACL-01, Decisions *MCP auth* · **Area** MCP tools · `area: backend` · **Depends on** E12-03 · **Size** M

```gherkin
Scenario: A web host connects with OAuth
  When a web MCP host discovers the OAuth metadata and signs the user in
  Then it can call "list_libraries" as that user
  And API tokens keep working
```

- [ ] FastMCP `OIDCProxy` + token verifier via `MultiAuth`; `/.well-known/...` served at the root; host/origin allowlist still applies

### E12-13 · feat: operators create, disable and reset local user accounts

**Stories** ACL-06 · **Area** backend / identity, web UI · `area: backend` `area: web` · **Depends on** E2-02, E8-01 · **Size** M

**Context.** Not every team member signs in through OIDC; operators need local accounts beyond
the first admin, without opening self-signup.

```gherkin
Scenario: An operator creates a local user
  When the operator runs "exactdocs user create bob"
  Then "bob" can sign in with the password set at creation
  And there is no sign-up page

Scenario: A disabled user is locked out
  Given "bob" is signed in and has an API token
  When the operator disables "bob" in the UI
  Then bob's session and token are refused
```

- [ ] `user create|disable|reset-password` (local CLI commands, like `admin create`) and an operator-only users page in the UI (list, create, disable, reset password)
- [ ] uses the `role` column of `Account` (E2-01); disabling ends sessions and refuses tokens; reset ends sessions
- [ ] no self-signup route; unit, behave and vitest tests

### E12-05 · feat: library roles are enforced on every UI action, REST call and MCP tool

**Stories** ACL-02 · **Area** backend / identity, backend / catalog · `area: backend` · **Depends on** E12-03, E12-13 · **Size** L

**Context.** Docs belong to teams, not to whoever imported them.

```gherkin
Scenario: A viewer can read but not edit
  Given "bob" is a viewer of "/fixture/docs-repo"
  Then "bob" can search and read it in the UI and over MCP
  But changing its paths is refused
```

- [ ] roles viewer < contributor < admin < creator; grants to users and groups; effective role = highest
- [ ] an authorization check in every use case via an `AccessPolicy` driven port (identity bridge); test matrix role × action

### E12-06 · feat: owners share libraries and transfer ownership in the UI

**Stories** ACL-02 · **Area** web UI · `area: web` · **Depends on** E12-05 · **Size** M

```gherkin
Scenario: Transferring ownership
  When the creator transfers "/fixture/docs-repo" to "carol"
  Then "carol" is the creator and the previous owner becomes admin
```

- [ ] sharing dialog (users, groups, roles); only the creator removes admins and transfers ownership; vitest

### E12-07 · feat: operators control who may create libraries

**Stories** ACL-03 · **Area** backend / identity · `area: backend` · **Depends on** E12-05 · **Size** S

```gherkin
Scenario: Only permitted users create libraries
  Given only group "docs-admins" may create libraries
  When "bob" outside that group adds a library
  Then it is refused
```

- [ ] instance permission mapped from users or groups; the creator becomes owner

### E12-08 · feat: tokens act as their user, optionally narrowed, and hidden libraries stay invisible

**Stories** ACL-04 · **Area** backend / identity, MCP tools · `area: backend` · **Depends on** E12-05 · **Size** M

```gherkin
Scenario: No access looks like not found
  Given "bob" has no access to "/acme/secret"
  When bob's agent calls "query-docs" for "/acme/secret"
  Then the error is the same as for a library that does not exist
  And "/acme/secret" never appears in listings
```

- [ ] tokens scoped to their user and optionally to chosen libraries; listings, `resolve-library-id`, errors and caches filtered

### E12-09 · feat: access changes and deletions are logged

**Stories** ACL-05 · **Area** backend / identity · `area: backend` `area: web` · **Depends on** E12-05 · **Size** M

```gherkin
Scenario: A grant is recorded
  When "alice" grants "bob" the viewer role
  Then the library's audit log shows actor "alice", the grant and the time
```

- [ ] grants, revocations, deletions, ownership transfers recorded; visible to library admins and operators (REST + UI)

### E12-10 · feat: libraries are declared in `exactdocs.sources.yaml` and applied with a dry-run diff

**Stories** TEAM-02 · **Area** backend / ingestion · `area: backend` · **Depends on** E9-05, E4-05, E6-02 · **Size** L

```gherkin
Scenario: Apply is idempotent
  Given a sources file declaring "/fixture/docs-repo" with tag pattern "v*"
  When the operator runs "exactdocs sources plan"
  Then the diff is printed and nothing changes
  When the operator runs "apply" twice
  Then the second apply reports no changes
```

- [ ] schema (URL, ID, ref or tag pattern, paths, tags, chunking) with JSON Schema; plan/apply via REST

### E12-11 · feat: a push to the docs repository triggers a sync

**Stories** TEAM-03 · **Area** backend / ingestion · `area: backend` · **Depends on** E9-01 · **Size** M

```gherkin
Scenario: A signed webhook starts a sync
  When GitHub sends a signed push webhook for the library's branch
  Then a sync starts within 30 seconds
  And unsigned or unknown webhooks are rejected
```

- [ ] per-library webhook secret; GitHub, GitLab and Bitbucket signature formats; deduplicated deliveries

### E12-12 · feat: MCP hosts that support Apps render articles and results as UI

**Stories** MCP-08 · **Area** MCP tools · `area: backend` · **Depends on** E12-04 · **Size** L

```gherkin
Scenario: App tools add UI without changing existing tools
  When a host that supports MCP Apps calls "view_article"
  Then it renders the article with headings and code
  And hosts without Apps support get a text fallback
  And "read_article" is unchanged
```

- [ ] `view_article`, `view_search` with `@mcp.tool(app=True)`, `fastmcp[apps]` with a pinned `prefab-ui`; explicit text fallback

---

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
| reStructuredText, AsciiDoc, Jupyter notebooks | Markdown covers most repositories |

---

## Coverage matrix

Every story ID → the issues that deliver it. *(MVP-2)* parts are listed separately.

| Story | MVP-1 issues | MVP-2 / Next issues |
|---|---|---|
| AUTH-01 | E2-01, E2-02, E8-01 | - |
| AUTH-02 | E2-03, E7-07 (stdio), E8-02 | E6-02 (login), E6-03 (CLI) |
| CLI-01 | - | E6-02, E6-03, E10-04 (`reindex`), E10-06 (`backup`/`restore`) |
| LIB-01 | E3-01, E8-04 | - |
| LIB-02 | E3-02, E8-04 | E3-10 (images) |
| LIB-03 | - | E3-08, E8-11 |
| LIB-04 | E1-02, E1-03, E3-02, E3-05a, E8-04, E9-01 | - |
| LIB-05 | E3-04, E8-04 | - |
| LIB-06 | - | E3-09, E8-11 |
| LIB-07 | E3-06, E8-04, E8-10b, E7-05 | E3-09 (precedence) |
| LIB-08 | - | E6-03 |
| LIB-09 | - | E9-04, E8-10a, E4-05 (re-chunk only) |
| LIB-10 | - | E9-07 |
| LIB-11 | E3-07, E8-10b | E6-03 (CLI) |
| IMP-01 | E3-03 | E3-10 (images) |
| IMP-02 | E4-02, E1-04 | - |
| IMP-03 | - | E4-05 |
| IMP-04 | E4-01, E8-07, E7-03 | - |
| IMP-05 | E1-03, E1-05, E3-05a | E3-11 (DBOS resume) |
| IMP-06 | E1-05, E3-05b, E8-04 | - |
| TAG-01 | E4-03, E8-06 | E4-06, E8-14 (manual tags), E3-12 |
| TAG-02 | E4-03, E8-04 (rules set when adding) | E9-04, E8-10a (editing rules), E4-06 (manual tags combine) |
| TAG-03 | E4-03 (listing), E5-03 (search), E7-02, E7-04, E8-06, E8-09 | - |
| BRW-01 | E8-06, E8-07 | E8-12 (imported images) |
| BRW-02 | - | E8-12 |
| BRW-03 | E8-06, E5-03 (links) | - |
| BRW-04 | E8-06 | E8-13, E3-12 (renames) |
| BRW-05 | E8-03 | - |
| SRCH-01 | E5-01, E5-02, E5-03, E5-04, E8-09 | E12-02 (PostgreSQL parity) |
| SRCH-02 | E5-02, E5-03, E8-09 | - |
| SRCH-03 | - | E5-06, E8-15 |
| MCP-01 | E7-02 | - |
| MCP-02 | E7-02 | - |
| MCP-03 | E7-03 | E7-08 (resources) |
| MCP-04 | E1-04, E5-03, E7-03, E7-04, E9-01 (`stale_chunk` scenario) | E7-09 (new location), E3-12 (renames) |
| MCP-05 | E5-03, E7-04 | E11-01 (modes) |
| MCP-06 | - | E7-10 |
| MCP-07 | E4-01 (import), E7-02, E7-05 (context7 tools) | - |
| MCP-08 | - | E12-12 (Next: Teams & integrations, needs ACL-01) |
| C7-01 | E7-05 | - |
| C7-02 | E7-06 | E3-09 (`rules`), E11-01 (library mode) |
| C7-03 | - | E6-04 |
| C7-04 | - | E6-05 |
| SYNC-01 | E9-01, E8-10b | E6-03 (CLI) |
| SYNC-02 | - | E9-05 |
| SYNC-03 | E9-03, E8-10b | - |
| SYNC-04 | E9-01 (last good version, error on the job), E8-03 (error shown) | E9-02 (error codes, moved tags), E9-06 (moved-tag re-import) |
| RUN-01 | E1-01, E10-03a, E10-03b | - |
| RUN-02 | E10-02, E4-02 | E11-01 (lazy `[ai]` extra) |
| RUN-03 | E10-01, E7-02 | E10-07 (collector only) |
| RUN-04 | - | E10-04 |
| RUN-05 | E1-06, E5-04 | E11-02 |
| RET-01 | - | E11-03, E11-04, E12-02 (pgvector) |
| RET-02 | - | E11-05, E11-07 |
| RET-03 | - | E11-06 (incl. extra headers) |
| RET-04 | - | E11-09, E11-10, E11-11 (and E10-07 for spans) |
| RET-05 | - | E11-12 |
| RET-06 | - | E11-01, E11-14 |
| RET-07 | - | E11-08, E11-14 (and E10-08 for metrics) |
| RET-08 | - | E11-13 |
| RET-09 | - | E11-02, E11-11 (agentic trace check) |
| ACL-01 | - | E12-03, E12-04 |
| ACL-02 | - | E12-05, E12-06 |
| ACL-03 | - | E12-07 |
| ACL-04 | - | E12-08 |
| ACL-05 | - | E12-09 |
| ACL-06 | - | E12-13 |
| TEAM-01 | - | E12-01, E12-02 |
| TEAM-02 | - | E12-10 |
| TEAM-03 | - | E12-11 |
| OPS-01 | - | E10-07, E10-08 |
| OPS-02 | - | E10-05, E10-06 |

!!! warning "Deferred and cross-milestone notes"
    - **Intentionally deferred:** all *Later* ideas (no issues). MCP-08 is placed in
      *Next: Teams & integrations* because it depends on ACL-01.
    - **Settled in review round 1:** library-ID case and charset (E1-02), SSH host-key policy
      (E3-04), SQLite vector storage (E11-03, Decisions *Vector storage*), the persistence stack
      (E1-01, Decisions *Persistence*), and extra local users (ACL-06, E12-13).
    - **Settled in review round 2:** private repositories (E3-04, LIB-05) stay in MVP-1; E6-02,
      E6-03, E9-02, E9-04 and E8-10a moved to MVP-2, so MVP-1 manages tokens and libraries in the
      web UI (title edits and adding versions moved from E8-10a to E8-10b); the smoke test
      imports the mounted fixture via `file://` and needs neither GitHub nor this repository.
    - **Merged or split IDs:** E7-01 → E7-02, E5-05 → E7-03, E8-05 → E8-04, E8-08 → E8-06;
      E4-04 dissolved into E4-03 (listing) and E5-03 (search); E3-05 → E3-05a, E3-05b;
      E8-10 → E8-10a, E8-10b; E10-03 → E10-03a, E10-03b.
    - **Cross-milestone dependencies:** RET-07 metrics need E10-08; RUN-03's test grows with
      E10-07 (collector) and E11 (model endpoints); E12-02's pgvector part needs E11-03; E12-10
      needs MVP-2's E9-05, E4-05 and E6-02.
