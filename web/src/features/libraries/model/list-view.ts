import {
  parseChoice,
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/** The libraries list's view state: what the URL holds and what `GET /v1/libraries` is asked for. */

/** AI allowed or turned off (`ai_enabled`). */
export const AI_CHOICES = ["on", "off"] as const;
/** With an imported version or without one (`has_versions`). */
export const VERSION_CHOICES = ["some", "none"] as const;
/** Last imported within a period (`updated_after`), or longer ago than 30 days (`updated_before`). */
export const IMPORTED_WITHIN = ["24h", "7d", "30d", "older"] as const;

/** The state of a library's latest sync (its newest import or refresh job), `sync_state`. */
export const SYNC_STATES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;

export type ImportedWithin = (typeof IMPORTED_WITHIN)[number];

/** The libraries table (DataTable v2): sortable by the API's fields; the API sorts by ID unless told. */
export const LIBRARIES_TABLE: TableConfig = {
  id: "libraries",
  sortFields: ["id", "title", "last_imported_at", "version_count"],
};

export interface ListView extends TableSearch {
  ai?: (typeof AI_CHOICES)[number] | undefined;
  versions?: (typeof VERSION_CHOICES)[number] | undefined;
  imported?: ImportedWithin | undefined;
  sync?: (typeof SYNC_STATES)[number][] | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseListView(search: Record<string, unknown>): ListView {
  return {
    ...parseTableSearch(search, LIBRARIES_TABLE),
    ai: parseChoice(search.ai, AI_CHOICES),
    versions: parseChoice(search.versions, VERSION_CHOICES),
    imported: parseChoice(search.imported, IMPORTED_WITHIN),
    sync: parseFacet(search.sync, SYNC_STATES),
  };
}

const DAY = 86_400_000;
const WITHIN_MS: Record<ImportedWithin, number> = {
  "24h": DAY,
  "7d": 7 * DAY,
  "30d": 30 * DAY,
  older: 30 * DAY,
};

/** What `GET /v1/libraries` filters and sorts by: the view without its page and size. */
export interface ListFilters {
  q?: string;
  sort?: string;
  ai_enabled?: boolean;
  has_versions?: boolean;
  updated_after?: string;
  updated_before?: string;
  sync_state?: readonly string[];
}

/**
 * The view's filters for the API. A period counts back from `now` rounded down to the minute, so
 * the route's loader and the page ask for the same thing.
 */
export function listFilters(view: ListView, now: number): ListFilters {
  const minute = Math.floor(now / 60_000) * 60_000;
  const since = view.imported && new Date(minute - WITHIN_MS[view.imported]).toISOString();
  return {
    ...(view.q && { q: view.q }),
    ...(view.sort && { sort: view.sort }),
    ...(view.ai && { ai_enabled: view.ai === "on" }),
    ...(view.versions && { has_versions: view.versions === "some" }),
    ...(view.sync && { sync_state: view.sync }),
    ...(since &&
      (view.imported === "older" ? { updated_before: since } : { updated_after: since })),
  };
}

/** The query string of `GET /v1/libraries` for some filters and one request's `limit` and offset or cursor. */
export function listParams(
  filters: ListFilters,
  limit: number,
  cursor?: string | null,
  offset?: number,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (filters.q) p.set("q", filters.q);
  if (filters.sort) p.set("sort", filters.sort);
  if (filters.ai_enabled !== undefined) p.set("ai_enabled", String(filters.ai_enabled));
  if (filters.has_versions !== undefined) p.set("has_versions", String(filters.has_versions));
  if (filters.updated_after) p.set("updated_after", filters.updated_after);
  if (filters.updated_before) p.set("updated_before", filters.updated_before);
  for (const state of filters.sync_state ?? []) p.append("sync_state", state);
  // A page by offset (0 to 10000) or after a cursor, never both (422 `cursor_with_offset`).
  if (offset !== undefined) p.set("offset", String(offset));
  else if (cursor) p.set("cursor", cursor);
  return p.toString();
}
