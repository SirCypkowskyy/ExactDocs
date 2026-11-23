import {
  parseChoice,
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/** The versions table's view: what the settings URL holds and what `GET .../versions` is asked for. */
export const REF_KINDS = ["tag", "branch", "commit"] as const;
export const VERSION_ORIGINS = ["manual", "auto"] as const;
/** "Imported within" presets of the date filter. */
export const IMPORTED_WITHIN = ["24h", "7d", "30d"] as const;

type RefKind = (typeof REF_KINDS)[number];
type VersionOrigin = (typeof VERSION_ORIGINS)[number];
type ImportedWithin = (typeof IMPORTED_WITHIN)[number];

/** The versions table (DataTable v2): sortable by the API's fields, by ref unless told. */
export const VERSIONS_TABLE: TableConfig = {
  id: "versions",
  sortFields: ["ref", "kind", "imported_at", "origin"],
  defaultSort: "ref",
};

export interface VersionsView extends TableSearch {
  kind?: RefKind[] | undefined;
  origin?: VersionOrigin[] | undefined;
  imported?: ImportedWithin | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export const parseVersionsView = (search: Record<string, unknown>): VersionsView => ({
  ...parseTableSearch(search, VERSIONS_TABLE),
  kind: parseFacet(search.kind, REF_KINDS),
  origin: parseFacet(search.origin, VERSION_ORIGINS),
  imported: parseChoice(search.imported, IMPORTED_WITHIN),
});

const WITHIN_MS: Record<ImportedWithin, number> = {
  "24h": 24 * 3_600_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
};

/** What `GET .../versions` filters and sorts by: the view without its page and size. */
export interface VersionsFilters {
  q?: string;
  kind?: readonly string[];
  origin?: readonly string[];
  imported_after?: string;
  sort?: string;
}

/**
 * The view's filters for the API. An "imported within" preset counts back from `now` rounded down
 * to the minute, so every render within a minute asks for the same thing.
 */
export function versionsFilters(view: VersionsView, now: number): VersionsFilters {
  const minute = Math.floor(now / 60_000) * 60_000;
  return {
    ...(view.q && { q: view.q }),
    ...(view.kind && { kind: view.kind }),
    ...(view.origin && { origin: view.origin }),
    ...(view.imported && {
      imported_after: new Date(minute - WITHIN_MS[view.imported]).toISOString(),
    }),
    ...(view.sort && { sort: view.sort }),
  };
}

/** The query string of `GET /v1/libraries/{owner}/{repo}/versions` for some filters and one request. */
export function versionsParams(
  filters: VersionsFilters,
  limit: number,
  cursor?: string | null,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (filters.q) p.set("q", filters.q);
  for (const kind of filters.kind ?? []) p.append("kind", kind);
  for (const origin of filters.origin ?? []) p.append("origin", origin);
  if (filters.imported_after) p.set("imported_after", filters.imported_after);
  if (filters.sort) p.set("sort", filters.sort);
  // #509: once the endpoint takes `offset`, the source asks with it here instead of a cursor.
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}
