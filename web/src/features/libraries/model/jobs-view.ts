import { textParam } from "@/shared/lib/list-sort";
import {
  parseChoice,
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/** The jobs list's view state: what the URL holds and what `GET /v1/jobs` is asked for. */
export const JOB_STATES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;
export const JOB_KINDS = [
  "import",
  "refresh",
  "reprocess",
  "retag",
  "rechunk",
  "collect",
  "embed",
  "push",
] as const;
/** Who queued a job: the instance on its own (`auto`) or a request (`manual`). */
export const JOB_ORIGINS = ["manual", "auto"] as const;
/** "Queued within" presets of the date filter. */
export const QUEUED_WITHIN = ["24h", "7d", "30d"] as const;

export type JobState = (typeof JOB_STATES)[number];
export type JobKind = (typeof JOB_KINDS)[number];
export type JobOrigin = (typeof JOB_ORIGINS)[number];
export type QueuedWithin = (typeof QUEUED_WITHIN)[number];

/** The jobs table (DataTable v2): sortable by the API's fields, newest first by default. */
export const JOBS_TABLE: TableConfig = {
  id: "jobs",
  sortFields: ["id", "created_at", "state", "kind", "library"],
  defaultSort: "-id",
};

export interface JobsView extends TableSearch {
  state?: JobState[] | undefined;
  kind?: JobKind[] | undefined;
  origin?: JobOrigin[] | undefined;
  created?: QueuedWithin | undefined;
  /** A library ID, `/owner/repo`. */
  library?: string | undefined;
  /** An exact ref. */
  version?: string | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseJobsView(search: Record<string, unknown>): JobsView {
  const library = textParam(search.library);
  return {
    ...parseTableSearch(search, JOBS_TABLE),
    state: parseFacet(search.state, JOB_STATES),
    kind: parseFacet(search.kind, JOB_KINDS),
    origin: parseFacet(search.origin, JOB_ORIGINS),
    created: parseChoice(search.created, QUEUED_WITHIN),
    library: library && /^\/[^/]+\/[^/]+$/.test(library) ? library : undefined,
    version: textParam(search.version),
  };
}

const WITHIN_MS: Record<QueuedWithin, number> = {
  "24h": 24 * 3_600_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
};

/** What `GET /v1/jobs` filters and sorts by: the view without its page and size. */
export interface JobsFilters {
  q?: string;
  state?: readonly string[];
  kind?: readonly string[];
  origin?: readonly string[];
  library?: string;
  version?: string;
  created_after?: string;
  sort?: string;
}

/**
 * The view's filters for the API. A "queued within" preset counts back from `now` rounded down to
 * the minute, so the route's loader and the page ask for the same thing.
 */
export function jobsFilters(view: JobsView, now: number): JobsFilters {
  const minute = Math.floor(now / 60_000) * 60_000;
  return {
    ...(view.q && { q: view.q }),
    ...(view.state && { state: view.state }),
    ...(view.kind && { kind: view.kind }),
    // Both origins are every job: no filter at all.
    ...(view.origin && view.origin.length < JOB_ORIGINS.length && { origin: view.origin }),
    ...(view.library && { library: view.library }),
    ...(view.version && { version: view.version }),
    ...(view.created && {
      created_after: new Date(minute - WITHIN_MS[view.created]).toISOString(),
    }),
    ...(view.sort && { sort: view.sort }),
  };
}

/** The query string of `GET /v1/jobs` for some filters and one request's `limit` and offset or cursor. */
export function jobsParams(
  filters: JobsFilters,
  limit: number,
  cursor?: string | null,
  offset?: number,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (filters.q) p.set("q", filters.q);
  for (const state of filters.state ?? []) p.append("state", state);
  for (const kind of filters.kind ?? []) p.append("kind", kind);
  for (const origin of filters.origin ?? []) p.append("origin", origin);
  if (filters.library) p.set("library", filters.library);
  if (filters.version) p.set("version", filters.version);
  if (filters.created_after) p.set("created_after", filters.created_after);
  if (filters.sort) p.set("sort", filters.sort);
  // A page by offset (0 to 10000) or after a cursor, never both (422 `cursor_with_offset`).
  if (offset !== undefined) p.set("offset", String(offset));
  else if (cursor) p.set("cursor", cursor);
  return p.toString();
}
