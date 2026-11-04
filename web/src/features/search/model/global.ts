import type { components } from "@/shared/lib/api-schema";

export type GlobalResults = components["schemas"]["SearchAllResult"];
export type GlobalHit = components["schemas"]["LibrarySearchResultOut"];

/** `/owner/repo` as route params. */
export function splitLibrary(id: string): { owner: string; repo: string } {
  const [owner = "", repo = ""] = id.split("/").filter(Boolean);
  return { owner, repo };
}
