import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { getJson, type QueryOf } from "@/shared/lib/http";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { normalizeQuery } from "@/shared/lib/search-query";
import type { GlobalResults } from "../model/global";

const SEARCH_LIMIT = 20;

export interface GlobalArgs {
  q: string;
  /** `/owner/repo`: narrows the hits; the facet counts stay whole. */
  library: string | undefined;
}

/** Search across the default version of every library. */
export const globalSearchQueryOptions = ({ q, library }: GlobalArgs) => {
  const text = normalizeQuery(q) ?? "";
  return queryOptions({
    queryKey: [...BROWSE_KEY, "search-all", text, library ?? ""] as const,
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/search"> = {
        q: text,
        ...(library && { library }),
        limit: SEARCH_LIMIT,
      };
      return getJson<GlobalResults>("/v1/search", { signal, query });
    },
    placeholderData: keepPreviousData,
  });
};
