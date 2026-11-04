import type { BrowseSearch } from "./browse";

const text = (value: unknown): string | undefined => {
  // The router parses `?version=2` as the number 2: keep what the user wrote, as text.
  if (typeof value === "number") return String(value);
  return typeof value === "string" && value !== "" ? value : undefined;
};

/** Reads the URL's search: unknown keys are dropped, anything but text is ignored. */
export function parseSearch(raw: Record<string, unknown>): BrowseSearch {
  return {
    version: text(raw.version),
    path: text(raw.path),
    tags: text(raw.tags),
    q: text(raw.q)?.trim() || undefined,
    match: raw.match === "all" ? "all" : undefined,
  };
}
