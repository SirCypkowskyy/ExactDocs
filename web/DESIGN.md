---
name: ExactDocs
description: Version-accurate documentation. A mole with a headlamp lights exactly the version you asked for and hands you the page.
colors:
  frame: "#f3f2ef"
  sheet: "#ffffff"
  raised: "#f7f6f4"
  accent-fill: "#efeeeb"
  ink: "#17171a"
  ink-muted: "#5c5d63"
  ink-inverse: "#ffffff"
  border: "#e5e4e0"
  rule: "#efeeea"
  control-border: "#b9b8b3"
  lamp: "#f5c542"
  route: "#17171a"
  route-soft: "#fcefc4"
  focus-ring: "#17171a"
  tip: "#17171a"
  tip-foreground: "#f6f5f2"
  overlay: "rgb(23 23 26 / 0.38)"
  code: "#f7f6f4"
  logo-tile: "#ffffff"
  logo-tile-edge: "rgb(23 23 26 / 0.12)"
  chart-series: "#6b6c72"
  chart-highlight: "#17171a"
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
    fontFamily: "Schibsted Grotesk Variable, Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "1.125rem"
  mono:
    fontFamily: "JetBrains Mono Variable, JetBrains Mono, ui-monospace, SF Mono, Cascadia Mono, Menlo, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: "1.25rem"
  body:
    fontFamily: "Schibsted Grotesk Variable, Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.25rem"
  section:
    fontFamily: "Schibsted Grotesk Variable, Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: "1.5rem"
  title:
    fontFamily: "Schibsted Grotesk Variable, Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: "1.75rem"
    letterSpacing: "-0.01em"
  figure:
    fontFamily: "Schibsted Grotesk Variable, Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 400
    lineHeight: "2.125rem"
  reader-title:
    fontFamily: "Schibsted Grotesk Variable, Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 600
    lineHeight: 1.2
  reader-body:
    fontFamily: "Schibsted Grotesk Variable, Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
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
  sheet-inset: "8px"
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
  nav-pill:
    textColor: "{colors.ink-muted}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  nav-pill-hover:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.ink}"
  nav-pill-active:
    textColor: "{colors.ink}"
  band-icon-button:
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.md}"
    size: "36px"
  band-icon-button-hover:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.ink}"
  tooltip:
    backgroundColor: "{colors.tip}"
    textColor: "{colors.tip-foreground}"
    typography: "{typography.small}"
    rounded: "{rounded.sm}"
    padding: "4px 8px"
  menu:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "4px"
  menu-item:
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 8px"
    height: "32px"
  menu-item-highlighted:
    backgroundColor: "{colors.accent-fill}"
  tab:
    textColor: "{colors.ink-muted}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "40px"
  tab-active:
    textColor: "{colors.ink}"
  choice-selected:
    backgroundColor: "{colors.route-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
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
  badge-count:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    padding: "0 6px"
    height: "20px"
  icon-button:
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    size: "36px"
  icon-button-hover:
    backgroundColor: "{colors.accent-fill}"
  alert-dialog:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xl}"
    padding: "24px"
  confirm-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.ink-inverse}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "36px"
  toggle-item:
    textColor: "{colors.ink-muted}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "32px"
  toggle-item-on:
    backgroundColor: "{colors.route-soft}"
    textColor: "{colors.ink}"
  avatar:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    size: "24px"
  meter:
    backgroundColor: "{colors.accent-fill}"
    rounded: "{rounded.full}"
    height: "6px"
  logo-tile:
    backgroundColor: "{colors.logo-tile}"
    rounded: "{rounded.md}"
    padding: "2px"
  table-header:
    textColor: "{colors.ink-muted}"
    typography: "{typography.small}"
  library-bullet:
    backgroundColor: "{colors.line-1}"
    textColor: "{colors.ink-inverse}"
    typography: "{typography.small}"
    rounded: "{rounded.full}"
    size: "28px"
  code-well:
    backgroundColor: "{colors.code}"
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
use each one. Tokens live in `src/app/styles.css`. Components live in `src/shared/ui/` (shadcn/ui
on Radix, restyled to these tokens). The class recipes live in `src/shared/ui/recipes.ts`. A screen
uses these names only: no raw colours, no one-off sizes or durations. If something is missing, add
it here and to the tokens first. The frontmatter above is normative for values (light theme; the
dark theme's counterparts are in `.impeccable/design.json` under `darkTheme` and in `styles.css`);
the sections below say which token to reach for.

## Overview

**Creative North Star: "The Headlamp"**

**Of all the layers, one thing is lit.** The sign is an anthracite mole with a yellow headlamp who
digs through layers of versions, lights exactly the one you asked for, and hands you the page. The
UI keeps that one idea: a quiet, mature working tool in which a single light, the lamp, says which
exact thing is lit (the current page, the selected version, the checked option, the active tab).

The layout is a framed sheet. A warm stone **frame** (the band at the top and the window's margin)
holds a white **sheet** where the work happens. It is flat: hairlines separate, tones layer, nothing
at rest casts a shadow. Words are anthracite ink with one grey. In light mode the lamp appears as a
pale yellow wash behind the lit item, with ink marks on it, because yellow text and thin yellow
marks do not read on white. In dark mode the lamp itself draws the marks. The mascot is friendly;
the interface and the type around it are grown-up.

Built from shadcn/ui and these free shadcnblocks.com blocks (no premium code):
`navbar1`, `navbar5` and `navbar35` (the band's navigation menu and the phone's accordion),
`application-shell3` (the frame, sheet and user menu), `login2` (the auth card),
`blogpost2` (the reader's sticky contents column), `changelog1` (the version rail) and
`data-table1` (the server-side tables, #434). The app style is the design-taste "framed-sheet"
(dealt seed 913649743) in Operate mode.

**Key Characteristics:**
- Warm stone frame around a white sheet; from `md` up the sheet is inset 8px with 16px corners and a hairline border.
- Anthracite ink plus one grey for all words; one accent, the lamp; eight line colours only on library bullets.
- Schibsted Grotesk for the whole UI, JetBrains Mono only for literals (versions, SHAs, paths, IDs, tokens, code).
- Flat: depth is tonal (frame, sheet, raised) and by hairlines; the one shadow is for floating layers.
- Motion is short, composite-only (transform and opacity), interruptible, and explains state.
- Interface preferences (theme, contrast, text size, spacing, motion, face, links, targets) are first-class and synced to the account.

### The sign

The mark lives in `public/brand/` (built with the logo-design skill; no gradients, no filters).

- **The mole:** anthracite fur (#2f3033), a lighter belly (#4e4f55), cream closed eyes, pink nose
  and paws, a yellow headlamp in the lamp colour, holding a white page with no tab. No ground and
  no light rays.
- **Cuts:** `exactdocs-mark.svg` (full, light grounds), `exactdocs-mark-on-dark.svg` (the same with
  a cream outline so the fur holds on dark), `exactdocs-mark-small.svg` and
  `-small-on-dark.svg` (the small-size cut without the page, for 16 to 48px: the band's `Mark`, the
  favicon), and `exactdocs-mark-mono-black.svg` / `-mono-white.svg` (one-colour line art).
- **Wordmark:** "ExactDocs" set in Bricolage Grotesque 650 at opsz 96, outlined in the SVG with
  manual kerning (c-t tightened, t-D opened), so no font is shipped for it. In the lockups
  (`exactdocs-lockup-light.svg`, `-dark.svg`) the text is optically centred on the mole. The
  wordmark face appears nowhere else in the UI.
- **Favicon set:** `favicon.svg` (the small cut), `favicon.ico` (48px), `apple-touch-icon.png`,
  `icon-192.png`, `icon-512.png`, `maskable-512.png`, listed in `site.webmanifest`. The browser
  chrome colour (`theme-color`) is the frame in each theme (#F3F2EF, #0E0E10).

## Colors

A warm stone and anthracite world with a single yellow light. Both themes are defined on `:root`
and `.dark`; `src/shared/lib/preferences.ts` picks one.

### Primary
- **The Lamp** (`lamp`): the brand yellow and the one accent. On light grounds it is never text and
  never a thin mark: it shows as its wash, `route-soft` (the lamp's wash behind the lit item: the
  selected option, a route pill), and as text selection (the lamp at 55%). In dark mode
  `route`, `ring` and `selection` all become the lamp itself: it draws the active tab rule, the
  current nav underline, the current station, checked switches and the focus ring.
- **Route** (`route`, also `selection`): the mark that must read. Ink in light mode (tab rule,
  current station, nav underline, checked switch, menu check marks), the lamp in dark mode.
  `route-foreground` is the text on a filled route.
- **Ink** (`ink` = `foreground`, `primary`, `ring` in light): all running text, the one primary
  action per screen (anthracite button, inverted to near-white in dark), and the focus ring in light.

### Secondary (states)
- **Positive / Warning / Destructive** (`positive`, `warning`, `destructive`, each with `-soft`
  and `-ink`): states only. Text in the plain token; pills as the `-soft` ground with `-ink` text.

### Tertiary (library lines)
- **Line 1 to 8** (`line-1` … `line-8`): a library's own colour, only on its bullet
  (`LibraryBullet`, picked by a stable hash of the ID). White initials on each clear 4.5:1.

### Neutral
- **Stone Frame** (`frame`): the band and the margin around the sheet. Never behind content.
- **White Sheet** (`background`, `sheet`, also `card` and `popover` in light): where the work is.
  Inputs are white on it too.
- **Raised** (`raised`, `muted`, `code`): a panel one step off the sheet: settings panels, code
  blocks, `codeWell`.
- **Hover Fill** (`accent`, `secondary`): hover fills, highlighted menu rows, the current row in the
  phone menu, neutral pills and the avatar disc.
- **Muted Ink** (`muted-foreground`, 6.6:1 on white, 5.9:1 on the frame): secondary text, labels,
  meta, idle nav pills and band icons. The only grey for words.
- **Border / Rule / Control Border** (`border`, `rule`, `input`): card and sheet edges; row rules
  in lists, tables and menus (one step lighter); control borders (one step stronger).
- **Tip** (`tip`, `tip-foreground`): the tooltip, inverted (anthracite in light, cream in dark).
- **Overlay** (`overlay`): the scrim behind dialogs and sheets.
- **Logo Tile** (`logo-tile`, `logo-tile-edge`): the ground of a library's own logo in
  `LibraryMark`: white in both themes, inside a hairline of ink at 12% (30% with more contrast)
  drawn over the white, so a dark logo with a transparent background stays visible on the dark
  sheet. Only logos sit on it.
- **Reader roles** (`hl-*`, `tint-*`): syntax roles in code and callout tints in articles (reader
  only). Each syntax role is 4.5:1+ on `code`.

### Charts
- **Chart Series** (`chart-series`): every bar, line and area of a chart (`#6b6c72`; 5.2:1 on the
  sheet, 4.8:1 on `raised`). One grey for all series: a chart compares amounts, not colours.
- **Chart Highlight** (`chart-highlight` = `route`): the one lit series or bar ("you" on the
  leaderboard, the selected day). Ink in light (17.9:1), the lamp in dark (11:1). It is never told
  by colour alone: a label or the legend names it too.
- Grids are `rule`, axes `text-small` in `muted-foreground`, the chart tooltip is the inverted `tip`.
  State series (jobs by state) use the state tokens because they are states. Never `line-1` to
  `line-8` (library colours belong to bullets), never the lamp as a fill on a light ground.

### Dark
The mole's own colours: the frame (#0e0e10) is darker than the sheet (#17171a), text is cream
(#f3f1ec) with a grey of #a6a6ae, the primary button inverts to cream, and the lamp draws every mark
that must read (10:1+ on the sheet). `route-soft` becomes a dim amber (#3b3320). The logo tile stays
white; `chart-series` is #8b8b94 (5.3:1 on the sheet, 5:1 on `raised`) and `chart-highlight` is the
lamp. Dark is true anthracite, never navy.

### More contrast
`data-contrast="more"` darkens `muted-foreground` and strengthens `border`, `rule`, `input` and the
frame in both themes; `chart-series` goes to #4f5055 in light (8:1) and #a0a0a8 in dark (6.9:1),
and the logo tile's hairline to 30% ink. Nothing else changes.

### Named Rules
**The One Lamp Rule.** The lamp is the only accent. It marks the one lit thing (where you are, what
is selected, what is checked, what has focus) and nothing else. Line colours live only on library
bullets; states only on states.

**The Wash, Not The Word Rule.** On light grounds the lamp is a wash (`route-soft`) with ink on it,
never yellow text or a yellow hairline. Marks that must read in light mode are ink (`route`).

**The Lamp Draws In The Dark Rule.** In dark mode `route`, `ring` and `selection` are the lamp
itself; use the tokens, never `lamp` directly, and each theme does the right thing.

**The Three Percent Rule.** Colour is under about 3% of a screen. A delta or status is coloured
only when it means good or bad. Zero is grey.

**The Two Inks Rule.** Words are ink or `muted-foreground`. No third grey for text.

## Typography

**Display Font:** none (the UI has no display face)
**Body Font:** Schibsted Grotesk Variable (with ui-sans-serif, system-ui)
**Label/Mono Font:** JetBrains Mono Variable (with ui-monospace, SF Mono, Cascadia Mono, Menlo)

**Character:** One mature grotesk for every word of the interface, firm at 14px and calm at 600 for
headings; a mono that appears only where the text is literal. Both are self-hosted by
`@fontsource`, so nothing loads from another origin. The wordmark's Bricolage Grotesque lives only
in the outlined logo.

### Hierarchy

| Class | Size / line | Use |
|---|---|---|
| `text-small` | 12 / 18 | Meta, helper text, table headers, pills, key hints, tooltips, library bullets |
| `text-mono` | 13 / 20 | Monospace beside 14px text: refs, paths, IDs, SHAs |
| `text-body` | 14 / 20 | UI text, cells, labels, nav pills, menu rows, descriptions |
| `text-section` | 16 / 24 | Section headings (600), list titles; inputs on touch (no zoom) |
| `text-title` | 22 / 28 | The page's h1 (600, -0.01em), one per page; dialog titles |
| `text-figure` | 28 / 34 | The one figure that answers a screen's question (400) |
| `text-reader-title` | 30 / 1.2 | The article's own title in the reader |
| reader | 17 / 1.65, 68ch | Article prose (`prose.css`); headings 22 / 20 / 17 at 600, inline code 14 |

These are the only sizes: no `text-[13px]` and no default `text-sm`. Every size is in rem, so the
text-size preference scales all of them at once. `cn()` (`src/shared/lib/utils.ts`) teaches
tailwind-merge the names, so `text-small` next to `text-white` keeps both.

Weights: 400; 500 for labels, buttons, nav pills and tooltips; 600 for headings and bullet
initials. Sentence case everywhere, no tracked capitals. Figures are tabular wherever they are
compared (`table`, `time` and `.num` do this automatically).

### Readable faces
The face is a preference (`data-font`): the default Schibsted Grotesk; Atkinson Hyperlegible Next;
OpenDyslexic (400 and 700); or the device's own system UI face. Each swaps `--ui-font` only, so the
mono stays. The Interface tab previews each face in itself.

### Named Rules
**The Literal Is Mono Rule.** If a reader could copy it into a terminal or a config (version,
SHA, path, ID, token, code), it is JetBrains Mono; nothing else is.

**The Closed Scale Rule.** Only the sizes above exist. A new size is added to the tokens and this
file first.

## Layout

- **Spacing** is on a 4px base. Inside a block, 8 and 16. Between blocks, 24 and 32. Between page
  sections, 48. There is more space above a heading than below it.
- **Frame:** the band is 56px (`h-14`), sticky, on the frame colour, and never scrolls away. From
  `md` up the sheet is inset 8px from the window sides and bottom, with 16px corners and a 1px
  `border`. Below `md` the sheet is the screen.
- **The band, left to right:** the menu button (below `md`), the lockup (mole and wordmark), a
  hairline divider, the navigation menu (from `md`: Libraries and Search as direct links, Tools and
  Admin as panels), the search field (from `xl`; below it a search icon), the interface console
  (text size A- / A+ from `sm`, a hairline, the theme button and the interface and accessibility
  menu, in one bordered group) and the account (from `md`; the name from `lg`).
- **Auth pages:** the lockup at 48px over one 400px card that is itself a sheet (16px corners, a
  hairline) on the frame, a line under it about the product; the three interface controls sit in
  the top right corner.
- **Page widths:** `Page width="operate"` (1152px) for lists, settings and forms; `wide` for the
  library page and reader; `narrow` (720px) only for single-form pages. The reader's measure is 68ch.
- **Every page** starts with `PageHeader`: an h1 (`text-title`), one line about the data, and the
  actions at the right. Sections use `Section` (h2 `text-section`).
- **Breakpoints:** phone below `md` (the band opens a menu sheet from the left). `xl` puts the
  search field in the band. `xl` shows the reader's contents column.
- **Targets:** every control is 44px on touch and with the large-targets preference; with a fine
  pointer it is 36px (small buttons 32px, menu rows 32px, tabs 40px).

## Elevation & Depth

Flat by default. Depth is tonal: the frame sits behind, the white sheet in front, `raised` one step
off the sheet, with hairline `border` and `rule` lines doing the separating. In dark mode the frame
is darker than the sheet, so the sheet still reads as the lit surface.

### Shadow Vocabulary
- **Float** (`--shadow-float`): a soft drop with a 1px hairline ring. Menus, tooltips and popovers.
  Its dark value deepens the drop and turns the ring white at 7%.

Focus is a 2px `ring` outline (or ring) with a 2px offset: ink in light, the lamp in dark.

### Named Rules
**The Flat-At-Rest Rule.** Surfaces never carry a shadow at rest; only floating layers (menu,
tooltip, popover, dialog, sheet) do, and they use `shadow-float`.

## Shapes

Soft but not round. The sheet is 16px (`rounded-sheet`), dialogs 12px, cards, menus and panels 8px
(`rounded-lg`), controls, buttons, nav pills and menu rows 6px (`rounded-md`), tooltips and key
hints 4px, pills, switches, bullets and the avatar full. Borders are 1px hairlines; the thick lines
are 2px and mean "this one": the tab indicator, the nav underline and the route rule. Library
bullets and version stations are circles (a station is a 10px ring with a 2px `route` border,
filled when it is the default version). An empty state keeps its block's frame with a dashed
control border.

## Components

Quiet and restrained: white controls with a hairline border on the sheet, one anthracite primary,
and the lamp on the one lit thing.

| Component | Where | Notes |
|---|---|---|
| `Button` | `ui/button.tsx` | `default` (the one primary), `outline` (secondary), `ghost` (toolbar), `destructive` (outlined), `destructive-solid` (only inside a confirmation), `band` (the band's icon controls). Sizes `default`, `sm`, `icon`, `icon-sm`. `pending` keeps the label and adds the spinner; `done` cross-fades the label to a check for a moment. |
| `IconButton` | `ui/button.tsx` | A button that shows only an icon. `label` is required and is both its accessible name and its tooltip; `shortcut` adds a key hint; `motion` puts an icon reaction on the icon. Variants `ghost` (default), `outline`, `destructive`, `band`; sizes `icon` (36px with a mouse) and `icon-sm` (32px, dense rows). It forwards its ref and props, so it can be a Radix trigger (`<DropdownMenuTrigger asChild>`). |
| `Input`, `Field`, `TextareaField`, `SelectField` | `ui/` | Label above (14 / 500), help text below in `text-small`, errors announced. Built on the `control` recipe. |
| `trigger` recipe | `recipes.ts` | A button that opens a picker (versions, files). |
| `pill` + `pillTone` | `recipes.ts` | Status beside a value. One status mark per row. Tones: neutral, route (the lamp's wash), positive, warning, destructive. |
| `Badge` | `ui/badge.tsx` | The `pill` recipe as a component: `tone` (neutral, route, positive, warning, destructive); `count` makes the number pill of a filter button ("State · 2"). `StateBadge` (data-table cells) maps job states to tones and icons. |
| `Meter` | `ui/meter.tsx` | A 6px determinate bar on `secondary`; the fill moves by `scaleX`. `value` in whole percent, or `null` for the travelling `sweep` when no total is known; tone `route` (progress), `warning` or `destructive` (budgets near or over); `role` `progressbar` or `meter`. |
| `Avatar` | `ui/avatar.tsx` | Initials only (no pictures are kept): a full-round disc on `secondary`, 24px (`md`) or 32px (`lg`), 12 / 600. Decorative: the username is always beside it. |
| `ToggleGroup`, `ToggleGroupItem` | `ui/toggle-group.tsx` | A segmented control for a few views or periods kept in the URL: one bordered group, the picked item on the lamp's wash. Single choice is a `radiogroup` (name it with `aria-label`); arrow keys move, Space picks. |
| `codeWell`, `kbd` | `recipes.ts` | Literal text (tokens, snippets) and key hints. |
| `LibraryBullet`, `VersionStation`, `Commit`, `RouteStrip` | `ui/route.tsx` | Use them wherever a library, version or commit is named. |
| `LibraryMark` | `ui/library-mark.tsx` | A library's logo on the `logo-tile`, else a generic icon on its line colour; the monogram bullet when the person turned logos off. Takes the library's `logo` as the API sends it (its version) and builds `/api/v1/libraries/{owner}/{repo}/logo?v=<logo>`; a fixed box, `loading="lazy"`, a failed image falls back to the generic icon. Sizes `sm` 24, `md` 28, `lg` 36, `xl` 48. |
| `Page`, `PageHeader`, `Section`, `EmptyState` | `ui/page.tsx` | The page frame. `PageHeader` takes the page's nav `icon`, `description`, `actions` and `above` (a breadcrumb); a library's own pages pass its `LibraryMark` as `mark` instead of the icon (`xl` on the library page, `lg` on its settings, sharing and access log). `EmptyState` draws its `icon` at 32px with a 1.5 stroke (like a table's empty frame), takes `headingLevel` when its title is the page's answer ("No results") and `role="alert"` when it says something failed. |
| `Breadcrumb` and its parts | `ui/breadcrumb.tsx` | Slash separators, the way back in muted ink, the current page in ink with `aria-current`. One for the library page, settings, sharing and the library's access log. `BreadcrumbLink` is a 44px target on touch and a line high with a mouse on its own. |
| `Mark`, `Wordmark` | `ui/wordmark.tsx` | The small mole (28px) and the lockup; light and dark files swap with the theme. |
| `TextSizeControl`, `ThemeButton`, `LanguageMenu`, `InterfaceMenu`, `InterfaceCluster` | `ui/interface-controls.tsx` | The band's interface console (#486); every trigger is a band `IconButton`. |
| `InterfaceSettings`, `PreferenceToggle` | `ui/interface-settings.tsx` | Account → Interface: every preference, with a reset. `children` adds settings after the built-in ones (the auth feature's "Show me on the leaderboard", an account-only choice); `PreferenceToggle` is the switch row they use (label, a `description` node, `disabled` while the choice cannot be changed, said in the description). |
| `ProviderMark` | `ui/brand-marks.tsx` | A sign-in provider's mark: Google's G and Microsoft's four squares in their own colours (their sign-in guidelines ask for them), GitHub and Discord in the text colour, all inline SVG (no icon package, no remote loads); else the operator's icon from this server (`icon_url`, a same-origin path only, fitted with `object-contain`, `alt=""`); else, or when it fails to load, `KeyRound`. Always decorative, the name is written beside it. `sm` 16px in buttons, `md` 20px in lists. `isBrandIcon` puts the brands first on the sign-in page. |
| `Tooltip` | `ui/tooltip.tsx` | A short name or a key for an icon control. `IconButton` brings its own. |
| `Tabs` | `ui/tabs.tsx` | Underline tabs with one sliding indicator. |
| `AlertDialog` and its parts | `ui/alert-dialog.tsx` | The one way to confirm: `role="alertdialog"`, Cancel focused first, Escape cancels, a click outside does nothing; 12px corners, 24px padding. |
| `ConfirmDialog`, `TypedConfirmDialog` | `ui/confirm-dialog.tsx` | The usual confirmation built on AlertDialog: a question as the title, what happens, Cancel and the verb. The confirm runs `onConfirm` and the dialog stays open until the caller closes it, so a refusal shows inside it (`error`, with `errorLink` for its way out, e.g. Sign in); while `pending` it cannot be closed. The typed one keeps the confirm inert until the field holds `phrase` exactly. Focus goes back to what opened it. |
| `DropdownMenu`, `ContextMenu` | `ui/dropdown-menu.tsx`, `ui/context-menu.tsx` | One menu feel (Menus below). A context menu only mirrors a visible menu. |
| `Popover`, `Command` | `ui/popover.tsx`, `ui/command.tsx` | A floating card like a menu, and the filterable list (cmdk) inside pickers and faceted filters; rows use the menu recipe. |
| `LibraryCombobox` | `ui/library-combobox.tsx` | The one library picker (Playground, a token's scope, the jobs and access-log library filters, the global search's other libraries): a Popover with a Command list, "Recent" (the last five picked in this browser, `localStorage`, never required) then every library, grouped by owner above 20. Each row is the `LibraryMark` (sm), the mono ID and the title when it says more; `detail` puts a count at the end. `multiple` ticks several (`aria-multiselectable`, the list stays open, the choice shows as removable `Tag`s under a field); single closes on a pick and offers Clear. `variant` `field` (label above, `trigger` recipe box) or `filter` (an outline toolbar button naming the chosen library); `children` is a trigger of the caller's own. Data from the feature: `options` (with `loading`, `failed`, `onRetry`) or `query` (text to the feature's queryOptions, asked on first open, debounced 200 ms, the old answer filtered meanwhile; `total` above the list's length says "Showing 200 of 340. Type to narrow the list."). `custom` offers a typed value that passes (a removed library's `/owner/repo`). Keyboard: arrows, Home, End, Enter, Escape (focus back on the trigger); the input is a `combobox` pointing at the highlighted `option` with `aria-activedescendant`, and a live line counts the matches. |
| `Tag`, `TagList` | `ui/tags.tsx` | The chip of every tag filter and active filter: 44px on touch, 32px with a mouse, full round on `secondary`. `pressed` + `onClick` is a toggle (`aria-pressed`, picked = solid `route`; the browse and search tag filters through `TagChips`); `onRemove` + `removeLabel` adds the remove `IconButton` (the table's active filters, a picker's chosen libraries); neither is a plain chip. `TagList` is the named `<ul>`; one `<li>` per chip. |
| `Table` and its parts | `ui/table.tsx` | The shadcn table primitives on the tokens: headers `text-small` muted, rows on `rule` hairlines, figures tabular. `TableRowHeader` is a body cell that names its row (`<th scope="row">`), set like any cell. |
| `DataTable` (v2) | `ui/data-table/` | Every list with many rows (Data tables below): `useDataTable`, `DataTable`, `DataTableToolbar`, `DataTablePagination`, row actions and the cell kit. `ui/data-table.tsx` is v1 ("Load more"), kept until the last page moves. |
| `Skeleton` | `ui/skeleton.tsx` | A flat bar at the size of the value it stands for; no pulse. |
| `Dialog`, `Sheet` | `ui/` | shadcn on these tokens. A dialog only for confirmations (as an `AlertDialog`) and for showing a secret once. |
| `Toaster` / `toast` | `ui/sonner.tsx` | Mounted once in `__root`, bottom right, on `popover` with a hairline. |

### Buttons
- **Shape:** gently rounded (6px), 14px / 500 label, 16px side padding (12px small), 16px icons.
- **Primary:** anthracite ground with white text (cream ground, anthracite text in dark); one per screen.
- **Hover / Focus / Press:** hover takes the primary to 88% or fills `accent` (outline, ghost);
  focus is a 2px `ring` with a 2px offset; press scales to 0.97; `pending` keeps the label, adds a
  spinner and sets `aria-busy`.
- **Outline / Ghost / Destructive:** outline is a white button with a control border; ghost has no
  border; destructive is outlined in 40% destructive and fills `destructive-soft` on hover.

### Inputs / Fields
- **Style:** white on the sheet, 1px control border, 6px radius, 14px text (16px on touch so mobile
  browsers do not zoom).
- **Focus:** the border becomes `ring` with a soft 3px ring at 25%.
- **Error / Disabled:** `destructive` border with a 20% ring; disabled sits on `muted` with muted text.

### Pills and chips
- **Style:** 20px high, full radius, 12px / 500, `-soft` ground with `-ink` text. The route tone is
  the lamp's wash with ink text.
- **Chips** (`Tag`) are the pill grown to a target: 44px on touch, 32px with a mouse, on
  `secondary`. A filter you toggle reads in body text and fills solid `route` when on; a chip that
  narrows a list reads `Title: value` in small text with its remove button. One component for both,
  so the tag panel, the articles' Tags facet chips and every active filter look like one family.

### Navigation (the band)
Built on shadcn's Navigation Menu after the free shadcnblocks `navbar1`, `navbar5` and `navbar35`.
- **Information architecture:** where people work every day is one click away (Libraries, Search);
  everything else sits in two panels: Tools (Playground, Jobs) and Admin (AI, Users, Access log;
  operators only, the API refuses anyone else).
- **Triggers and links:** 14px / 500 in muted ink, 6px radius, hover and open fill `accent` with
  ink text; a trigger carries a chevron that turns when open. The current page, or the panel that
  holds it, turns ink and gets a 2px `route` underline (ink in light, the lamp in dark) that grows
  from the centre on the band's lower edge.
- **Panels:** one column, 23rem, on `popover` with `border`, `radius-lg` and `shadow-float`. Each row
  is an 18px line icon, the page's name (500) and one line on what is there (`text-small`, muted);
  hover fills `accent`, the current page has the lamp's wash. The viewport scales in from under
  the trigger (150ms in, 100ms out) and moving between triggers slides the content; reduced motion
  keeps the fades.
- **Interface console:** text size, theme and the interface menu sit in one bordered group
  (`border`, `background` at 70%, `radius-lg`, 2px padding) so they read as one instrument.
- **Band icon buttons:** square, muted ink, 18px icons, hover and open fill `accent`; press scales
  to 0.94. Each has a tooltip and an accessible name.
- **Interface menu:** a dot in `selection` on its icon when any preference differs from the default.
- **Phone:** below `md` the nav opens in a sheet from the left: the lockup, the daily places as
  icon rows with their one line, then Tools and Admin as an accordion (the one holding the current
  page open), the current row on the lamp's wash, and Account and Sign out at the foot.

### Menus
One feel for every floating list: white (`popover`) on an 8px card with a hairline and
`shadow-float`, 4px inner padding, 6px rows 44px on touch and 32px with a mouse, highlighted rows on
`accent`, labels in `text-small` muted, separators in `rule`, check and radio marks in `selection`.
A menu scales from the trigger's corner (0.97 in, 0.98 out; never from the centre, never sliding),
150ms in and 100ms out. Every item has a leading icon in muted ink; a destructive item is red and
fills `destructive-soft` when highlighted.

### Tooltips
Inverted (`tip` ground), 4px radius, 4px by 8px, 12px / 500, at most 256px wide, 6px from the
trigger, below it by default, with an optional key hint. They open after 400ms on hover and at
once on keyboard focus; once one is open the next opens instantly with no animation. A tooltip
scales in from the trigger. It is never the only name: the control's accessible name always says
the same.

### Tabs
Underline tabs: 14px / 500 muted labels, the active one ink. One 2px indicator in `route` slides
under the active tab and takes its width (transform only), on a hairline `border`.

### Confirmations
Built on `AlertDialog` (`ConfirmDialog`, `TypedConfirmDialog`). The title asks a question ("Cancel
this job?", "Remove v1.4.0?"), one or two sentences say what happens, then Cancel (ghost, focused
first) and the verb. The verb is `destructive-solid` with a leading `Trash2` (`warn` reaction) when
it removes or stops something (`Ban` for a cancel), or the primary when it does not. A refusal from
the server shows inside the dialog in a `FormAlert`; while the request runs the confirm keeps its
label with the spinner and the dialog cannot be closed. Removing something that cannot be undone
and is named (a library, a version) asks for the name to be typed: the confirm stays visible but
inert, in a neutral fill, until the text matches, and Enter in the field confirms. The panel is
anchored near the top so a message arriving below never moves it.

### Data tables
DataTable v2 (`ui/data-table/`, after the free shadcnblocks `data-table1` and `data-table4` and
shadcn/ui's data-table guide) is the one way to show a list with many rows.

- **The view lives in the URL:** `q` (the global filter), each filter (`state=failed,queued`),
  `sort` (an API sort field, `-` for descending), `page` (from 2) and `size` (5, 20, 50 or 100;
  20 is left out). A new filter, sort or size goes back to page 1. The last size per table is
  remembered in this browser; the URL wins, and a link to page *n* without a size means 20. A
  route parses its view with `parseTableSearch` and `parseFacet` in `validateSearch`; the app
  router's `stringifySearch` writes a validated list back as `a,b`.
- **Server mode** (`source`): the API sorts, filters and pages. Every list of the app pages by
  offset (`paging: "offset"`, docs/rest-api.md "Jumping to a page"): page *n* is one request of
  `limit = size` and `offset = (n - 1) × size`, never with a cursor, so numbered jumps, Last and a
  link to page *n* each cost one request (and the pages on either side are fetched ahead).
  The API's offset stops at 10,000: a page past it is reached with Next or Previous, which go on
  by cursor from the page beside it (a link straight to it walks by cursor from row 10,000, in
  requests of at most 200 rows). A source without `paging: "offset"` walks the same way from the
  start and offers no jumps or Last.
- **Client mode** (`query`): a bounded list arrives in one request and is sorted, filtered,
  paged and counted in the browser; `maxRows` hides sizes above the list's cap; Last is offered.
- **A table inside another page** whose URL is not its own (a job's problems) uses
  `useLocalDataTable({ rows, … })`: the same model, its view kept in the component. When the page
  owns `q`, `qParam` names the key the search box writes (the articles table's `filter`). Writing
  the view keeps the URL's hash (a settings section stays where it is).
- **Filterable and sortable** only where the server filters and sorts (never a client filter over
  one server page). Enum filters are faceted multi-selects (an outline button with a count pill,
  a Popover with a Command list, counts per value in client mode); date filters are single presets.
  Active filters show as `Tag` chips (with a remove `IconButton`) and Clear all. A library filter
  is the `LibraryCombobox` (`variant="filter"`) in the toolbar, its value a `TableParam` chip. A
  narrowing parameter (`TableParam`: a library, a version, an owner) shows its value as is, in mono
  with `mono`; `format` names it instead when the URL holds an ID the page can put in words (the
  all-tokens owner chip shows the username once a row names it). The chip still removes the
  parameter itself.
- **Pagination bar:** "21–40 of 233", Rows per page, "Page 2 of 12", then First and Previous
  (`icon-sm` IconButtons), the numbered pages (at most seven slots: both ends, the shown page and
  its neighbours, "…" for the gaps; the shown one outlined with `aria-current="page"`, each named
  "Page 5"; from `sm` up, phones keep the arrows), then Next and Last. An end that cannot be passed
  is `aria-disabled` so focus stays; a live region says the page after a move; the table's top
  scrolls into view. In a list longer than the API's offset bound (more than 10,000 rows), Last
  and the numbers past page `lastJump` are `aria-disabled` and say why in their name and tooltip
  ("Last page (out of reach: jumps stop at page 501; go on with Next page)"), and a line under the
  bar says the same for touch screens.
- **States in the frame:** loading is skeleton rows at the page size, each cell in its column's
  shape (`meta.skeleton`: text, mono, pill, avatar, number, meter), shown after 150ms; while
  another page or view loads the shown rows stay, at 60% with `aria-busy`; empty and no-match keep
  the frame with a dashed border and the next step; an error is one sentence and Retry
  (`errorMessage` from `model.error`, the page query's failure; `retryLabel` when another Try
  again sits beside the table). A route's `pendingComponent` draws `DataTableSkeleton` (toolbar,
  real headers, skeleton rows per column shape, the pagination line).
- **Rows:** `aria-rowcount` and `aria-rowindex` place the page in the whole list. The
  `meta.priority` 1 cell (else the first) is the row's header (`<th scope="row">`). A dialog a row
  action opens returns focus to that row's kebab (`onCloseAutoFocus={restoreRowFocus}`), whether
  the menu was opened with the keyboard or the mouse. Below `md` rows
  become cards: the `meta.priority` 1 cell as the title, 2 and 3 under it with their column named
  for screen readers, the row menu at the right; the Columns menu is not offered there. Give
  every cell a reader needs to tell rows apart (the version, not only the library) a priority. Page changes swap rows at once; only rows that
  arrive on a refresh use `row-in`.
- **Cells** (`cells.tsx`): `RelativeTime` (`future` for an expiry: "in 12 days"), `VersionCell`,
  `LibraryCell` (title link, mono ID, `description` line from `lg`), `Person`, `StateBadge`,
  `Progress`, `Bytes`, `Count`, `Money`, `MonoCopy`, `Chips` (a few literals, the rest behind a
  "+N" popover; `look="pill"` for tags); literals in mono, figures tabular and at the end.

### Interface settings
Each preference is a row: label and description on the left (240px column from `md`), the control
on the right. Choices are segmented cards: the selected one takes the lamp's wash
(`selection-soft`) with a `selection` border. Switches are full-round, checked in `selection`.

### Library bullet and route strip
A 24 to 36px circle in the library's line colour with two white initials (12px / 600; 14px at the
large size), then the library's name, a 2px `route` rule at 60% that draws in, and the stops: a
version station (ring plus a mono ref) and a short SHA in muted mono.

### Motion
Motion explains state. It is never decoration. Durations and easing come from the tokens (listed in
the sidecar's `motion`), never from literals.

- **Press:** buttons scale to 0.97, band icons to 0.94. Nothing scales up on hover, and nothing
  bounces or overshoots: every curve is `--ease-out`.
- **Tooltips:** 125ms in (fade plus a 0.96 scale from the trigger), 120ms out.
- **Menus and popovers:** 150ms in (`--dur-menu`), 100ms out (`--dur-exit`), scaling from the
  trigger's corner.
- **Tabs and the nav underline:** the indicator slides or grows in 180ms (`--dur`).
- **Theme:** the icon turns over (a quarter turn with a cross-fade) and the page cross-fades for 180ms.
- **Route change:** the sheet cross-fades with a 4px rise (View Transitions, `page`). The band and
  frame stay still.
- **Lists and notices:** a new row fades in from 4px above (`row-in`); something that appears in
  place uses `reveal`.
- **Progress:** fills move with `transform: scaleX`. A job with no total yet shows the `sweep`.
- **Dialogs and sheets:** a dialog fades and zooms from 0.95 in 180ms; a sheet slides in 240ms.

Only transform and opacity animate. Exits are faster than entrances. Reduced motion (the
`data-reduce-motion` attribute: the person's choice first, the OS second) removes travel, zoom,
rotation and view transitions; what appears in place still fades, and busy indicators breathe
instead of spinning.

### Icons and motion
Every page and element gets a lucide icon where it helps people scan or act, and every icon inside
something pressable reacts in a way that says what the action does. The reactions live in
`src/app/icon-motion.css`; opt in with `data-icon-motion="<name>"` on the icon (or `motion` on an
`IconButton`, `motion` on a row action). Icons are always `aria-hidden`; the text or the
accessible name carries the meaning. The reaction plays when the control is hovered (where hover
exists), focused by keyboard, highlighted in a menu or pressed; it moves by `transform` only (the
one-off `draw` uses `clip-path`), at most 2px, in `--dur` on `--ease-out`; reduced motion turns all
of it off.

| Element | Icon | Notes |
|---|---|---|
| Page header (`PageHeader icon`) | the page's nav icon (LibraryBig, Search, FlaskConical, Activity, Cpu, Users, ScrollText; UserRound for Account) | in the hairline tile beside the title; not on auth pages |
| Section headings | one per section (Settings2, GitBranch, Tags, FolderTree, Share2; ShieldAlert for danger) | 16px, muted |
| Tabs | icon and label (KeyRound tokens, SlidersHorizontal interface, LogIn sign-in) | 16px |
| Buttons | a leading icon for every action (Plus add, Save, RefreshCw sync, Trash2 delete, Copy, Download, Upload, ExternalLink, LogIn / LogOut, Send, Check) | 16px |
| Menu items | every item has a leading icon | 16px, muted |
| State badges | succeeded CircleCheck, failed CircleX, running LoaderCircle (spins), queued Clock, cancelled Ban, skipped CircleSlash, warning TriangleAlert | 12px inside the pill |
| Empty states | one large muted icon above the sentence | 32px, no reaction |
| Alerts and toasts | CircleCheck success (`draw`), TriangleAlert warning, CircleAlert error (`alert`), Info | |
| Form fields | a leading icon only in search and filter inputs (Search) and on credentials (KeyRound) | |
| Links that leave the app | ExternalLink after the text | |
| Row links | ChevronRight at the row's end | |

| Reaction | Motion | Icons |
|---|---|---|
| `forward` | 2px right | ArrowRight, ChevronRight, LogIn, LogOut, Send, CornerDownRight |
| `back` | 2px left | ArrowLeft, ChevronLeft, Undo2 |
| `out` | 1.5px up and right | ExternalLink, ArrowUpRight, Share2 |
| `down` | 1.5px down | Download, ChevronsDown, ArrowDown |
| `up` | 1.5px up | Upload, ArrowUp |
| `turn` | a quarter turn | Plus, X (close, remove) |
| `cog` | 60° on hover, 180° while pressed | Settings, Settings2, SlidersHorizontal |
| `refresh` | 60° on hover, 180° pressed, turns while `aria-busy` | RefreshCw, RotateCcw, History |
| `tilt` | -10° | Search, Pencil, Tag, Tags, KeyRound, Filter, ListFilter, Languages |
| `pop` | scale 1.12, 0.9 pressed | Copy, Check, Star, Sparkles, Eye, Bookmark, CircleCheck in buttons |
| `warn` | one small swing, never a loop | Trash2, Ban, UserX, ShieldAlert, LogOut in destructive menus |
| `draw` | draws itself in once on arrival | Check and CircleCheck for "done" and in success toasts |
| `alert` | one nudge on arrival | CircleAlert and TriangleAlert in form alerts and error toasts |

Not animated: icons that only label (page headers, section headings, empty states, badges other
than "running") and the band's daily links (they move with their underline).

### Interface preferences
Stored in `localStorage` (`exactdocs-preferences`), applied to `<html>` before first paint by the
inline script in `index.html`, and synced to the account when signed in (GET/PUT
`/api/v1/account/preferences`, #487).

| Preference | Values | Applied as |
|---|---|---|
| Theme | light, dark, system | `.dark`, `color-scheme`, `data-theme` |
| Contrast | standard, more | `data-contrast="more"` |
| Text size | 90, 100, 110, 125, 150% | the root font size |
| Text spacing | standard, wide (WCAG 1.4.12: line 1.5, paragraphs 2em, letters 0.12em, words 0.16em) | `data-spacing="wide"` |
| Motion | system, reduced, full | `data-motion`, and `data-reduce-motion` when reduced either way |
| Font | default, hyperlegible, dyslexic, system | `data-font` |
| Underline links | on, off | `data-links="underline"` |
| Large targets | on, off | `data-targets="large"`: the `fine:` variant stops applying, so 44px stays |
| Show me on the leaderboard | on, off (default off) | nothing on the page: consent to be named on the people leaderboard (#510). Offered only while signed in, changeable only once the account's answer is read, and always taken from the account at sign-in (the browser's copy may be someone else's) |

Components read these through the `fine:`, `can-hover:`, `motion-safe:` and `motion-reduce:`
variants, never the raw media queries.

### Accessibility
WCAG 2.2 AA. Every interactive element has a visible 2px focus ring; targets are 44px on touch and
with large targets on. Text meets 4.5:1 in both themes and with more contrast. A Skip to content
link leads to `#main`; each page has one h1, focused on navigation. Status changes are announced
(`role="status"` or `role="alert"`); toasts duplicate an inline status and are never its only form.
Icon-only controls have accessible names; tooltips repeat them.

### States and feedback
- **Loading:** `Skeleton` bars at the size of the value, in the final layout, no pulse. A cold load
  waits 150ms before showing anything (`pending-in`). Every route with a loader has a
  `pendingComponent` that draws the page's skeleton in its final layout; tables draw skeleton rows.
- **Results:** a toast for an outcome that happened off-screen or after a dialog closed; an inline
  status line when it belongs to a field or row.
- **Errors:** inside the block that failed, one sentence on what failed and how to recover, and a
  Retry. `FormAlert` for forms, `StatusScreen` for a whole page.
- **Empty:** `EmptyState` keeps the block's frame and says what to do next, with the action.

### Named Rules
**Confirm with AlertDialog.** Every confirmation is an AlertDialog (`ConfirmDialog` or
`TypedConfirmDialog`): `role="alertdialog"`, Cancel focused first, Escape cancels, a click outside
does nothing, the verb in `destructive-solid` when it removes or stops something. Never an inline
"Are you sure?" row and never a plain Dialog.

**A context menu mirrors a visible menu.** Nothing is reachable by right-click alone: touch,
keyboard and new users would never find it. A row's context menu shows the same items as its
visible "More actions" menu, fed from one list (`RowActions`), and opens from the keyboard with
Shift+F10 or the Menu key.

## Do's and Don'ts

### Do:
- **Do** let the lamp mark only the one lit thing, through `route`, `route-soft`, `selection` and `ring`.
- **Do** put ink marks on the lamp's wash in light mode and let the lamp draw the marks in dark mode.
- **Do** use only the named tokens, sizes, durations and recipes; add to the tokens first.
- **Do** keep one primary button per screen and start every page with `PageHeader`.
- **Do** set literal text (versions, SHAs, paths, IDs, tokens, code) in JetBrains Mono.
- **Do** give every icon control an accessible name and a tooltip that repeats it.
- **Do** read interface preferences through the `fine:`, `can-hover:` and `motion-*` variants, and size everything in rem.
- **Do** animate transform and opacity only, with `--dur-*` and `--ease-out`.
- **Do** confirm with an AlertDialog and give every row action a visible menu as well as a context menu.
- **Do** keep a list's view (filters, sort, page, size) in the URL.

### Don't:
- **Don't** set the lamp yellow as text or as a thin mark on a light ground.
- **Don't** add a second accent hue, gradients or glows; line colours belong on library bullets only.
- **Don't** put `frame` behind content, or use navy in dark mode.
- **Don't** use the mascot's playfulness in the interface: no rounded display faces, cartoon icons or bouncy motion in the UI.
- **Don't** use raw colours, `text-[13px]`, the default `text-sm`, tracked capitals or ad hoc durations.
- **Don't** put a shadow on anything at rest, or any shadow but `shadow-float` on a floating layer.
- **Don't** animate a height, a width or `grid-template-rows`.
- **Don't** let a tooltip carry information the control's name does not.
- **Don't** use a dialog except for confirmations and for showing a secret once.
- **Don't** scale a button up on hover, or let anything bounce or overshoot.
- **Don't** give a chart a second hue for its series: `chart-series`, with `chart-highlight` for the one lit thing.
