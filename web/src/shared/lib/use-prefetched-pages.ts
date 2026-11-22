import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";
import { useEffect, useState } from "react";

/**
 * Shows the pages of an infinite query one at a time and keeps the next one fetched in the
 * background, so "Load more" shows it at once. `view` is what the query is filtered and sorted
 * by: a new view starts again at one page.
 */
export function usePrefetchedPages<P>(
  query: UseInfiniteQueryResult<InfiniteData<P>>,
  view: unknown,
) {
  const key = JSON.stringify(view ?? null);
  const [asked, setAsked] = useState({ key, shown: 1 });
  const shown = asked.key === key ? asked.shown : 1;
  const loaded = query.data?.pages.length ?? 0;
  const { hasNextPage, isFetching, isFetchNextPageError, fetchNextPage } = query;
  // One page ahead, never two; a failed prefetch waits for the reader to ask again.
  useEffect(() => {
    if (hasNextPage && loaded === shown && !isFetching && !isFetchNextPageError) {
      void fetchNextPage();
    }
  }, [hasNextPage, loaded, shown, isFetching, isFetchNextPageError, fetchNextPage]);
  return {
    pages: query.data?.pages.slice(0, shown) ?? [],
    hasMore: loaded > shown || hasNextPage,
    /** The reader asked for a page that has not arrived yet. */
    loadingMore: loaded < shown && query.isFetchingNextPage,
    loadMore: () => {
      // Never more than one page past what has arrived (a failed page is asked for again).
      setAsked({ key, shown: Math.min(shown + 1, loaded + 1) });
      if (loaded <= shown && !isFetching) void fetchNextPage();
    },
  };
}
