import { useSyncExternalStore } from "react";
import { usePreferences } from "./preferences";

const media = (query: string) =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(query)
    : null;

/**
 * Whether a media query matches now; re-renders when it changes. Without `matchMedia` (a test
 * environment, the server) it is false, so the desktop layout is the fallback.
 */
function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = media(query);
      list?.addEventListener("change", onChange);
      return () => list?.removeEventListener("change", onChange);
    },
    () => media(query)?.matches ?? false,
    () => false,
  );
}

/**
 * Below Tailwind's `md` (48rem): the phone layout. Like the `md:` variant (styles.css, #576) it
 * follows the text size: at 150% the phone layout lasts up to 72 of the browser's rem.
 * shortcut: a media query counts a classic scrollbar and the container query doesn't, so in a
 * 15 px band at the breakpoint the two can disagree; measure <body> if that ever shows.
 */
export function usePhoneLayout(): boolean {
  const { prefs } = usePreferences();
  return useMediaQuery(`(max-width: ${(48 * prefs.text_scale) / 100 - 0.01}rem)`);
}
