# Design review records (#427)

The review rounds of the web redesign, kept in the repository (they were only in PR text before).
The system they review is `DESIGN.md`; its machine-readable form is `.impeccable/design.json`.
Before and after screenshots of rounds 1 and 2 are linked from PR #443; round 3 screenshots are the
output of `e2e/loop.spec.ts` (`just e2e`, written to `e2e/shots/`, also uploaded by CI).

## Round 1: before the redesign (PR #443)

Impeccable `critique` (dual review plus detector) and design-taste `lint` and `inspect --app`, at
1440, 768 and 390 px. Nielsen score 26/40.

| Area | What read as generic or was broken | Resolved in |
|---|---|---|
| Shell | five content widths; phone header on two rows; browser-locale dates; loose Sign out | #443 |
| Sign-in and setup | stock split screen with a quote the instance never imported | #443 |
| Libraries | mono path led, title small and grey; 60 % empty right side | #443 |
| Library page | two-line start state, tree twice on a phone, SHA buried | #443 |
| Reader | seven metadata pieces, jargon labels, no table of contents, 2.75em heading gaps | #443 |
| Search results | raw Markdown snippets, no ellipsis, faint tags | #443 |
| Settings, AI, users, account, add library, global search | long page with five Save buttons, "Not set" with no next step, no MCP template | #448 |
| Feedback | no toasts, pulsing skeletons | #443, #448 |

## Round 2: after pages 1 (#443) and pages 2 (#448)

Detector reruns and single-context design review; axe on 12 pages, light and dark, 1440 and 390 px:
0 violations. It left five items open, closed in round 3:

| Open after round 2 | Closed by |
|---|---|
| reader used 9 to 17 px text | one scale: 12, 13, 14, 17, 20, 22, 30 px, checked by e2e |
| search tag pills rendered too large | root cause was `tailwind-merge` reading `text-small` as a colour; `cn()` now knows the size names (`utils.test.ts`) |
| library page stacked about 220 px of controls at 390 px | 92 px less from the band to the first file (450 to 358 px); e2e budget 380 px |
| `hero-void` on Libraries with one library | judged honest data; left |
| snippet table rows keep inline backticks | left (a snippet is a glimpse) |

## Round 3: finish review, motion review, documenter (this PR)

Run with the impeccable `finish-reviewer`, `motion-reviewer` and `documenter` agents on the final
build. The finish reviewer had no browser and read the Playwright full-page captures; the motion
reviewer read `motion-capture` filmstrips. The capture tool cannot type a password, so the only
interaction it could capture was the header theme menu on the first-run page (normal and reduced
motion). Every other motion was reviewed from the CSS and class usage only.

### Finish review

First disposition `fix`, eight findings. After the fixes the verdict pass scored:

| # | Finding | Result |
|---|---|---|
| 1 | playground results were stacked cards with a second renderer | ruled rows like search; sharing the search `Snippet` is blocked by the no cross-feature import rule, left |
| 2 | AI usage table clipped on a phone | money and tokens split into two lines, narrower table; still scrolls (focusable) below `md`, left |
| 3 | AI roles repeated "Not set" four times | resolved |
| 4 | side stripe on quotes; snippet table lines wrap | stripe replaced by a tinted block; wrapping kept on purpose (a scrolling `pre` failed axe) |
| 5 | account had no description, role case differed | resolved |
| 6 | library landing repeated the commit, no orientation data | station line removed, heading resized; orientation facts (article count, top tags) not added: new feature, out of scope |
| 7 | token secret wrapped with an orphan character | set at 12 px so it fits |
| 8 | off-scale sizes, literal durations and easings | resolved, including `sheet.tsx` |

### Motion review

First disposition `fix`. Captured defect: the menu's zoom pivot slid from the centre to the corner
because `duration-*` left `transition-property: all`; fixed with `transition-none` on every popup
(verified in the recapture: right edge and top fixed from the first frame). Static findings fixed:
easing and durations off the tokens, `.rise` over budget (now 240 ms, 4 px), press scale 0.95 to
0.97, missing `motion-reduce` on two progress bits, pure fades lost under reduced motion (now kept
as opacity-only). The earlier `grid-template-rows` disclosures were replaced by `reveal` (fade and
4 px rise). Left open: `route-draw` and `row-in` play on every result row when results arrive (N
simultaneous 180 to 240 ms entrances; `route-draw` is a `scaleX`). Not gated to the route change.

### Documenter

`DESIGN.md` regenerated in the Stitch format with the existing prose kept, and
`.impeccable/design.json` written. Noted drift left: `prose.css` still spells the easing curve
instead of using `var(--ease-out)`.

## Measurements

Bundle size, one definition (`scripts/bundle-size.mjs`, entry JS is everything `index.html` loads,
gzip, kB):

| Commit | Entry JS | All JS | CSS |
|---|---|---|---|
| before the redesign (#436, `7c9cb7a`) | 204.0 | 332.5 | 14.4 |
| before #443 (`98adc56`) | 222.0 | 350.2 | 17.6 |
| after #443 | 221.3 | 349.5 | 17.6 |
| before #448 | 222.9 | 355.5 | 17.7 |
| after #448 (develop) | 224.9 | 361.0 | 17.9 |
| this PR | 224.9 | 361.2 | 17.4 |

Large libraries (`e2e/loop.spec.ts`, production bundle in Chromium, synthetic API answers, Apple
silicon laptop, headless): 300 libraries ready in 0.3 to 0.6 s, longest task 80 to 300 ms, scroll
frames p95 17 ms; a 2,100-row file tree (21 pages of one flat folder) scroll frames p95 17 ms,
longest task 80 to 580 ms while paging. The tree rows use `content-visibility: auto`; row building
for 7,000 articles is a unit test with a 500 ms budget.
