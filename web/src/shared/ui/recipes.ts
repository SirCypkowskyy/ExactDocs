/*
 * Shared class recipes (DESIGN.md, Components). A component that needs one of these looks imports
 * it from here instead of writing its own class string, so every input, picker, code well and
 * keyboard hint in the app is the same object.
 */

/** Text inputs, textareas and native selects: white on the sheet, a control border, a soft ring on focus. */
export const control =
  "w-full rounded-md border border-input bg-background text-section outline-none transition-[border-color,box-shadow] duration-(--dur-fast) hover:border-muted-foreground/45 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 aria-invalid:border-destructive aria-invalid:ring-destructive/20 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground fine:text-body";

/** Single-line control height: 44px on touch, 36px with a fine pointer. */
export const controlHeight = "h-11 fine:h-9";

/** A native <select>: the control plus room for its chevron (render <SelectChevron/> beside it). */
export const select = `${control} ${controlHeight} cursor-pointer appearance-none pr-9 pl-3`;

/** A button that opens a picker (version, files): looks like a control, acts like a button. */
export const trigger =
  "flex h-11 min-w-0 cursor-pointer items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-body outline-none transition-[border-color,background-color,scale] duration-(--dur-fast) hover:border-muted-foreground/45 focus-visible:ring-2 focus-visible:ring-ring motion-safe:active:scale-[0.99] aria-expanded:border-ring fine:h-9";

/** Monospace text shown as it is: a token, a config snippet, server output. */
export const codeWell =
  "rounded-md bg-code px-3 py-2.5 font-mono text-mono leading-5 text-foreground [overflow-wrap:anywhere]";

/** A keyboard key hint ("/", "↓"). */
export const kbd =
  "inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-background px-1 font-mono text-small text-muted-foreground";

/** A small pill: a status or a count beside a value. Pair with a tone from `pillTone`. */
export const pill =
  "inline-flex h-5 flex-none items-center gap-1 rounded-full px-2 text-small font-medium whitespace-nowrap";

export const pillTone = {
  neutral: "bg-secondary text-muted-foreground",
  route: "bg-route-soft text-foreground",
  positive: "bg-positive-soft text-positive-ink",
  warning: "bg-warning-soft text-warning-ink",
  destructive: "bg-destructive-soft text-destructive-ink",
} as const;

/** A section of a page: its heading, then its content. */
export const sectionHeading = "text-section font-semibold [scroll-margin-top:5rem]";

/** The scrim behind a dialog or confirmation: fades in 180 ms, out faster. */
export const dialogOverlay =
  "fixed inset-0 z-50 bg-overlay transition-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:duration-(--dur) data-[state=open]:ease-(--ease-out) data-[state=closed]:duration-(--dur-fast)";

/**
 * A dialog's panel, centred (a modal is not anchored to a trigger): 12 px corners, fades and zooms
 * from 0.95 in 180 ms, leaves faster; reduced motion keeps only the fade.
 */
export const dialogPanel =
  "fixed top-1/2 left-1/2 z-50 max-sm:top-4 max-sm:translate-y-0 max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-border bg-card p-6 text-card-foreground shadow-float outline-none transition-none data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-safe:data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 motion-safe:data-[state=closed]:zoom-out-95 data-[state=open]:duration-(--dur) data-[state=open]:ease-(--ease-out) data-[state=closed]:duration-(--dur-fast)";
