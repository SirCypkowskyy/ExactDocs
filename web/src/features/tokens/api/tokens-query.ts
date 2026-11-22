import { infiniteQueryOptions, keepPreviousData } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { getJson, sendJson } from "@/shared/lib/http";
import { type TokensView, tokensParams } from "../model/list-view";
import type { TokenGrant } from "../model/token";

export const tokensKey = ["tokens"] as const;

/** One page at a time; the next page is fetched on demand, sorted and filtered by the server. */
export const tokensQueryOptions = (view: TokensView = {}) =>
  infiniteQueryOptions({
    queryKey: [...tokensKey, "list", view] as const,
    queryFn: ({ signal, pageParam }) =>
      getJson<components["schemas"]["TokenList"]>(`/v1/tokens?${tokensParams(view, pageParam)}`, {
        signal,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });

/**
 * Deliberately not a mutation or a query: the response holds the one-time secret, so it must
 * live only in the caller's state and never in a TanStack cache.
 */
export function createToken(name: string, expiresAt: string | undefined, libraryIds?: string[]) {
  return sendJson<TokenGrant>("POST", "/v1/tokens", {
    name,
    ...(libraryIds !== undefined && { library_ids: libraryIds }),
    ...(expiresAt && { expires_at: expiresAt }),
  });
}

export const revokeToken = (id: string) =>
  sendJson<void>("DELETE", `/v1/tokens/${encodeURIComponent(id)}`);
