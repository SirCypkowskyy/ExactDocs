import { oneOf, pickSort, textParam } from "@/shared/lib/list-sort";

/** The versions table's view: what the settings URL holds and what `GET .../versions` is asked for. */
export const REF_KINDS = ["tag", "branch", "commit"] as const;
const SORT_FIELDS = ["ref", "kind", "imported_at", "origin"];

export interface VersionsView {
  q?: string | undefined;
  kind?: (typeof REF_KINDS)[number] | undefined;
  sort?: string | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export const parseVersionsView = (search: Record<string, unknown>): VersionsView => ({
  q: textParam(search.q),
  kind: oneOf(search.kind, REF_KINDS),
  sort: pickSort(search.sort, SORT_FIELDS),
});

export const versionsFiltered = (v: VersionsView) => Boolean(v.q || v.kind);

/** The query string of `GET /v1/libraries/{owner}/{repo}/versions` for a view and a cursor. */
export function versionsParams(view: VersionsView, cursor?: string | null): string {
  const p = new URLSearchParams({ limit: "50" });
  if (view.q) p.set("q", view.q);
  if (view.kind) p.set("kind", view.kind);
  if (view.sort) p.set("sort", view.sort);
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}
