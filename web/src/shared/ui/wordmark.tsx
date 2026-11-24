import { cn } from "@/shared/lib/utils";

/*
 * The ExactDocs sign: the mole with a headlamp who brings you exactly the page you asked for
 * (web/public/brand, built with the logo-design skill; DESIGN.md, Brand). The wordmark is set in
 * Bricolage Grotesque 650 and outlined, so it needs no font. Light and dark artwork are separate
 * files: on dark grounds the mole carries a cream edge so it does not disappear.
 */

/** The mole alone, at band size (24-40 px): the small-size cut without the page. */
export function Mark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex size-7 flex-none", className)} aria-hidden="true">
      <img
        src="/brand/exactdocs-mark-small.svg"
        alt=""
        className="size-full dark:hidden"
        draggable={false}
      />
      <img
        src="/brand/exactdocs-mark-small-on-dark.svg"
        alt=""
        className="hidden size-full dark:block"
        draggable={false}
      />
    </span>
  );
}

/** Mole and name together, as the band and the auth pages show them. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex h-8 flex-none items-center", className)}>
      <img
        src="/brand/exactdocs-lockup-light.svg"
        alt="ExactDocs"
        className="h-full w-auto dark:hidden"
        draggable={false}
      />
      <img
        src="/brand/exactdocs-lockup-dark.svg"
        alt="ExactDocs"
        className="hidden h-full w-auto dark:block"
        draggable={false}
      />
    </span>
  );
}
