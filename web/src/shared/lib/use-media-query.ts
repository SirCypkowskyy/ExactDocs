import { useSyncExternalStore } from "react";

const media = (query: string) =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(query)
    : null;

/**
 * Whether a media query matches now; re-renders when it changes. Without `matchMedia` (a test
 * environment, the server) it is false, so the desktop layout is the fallback.
 */
export function useMediaQuery(query: string): boolean {
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

/** Below Tailwind's `md` (48rem): the phone layout. */
export const PHONE_QUERY = "(max-width: 47.99rem)";
