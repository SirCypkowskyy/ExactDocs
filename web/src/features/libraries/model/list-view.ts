/** The libraries list's view state: what the URL holds and what the API is asked for. */
const SORT_FIELDS = ["title", "last_imported_at", "version_count"] as const;

export interface ListView {
  q?: string | undefined;
  /** An API `sort` value: a field, `-` in front for descending. */
  sort?: string | undefined;
  ai?: "on" | "off" | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseListView(search: Record<string, unknown>): ListView {
  const q = typeof search.q === "string" ? search.q.trim().slice(0, 256) : "";
  const sort = typeof search.sort === "string" ? search.sort : "";
  const field = sort.replace(/^-/, "");
  return {
    q: q || undefined,
    sort: (SORT_FIELDS as readonly string[]).includes(field) ? sort : undefined,
    ai: search.ai === "on" || search.ai === "off" ? search.ai : undefined,
  };
}

export const isFiltered = (v: ListView) => Boolean(v.q || v.ai);

/** The query string of `GET /v1/libraries` for a view and a page cursor. */
export function listParams(view: ListView, cursor?: string | null): string {
  const p = new URLSearchParams({ limit: "50" });
  if (view.q) p.set("q", view.q);
  if (view.sort) p.set("sort", view.sort);
  if (view.ai) p.set("ai_enabled", String(view.ai === "on"));
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}
