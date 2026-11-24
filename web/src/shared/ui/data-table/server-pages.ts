import { keepPreviousData, type QueryClient, queryOptions } from "@tanstack/react-query";

/*
 * Numbered pages over the list API (blocks-map §2.2, docs/rest-api.md "Jumping to a page"). The
 * API pages with `limit` (1 to 200) and either an `offset` (0 to 10000) or an opaque,
 * forward-only `cursor`, and every list carries `total`; the page count is `ceil(total / size)`.
 *
 * A source with `paging: "offset"` (every list of the app) asks for page n with
 * `offset = (n - 1) × size` and never a cursor: any page within the bound is one request, so the
 * table offers numbered jumps and Last, and a link to page n loads it directly.
 *
 * Past the bound (and for a source without an offset) the cursor walk is the fallback: each page
 * in the query cache remembers the cursor it started at and the one after it, and a page starts
 * from the nearest of them (or, by offset, from the bound itself): one request of
 * `limit = rows to skip + size` while that fits in 200, otherwise steps of 200 first. Next from a
 * page goes on from its cursor in one request; the table does not offer jumps that would walk.
 */

/** One page as a list endpoint returns it, mapped to rows. */
export interface ServerPage<T> {
  rows: readonly T[];
  /** Rows that match the filters, across every page. */
  total: number;
  /** Pass back to continue after this page; null on the last one. */
  nextCursor: string | null;
}

/** The API's largest `offset` (`exactdocs_kernel.MAX_OFFSET`): farther pages walk by cursor. */
export const MAX_OFFSET = 10_000;

/**
 * How a source is asked for rows: from `offset` (then `cursor` is null and never sent), or after
 * `cursor` (null for the first page).
 */
export interface PageRequest {
  limit: number;
  cursor: string | null;
  offset?: number;
  signal: AbortSignal;
}

export interface ServerSource<T> {
  /** The list and its view (filters, sort): never the page or the size. */
  key: readonly unknown[];
  fetchPage: (request: PageRequest) => Promise<ServerPage<T>>;
  /** `offset` where the endpoint takes one (any page in one request); `cursor` by default. */
  paging?: "cursor" | "offset";
  /** The API's largest `limit`. */
  maxLimit?: number;
  /** With `paging: "offset"`: the API's largest `offset` (default `MAX_OFFSET`). */
  maxOffset?: number;
  /** Ask for the shown page again while this says so (jobs still running): ms, or false. */
  refetchInterval?: (page: ServerPage<T> | undefined) => number | false;
}

/** A page as the cache keeps it: where it starts, and the cursor that started it. */
export interface LoadedPage<T> extends ServerPage<T> {
  offset: number;
  cursor: string | null;
}

const pagesKey = (source: ServerSource<unknown>) => [...source.key, "page"] as const;

/** Every cursor the cached pages of this view know, by the row offset it starts at. */
function knownCursors(client: QueryClient, source: ServerSource<unknown>): Map<number, string> {
  const known = new Map<number, string>();
  for (const [, page] of client.getQueriesData<LoadedPage<unknown>>({
    queryKey: pagesKey(source),
  })) {
    if (!page) continue;
    if (page.cursor) known.set(page.offset, page.cursor);
    if (page.nextCursor) known.set(page.offset + page.rows.length, page.nextCursor);
  }
  return known;
}

/**
 * The farthest page a jump reaches in one request, at this size: every page of a list that pages
 * by offset up to the API's bound, only the first one of a list that pages by cursor.
 */
export function lastJumpPage(
  source: Pick<ServerSource<unknown>, "paging" | "maxOffset">,
  size: number,
): number {
  if (source.paging !== "offset") return 1;
  return Math.floor((source.maxOffset ?? MAX_OFFSET) / size) + 1;
}

/** Where a page's walk starts: a row offset, and the cursor there (or the offset to ask from). */
interface Start {
  at: number;
  cursor: string | null;
  /** Ask the first request by `offset = at` (no cursor). */
  byOffset: boolean;
}

/** The nearest start at or before `offset`: a cursor the cache knows, or the API's offset bound. */
function startOf(client: QueryClient, source: ServerSource<unknown>, offset: number): Start {
  let start: Start = { at: 0, cursor: null, byOffset: false };
  if (source.paging === "offset") {
    const at = Math.min(offset, source.maxOffset ?? MAX_OFFSET);
    // Within the bound: the page itself, by offset, never a cursor.
    if (at === offset) return { at, cursor: null, byOffset: true };
    start = { at, cursor: null, byOffset: true };
  }
  for (const [at, cursor] of knownCursors(client, source)) {
    if (at <= offset && at > start.at) start = { at, cursor, byOffset: false };
  }
  return start;
}

async function loadPage<T>(
  client: QueryClient,
  source: ServerSource<T>,
  page: number,
  size: number,
  signal: AbortSignal,
): Promise<LoadedPage<T>> {
  const offset = (page - 1) * size;
  const max = source.maxLimit ?? 200;
  let { at, cursor, byOffset } = startOf(client, source as ServerSource<unknown>, offset);
  // The first request starts at `at` by offset or by cursor; later ones go on by cursor.
  const ask = (limit: number) =>
    source.fetchPage({ limit, cursor, ...(byOffset && { offset: at }), signal });
  let skip = offset - at;
  while (skip > 0) {
    if (skip + size <= max) {
      // One request reaches the page: take its tail.
      const found = await ask(skip + size);
      return {
        rows: found.rows.slice(skip),
        total: found.total,
        nextCursor: found.nextCursor,
        offset,
        cursor: null,
      };
    }
    const found = await ask(Math.min(max, skip));
    if (!found.nextCursor || found.rows.length === 0) {
      // The list ended before this page (it shrank): an empty page past the end.
      return { rows: [], total: found.total, nextCursor: null, offset, cursor: null };
    }
    skip -= found.rows.length;
    at += found.rows.length;
    cursor = found.nextCursor;
    byOffset = false;
  }
  const found = await ask(size);
  return { ...found, offset, cursor };
}

/** The query of one numbered page; a route loader can `ensureQueryData` it. */
export function pageQueryOptions<T>(source: ServerSource<T>, page: number, size: number) {
  const interval = source.refetchInterval;
  return queryOptions({
    queryKey: [...pagesKey(source as ServerSource<unknown>), page, size] as const,
    queryFn: ({ client, signal }) => loadPage(client, source, page, size, signal),
    placeholderData: keepPreviousData,
    ...(interval && {
      refetchInterval: (query: { state: { data: LoadedPage<T> | undefined } }) =>
        interval(query.state.data),
    }),
  });
}
