---
name: ExactDocs
description: Version-accurate documentation, set like a wayfinding system. Every screen says exactly where you are on the line.
colors:
  frame: "oklch(0.965 0.006 230)"
  sheet: "oklch(1 0 0)"
  raised: "oklch(0.973 0.004 240)"
  accent-fill: "oklch(0.948 0.004 240)"
  ink: "oklch(0.2 0.006 250)"
  ink-muted: "oklch(0.47 0.005 250)"
  ink-inverse: "oklch(0.99 0 0)"
  border: "oklch(0.925 0.004 240)"
  rule: "oklch(0.955 0.003 240)"
  control-border: "oklch(0.84 0.005 250)"
  route: "oklch(0.47 0.08 215)"
  route-soft: "oklch(0.95 0.025 215)"
  focus-ring: "oklch(0.55 0.1 215)"
  positive: "oklch(0.5 0.11 155)"
  positive-soft: "oklch(0.96 0.04 155)"
  positive-ink: "oklch(0.3 0.07 155)"
  warning: "oklch(0.47 0.12 55)"
  warning-soft: "oklch(0.975 0.035 85)"
  warning-ink: "oklch(0.42 0.11 55)"
  destructive: "oklch(0.52 0.19 27)"
  destructive-soft: "oklch(0.965 0.025 27)"
  destructive-ink: "oklch(0.4 0.15 27)"
  line-1: "oklch(0.47 0.08 215)"
  line-2: "oklch(0.47 0.15 255)"
  line-3: "oklch(0.48 0.11 155)"
  line-4: "oklch(0.5 0.17 27)"
  line-5: "oklch(0.47 0.1 70)"
  line-6: "oklch(0.48 0.14 350)"
  line-7: "oklch(0.48 0.09 120)"
  line-8: "oklch(0.45 0.02 250)"
typography:
  small:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "1.125rem"
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, SF Mono, Cascadia Mono, Menlo, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: "1.25rem"
  body:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.25rem"
  section:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: "1.5rem"
  title:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: "1.75rem"
    letterSpacing: "-0.01em"
  figure:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 400
    lineHeight: "2.125rem"
  reader-title:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 600
    lineHeight: 1.2
  reader-body:
    fontFamily: "IBM Plex Sans Variable, IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.65
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
  sheet: "16px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  section: "48px"
  band: "52px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ink-inverse}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "36px"
  button-outline:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "36px"
  button-outline-hover:
    backgroundColor: "{colors.accent-fill}"
  button-ghost-hover:
    backgroundColor: "{colors.accent-fill}"
  button-destructive:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.destructive}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "36px"
  button-destructive-hover:
    backgroundColor: "{colors.destructive-soft}"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  pill-neutral:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 8px"
    height: "20px"
  pill-route:
    backgroundColor: "{colors.route-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 8px"
    height: "20px"
  pill-positive:
    backgroundColor: "{colors.positive-soft}"
    textColor: "{colors.positive-ink}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 8px"
    height: "20px"
  pill-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning-ink}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 8px"
    height: "20px"
  pill-destructive:
    backgroundColor: "{colors.destructive-soft}"
    textColor: "{colors.destructive-ink}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 8px"
    height: "20px"
  library-bullet:
    backgroundColor: "{colors.line-1}"
    textColor: "{colors.ink-inverse}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    size: "28px"
  code-well:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    typography: "{typography.mono}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
  sheet:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.sheet}"
  band:
    backgroundColor: "{colors.frame}"
    height: "52px"
---

# Design System: ExactDocs

The web UI's visual language: the tokens and components every screen is built from, and when to
use each one. Tokens live in `src/app/styles.css`. Components live in `src/shared/ui/` (shadcn/ui,
restyled to these tokens). The class recipes live in `src/shared/ui/recipes.ts`. A screen uses these
names only: no raw colours, no one-off sizes or durations. If something is missing, add it here
and to the tokens first. The frontmatter above is normative for values (light theme; the dark
theme's counterparts are in `.impeccable/design.json` and `styles.css`); the tables below say which
token to reach for.

## Overview

**Creative North Star: "The Wayfinding Line"**

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

**Key Characteristics:**
- Cool tinted frame around a white sheet; the sheet is inset 16px-rounded from `md` up.
- Ink plus two greys for all words; one deep-teal route hue; eight line colours only on library bullets.
- IBM Plex Sans for everything, IBM Plex Mono for versions, SHAs, paths, IDs, tokens and code.
- Flat: depth is tonal (frame, sheet, raised) and by hairline borders, not shadows.
- Motion is composite-only (transform and opacity) and explains state.

## Colors

A cool-tinted neutral world with a single teal voice. Light and dark are both defined on `:root`
and `.dark` (see `src/shared/lib/theme.ts`). Dark mode uses true neutrals, never navy.

### Primary
- **Deep Route Teal** (`route`, oklch(0.47 0.08 215), about #1b6c80): where you are. The active
  tab rule, the current version station, selected tree rows, progress fills, the route rule
  between stops, text selection. Its pale ground is `route-soft`. The focus ring is a lighter
  step of the same hue (`focus-ring`, `ring`).
- **Ink** (`ink` = `foreground` and `primary`, oklch(0.2 0.006 250)): all running text in full
  ink, and the one primary action per screen (near-black button, white in dark).

### Secondary (states)
- **Positive / Warning / Destructive** (`positive`, `warning`, `destructive`, each with `-soft`
  and `-ink`): states only. Text in the plain token; pills as the `-soft` ground with `-ink`
  text.

### Tertiary (library lines)
- **Line 1 to 8** (`line-1` … `line-8`): a library's line colour, only on its bullet
  (`LibraryBullet`, picked by a stable hash of the ID). White text on each clears 4.5:1.

### Neutral
- **Cool Frame** (`frame`, oklch(0.965 0.006 230)): the band and the margin around the sheet.
  Never behind content.
- **White Sheet** (`background`, `sheet`): where the work is. Inputs are white on it too
  (`control`).
- **Raised / Muted** (`raised`, `muted`, oklch(0.973 0.004 240)): a panel one step off the sheet:
  settings panels, the reader's contents. `code` shares the value: code blocks and `codeWell`.
- **Hover Fill** (`accent`, `secondary`, oklch(0.948 0.004 240)): hover fills and the active nav
  pill.
- **Muted Ink** (`muted-foreground`, oklch(0.47 0.005 250), 6.6:1 on white): secondary text,
  labels and meta. The only grey for words.
- **Border / Rule / Control Border** (`border`, `rule`, `input`): card and sheet edges; row rules
  in lists and tables (one step lighter than `border`); control borders (one step stronger).
- **Overlay** (`overlay`): the scrim behind dialogs and sheets.
- **Reader roles** (`hl-*`, `tint-*`): syntax roles in code and callout tints in articles (reader
  only). Each syntax role is 4.5:1+ on `code`.

### Named Rules
**The Three Percent Rule.** Colour is under about 3% of a screen. A delta or status is coloured
only when it means good or bad. Zero is grey.

**The One Route Hue Rule.** Teal means place, selection and progress, nothing else. Line colours
live only on library bullets. Violet, indigo, gradients and glows are not used anywhere.

**The Two Greys Rule.** Words are ink or `muted-foreground`. No third grey for text.

## Typography

**Display Font:** IBM Plex Sans (variable, self-hosted, with ui-sans-serif, system-ui)
**Body Font:** IBM Plex Sans
**Label/Mono Font:** IBM Plex Mono (400 and 500, with ui-monospace, SF Mono, Menlo)

**Character:** One family, no display face. Plex Sans carries the UI at 14px; Plex Mono appears
only where the text is literal: versions, commit SHAs, paths, IDs, tokens and code. Both are
self-hosted by `@fontsource`, so nothing loads from another origin. Plex's `ss02` single-storey g
is on in the body.

### Hierarchy

| Class | Size / line | Use |
|---|---|---|
| `text-small` | 12 / 18 | Meta, helper text, table headers, pills, key hints, library bullets |
| `text-mono` | 13 / 20 | Monospace beside 14 px text: refs, paths, IDs, SHAs |
| `text-body` | 14 / 20 | UI text, cells, labels, descriptions |
| `text-section` | 16 / 24 | Section headings (600), list titles |
| `text-title` | 22 / 28 | The page's h1 (600), one per page |
| `text-figure` | 28 / 34 | The one figure that answers a screen's question (400) |
| `text-reader-title` | 30 / 1.2 | The article's own title in the reader |
| reader | 17 / 1.65, 68ch | Article prose (`prose.css`); headings of the file 22 / 20 / 17, code and tables 14, captions 12 |

These are the only sizes: no `text-[13px]` or the default `text-sm`. The reader uses seven in all
(12, 13, 14, 17, 20, 22, 30) and nothing under 12 px; the e2e test checks both. `cn()`
(`src/shared/lib/utils.ts`) teaches tailwind-merge the names, so `text-small` next to `text-white`
keeps both.

Weights: 400, 500 for labels and the active nav, 600 for headings. Use sentence case everywhere,
no tracked capitals. Figures are tabular wherever they are compared (`table`, `time` and `.num` do
this automatically).

### Named Rules
**The Literal Is Mono Rule.** If a reader could copy it into a terminal or a config (version,
SHA, path, ID, token), it is Plex Mono; nothing else is.

**The Closed Scale Rule.** Only the sizes above exist. A new size is added to the tokens and this
file first.

## Layout

- **Spacing** is on a 4 px base. Inside a block, 8 and 16. Between blocks, 24 and 32. Between page
  sections, 48 (`gap-12`). There is more space above a heading than below it.
- **Frame**: the band is 52 px (`h-13`). From `md` up the sheet is inset 8 px from the window with a
  1 px `border`. Below `md` the sheet is the screen.
- **Page widths**: there are two. `Page width="operate"` (1152 px) is for lists, settings and
  forms. `width="wide"` is for the library page and reader. `narrow` (720 px) is only for
  single-form pages. The reader's text column is 68ch.
- **Every page** starts with `PageHeader`: an h1 (`text-title`), one line about the data, and the
  actions at the right. Sections use `Section` (h2 `text-section`).
- **Breakpoints**: phone below `md` (the band shows the menu sheet). `lg` puts the search field in
  the band. `xl` shows the reader's contents column.
- **Touch**: controls are 44 px high on touch and 36 px (sm 32 px) with a fine pointer.

## Elevation & Depth

Flat by default. Depth is tonal: the frame sits behind, the white sheet in front, `raised` one
step off the sheet, with hairline `border` and `rule` lines doing the separating. The only
shadows are the library's stock overlay shadows on menus, popovers and dialogs (`shadow-md`,
`shadow-lg`); nothing at rest carries one. Focus is a 2px `ring` outline with 2px offset.

### Named Rules
**The Flat-At-Rest Rule.** Surfaces never carry a shadow at rest; only floating layers (menu,
popover, dialog) do.

## Shapes

Soft but not round. The sheet is 16px (`rounded-sheet`), cards and panels 8px (`rounded-lg`),
controls 6px (`rounded-md`), key hints and small chips 4px, pills and bullets full. Borders are
1px hairlines; the one thick line is the 2px route rule between stops. Library bullets and
version stations are circles (a station is a 10px ring with a 2px teal border, filled when it is
the default).

## Motion

Motion explains state. It is never decoration. (Tokens are in the sidecar's `motion` list.)

| Token | Value | Use |
|---|---|---|
| `--dur-fast` | 120 ms | Hover, press and colour changes |
| `--dur` | 180 ms | Menus, rows arriving, notices opening, route change |
| `--dur-slow` | 240 ms | Sheets, the route rule drawing in |
| `--ease-out` | `cubic-bezier(0.23, 1, 0.32, 1)` | Everything that arrives |

Motion uses composite properties only (transform and opacity): nothing animates a height, a width
or `grid-template-rows`. Something that appears in place (a notice, a form, a failure detail) uses
`reveal`: a fade with a 4 px rise. Exits are faster than entrances. Durations and easing come from
the tokens above, never from literals; menus, popovers and dialogs set `transition-none` so their
zoom pivots on the anchored corner from the first frame.

- **Press**: buttons scale to 0.97.
- **Route change**: the sheet cross-fades with a 4 px rise (View Transitions, `page`). The band
  stays still.
- **Signature**: the route rule draws from the library bullet to the new station (`route-draw`).
- **Lists**: a new row fades in from 4 px above (`row-in`).
- **Progress**: fills move with `transform: scaleX`. A job with no total yet shows the `sweep`.
- **Theme**: a 180 ms cross-fade.

`prefers-reduced-motion` removes travel, zoom and view transitions; what appears in place still
fades in (opacity only), and shadcn menus and dialogs keep their fade. Busy indicators breathe
instead of spinning.

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

Quiet and restrained: white controls with a hairline border on the sheet, one near-black primary.

| Component | Where | Notes |
|---|---|---|
| `Button` | `ui/button.tsx` | `default` (the one primary), `outline` (secondary), `ghost` (toolbar), `destructive` (outlined), `destructive-solid` (only inside a confirmation). Sizes `default`, `sm`, `icon`. 44 px on touch, 36 px with a fine pointer. |
| `Input`, `Field`, `TextareaField`, `SelectField` | `ui/` | Label above (14 / 500), help text below in `text-small`, errors announced. Built on the `control` recipe. |
| `trigger` recipe | `recipes.ts` | A button that opens a picker (versions, files). |
| `pill` + `pillTone` | `recipes.ts` | Status beside a value. One status mark per row. Tones: neutral, route, positive, warning, destructive. |
| `codeWell`, `kbd` | `recipes.ts` | Literal text (tokens, snippets) and key hints. |
| `LibraryBullet`, `VersionStation`, `Commit`, `RouteStrip` | `ui/route.tsx` | The signature. Use them wherever a library, version or commit is named. |
| `Page`, `PageHeader`, `Section`, `EmptyState` | `ui/page.tsx` | The page frame. |
| `StatusScreen` | `ui/status-screen.tsx` | Not found and route errors. |
| `Skeleton`, `Spinner` | `ui/` | Loading. |
| `Dialog`, `Sheet`, `DropdownMenu`, `Tooltip`, `Tabs`, `Table` | `ui/` | shadcn, on these tokens. Use a dialog only for confirmations and for showing a secret once. |
| `ThemeSwitch` | `ui/theme-switch.tsx` | Light, Dark, System. In the band and on the auth card. |
| `Toaster` / `toast` | `ui/sonner.tsx` | Mounted once in `__root`. |

### Buttons
- **Shape:** gently rounded (6px), 14px / 500 label, 16px side padding, 16px icons.
- **Primary:** near-black ground with near-white text (inverted in dark); one per screen.
- **Hover / Focus / Press:** hover darkens to 88% (primary) or fills `accent` (outline, ghost);
  focus is a 2px `ring` with 2px offset; press scales to 0.97; pending sets `aria-busy`.
- **Outline / Ghost / Destructive:** outline is a white button with a `input` border; ghost has no
  border; destructive is outlined in 40% destructive and fills `destructive-soft` on hover.

### Inputs / Fields
- **Style:** white on the sheet, 1px `input` border, 6px radius, 14px text (16px on touch so
  mobile browsers do not zoom).
- **Focus:** border becomes `ring` with a soft 3px ring at 25%.
- **Error / Disabled:** `destructive` border with a 20% ring; disabled sits on `muted` with muted text.

### Pills and chips
- **Style:** 20px high, full radius, 12px / 500, `-soft` ground with `-ink` text.

### Navigation
- Band on `frame`, 52px, with the wordmark, nav pills (active pill on `accent`, 500), the
  search field from `lg`, theme switch and user menu. Below `md` the menu opens in a `Sheet`.

### Library bullet and route strip (signature)
A 24 to 36px circle in the library's line colour with two white initials (12px / 600; 14px at the
large size), followed by the library's name, a 2px teal rule 16px long that draws in, and the
stops: a version station (ring plus Plex Mono ref) and a short SHA in muted mono.

## Accessibility

- Every interactive element has a visible focus ring (`ring`, 2 px). Touch targets are at least
  44 px.
- Text meets 4.5:1 (axe-clean in both themes; the e2e test checks this).
- A Skip to content link leads to `#main`. Each page has one h1, focused on navigation by
  `usePageTitle`.
- Status changes are announced (`role="status"` or `role="alert"`). Toasts duplicate an inline
  status; they are never its only form.

## Do's and Don'ts

### Do:
- **Do** name library, version and commit with `LibraryBullet`, `VersionStation` and `Commit`
  wherever they appear.
- **Do** use only the named tokens, sizes, durations and recipes; add to the tokens first.
- **Do** keep one primary button per screen and start every page with `PageHeader`.
- **Do** set literal text (versions, SHAs, paths, tokens) in Plex Mono.
- **Do** animate transform and opacity only, with `--dur-*` and `--ease-out`.

### Don't:
- **Don't** colour more than about 3% of a screen, or use a delta colour for anything but good or bad.
- **Don't** use violet, indigo, gradients or glows; line colours belong on library bullets only.
- **Don't** put `frame` behind content, or use navy in dark mode.
- **Don't** use raw colours, `text-[13px]`, the default `text-sm`, tracked capitals or ad hoc durations.
- **Don't** animate a height, a width or `grid-template-rows`.
- **Don't** use a dialog except for confirmations and for showing a secret once.
