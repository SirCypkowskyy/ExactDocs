# Progress: ExactDocs redesign (#486) and its backend issues

Kept up to date by the overnight session that continues `HANDOFF.md`. Newest state first in each
section. Read `HANDOFF.md` for the plan, the owner's decisions and the rules.

_Last updated: 2026-11-24 01:25 UTC._

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

### B. Per-feature pass: done (merged up to `dbfa558`)

Five agents, one per feature group, each on a local branch cut from `15c42f9`, merged here when
green. The merged branch: typecheck, Biome (no warnings left), fallow arch + dead code,
react-doctor, 59 files / 846 tests, build (check-dist, bundle-size) all green.

| Group | What changed |
|---|---|
| libraries | Libraries list on DataTable v2 (server, AI / versions / imported facets, sync badge with popover, row menu + context menu incl. Sync now); Jobs header icon, state-facet icons, skeleton; inline job cancel on ConfirmDialog; job problems as a client table (local view state); add page and import progress icons and reactions |
| browse | Articles table on DataTable v2 (server, tags facet, folder chip, row menu with copy link / open on host / folder); shared Breadcrumb; reader and tree buttons on IconButton/Button; `BrowseSkeleton`; prose.css specificity warnings fixed with zero computed-style differences across 552 elements; global search icons only |
| settings | Versions table on DataTable v2 (kind / origin facets, imported preset, pinned default); both typed removals on TypedConfirmDialog (local `typed-confirm.tsx` deleted); re-process on ConfirmDialog; section icons; skeleton |
| sharing | Grants table (kind / role facets, role select or pill, removal on ConfirmDialog); both access logs on DataTable v2 (change facet, library chip); AI usage as a client table; playground icons only (no table, as decided) |
| people | Users table (avatars, role / sign-in / status badges, groups "+N" popover, disable on ConfirmDialog); API tokens as a client table (libraries / expires / used facets, revoke on ConfirmDialog); account tab reactions; sign-in provider buttons with KeyRound until #506's brand marks |

Every server table uses the cursor walk with a `// #509:` note where offset paging goes.

### Kit follow-ups from section B: done (`2d586ee..0d29563`, 867 tests)

Row-menu focus return after a mouse-opened menu (one bug, found twice); future relative times;
`EmptyState` icon at 32 px; `DataTableModel.error`; a local (non-URL) view option; `qParam`;
TableError retry label; breadcrumb links 44 px on touch; keep the URL hash; row headers;
`formatBytes` "B"; `DataTableSkeleton`; `LibraryCell` description; a shared "chips + N" cell;
FormAlert's alert reaction. Then the local workarounds go.

### C. UI for finished backend branches: in progress

- **#504 library logos: done** (`f9844a0` merges the backend and develop; `1ddac14`, `f32001b`).
  `LibraryMark` takes the API's `logo` version and builds `/api/v1/libraries/{owner}/{repo}/logo?v=`;
  the logo sits on the white logo tile (lazy, async, `alt=""`, fixed box); no logo or a failed
  image shows the generic icon on the library's line colour; logos turned off show the monogram
  bullet (new `xl` size). Shown in the libraries table, the library page header (`xl`, new
  `PageHeader` `mark` slot), the settings / sharing / library access-log headers (`lg`) and the
  playground. The "Library logos" switch is also in the band's interface menu. 881 tests.
- Next: #487 (drop the `as ApiPath` cast once merged), #505/#506 (Account → Sign-in tab, brand
  buttons), #509 (offset paging in DataTable v2), #510–#513 (Overview and Leaderboard),
  #514/#515 (access-log and users filters).

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
3. **Logos turned off vs. no logo yet.** `LibraryMark` shows the generic icon on the library's
   line colour when a library has no logo, and the monogram when logos are turned off. If "keep
   the monogram bullet" meant the monogram until logos exist, the tables switch to
   `LibraryBullet`.
4. **Tags on the library page.** The table's Tags facet and the side panel's tag chips drive the
   same filter; on desktop that is two controls for one filter. Keep both or drop the facet.
5. **Libraries table.** Failed libraries no longer sort first (the server pages the list); the AI
   column needs an `ai_enabled` field on `LibrarySummary`.
6. **#506 defaults.** Discord / Google / Microsoft presets default to `auto_create_users = false`
   (they link or sign in already-linked identities only); Microsoft `tenant` must be a GUID or
   `organizations` / `common` / `consumers`; a link callback that fails before its attempt is
   found lands on `/sign-in?error=…`.
7. **Logo placement.** On the sharing and access-log pages the library mark replaces the page's
   own icon (blocks-map §4 "the page header, lg 36"); breadcrumbs no longer carry the bullet
   (§4 "not in breadcrumbs"). The alternative is to keep the function icon there.
8. **Logos missing from some DTOs.** Global search hits/facets, jobs, access-log and AI-usage
   rows have no `logo`, so they show the generic mark; adding `logo` there is a small backend
   follow-up (search was already gap G11).
9. **Commit identity.** Commits use the repository's existing identity (no AI attribution);
   GitHub shows them as Unverified because they are not signed.
