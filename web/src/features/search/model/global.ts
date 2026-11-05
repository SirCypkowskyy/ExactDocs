import type { components } from "@/shared/lib/api-schema";
import { resultsNoun } from "./search";

export type GlobalResults = components["schemas"]["SearchAllResult"];
export type GlobalHit = components["schemas"]["LibrarySearchResultOut"];

/** `/owner/repo` as route params. */
export function splitLibrary(id: string): { owner: string; repo: string } {
  const [owner = "", repo = ""] = id.split("/").filter(Boolean);
  return { owner, repo };
}

/** How many chunks match in all: the narrowed library's own count, or every library's. */
export function totalMatches(data: GlobalResults, library: string | undefined): number {
  const facets = library ? data.libraries.filter((f) => f.library === library) : data.libraries;
  return facets.reduce((sum, f) => sum + f.matches, 0);
}

/** "3 results", "Showing 3 of 5", "Top 20 of 87": the visible count next to the facet totals. */
export function countLine(shown: number, total: number, complete: boolean): string {
  if (total <= shown) return resultsNoun(shown, complete);
  return `${complete ? "Showing" : "Top"} ${shown} of ${total}`;
}

/** The one sentence the live region announces once a result set settles. */
export function statusLine(
  shown: number,
  q: string,
  library: string | undefined,
  complete: boolean,
) {
  const what = shown === 0 ? "No results" : resultsNoun(shown, complete);
  return `${what} for “${q}” ${library ? `in ${library}` : "in all libraries"}`;
}
