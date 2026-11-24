# Blocks map: shadcn and shadcnblocks pieces in the ExactDocs web UI

Planning only (2026-11-23); nothing in `web/src` was changed. Read with `web/DESIGN.md` ("The
Headlamp") and `web/PRODUCT.md`. Related issues: #486 (design system), #487 (preferences sync),
#504 (library logos), #505 (own password), #506 (linking sign-in providers).

## 0. What was checked, and three facts that shape the plan

- **How "free" was checked.** Each listed page embeds its catalogue (`id`, `title`,
  `access: free | basic | pro`). Every variant on every page was requested from the registry:
  `https://www.shadcnblocks.com/r/<id>.json` for blocks, `/r/<group>/<id>.json` for components
  (the CLI name is `@shadcnblocks/<group>/<id>`). Result: 263 block variants, 21 answer 200;
  533 component variants, 34 answer 200; **every other one answers 401**. A component page has
  exactly one `free` and one `basic` item; `basic` items are served without authentication too.
- **`free` and `basic` are both usable.** The shadcnblocks Terms define Free Blocks as "items
  served from the public shadcn registry at shadcnblocks.com without authentication". They may
  be modified and kept in the product's own public repository; they may not be republished as a
  kit. The Terms forbid removing attribution or licence markers, also by rewriting with AI: every
  adapted file keeps a header comment "after the free shadcnblocks <Title> (`<id>`)", as
  `app-shell.tsx` and `auth-layout.tsx` already do. Pro items: look only, build our own from
  shadcn/ui primitives, copy nothing.
- **A Pro example is not a Pro component.** alert-dialog, context-menu, breadcrumb, badge,
  skeleton, tooltip, avatar, resizable, aspect-ratio, menubar, chart, popover + command
  (combobox), toggle-group, input-otp and table are shadcn/ui primitives (MIT). Take them from
  ui.shadcn.com in the Radix flavour the rest of `shared/ui` uses (not the Base UI flavour the
  navigation-menu link points to) and restyle them to the tokens. Third-party bases pulled in by
  free items: kibo-ui `tags` and `avatar-stack`, DiceUI `file-upload`, `react-icons`
  (social-button), `recharts` (charts); check each licence file when adding.
- **Correction to the brief: the access log does not record reads.** `GET /access-log` (ACL-05)
  lists permission changes: `library_created`, `granted`, `revoked`, `ownership_transferred`,
  `library_deleted`, with actor and time. Nothing stores which person or token read or searched
  which library. "Who read what, when", the leaderboard and most of the dashboard need one
  backend addition (G1 in §6).

## 1. Item map

P1 now (owner's high priority, or others depend on it) · P2 next · P3 later · "No place" = not
used, with the reason.

| Item | Free code (variants checked) | Where it goes | How it is adapted | Prio |
|---|---|---|---|---|
| Navigation menu | shadcn/ui (MIT); navbar1, 5, 35 free, in use | The band, as today. Admin gains **Overview** (first) and **Sign-in providers**; Tools gains **Leaderboard** when it is turned on. Help and About go in the account menu | Same panel rows (icon, name, one line). Library sub-pages (docs, settings, sharing, access log) stay underline tab links, not a second menu | P2, with those pages |
| chart-card | 27: chart-card1 (area), chart-card3 (bar) free; 25 Pro | Overview: "AI spend per day", "Docs read per day", "Jobs per day"; AI page: spend history above the usage table | Hairline card (`rounded-lg border`, no shadow); title `text-section`; the headline number `text-figure`; flat fill instead of card1's gradient; series colours from new chart tokens (§5); Recharts animation off; a "Show as table" switch | P2 |
| chart-group | 15: chart-group1 free | Overview, row 2: two charts side by side | Stacks below `lg`; one range control in the page header instead of one per card | P2 |
| chart (component page) | 85: chart-radar-multiple free, chart-pie-donut-active basic | Neither example: radar and donut charts compare poorly and read as decoration. Use the shadcn/ui `chart.tsx` primitive with area and bar charts only | Recharts in a lazily loaded route chunk (`autoCodeSplitting` is on) | Primitive P2; examples no place |
| banner | 25: banner1 free, banner2 basic | Instance notices for operators at the top of the sheet: search reindex required, vector store extension missing, instance AI budget reached | `warning-soft` strip with a hairline under it, inside the sheet (never on the frame); one sentence and the action; IconButton "Dismiss" (for the session; the reindex notice cannot be dismissed); `role="status"` | P2 |
| changelog | 7: changelog1 free (already the version rail) | Stays the version rail. An About page (account menu) shows the server version from `/healthz` and links to the release notes | No bundled changelog | P3 |
| compare | 11: compare7 free, compare8 basic | Library settings → Retrieval: a mode matrix (BM25, hybrid, HyDE, rerank, judge, agentic × needs embedding, needs LLM, sends text to a provider, available here) | Data from `GET .../retrieval` (`available_modes`, `configured_roles`); ✓ and – in ink; a tooltip names the missing role | P3 |
| compliance | 12: compliance1 free | Admin → **Security and data**, for platform teams doing a security review | Left: a short narrative. Right: cards of live facts: which AI providers exist and which libraries send them text, sign-in methods, throttle and session limits, keys sealed, no third-party requests, version, schema, search engine and vector store from `/healthz`. No certification claims | P3 |
| data-table | 32: data-table1 free (in use), data-table4 basic | Every list with many rows (§2) | Structure from data-table1, horizontal scroll from data-table4; pagination, page size and faceted filters after shadcn/ui's own data-table guide (MIT); the 30 Pro variants are inspiration only | P1 |
| faq | 38: faq1 free, faq3 and faq5 basic | `/help` (account menu): about eight questions about this instance (connect an agent, "no result" for a version, what a job's error code means, AI on or off and what leaves the server) | The existing Accordion; each answer links to the docs; no marketing intro | P3 |
| invite-user, accept-invite | 11: invite-user1, accept-invite1 free | Now: the Users page's Create user dialog takes invite-user1's dialog layout. Later, with invitations (G13): accept-invite1 as the accept page | No email or message field: username, role, a password or "Generate one". The accept page uses the auth card | P3 |
| integration | 35: integration3 free, integration9 basic | Account → API tokens: "Connect an agent" (Claude Code, Cursor, VS Code, Codex…), each row opening the existing MCP config. Admin → Sign-in providers list | Rows: a one-colour mark, the name, one line, the action. Marks bundled as SVG (no remote loads) | P2 |
| leaderboard | 3: leaderboard1 free | `/leaderboard`, and a "Most-read libraries" card on Overview (§5) | The top ten as upright columns that rise from the bottom; leaderboard1's horizontal bars become the share column for ranks 11 and up | P3 (needs G1) |
| login | 8: login1 free, login2 basic (in use) | Nothing new: the auth card is already after login2 | n/a | No place |
| dashboard | 31 checked, all Pro | Own composition: Admin → **Overview** (§5), from the free chart-card1/3, chart-group1, leaderboard1 and stat tiles | Pro layouts only as inspiration | P2 |
| survey | 4 checked, all Pro | No place now. A later idea: relevance votes on Playground results that feed the eval golden set (own composition plus backend) | n/a | No place |
| two-factor | 4 checked, all Pro | No backend. Organisations get MFA from their identity provider. If TOTP for local accounts is built (G14): own composition with shadcn/ui InputOTP on the auth card, recovery codes shown once in a Dialog | n/a | No place |
| file-upload | 45: file-upload-special-6 free, form-4 basic | Admin → Sign-in providers: the icon of a generic provider. Later: a library logo override when the importer found none (G11) | Own small component after special-6's square "Add" tile, on a native `<input type="file">` (skip the DiceUI dependency for one field). Accepts PNG, WebP and SVG, up to 64 KiB, square; previews at 20 and 48 px | P2 (#506) |
| avatar-stack | 6: avatar-stack-animate-1 free (kibo-ui base), compact-1 basic | **Not presence.** "Who is viewing now" would need a realtime channel the server lacks; reading docs is solitary, and two operators editing the same settings is better handled by a 409 on save. Use it for "Shared with" on the library page and the sharing summary (G12) | Initials discs on `accent` with a `background` ring and +N; hover spread by transform within `--dur-fast`, none with reduced motion | P3 |
| avatar-group | 9: avatar-group-animated-1 free, border-1 basic | Leaderboard and Overview "people active this week" (G1). The plain Avatar is part of the cell kit wherever a username appears | The same disc. Avatars are initials only (there are no pictures) | Avatar P1, group P3 |
| button | 126: button-standard-1 free, -2 basic | Everywhere | Button exists. The work: an `IconButton` (icon, required label, tooltip with the same name), an audit of the raw `<button>`s in 20 feature files (icon-only ones become IconButtons, the rest Buttons where they look like one), and a short `done` state (check icon, opacity cross-fade; idea from the Pro button-async, own code) | P1 |
| aspect-ratio | 7: standard-4 free, -6 basic | No place: logo tiles are square through size utilities; reader images keep their own width and height | n/a | No place |
| alert-dialog | 39: alert-dialog-form-6 free, form-5 basic | Every confirmation (§7, chunk 3); typed confirmation follows form-5's validation pattern; unlinking a provider | AlertDialog (`role="alertdialog"`, Escape cancels, a click outside does nothing), Cancel focused first, `destructive-solid` confirm, 12 px radius, 180 ms zoom from 0.95. form-6's radio pattern has no current use | P1 |
| resizable | 9: horizontal-split free, vertical-split basic | Library page: file tree and reader, the tree's width remembered in this browser | The handle is the 1 px `border` with a 44 / 36 px hit area and arrow keys; shadcn/ui resizable adds `react-resizable-panels` | P3 |
| tooltip | 8: tooltip-content-4 free, standard-1 basic | Every icon control (through IconButton), truncated paths and IDs, relative times | Existing Tooltip (400 ms, then instant); never the only name: the exact time also sits in the `<time>`'s `dateTime` and accessible name | P1 |
| badge | 22: badge-outline-5 free, standard-1 basic | Table cells (states, kinds, roles); counts on filter buttons ("State · 2"); a failed-jobs count on Tools → Jobs | `Badge` = the `pill` recipe and a tone; the count is a 20 px pill | P1 |
| social-button | 48: the base `social-button` and google-default free, google-outline basic. The base file renders all eight brands; the Pro items are only its props | Sign-in page; Account → Sign-in methods | Outline variant, full width on the auth card, "Continue with <display_name>". Google, Microsoft, Discord and GitHub as inline SVG (drop `react-icons`); a generic provider shows the operator's icon or `KeyRound` | P2 (#506) |
| menubar | 10: standard-6 free, -9 basic | No place: a File/Edit menubar would be a third navigation idiom beside the band and the tabs; the reader's actions fit a toolbar with a menu | n/a | No place |
| breadcrumb | 14: standard-6 free, home-icon-2 basic | One shared Breadcrumb for the library page, settings, sharing and library access log (four hand-rolled copies today) | Slash separators (standard-6), as today; below `md` the middle crumbs collapse into a dropdown (home-icon-2); the library ID in mono | P2 |
| context-menu | 27: context-menu-standard-1 free, text-4 basic; table and file variants Pro | Table rows, file tree nodes, search hits, reader headings and code blocks | One action list feeds both the row's visible "More actions" menu and the context menu, so nothing is reachable only by right-click (touch, discoverability); Shift+F10 and the Menu key open it on a focused row | P1 |
| skeleton | 30: skeleton-profile-2 free, list-1 basic | Every loading route and block (§7, chunk 7); table rows at the page size; the account header (profile-2) | No pulse, the final layout, shown after 150 ms (DESIGN) | P1 |
| combobox | 42: combobox-grouped-6 free, grouped-3 basic | Library picker: Playground, token scope, jobs and access-log library filters, global search; the tables' faceted filters | Popover + Command (adds `cmdk`); "Recent" (this browser) then "All" (grouped-6); grouped by owner above 20 libraries (grouped-3) | P2 |
| tags | 6: tags-composition-1 free, empty-1 basic (kibo-ui base) | Active-filter chips in the table toolbar; tag filters (articles, search); a token's library scope | Chips are `pill-neutral` with a remove IconButton, plus "Clear all" | P2 |

## 2. Data tables

### 2.1 `shared/ui/data-table.tsx` today

Has: `useServerTable` (manual sort, filter and paging; the sort lives in the URL as the API's
`sort`), `SortHeader` (a button with `aria-sort` and an arrow), `ColumnsMenu` (show and hide
columns), `DataTable` (a raw `<table>` with a skeleton row while the next page loads),
`ListFooter` ("Showing n of total" and Load more) and `SearchFilter` (the debounced `q` box).
Five pages use it: libraries, jobs, versions, articles, grants. Users and tokens are `<ul>`s, the
access log an `<ol>`, AI usage a hand-built table, Playground and search ranked lists.

Lacks: page-based pagination and a page-size choice; page and size in the URL; per-column
(faceted) filters and chips for the active ones; a client-side mode for short lists; a generic
global filter wiring; row actions (visible menu and context menu); built-in loading, empty and
error states; formatted cells; a phone layout other than hiding columns; `aria-rowcount`; the
shadcn table primitives.

### 2.2 DataTable v2: one shared kit

- **Files**: `shared/ui/table.tsx` (shadcn primitives on the tokens) and `shared/ui/data-table/`:
  `use-data-table.ts` (server and client modes), `pagination.tsx`, `toolbar.tsx` (global filter,
  faceted filters, chips, Columns, Clear filters), `faceted-filter.tsx` (Popover + Command
  checkbox list), `row-actions.tsx` (one list → kebab DropdownMenu and ContextMenu),
  `cells.tsx`, `states.tsx` (skeleton rows, EmptyState inside the table frame, error with Retry).
  Move `Meter` from `features/ai` to `shared/ui` (jobs, the dashboard and the leaderboard need it).
- **URL**: every table keeps `q`, its filters, `sort`, `page` (1-based) and `size` (5, 20, 50 or
  100; default 20). The last size per table is remembered in `localStorage` as a convenience; the
  URL wins. A new filter, sort or size goes back to page 1.
- **Server mode by offset** (G8, #509): the API pages with `limit` (1 to 200) and an `offset`
  (0 to 10000) or an opaque, forward-only `cursor` (never both), and every list carries `total`;
  the page count is `ceil(total / size)`. Every server table sets `paging: "offset"`: page *n* is
  one request of `offset = (n - 1) × size`, so numbered jumps, Last and a link to page *n* are one
  request each, and the pages on either side are prefetched. Past the offset bound the cursor
  walk is the fallback: Next and Previous go on from the cursor of the page beside them, a link to
  such a page walks from row 10,000 in steps of ≤ 200, and Last and the numbers past the bound are
  disabled with the reason in their name and tooltip and a line under the bar.
- **Client mode** for bounded lists (tokens ≤ 50, AI usage, job problems ≤ 1,200, Playground
  ≤ 50 per mode, leaderboard ranks): one request, then TanStack's sorted, filtered, paginated and
  faceted row models.
- **Rules**: a column is filterable only where the server filters it (no client filter over one
  server page: it would hide rows silently). Sortable only by the API's sort fields. The global
  filter is `q`. Filter values that are enums (state, kind, role, change, origin) are faceted
  multi-selects; dates are presets (24 h, 7 d, 30 d, custom).
- **Pagination bar**: "21–40 of 233" (tabular) · Rows per page (SelectField: 5, 20, 50, 100; sizes
  above a list's cap are not offered) · First, Previous, numbered pages (seven slots, "…" for gaps,
  from `sm`), Next, Last as IconButtons with tooltips · "Page 2 of 12". A live region says "Page 2 of 12". The table's top scrolls into view; focus
  stays on the button.
- **States**: loading = skeleton rows at the page size, shaped per column (`meta.skeleton`:
  text, mono, pill, avatar, number); refetches keep the old rows with `aria-busy`; empty = the
  frame with a dashed border and what to do next ("Clear filters" when filtered); error = one
  sentence and Retry inside the table.
- **Phones** (below `md`): rows become stacked cards: the primary cell as the title, two or
  three meta cells under it (`meta.priority`), the kebab on the right. No sideways scroll for the
  main lists.
- **Motion**: page changes swap rows at once; only rows that arrive live (polled jobs) use
  `row-in`. Sorting arrows do not animate.
- **Cell kit** (`cells.tsx`): `RelativeTime` (`shared/lib/time.ts`; exact value in `dateTime`, the
  accessible name and a tooltip), `VersionCell` (VersionStation and mono ref), `Commit` (exists),
  `LibraryCell` (LibraryMark, title, mono ID), `Person` (Avatar initials, username, provider icon),
  `StateBadge` (job and sync states to pill tones), `Progress` (Meter and "1,204 / 2,000 files";
  `sweep` without a total), `Bytes`, `Count`, `Money`, `MonoCopy` (literal with a copy
  IconButton), `TagChips` (exists).

### 2.3 Page by page

Sort and filter name the API parameter; "G" points to a backend gap in §6.

**Libraries** (`/`, `libraries-list.tsx`). Server: `GET /libraries`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| Library | LibraryCell (md mark), one line of description from `lg` | `title` (ID via the header menu: `id`) | `q` |
| Default version | VersionCell; a pin icon (tooltip "Pinned") when `default_pinned` | n/a | n/a |
| Versions | Count | `version_count` | `has_versions` |
| Last imported | RelativeTime | `last_imported_at` | `updated_after` / `updated_before` presets |
| AI | "AI on" neutral pill, or muted "Off" | n/a | `ai_enabled` |
| Sync | from `/jobs/latest`: "Up to date" positive, "Importing 40 %" with Meter, "Failed" destructive with the mono error code, "Tag moved" warning | n/a | n/a (a server filter would need G3) |
| Actions | Open, Settings, Sharing, Sync now, Copy ID, Open on git host | | |

**Jobs** (`/jobs`, `jobs-page.tsx`; the pilot for v2). Server: `GET /jobs`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| # | mono `#1234`, links to the job | `id` (default `-id`) | `q` |
| Library | LibraryCell (sm) | `library` | `library` (combobox) |
| Version | VersionCell, short SHA under it | n/a | `version` (text) |
| Kind | neutral pill (import, refresh, reprocess, rechunk, retag, collect, embed, push) | `kind` | `kind`, multi |
| State | queued neutral; running on the lamp's wash; succeeded positive; failed destructive with `error_code` under it; cancelled neutral, "by alice" | `state` | `state`, multi |
| Progress | Progress (files, or chunks for `embed`); "3 skipped" count | n/a | n/a |
| Origin | "auto" or "manual", muted | n/a | G3 (`origin`) |
| Queued | RelativeTime | `created_at` | `created_after` / `created_before` presets |
| Took | finished minus started, or "running 2 min" | n/a | n/a |
| Actions | Open, Cancel… (AlertDialog, only when `cancellable`), Copy ID, This library's jobs | | |

**Versions** (Library settings → Versions, `versions-table.tsx`). Server: `GET .../versions`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| Version | VersionStation (filled for the default) and mono ref; "Pinned" | `ref` | `q` |
| Kind | tag, branch or commit, neutral pill | `kind` | `kind`, multi |
| Commit | Commit with copy and a link to the host | n/a | n/a |
| Origin | manual or auto | `origin` | `origin`, multi |
| Imported | RelativeTime | `imported_at` | `imported_after` / `imported_before` presets |
| Latest job | StateBadge from `/jobs/latest`; "Tag moved" offers Re-import | n/a | n/a |
| Articles, Embedded | Count; Meter of chunks embedded | n/a | n/a (G4) |
| Actions | Browse, Make default / Unpin, Sync (branch), Re-import (moved tag), Remove… (typed AlertDialog) | | |

**Articles** (library page, `articles-table.tsx`; up to 7,000 per version). Server:
`GET .../articles`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| Path | mono; folder muted, file name in ink; links to the reader | `path` | `path_prefix` from the tree, shown as a chip |
| Title | text, hidden below `md` | `title` | `q` |
| Tags | TagChips, +N | n/a | `tags`, multi, with any / all (`tags_match`) |
| Size | Bytes, right-aligned | `size` | n/a |
| Actions | Open, Copy path, Copy link to this version, Open on git host, Edit tags | | |

**Grants** (Sharing, `grants-table.tsx`). Server: `GET .../grants`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| Who | Person, or a group icon and the group name (exact case) | `subject` | `q` |
| Kind | user or group pill | `kind` | `kind` |
| Role | a role select on rows the caller may change; "Creator" pill otherwise | `role` | `role`, multi |
| Actions | Change role, Remove… (AlertDialog), Transfer ownership (creator) | | |

**Access log**, global (`/access-log`) and per library (`access-log-list.tsx`, an `<ol>` today).
Server: `GET /access-log`, `GET .../access-log`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| When | RelativeTime | newest first only (G5) | date presets (G5) |
| Library (global only) | LibraryCell (sm); a removed library muted with "removed" | n/a | `library` (combobox) |
| Change | neutral pill with an icon; `library_deleted` destructive | n/a | `change`, multi |
| Subject | Person or group | n/a | G5 |
| Role | "viewer → admin" (`previous_role` → `role`) | n/a | n/a |
| By | Person, or "ExactDocs" when the instance made it | n/a | G5 (`actor`) |
| Actions | Show this library's / actor's / subject's entries | | |

**Users** (`/users`, `users-list.tsx`, a `<ul>` today). Server: `GET /users` (an organisation
may have thousands of SSO accounts).

| Column | Cell | Sort | Filter |
|---|---|---|---|
| User | Person | `username` | `q` |
| Role | "Operator" or "User" pill | `role` | `role` |
| Sign-in | "Password", or the provider's icon and name | n/a | G6 (`provider`) |
| Groups | chips, +N opens a popover | n/a | n/a |
| Status | nothing when active; "Disabled" neutral pill | n/a | `disabled` |
| Created | RelativeTime | `created_at` | n/a |
| Last active | RelativeTime | n/a | G6 |
| Actions | Reset password… (local only), Disable… / Enable, Show their access-log entries (G5) | | |

**API tokens** (Account → API tokens, `token-list.tsx`). Client: at most 50 per account, one
`GET /tokens?limit=50`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| Name | text | yes | global |
| Token | MonoCopy of the prefix (`exd_ab12…`) | n/a | n/a |
| Libraries | "All libraries" muted, or library chips +N | n/a | all / some / none |
| Created | RelativeTime | yes | n/a |
| Expires | "in 12 days"; warning pill under 7 days; "Never" muted | yes | expiring in 7 days / never |
| Last used | RelativeTime, or "Never" muted | yes | used in 30 days / not used |
| Actions | Revoke… (AlertDialog), Copy prefix | | |

**AI usage** (AI → Usage and budgets, hand-built table today). Client: one `GET /ai/usage`.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| Scope | Instance, Embedding (icons), LibraryCell or Person | name | scope kind |
| Today | Money, "12.3k tokens · 40 calls" under it | USD | n/a |
| This month | the same | USD | n/a |
| Budget | Meter (warning from 80 %, destructive when reached), "$3.10 of $5 left · resets in 6 h" | share used | reached |

**Job problems** (job details and import progress, `skipped-list.tsx`). Client: up to 1,000
skips and 200 notes, plus the `truncated` marker as a last row.

| Column | Cell | Sort | Filter |
|---|---|---|---|
| Path | mono | yes | global |
| Problem | code pill (`binary`, `too_large`, …) and the reason | code | code |
| Result | "Skipped" or "Imported with a note" (`is_skip`) | n/a | yes |

**Playground results** (`mode-results.tsx`). Client: at most 50 per mode; sizes 5, 20, 50.
One mode: Rank (default sort) · Library (LibraryCell sm, facet) · Article (mono path, heading
crumbs; two lines of snippet under it, expandable) · Score (3 decimals) · BM25 rank · Vector rank
(facet "both / BM25 only / vector only") · Tags (facet). Global filter over path, heading and
snippet. Compare mode: one merged table per chunk instead of two lists: Article · Rank in A ·
Rank in B · Change ("↑3", "↓2", "only in A"; neutral, since a rank change is neither good nor
bad) · Library; sortable by either rank or the change.

**Leaderboard ranks 11 to 100**: client; see §5.

### 2.4 Lists that stay lists

- Global search (`/search`) and a library's search box: ranked snippets. The API returns its best
  10 (at most 50) with no cursor; sorting a column would throw the ranking away, and the snippet is
  the content. They keep their facets and gain row actions (Open, Copy link, Copy chunk ID) through
  the context menu with its visible twin.
- AI providers and embedding spaces: a handful of cards each.
- Add library's file preview and the file tree: trees, with selection.

## 3. Account settings

`/account`, tabs in the URL (`?tab=`): **Sign-in**, **API tokens** (stays the default, so
existing links keep working) and **Interface** (exists). Same `PageHeader` and underline Tabs.

**Sign-in tab**

1. Who you are: the Avatar disc, username, role pill, "Signs in with: password / Google",
   groups as chips. Loading: skeleton-profile-2's layout.
2. Password (#505, G9), only for accounts with a local password: current, new, repeat (Field),
   the primary "Change password". Success: an inline status ("Your other sessions were signed
   out") and a toast. A 429 says when to try again (`Retry-After`). An account that signs in only
   through a provider sees one line instead: "Your password is managed by Google."
3. Sign-in methods (#506, G10): one row per configured provider (integration3's row pattern):
   its icon, its name, then "Linked · since 3 Nov" or "Not linked", and the action. Link is a
   SocialButton-style outline button that navigates to the provider's link start and comes back
   to `?tab=sign-in`. Unlink is an outline destructive button that opens an AlertDialog ("Unlink
   Google? You will no longer be able to sign in with Google."), Cancel focused. The password
   counts as a method; the last method cannot be unlinked, and the row says why in text.
4. Two-step verification: no section until the server supports it (G14).

**API tokens tab**: the token table (§2.3), "Create token" as the one primary, and "Connect an
agent" (integration3 list, each row opening the existing `mcp-config.tsx` snippet).

**Interface tab**: as today (`InterfaceSettings`), plus "Show me on the leaderboard" when the
operator turned the people board on (§5).

**Sign-in page**: providers become SocialButtons (outline, full width in the 400 px card,
"Continue with <display_name>") under an "or" rule after the password form; brands first,
generic providers after.

**Admin side** (Admin → Sign-in providers, `/sign-in-providers`, operators): a read-only list of
the configured providers (name, kind, issuer host, allowed groups) from the server's
configuration (G10). Google, Microsoft, Discord and GitHub show their built-in mark. A generic
OAuth or OIDC provider has an icon slot: the file-upload tile (§1) with preview, Replace and
Remove (AlertDialog). The server checks the file again and serves it from its own origin.

**Brand icons**: `shared/ui/brand-icons.tsx` with inline SVG: Google's four-colour G and
Microsoft's four squares (their sign-in guidelines ask for the colour marks), Discord and GitHub in
`currentColor`. Shown at 16 px in buttons and 20 px in lists; an uploaded icon is fitted into the
same box with `object-contain`.

## 4. Library logos

State: `shared/ui/library-mark.tsx` exists (#504): the library's logo from our origin, else a
generic icon on its line colour picked from the ID, else (preference off) the monogram
`LibraryBullet`. Nothing uses it yet; the API has no `logo` field yet (G11).

| Where | File | Size |
|---|---|---|
| Libraries table, Library column | `libraries-list.tsx` / `library-row.tsx` | md (28) |
| Library page header, beside the title and the route strip | `browse-page.tsx` | xl (48) |
| Library settings, sharing, library access log: the page header | `library-settings-page.tsx`, `sharing-page.tsx`, `access-log-pages.tsx` | lg (36) |
| Global search: library facets and each hit's library line | `global-search-page.tsx`, `hit-parts.tsx` | sm (24) |
| The band's search suggestions | `global-search-box.tsx` | sm |
| Jobs, access log, AI usage: Library / Scope cells | the three tables | sm |
| Library pickers: Playground, token scope, filters | the combobox | sm |
| Token scope chips, Playground hits, leaderboard (libraries) | chips and rows | sm |

Not in breadcrumbs, the band or chart axes (text only there).

Rules: always beside the name, decorative (`alt=""`); a fixed box, so nothing shifts while it
loads (`loading="lazy"`); a broken image falls back to the generic icon (exists). **Fix before
wiring**: the logo tile uses `bg-background`, which is dark in dark mode, so dark logos with
transparent backgrounds disappear. Add a `logo-tile` token (white in both themes, with the hairline)
to DESIGN.md and the styles first.

## 5. Leaderboard and dashboard

### 5.1 Data that exists today

| Signal | Where | Gives |
|---|---|---|
| Counts of libraries, failed jobs, disabled users… | `total` on every list; ask with `limit=1` and the filter | stat tiles |
| Newest job per version | `GET /jobs/latest` | sync health, the "needs attention" list |
| AI spend and budgets for today and this month, per instance, embedding, library and user | `GET /ai/usage` | spend tiles; who and which library spent most this day or month (AI steps only) |
| Every past day and month of AI spend per scope | `retrieval_ai_spend` keeps each window and nothing deletes them; **not exposed** | spend charts once exposed (G2) |
| Embedding progress | `GET /ai/embedding` | a progress tile |
| A token's last use | `GET /tokens`: your own tokens only, accurate to an hour | "tokens you never used" |
| Who created which library, and permission changes | access log | "libraries added per person" |
| Reindex required, vector store missing, version | `GET /healthz` | the banner, About |

Missing: reads, searches and tool calls per person, token, library and day (nothing is stored),
who queued a job, a user's last activity, an operator view of every token, offset paging.

### 5.2 Overview (`/overview`, Admin → Overview, operators)

PageHeader "Overview", one line ("This instance today. Money and days in UTC."), and a range
control (7 days, 30 days, 12 months) for the charts.

1. Four stat tiles (`text-figure`, no colour unless something is wrong): Libraries; Failing
   (latest job failed or tag moved, links to `/jobs?state=failed`); AI spend this month (Money and
   a Meter against the instance's monthly budget); Embedded (share of chunks).
2. chart-group1: "Docs read per day" (G1) and "AI spend per day" (G2). Until G1, the left card is
   "Jobs per day" (G3, or `/jobs` with `created_after` for 7 days).
3. chart-card3 "Jobs by state per day" (state colours, because they are states) and a
   "Most-read libraries" card (leaderboard1's horizontal bars; G1).
4. "Needs attention" as a list, not a chart: reindex required, vector store missing, budgets
   reached, failed syncs with their codes, moved tags with Re-import, tokens about to expire
   (your own today; everyone's with G7).

Charts: shadcn/ui `chart.tsx` and Recharts in the route's own chunk. New tokens first:
`--chart-series` (muted ink), `--chart-highlight` (= `route`), state colours for state series;
never `line-1..8` (library colours belong to bullets), never the lamp as a fill in light mode.
Grid in `rule`, axes `text-small` muted, the tooltip in the inverted `tip` style.
`isAnimationActive={false}`: Recharts tweens geometry, and DESIGN allows only transform and
opacity; the card fades in instead. `accessibilityLayer` on, and "Show as table" renders the same
series as a client DataTable.

### 5.3 Leaderboard (`/leaderboard`, Tools → Leaderboard, when the operator turns it on)

- **Metrics** (from G1): Docs read (articles and chunks read over MCP and in the reader),
  Searches, Agent answers. **Subjects**: Libraries (always available) and People (only when the
  operator turns it on and only people who opted in). **Periods**: Day, Week (ISO), Month, Year,
  in UTC. All three are segmented controls (ToggleGroup, the selected one on the lamp's wash) and
  live in the URL.
- **Top ten as upright columns**: each column is a full-height track (`secondary`, top corners
  `rounded-md`) whose fill is scaled with `transform: scaleY(value / max)` from `origin-bottom`.
  The value sits above it (tabular), the rank and the name below (Person or LibraryMark sm,
  truncated, with a tooltip repeating the name). Your own column is the one lit thing: `route`
  fill (ink in light, the lamp in dark); the others `muted-foreground` at low opacity.
- **Motion**: on first show and on every switch, fills move in 240 ms (`--dur-slow`,
  `--ease-out`), staggered 30 ms from left to right. Columns are keyed by subject, so switching
  the period grows or shrinks them from where they are; a newcomer fades in while it grows, a
  leaver fades out in `--dur-exit`. With reduced motion, no travel: the new heights cross-fade in
  place. Only transform and opacity.
- **Below**: ranks 11 to 100 as a client DataTable: Rank, Person or Library, Value, Share (a
  horizontal Meter, leaderboard1's bar), Change against the previous period (↑ / ↓, neutral). If
  you are not on the page, a last row shows you ("You · #23 · 41 docs").
- **Access**: the columns are an `<ol>` whose items read "3. alice, 128 docs read"; the bars are
  decoration over it.
- **Empty**: "Nothing read this week yet."
- **Privacy** (the customer is an organisation; usage per named employee is monitoring data under
  the GDPR and works-council rules): the people board is off by default (an operator setting),
  each person opts in from Interface, only daily counts are stored (no queries, no content), and
  counts are kept for a set time (13 months suggested). The libraries board needs none of this.
  A compact "Most-read libraries" card also sits on Overview.

## 6. Backend gaps

| # | Gap | For |
|---|---|---|
| G1 | **Usage counters**: daily counts per (day, account, token, library, operation: read, search, answer), upserted by REST and MCP, kept for a set time; `GET /stats/usage` (operators: by account, library or token; day, week, month, year), `GET /account/usage` (self), `GET /stats/leaderboard?subject=&metric=&period=` with the previous period's rank; an instance setting for the people board and a per-account opt-in in preferences | reads in the access log, leaderboard, Overview |
| G2 | **AI spend history**: `GET /ai/usage/history?scope=&id=&window=day\|month&from=&to=` from the existing `retrieval_ai_spend` rows; no new storage | spend charts |
| G3 | **Jobs**: `created_by` (who queued it), an `origin` filter, `GET /stats/jobs?bucket=day` (counts by state and kind), a sync-state filter for libraries | Jobs, Overview, Libraries |
| G4 | **Version counts**: `articles`, `chunks`, `embedded_chunks` per version; `article_count` per library | Versions table, Overview |
| G5 | **Access log**: `sort`, `actor`, `subject`, `at_after` / `at_before` | Access log filters |
| G6 | **Users**: `last_active_at` (hourly, from sessions and tokens), a `provider` filter, a token count | Users table |
| G7 | **All tokens** for operators: owner, expiry, last use | Overview, clean-up |
| G8 | **`offset`** on the paged lists (libraries, versions, jobs, articles, users, tokens, grants, both access logs), exclusive with `cursor` | numbered pages, Last, reload on page *n* |
| G9 | **Own password** (#505): `PUT /account/password` with the current one, throttled like sign-in | Account |
| G10 | **Provider linking and icons** (#506): `GET /account/identities`; a link start and callback that attach to the signed-in account; `DELETE /account/identities/{provider}` with the last-method guard; drop the UNIQUE on `identity_external_identities.account_id`; `preset` (google, microsoft, discord, github, generic) and `icon_url` in `GET /session`'s providers; `PUT` / `DELETE /auth/providers/{name}/icon` (operators, PNG, WebP or sanitised SVG up to 64 KiB) and a public `GET` for it; `GET /auth/providers` (operators, the configuration without secrets) | Account, sign-in page, admin page |
| G11 | **Logos** (#504): `logo` (our-origin URL or null) on library summaries, details and search facets; later an operator override upload | §4 |
| G12 | Grantee preview on the library detail (`count`, first few) | avatar stack, optional |
| G13 | Invitations: one-time links where the person sets their own password | invite-user1 / accept-invite1, optional |
| G14 | TOTP for local accounts | two-factor, optional |

Not planned: presence (a realtime channel for "who is viewing").

## 7. Implementation plan

Chunks in order; each can ship on its own. "Needs" names the backend gap it waits for.

1. **Primitives and tokens** (no screen changes). Add to `shared/ui` from shadcn/ui (Radix):
   alert-dialog, context-menu, popover, command (`cmdk`), avatar, badge (on the `pill` recipe),
   breadcrumb, table, toggle-group; move `Meter` to `shared/ui`. DESIGN.md: rows for each, the
   chart and `logo-tile` tokens, and rules "Confirm with AlertDialog" and "A context menu mirrors a
   visible menu". Done when `primitives.test.tsx` covers roles, focus and reduced motion, and
   `pnpm lint` (fallow zones) and `pnpm build` (`check-dist`) pass.
2. **Button, IconButton, tooltips** (P1). IconButton everywhere an icon is the only content (audit
   the 20 feature files with raw `<button>`s), the `done` state. Done when no icon-only control lacks a name
   and a tooltip with that same name.
3. **Confirmations on AlertDialog** (P1). `ConfirmDialog` and `TypedConfirm` on AlertDialog;
   migrate cancel job, revoke token, disable user, remove grant, transfer, remove version, delete
   library and the paths confirmation. Done when each has `role="alertdialog"`, Cancel is focused
   first, a click outside does nothing, and the tests pass.
4. **DataTable v2 and the Jobs pilot** (P1). §2.2 in `shared/ui/data-table/`; Jobs as in §2.3.
   Done when the data-table tests cover both modes, the URL round-trip of page, size, filters and
   sort, and the context menu by keyboard; `jobs.test.tsx` passes.
5. **The other server tables** (P1): libraries, versions, articles, grants, users (from `<ul>`),
   both access logs (from `<ol>`). Done when each matches §2.3, keeps its view in the URL, and its
   phone layout holds at 390 px.
6. **Client tables** (P1–P2): tokens, AI usage, job problems, Playground (one mode and the merged
   compare). Done when page sizes are capped at each list's maximum.
7. **Skeletons, breadcrumb, more context menus** (P1–P2). A `pendingComponent` for every route
   with a loader (today only `/` has one) and skeletons in the final layout for in-page queries;
   one Breadcrumb for the four copies; context menus with visible twins on file-tree nodes, search
   hits and reader headings (Copy link to heading, Copy chunk ID). Done when every route shows a
   skeleton on a cold load over 150 ms.
8. **Logos** (needs G11 / #504). The `logo-tile` fix, then §4. Done when every place in §4 shows
   the mark, the preference turns it off, and `check-dist` passes.
9. **Account and sign-in** (needs G9, G10 / #505, #506). §3: the Sign-in tab, SocialButtons,
   brand icons, Admin → Sign-in providers with the icon upload. Done when the UI scenarios of #505
   and #506 pass.
10. **Pickers and filter chips** (P2). The library combobox (recent and all, grouped by owner)
    for Playground, token scope, the jobs and access-log filters and global search; Tags for tag
    filters and active-filter chips. Done when those pickers are one component that works by
    keyboard and screen reader.
11. **Instance banner** (P2). From `/healthz` and `/ai/usage`, operators only. Done when the
    three notices show with their action and dismiss as specified.
12. **Overview** (P2). Part one without backend work: tiles, needs attention, today's spend, the
    nav entry. Part two (needs G2, G3): the charts with "Show as table". Done when §5.2 holds and
    the Recharts chunk stays out of the entry bundle (`scripts/bundle-size.mjs`).
13. **Usage counters and the leaderboard** (needs G1). §5.3, the opt-in preference and the
    operator setting, "Reads" in the access log if wanted. Done when the people board stays hidden
    unless turned on and opted into, and reduced motion is checked.
14. **Later** (P3): Security and data (compliance1), Help (faq1), About, the retrieval mode
    matrix (compare7), the resizable tree pane, "Shared with" avatars (G12), invitations (G13).
    "Connect an agent" (integration3) is small and can join chunk 9.

New feature slices (`overview`, `leaderboard`, possibly `account`) each need a zone in
`.fallowrc.json` and their entry in `web/README.md`.

## 8. Decisions for the owner

1. Logos turned off: keep the monogram bullet (recommended: DESIGN asks for `LibraryBullet`
   wherever a library is named, and rows keep their alignment) or show the name only, as #504's
   scenario says. One of the two must change.
2. People leaderboard: off by default with a personal opt-in (recommended), or on for everyone.
3. Offset paging (G8) now, or the cursor walk as the interim (no Last button). Decided: #509
   shipped the offset; every server table pages by it, the cursor walk only past 10,000 rows.
4. Playground: the table as the default view (recommended in compare mode), or keep the ranked
   lists and offer the table as a switch.
5. Brand marks as inline SVG (recommended) or the `react-icons` dependency the free
   social-button uses.
6. Recharts (a sizeable dependency, only in the Overview and AI route chunks) or plain SVG bars,
   which the current Meter shows are enough for simple series.
