import { oneOf, pickSort, textParam } from "@/shared/lib/list-sort";

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
const SORT_FIELDS = ["id", "created_at", "state", "kind", "library"];

export interface JobsView {
  q?: string | undefined;
  state?: (typeof JOB_STATES)[number] | undefined;
  kind?: (typeof JOB_KINDS)[number] | undefined;
  /** A library ID, `/owner/repo`. */
  library?: string | undefined;
  sort?: string | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseJobsView(search: Record<string, unknown>): JobsView {
  const library = textParam(search.library);
  return {
    q: textParam(search.q),
    state: oneOf(search.state, JOB_STATES),
    kind: oneOf(search.kind, JOB_KINDS),
    library: library && /^\/[^/]+\/[^/]+$/.test(library) ? library : undefined,
    sort: pickSort(search.sort, SORT_FIELDS),
  };
}

export const jobsFiltered = (v: JobsView) => Boolean(v.q || v.state || v.kind || v.library);

/** The query string of `GET /v1/jobs` for a view and a page cursor. */
export function jobsParams(view: JobsView, cursor?: string | null): string {
  const p = new URLSearchParams({ limit: "50" });
  if (view.q) p.set("q", view.q);
  if (view.state) p.set("state", view.state);
  if (view.kind) p.set("kind", view.kind);
  if (view.library) p.set("library", view.library);
  if (view.sort) p.set("sort", view.sort);
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}
