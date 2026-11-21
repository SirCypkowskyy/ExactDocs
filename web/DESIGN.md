# ExactDocs design system

The web UI's visual language: the tokens and components every screen is built from, and when to
use each one. Tokens live in `src/app/styles.css`. Components live in `src/shared/ui/` (shadcn/ui,
restyled to these tokens). The class recipes live in `src/shared/ui/recipes.ts`. A screen uses these
names only: no raw colours, no one-off sizes or durations. If something is missing, add it here
and to the tokens first.

## The idea

**Every screen says exactly where you are on the line.** ExactDocs serves text at an exact library,
version and commit, so the UI is set like a wayfinding system:

- each **library is a line**, with its own colour and a round bullet carrying its initials;
- each **version is a station** on that line (a ring; the default version is the filled
  interchange);
- the **route** (library, version, path, commit) is the identity line above an article, a search
  hit or a settings page.

Around that, the product is a quiet working tool. A cool tinted **frame** (the top band and the
window's margin) holds a white **sheet** where the work happens. The text is ink with two greys.
One **route hue** (deep teal) marks place, selection and progress. Nothing else is coloured unless
it is a state or a library's line.

Built from shadcn/ui and these free shadcnblocks.com blocks (no premium code):
`application-shell3` (the band, mobile sheet and user menu), `login2` (the auth card),
`blogpost2` (the reader's sticky contents column), `changelog1` (the version rail) and
`data-table1` (the server-side tables, #434).

## Colour

Light and dark are both defined on `:root` and `.dark` (see `src/shared/lib/theme.ts`). Dark mode
uses true neutrals, never navy.

| Token | Use |
|---|---|
| `frame` | The band and the margin around the sheet. Never behind content. |
| `background` | The sheet. Inputs are white on it too (`control`). |
| `raised` / `muted` | A panel one step off the sheet: settings panels, the reader's contents. |
| `code` | Code blocks and the `codeWell` recipe. |
| `foreground` | All running text, in full ink. |
| `muted-foreground` | Secondary text, labels and meta (6.6:1 on white). The only grey for words. |
| `border` | Card and sheet edges. |
| `rule` | Row rules in lists and tables (one step lighter than `border`). |
| `input` | Control borders (one step stronger than `border`). |
| `accent` | Hover fills and the active nav pill. |
| `primary` | The one primary action per screen: near-black, white in dark. |
| `route` / `route-soft` | Where you are: the active tab rule, the current version, selected tree rows, progress fills, focus ring (`ring`). |
| `positive`, `warning`, `destructive` (+ `-soft`, `-ink`) | States. Text in the plain token; pills as the `-soft` ground with `-ink` text. |
| `line-1` … `line-8` | A library's line colour, only on its bullet (`LibraryBullet`, picked by a stable hash of the ID). White text on each clears 4.5:1. |
| `overlay` | The scrim behind dialogs and sheets. |
| `hl-*`, `tint-*` | Syntax roles in code and callout tints in articles (reader only). |

Rules: colour is under about 3% of a screen. A delta or status is coloured only when it means
good or bad. Zero is grey. Violet, indigo, gradients and glows are not used anywhere.

## Type

One family: **IBM Plex Sans** (variable, self-hosted). **IBM Plex Mono** is used only for
versions, commit SHAs, paths, IDs, tokens and code. Both are self-hosted by `@fontsource`, so
nothing loads from another origin.

| Class | Size / line | Use |
|---|---|---|
| `text-small` | 12 / 18 | Meta, helper text, table headers, pills |
| `text-body` | 14 / 20 | UI text, cells, labels, descriptions |
| `text-section` | 16 / 24 | Section headings (600), list titles |
| `text-title` | 22 / 28 | The page's h1 (600), one per page |
| `text-figure` | 28 / 34 | The one figure that answers a screen's question (400) |
| reader | 17 / 1.65, 68ch | Article prose (`prose.css`); headings 30 / 24 / 20 / 17 |

Weights: 400, 500 for labels and the active nav, 600 for headings. Use sentence case everywhere,
no tracked capitals. Figures are tabular wherever they are compared (`table`, `time` and `.num` do
this automatically).

## Space, radius, layout

- **Spacing** is on a 4 px base. Inside a block, 8 and 16. Between blocks, 24 and 32. Between page
  sections, 48 (`gap-12`). There is more space above a heading than below it.
- **Radius**: the sheet 16 (`rounded-sheet`), cards and panels 8 (`rounded-lg`), controls 6
  (`rounded-md`), pills full.
- **Frame**: the band is 52 px (`h-13`). From `md` up the sheet is inset 8 px from the window with a
  1 px `border`. Below `md` the sheet is the screen.
- **Page widths**: there are two. `Page width="operate"` (1152 px) is for lists, settings and
  forms. `width="wide"` is for the library page and reader. `narrow` (720 px) is only for
  single-form pages.
- **Every page** starts with `PageHeader`: an h1 (`text-title`), one line about the data, and the
  actions at the right. Sections use `Section` (h2 `text-section`).
- **Breakpoints**: phone below `md` (the band shows the menu sheet). `lg` puts the search field in
  the band. `xl` shows the reader's contents column.

## Motion

Motion explains state. It is never decoration.

| Token | Value | Use |
|---|---|---|
| `--dur-fast` | 120 ms | Hover, press and colour changes |
| `--dur` | 180 ms | Menus, rows arriving, notices opening, route change |
| `--dur-slow` | 240 ms | Sheets, the route rule drawing in |
| `--ease-out` | `cubic-bezier(0.23, 1, 0.32, 1)` | Everything that arrives |

Motion uses composite properties only (transform and opacity), and exits are faster than
entrances.

- **Press**: buttons scale to 0.97.
- **Route change**: the sheet cross-fades with a 4 px rise (View Transitions, `page`). The band
  stays still.
- **Signature**: the route rule draws from the library bullet to the new station (`route-draw`).
- **Lists**: a new row fades in from 4 px above (`row-in`).
- **Progress**: fills move with `transform: scaleX`. A job with no total yet shows the `sweep`.
- **Theme**: a 180 ms cross-fade.

`prefers-reduced-motion` removes travel and view transitions. Busy indicators breathe instead of
spinning.

## States and feedback

- **Loading**: `Skeleton` bars at the size of the value they stand for, in the final layout, with
  no pulse. Labels and headers show at once. A cold load waits 150 ms before showing anything.
- **Pending actions**: `Button pending` keeps the label, adds a `Spinner` and sets `aria-busy`.
  Forms ignore repeat submits.
- **Results**: a `toast` (Sonner, bottom right) for an outcome that happened off-screen or after a
  dialog closed (saved, created, copied, removed). An inline status line when the result belongs to
  a field or a row.
- **Errors**: inside the block that failed, with one sentence on what failed and how to recover,
  and a Retry. `FormAlert` is for form-level errors. `StatusScreen` is for a whole page (not found,
  can't reach the server).
- **Empty**: `EmptyState` keeps the block's frame and says what to do next, with the action.
- **Jobs**: imports and embedding show a determinate bar as soon as a total is known, with counts
  in words and `role="status"` updates per phase.

## Components

| Component | Where | Notes |
|---|---|---|
| `Button` | `ui/button.tsx` | `default` (the one primary), `outline` (secondary), `ghost` (toolbar), `destructive` (outlined), `destructive-solid` (only inside a confirmation). Sizes `default`, `sm`, `icon`. 44 px on touch, 36 px with a fine pointer. |
| `Input`, `Field`, `TextareaField`, `SelectField` | `ui/` | Label above (14 / 500), help text below in `text-small`, errors announced. Built on the `control` recipe. |
| `trigger` recipe | `recipes.ts` | A button that opens a picker (versions, files). |
| `pill` + `pillTone` | `recipes.ts` | Status beside a value. One status mark per row. |
| `codeWell`, `kbd` | `recipes.ts` | Literal text (tokens, snippets) and key hints. |
| `LibraryBullet`, `VersionStation`, `Commit`, `RouteStrip` | `ui/route.tsx` | The signature. Use them wherever a library, version or commit is named. |
| `Page`, `PageHeader`, `Section`, `EmptyState` | `ui/page.tsx` | The page frame. |
| `StatusScreen` | `ui/status-screen.tsx` | Not found and route errors. |
| `Skeleton`, `Spinner` | `ui/` | Loading. |
| `Dialog`, `Sheet`, `DropdownMenu`, `Tooltip`, `Tabs`, `Table` | `ui/` | shadcn, on these tokens. Use a dialog only for confirmations and for showing a secret once. |
| `ThemeSwitch` | `ui/theme-switch.tsx` | Light, Dark, System. In the band and on the auth card. |
| `Toaster` / `toast` | `ui/sonner.tsx` | Mounted once in `__root`. |

## Accessibility

- Every interactive element has a visible focus ring (`ring`, 2 px). Touch targets are at least
  44 px.
- Text meets 4.5:1 (axe-clean in both themes; the e2e test checks this).
- A Skip to content link leads to `#main`. Each page has one h1, focused on navigation by
  `usePageTitle`.
- Status changes are announced (`role="status"` or `role="alert"`). Toasts duplicate an inline
  status; they are never its only form.
