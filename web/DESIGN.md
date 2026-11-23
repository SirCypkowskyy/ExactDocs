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
- **Reader roles** (`hl-*`, `tint-*`): syntax roles in code and callout tints in articles (reader
  only). Each syntax role is 4.5:1+ on `code`.

### Dark
The mole's own colours: the frame (#0e0e10) is darker than the sheet (#17171a), text is cream
(#f3f1ec) with a grey of #a6a6ae, the primary button inverts to cream, and the lamp draws every mark
that must read (10:1+ on the sheet). `route-soft` becomes a dim amber (#3b3320). Dark is true
anthracite, never navy.

### More contrast
`data-contrast="more"` darkens `muted-foreground` and strengthens `border`, `rule`, `input` and the
frame in both themes. Nothing else changes.

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
| `Button` | `ui/button.tsx` | `default` (the one primary), `outline` (secondary), `ghost` (toolbar), `destructive` (outlined), `destructive-solid` (only inside a confirmation). Sizes `default`, `sm`, `icon`. |
| `Input`, `Field`, `TextareaField`, `SelectField` | `ui/` | Label above (14 / 500), help text below in `text-small`, errors announced. Built on the `control` recipe. |
| `trigger` recipe | `recipes.ts` | A button that opens a picker (versions, files). |
| `pill` + `pillTone` | `recipes.ts` | Status beside a value. One status mark per row. Tones: neutral, route (the lamp's wash), positive, warning, destructive. |
| `codeWell`, `kbd` | `recipes.ts` | Literal text (tokens, snippets) and key hints. |
| `LibraryBullet`, `VersionStation`, `Commit`, `RouteStrip` | `ui/route.tsx` | Use them wherever a library, version or commit is named. |
| `Page`, `PageHeader`, `Section`, `EmptyState` | `ui/page.tsx` | The page frame. |
| `Mark`, `Wordmark` | `ui/wordmark.tsx` | The small mole (28px) and the lockup; light and dark files swap with the theme. |
| `TextSizeControl`, `ThemeButton`, `InterfaceMenu` | `ui/interface-controls.tsx` | The band's interface controls (#486). |
| `InterfaceSettings` | `ui/interface-settings.tsx` | Account → Interface: every preference, with a reset. |
| `Tooltip` | `ui/tooltip.tsx` | A short name or a key for an icon control. |
| `Tabs` | `ui/tabs.tsx` | Underline tabs with one sliding indicator. |
| `Dialog`, `Sheet`, `DropdownMenu`, `DataTable` | `ui/` | shadcn on these tokens. A dialog only for confirmations and for showing a secret once. |
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
A menu scales from the trigger's corner (0.97 in, 0.98 out; never from the centre, never sliding).

### Tooltips
Inverted (`tip` ground), 4px radius, 4px by 8px, 12px / 500, at most 256px wide, 6px from the
trigger, below it by default, with an optional key hint. They open after 400ms on hover and at
once on keyboard focus; once one is open the next opens instantly with no animation. A tooltip
scales in from the trigger. It is never the only name: the control's accessible name always says
the same.

### Tabs
Underline tabs: 14px / 500 muted labels, the active one ink. One 2px indicator in `route` slides
under the active tab and takes its width (transform only), on a hairline `border`.

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

- **Press:** buttons scale to 0.97, band icons to 0.94.
- **Tooltips:** 125ms in (fade plus a 0.96 scale from the trigger), 120ms out.
- **Menus:** 150ms in, out faster, scaling from the trigger's corner.
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
  waits 150ms before showing anything.
- **Results:** a toast for an outcome that happened off-screen or after a dialog closed; an inline
  status line when it belongs to a field or row.
- **Errors:** inside the block that failed, one sentence on what failed and how to recover, and a
  Retry. `FormAlert` for forms, `StatusScreen` for a whole page.
- **Empty:** `EmptyState` keeps the block's frame and says what to do next, with the action.

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
