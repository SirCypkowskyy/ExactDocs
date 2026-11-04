import { normalizeQuery } from "@/shared/lib/search-query";
import { parseTags } from "@/shared/lib/tags";
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
    // What the API would refuse (tags over 100 characters, a query over 1000) never reaches a request.
    tags: parseTags(text(raw.tags)).join(",") || undefined,
    q: normalizeQuery(text(raw.q)),
    match: raw.match === "all" ? "all" : undefined,
  };
}
