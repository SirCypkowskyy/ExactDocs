import type { FetchInfiniteQueryOptions, QueryKey } from "@tanstack/query-core";

/** One page of the feed: its items and the next page's number, or null for the last. */
export type Page = { items: string[]; next: number | null };
/** Fetches a page of the feed by number; the first page is 1. */
export type FetchPage = (page: number) => Promise<Page>;
/** The options of the feed's infinite query. */
export type FeedOptions = FetchInfiniteQueryOptions<Page, Error, Page, QueryKey, number>;

/** The infinite query of the feed. */
export function feedOptions(fetchPage: FetchPage): FeedOptions {
  return {
    queryKey: ["feed"],
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: 1,
    getNextPageParam: (last: Page) => last.next,
  };
}
