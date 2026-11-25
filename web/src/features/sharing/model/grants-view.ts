import {
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/** The grants table's view: what the sharing URL holds and what `GET .../grants` is asked for. */
export const GRANT_KINDS = ["user", "group"] as const;
export const GRANT_ROLES = ["viewer", "contributor", "admin", "creator"] as const;

type GrantKind = (typeof GRANT_KINDS)[number];
type GrantRole = (typeof GRANT_ROLES)[number];

/** The grants table (DataTable v2): the API sorts by these, users then groups by default. */
export const GRANTS_TABLE: TableConfig = {
  id: "grants",
  sortFields: ["kind", "subject", "role"],
  defaultSort: "kind",
};

export interface SharingView extends TableSearch {
  kind?: GrantKind[] | undefined;
  role?: GrantRole[] | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export const parseSharingView = (search: Record<string, unknown>): SharingView => ({
  ...parseTableSearch(search, GRANTS_TABLE),
  kind: parseFacet(search.kind, GRANT_KINDS),
  role: parseFacet(search.role, GRANT_ROLES),
});

/** What `GET .../grants` filters and sorts by: the view without its page and size. */
export interface GrantsFilters {
  q?: string;
  kind?: readonly string[];
  role?: readonly string[];
  sort?: string;
}

export const grantsFilters = (view: SharingView): GrantsFilters => ({
  ...(view.q && { q: view.q }),
  ...(view.kind && { kind: view.kind }),
  ...(view.role && { role: view.role }),
  ...(view.sort && { sort: view.sort }),
});

/** The query string of `GET /v1/libraries/{owner}/{repo}/grants` for some filters and a page. */
export function grantsParams(
  filters: GrantsFilters,
  limit: number,
  cursor?: string | null,
  offset?: number,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (filters.q) p.set("q", filters.q);
  for (const kind of filters.kind ?? []) p.append("kind", kind);
  for (const role of filters.role ?? []) p.append("role", role);
  if (filters.sort) p.set("sort", filters.sort);
  // A page by offset (0 to 10000) or after a cursor, never both (422 `cursor_with_offset`).
  if (offset !== undefined) p.set("offset", String(offset));
  else if (cursor) p.set("cursor", cursor);
  return p.toString();
}
