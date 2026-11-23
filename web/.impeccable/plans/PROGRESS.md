# Progress: ExactDocs redesign (#486) and its backend issues

Kept up to date by the overnight session that continues `HANDOFF.md`. Newest state first in each
section. Read `HANDOFF.md` for the plan, the owner's decisions and the rules.

_Last updated: 2026-11-23 23:40 UTC._

## Frontend (`feature/486-design-system`)

### A. Shared kit: done (`15c42f9`)

- Band menus (`InterfaceMenu`, `LanguageMenu`) open from `IconButton variant="band"`; unused
  messages dropped.
- Tokens: `--logo-tile` + `--logo-tile-edge` (white tile, ink hairline 12 %, 30 % with more
  contrast) used by `LibraryMark`; `--chart-series` (AA on the sheet and raised panels in every
  theme) and `--chart-highlight` (= `route`).
- `DESIGN.md` + `.impeccable/design.json`: rows for every new primitive, DataTable v2,
  IconButton, ConfirmDialog/TypedConfirmDialog, Badge, Meter, Avatar, ToggleGroup and the new
  tokens; sections Confirmations, Data tables, Icons and motion; rules "Confirm with
  AlertDialog" and "A context menu mirrors a visible menu".
- Fixes found while testing: faceted-filter options were not clickable with a mouse (cmdk's
  `data-disabled="false"` matched the menu row's disabled style; new `menuRow` recipe); facets
  were written to the URL as JSON (facet-aware `stringifySearch` in the router); confirmations
  return focus to their opener; ToggleGroup items are 44 px on touch; table details from the
  screenshots (row-menu alignment, no Columns menu on phones, pagination alignment, facet
  checkbox edges at 3:1); Jobs `#` shows the distinctive tail of the time-ordered id; phone
  cards show the version.
- Tests: 57 files / 809 tests (was 52 / 734): primitives, ConfirmDialog/TypedConfirmDialog,
  DataTable v2 (URL view, `pageOf`, `parseFacet`, cursor walk past 200 rows, client and offset
  modes, Polish pagination, states, menus, phone cards), reduced-motion rules read from the
  stylesheets.
- Checks: typecheck, Biome (3 known warnings in browse), fallow arch + dead code, react-doctor,
  vitest, build (check-dist, bundle-size) all green. `/jobs` checked at 1440 and 390 px, dark,
  Polish, with menus and popovers open.

### B. Per-feature pass: in progress

Five agents, one per feature group, each on a local branch cut from `15c42f9` and merged back
here when green:

| Group | Folders | State |
|---|---|---|
| libraries | `features/libraries` (libraries list, jobs, job problems, add library) | in progress |
| browse | `features/browse`, `features/search` (articles table, reader, breadcrumb; global search stays a list) | in progress |
| settings | `features/library-settings` (versions table, typed confirmations, reprocess) | in progress |
| sharing | `features/sharing`, `access-log`, `ai`, `playground` (grants, access logs, AI usage; playground icons only) | in progress |
| people | `features/users`, `tokens`, `auth` (users, tokens, account tabs, sign-in/setup) | in progress |

### C. UI for finished backend branches: not started

Waits for each backend branch to be green (below).

## Backend

| Issue | Branch | State |
|---|---|---|
| #487 | `feature/487-interface-preferences` (`69fd893`) | develop merged, API types regenerated, contract test on memory/SQLite/PostgreSQL (30 passed, 12 on PostgreSQL), targeted suites green. Full pytest + behave queued |
| #504 | `feature/504-library-logos` | develop merged, re-sync picks up a changed logo, docs. Full suites running |
| #505 | `feature/505-change-password` (`eca233e`) | develop merged; every criterion covered; PostgreSQL HTTP test added; targeted 41 passed. Full pytest + behave queued |
| #506 | `feature/506-link-sign-in-providers` | storage, migration, routes, presets, icons, tests and docs written; merging the finished #505; targeted checks running |
| #509 | `feature/509-offset-paging` (`8fd8e92`) | PostgreSQL variants pass (126 targeted incl. 20 on PostgreSQL), behave jobs.feature green. Full pytest + behave queued |
| #510 | `feature/510-usage-counters` | tests (use cases, counts store on every database, REST/MCP counting), behave, docs, schema; merging the finished #487; targeted checks running |
| #511–#515 | — | wave 2, not started |

Full suites run one at a time on this 4-CPU machine (parallel runs took the load to 10 and
caused timeouts). Local PostgreSQL 16 with pgvector; ParadeDB's pg_search is not available
here, so the BM25-on-PostgreSQL variants only run in CI.

## For the owner

1. **Bundle size.** Entry JS grew from 278 to 355 kB gzip since develop (`fc34ae2`), the main
   chunk from 434 to 549 kB (Vite warns above 500 kB). The growth came with the redesign's first
   commit; splitting it (e.g. lazy routes for admin pages) is your call.
2. **Dialogs rule.** DESIGN.md says "no dialog except confirmations and showing a secret once",
   but create user, create token and share are dialogs. Keep the rule and turn those into pages
   or sheets, or relax the rule. Left as they are for now.
3. **Commit identity.** Commits use the repository's existing identity (no AI attribution);
   GitHub shows them as Unverified because they are not signed.
