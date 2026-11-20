import { queryOptions } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { getJson, sendJson } from "@/shared/lib/http";
import type { TokenGrant } from "../model/token";

export const tokensKey = ["tokens"] as const;

export const tokensQueryOptions = () =>
  queryOptions({
    queryKey: tokensKey,
    queryFn: ({ signal }) => getJson<components["schemas"]["TokenList"]>("/v1/tokens", { signal }),
    select: (data) => data.tokens,
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
