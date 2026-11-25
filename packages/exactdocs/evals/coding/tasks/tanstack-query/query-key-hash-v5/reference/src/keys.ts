import { hashKey } from "@tanstack/query-core";
import type { QueryKey } from "@tanstack/query-core";

/** The string the query cache identifies `queryKey` by (a cached query's `queryHash`). */
export function cacheIdOf(queryKey: QueryKey): string {
  return hashKey(queryKey);
}
