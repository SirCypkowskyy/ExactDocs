import { keepPreviousData, type QueryClient, queryOptions } from "@tanstack/react-query";

/*
 * Numbered pages over the list API (blocks-map §2.2). The API pages with `limit` (1 to 200) and
 * an opaque, forward-only `cursor`, and every list carries `total`. Each page in the query cache
 * remembers the cursor it started at and the one after it, so First, Previous and Next ask for
 * one page (and are instant once prefetched), and the page count is `ceil(total / size)`.
 *
 * A page nobody has reached yet (a reload on page 5) walks forward from the nearest cursor the
 * cache knows: one request of `limit = rows to skip + size` while that fits in 200, otherwise
 * steps of 200 first. Last stays hidden, since it would walk the whole list.
 *
 * Once the API takes an `offset` (G8), a source sets `paging: "offset"`: every page is then one
 * request, and the table offers Last. Nothing else changes for the pages that use it.
 */

/** One page as a list endpoint returns it, mapped to rows. */
export interface ServerPage<T> {
  rows: readonly T[];
  /** Rows that match the filters, across every page. */
  total: number;
  /** Pass back to continue after this page; null on the last one. */
  nextCursor: string | null;
}

/** How a source is asked for rows: after `cursor`, or from `offset` when it pages by offset. */
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
  /** `cursor` today; `offset` once the API takes one (G8). */
  paging?: "cursor" | "offset";
  /** The API's largest `limit`. */
  maxLimit?: number;
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

async function loadPage<T>(
  client: QueryClient,
  source: ServerSource<T>,
  page: number,
  size: number,
  signal: AbortSignal,
): Promise<LoadedPage<T>> {
  const offset = (page - 1) * size;
  if (source.paging === "offset") {
    const found = await source.fetchPage({ limit: size, cursor: null, offset, signal });
    return { ...found, offset, cursor: null };
  }
  const max = source.maxLimit ?? 200;
  // Start from the nearest cursor at or before this page.
  let at = 0;
  let cursor: string | null = null;
  for (const [start, known] of knownCursors(client, source as ServerSource<unknown>)) {
    if (start <= offset && start > at) {
      at = start;
      cursor = known;
    }
  }
  let skip = offset - at;
  while (skip > 0) {
    if (skip + size <= max) {
      // One request reaches the page: take its tail.
      const found = await source.fetchPage({ limit: skip + size, cursor, signal });
      return {
        rows: found.rows.slice(skip),
        total: found.total,
        nextCursor: found.nextCursor,
        offset,
        cursor: null,
      };
    }
    const found = await source.fetchPage({ limit: Math.min(max, skip), cursor, signal });
    if (!found.nextCursor || found.rows.length === 0) {
      // The list ended before this page (it shrank): an empty page past the end.
      return { rows: [], total: found.total, nextCursor: null, offset, cursor: null };
    }
    skip -= found.rows.length;
    at += found.rows.length;
    cursor = found.nextCursor;
  }
  const found = await source.fetchPage({ limit: size, cursor, signal });
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
