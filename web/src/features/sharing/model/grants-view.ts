import { oneOf, pickSort, textParam } from "@/shared/lib/list-sort";

/** The grants table's view: what the sharing URL holds and what `GET .../grants` is asked for. */
export const GRANT_KINDS = ["user", "group"] as const;
export const GRANT_ROLES = ["viewer", "contributor", "admin", "creator"] as const;
const SORT_FIELDS = ["kind", "subject", "role"];

export interface SharingView {
  q?: string | undefined;
  kind?: (typeof GRANT_KINDS)[number] | undefined;
  role?: (typeof GRANT_ROLES)[number] | undefined;
  /** An API `sort` value: a field, `-` in front for descending. */
  sort?: string | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export const parseSharingView = (search: Record<string, unknown>): SharingView => ({
  q: textParam(search.q),
  kind: oneOf(search.kind, GRANT_KINDS),
  role: oneOf(search.role, GRANT_ROLES),
  sort: pickSort(search.sort, SORT_FIELDS),
});

export const sharingFiltered = (v: SharingView) => Boolean(v.q || v.kind || v.role);

/** The query string of `GET /v1/libraries/{owner}/{repo}/grants` for a view and a cursor. */
export function grantsParams(view: SharingView, cursor?: string | null): string {
  const p = new URLSearchParams({ limit: "50" });
  if (view.q) p.set("q", view.q);
  if (view.kind) p.set("kind", view.kind);
  if (view.role) p.set("role", view.role);
  if (view.sort) p.set("sort", view.sort);
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}
