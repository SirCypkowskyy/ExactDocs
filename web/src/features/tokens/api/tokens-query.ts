import { queryOptions } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { getJson, sendJson } from "@/shared/lib/http";
import { MAX_TOKENS, type TokenGrant } from "../model/token";

export const tokensKey = ["tokens"] as const;

/**
 * Every token of the account in one request: it holds at most 50, so the table sorts, filters and
 * pages them in the browser.
 */
export const tokensQueryOptions = () =>
  queryOptions({
    queryKey: [...tokensKey, "list"] as const,
    queryFn: ({ signal }) =>
      getJson<components["schemas"]["TokenList"]>(`/v1/tokens?limit=${MAX_TOKENS}`, { signal }),
    select: (list) => list.tokens,
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
