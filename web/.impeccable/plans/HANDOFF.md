# Handoff: ExactDocs redesign (#486) and its backend issues

Written 2026-11-23 for the session that continues this work overnight, autonomously, with
subagents. Read this whole file, then `AGENTS.md`, `web/PRODUCT.md`, `web/DESIGN.md`,
`web/.impeccable/plans/blocks-map.md` (the component/page spec) and
`web/.impeccable/plans/icons-motion.md` (icons and their reactions).

## What the owner asked for (all still in force)

- A design system of ExactDocs' own ("The Headlamp", `web/DESIGN.md`): mature and minimal, not
  childish, not loud; shadcn/ui (Radix) as the base with **free** shadcnblocks blocks only (the
  repo is public, no Pro licence; adapted files keep a header comment "after the free
  shadcnblocks <Title> (`<id>`)"; Pro items may only inspire).
- Smooth and reactive: micro-animations on buttons, tooltips wherever possible, hover/press/focus
  reactions, **more icons on every page and element, each with a small readable reaction**
  (`src/app/icon-motion.css`, opt in with `data-icon-motion`), all off under reduced motion.
- WCAG 2.2 AA interface preferences from the navbar (done) and Account → Interface (done), stored
  in the browser and synced to the account when signed in (#487).
- **Polish and English** everywhere (done): typed catalogues via `src/shared/lib/i18n.ts`;
  English text unchanged (tests assert it); every new string needs both languages.
- **Data tables** for every page with a lot of data (TanStack Table): full pagination with
  5 / 20 / 50 / 100 rows per page, per-column filters, sorting, a global filter, and formatted
  cells (badges, relative times, version pills, progress, avatars, logos), per blocks-map §2.
- Use the owner's list of blocks/components where blocks-map §1 places them (alert-dialog,
  context-menu, tooltip, button and skeleton are high priority; charts for statistics; banner;
  breadcrumb; combobox; tags; badge; avatar group; file upload for provider icons; leaderboard).
- **Account settings**: interface preferences, change own password (#505), link the account to
  sign-in providers when configured (Discord, Google, Microsoft, any generic OAuth/OIDC with an
  operator-supplied icon of bounded size) (#506).
- **Library logos** (#504): the importer finds a project logo; show it beside the library name
  and on the library page; a generic icon when there is none; a preference turns them off.
- **Leaderboard** (gamification) and **statistics**: who/what was used how much per day / week /
  month / year, switchable, columns growing bottom-up (#510, #511, #512).

## Owner's decisions

- People leaderboard: **off by default** (operator setting) **and opt-in** per person; the
  libraries board is always allowed. Only daily counts are stored, kept ~13 months.
- Backend gaps: **one issue each, built in waves** (filed: #509–#515).
- Playground: **leave it as it is for now** (no table conversion).
- Charts: **Recharts, lazy-loaded** only on the pages that chart (Overview, AI), shape animation off.
- Logos turned off: the library keeps its coloured monogram bullet (#504 updated).
- Brand marks (Google, Microsoft, Discord, GitHub): inline SVG, no `react-icons`.

## Branches (all pushed; none merged; no PRs yet)

| Branch | Issue | State | Next |
|---|---|---|---|
| `feature/486-design-system` | #486 | Frontend: design system, navbar, interface prefs + sync client, i18n PL/EN, icon reactions on navbar/auth/account/interface, shared kit (primitives, IconButton, ConfirmDialog, DataTable v2) with the Jobs page as pilot. `tsc` clean, 52 files / 734 tests green. fallow/react-doctor/build not re-run since the kit | Sections A, B, C below |
| `feature/487-interface-preferences` | #487 | Backend done (`f05ddfc`): GET/PUT `/api/v1/account/preferences` incl. `language`, `library_logos`; migration `e2b6c94f1a37` | Full pytest + PostgreSQL contract tests, `pnpm gen:api`, draft PR |
| `feature/504-library-logos` | #504 | Backend done (`0e4295f`): detection, sanitising, `catalog_library_logos` (migration `6a1e4c9b2d75`), `GET /libraries/{o}/{r}/logo`, `logo` field (hash or null; URL is `/api/v1/libraries/{id}/logo?v=<logo>`) | Full pytest/behave, draft PR |
| `feature/505-change-password` | #505 | Backend done (`5a378d3`): `PUT /api/v1/account/password`, `has_password` on AccountSummary | Full pytest/behave, draft PR |
| `feature/506-link-sign-in-providers` | #506 | WIP (`7bb5d16`), stacked on 505: domain code only; storage, migration, routes, presets, Microsoft multi-tenant, tests, docs left (see the #506 release comment for the full list and the two design choices) | Finish |
| `feature/509-offset-paging` | #509 | WIP (`8fd8e92`, from develop `7958bf9`): `offset` 0–10000 on all ten list endpoints, 422 `cursor_with_offset`, tests on SQLite, behave, docs, gen:api done | PostgreSQL variants, full pytest/behave, drop `wip:`, draft PR |
| `feature/510-usage-counters` | #510 | WIP (`b05f165`), **stacked on #487**: new `usage` domain, counters, endpoints, `leaderboard_opt_in` preference (**required on PUT**), `EXACTDOCS_USAGE__PEOPLE_LEADERBOARD`. 58 preference tests need the new key; usage tests, behave, docs, gen:api left | Finish |
| — | #511–#515 | Filed, not started (spend history, job stats, version counts, access-log filters, users/tokens) | Wave 2 |

`develop` has moved on since these branches were cut (now `7958bf9`): merge `origin/develop` into
a branch before its PR and re-run its checks.

Every issue above is released (`status: ready`) with a handoff comment: **claim before working**
(`.agents/skills/claiming-issues`), release or hand off when you stop.

Alembic: #487 `e2b6c94f1a37` and #504 `6a1e4c9b2d75` both start from `9d4f2b7e1c83`; #510
`7f3a91c5d2e8` follows `e2b6c94f1a37`; #506 will add one more. Whichever merges second re-points
its `down_revision` so there is one head.

## Work order

Use subagents in parallel where they touch different files; never two writers on the same files.
Backend subagents in their own worktrees on their own branches.

**Backend (parallel):** finish #487, #504, #505 (tests to the end, `just check`, draft PR to
`develop` with `Closes #n`), then #506, #509, #510; then wave 2 (#511–#515) from `develop`.

**Frontend, on `feature/486-design-system`, in order:**

A. *Finish the shared kit* (one agent):
   1. `interface-controls.tsx`: `InterfaceMenu` and `LanguageMenu` triggers as `<M.Trigger asChild><IconButton variant="band" …>`; drop unused messages.
   2. `styles.css`: `--logo-tile` (white with hairline in both themes) used by `library-mark.tsx` instead of `bg-background`; `--chart-series`, `--chart-highlight`.
   3. `DESIGN.md` + `.impeccable/design.json`: rows for the new primitives, DataTable v2, IconButton, ConfirmDialog/TypedConfirmDialog, Badge, Meter, Avatar, ToggleGroup; the tokens; the rules "Confirm with AlertDialog", "A context menu mirrors a visible menu", and the Icons and motion section (from icons-motion.md).
   4. Tests: `primitives.test.tsx` (IconButton, done, AlertDialog role/focus/outside click, reduced motion, Badge, Avatar, ToggleGroup), `confirm-dialog.test.tsx`, `data-table/*.test.tsx` (client mode, URL round trip, `pageOf`, `parseFacet`, the cursor walk over 200 rows, offset mode, Polish pagination).
   5. All checks green (below), and a look at `/jobs` at desktop and 390 px, dark, Polish.

B. *Per-feature pass* (parallel agents, one per feature group, disjoint folders): for each page,
   per blocks-map §2.3 and icons-motion.md:
   - tables on DataTable v2 (libraries, versions, articles, grants, users, both access logs, tokens, AI usage, job problems; **not** Playground, not global search);
   - confirmations on ConfirmDialog / TypedConfirmDialog (library-settings `typed-confirm.tsx` users, `ReprocessConfirm`, token revoke, grant removal, user disable, the inline job cancel);
   - every raw icon `<button>` to IconButton/Button;
   - PageHeader `icon` (the page's nav icon) and Section icons; leading icons on every button and menu item; state badges with icons; empty states with an icon; `data-icon-motion` per the table;
   - skeletons in the final layout + a `pendingComponent` for every route with a loader;
   - row actions mirrored in a context menu; one shared Breadcrumb for the four hand-rolled copies;
   - all new strings EN + PL; existing English unchanged; tests updated (each feature keeps a Polish test).

C. *After a backend branch is complete and green*, merge it into `feature/486-design-system`
   (`git merge --no-ff origin/feature/<n>-…`), `cd web && pnpm gen:api`, then build its UI:
   - #487: remove the `as ApiPath` cast in `features/auth/hooks/use-preferences-sync.ts`; #510 adds `leaderboard_opt_in` to `shared/lib/preferences.ts` (PUT needs every key).
   - #504: `LibraryMark` (exists, `shared/ui/library-mark.tsx`) everywhere blocks-map §4 lists, logo URL `/api/v1/libraries/{id}/logo?v=<logo>`.
   - #505/#506: Account → **Sign-in** tab (blocks-map §3), SocialButton-style provider buttons with inline brand SVGs on the sign-in page, Admin → Sign-in providers with the icon upload.
   - #509: DataTable v2 `paging: "offset"` → Last page and numbered jumps.
   - #510/#511/#512/#513: Admin → **Overview** (stat tiles, Recharts chart cards lazy-loaded, "needs attention"), Tools → **Leaderboard** (top ten as columns growing bottom-up with `scaleY` from `origin-bottom`, staggered 30 ms, switchable subject/metric/period in the URL, ranks 11+ in a client table; people only when the operator turned it on and they opted in; Interface tab gets "Show me on the leaderboard").
   - #514/#515: the access-log and users filters.
   - Then: instance banner, the library combobox and tag filter chips (blocks-map chunks 10–11).

Do **not** publish the Design System artifact; the owner's local session does that.

## Rules

- `AGENTS.md` hard rules. Conventional commits authored by the repo's git identity, **no AI
  attribution anywhere** (no Co-Authored-By, no "Generated with", nothing in PR bodies).
- Push feature branches only; **never push, delete or force-push `main` or `develop`**; never
  merge into `develop`; PRs only as **drafts** to `develop` for finished, green issues.
- Domains never import each other; web features never import each other; `shared/` imports no
  feature. Web strings through catalogues, EN + PL.
- Motion: transform/opacity only, ease-out tokens, press 0.97, menus scale from their trigger
  (150 ms in / 100 ms out), tooltips 400 ms then instant, exits faster than entrances, reduced
  motion respected (`data-reduce-motion`). No bounce, no hover scale-ups on buttons.

## Checks

Backend: `just check` (or `uv run pytest`, `uv run behave`, architecture tests).
Web (`web/`): `pnpm typecheck`, `pnpm check`, `pnpm lint:arch`, `pnpm lint:dead`,
`pnpm lint:react`, `pnpm test`, `pnpm build` (includes `check-dist` and `bundle-size`).

## Reporting

Keep `web/.impeccable/plans/PROGRESS.md` on `feature/486-design-system` up to date (what was
finished on which branch, what is next, anything the owner must decide), comment on each issue
when you stop, and push before you stop.
