import { queryOptions } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { getJson, type QueryOf, sendJson } from "@/shared/lib/http";
import type { LibraryChoices } from "@/shared/ui/library-combobox";
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

/** Libraries offered by the scope picker per request: the API's largest page. */
const PICKER_LIMIT = 200;

/**
 * The libraries the caller may read whose ID, title or description holds `q`, by ID, for the
 * token's scope picker (the library combobox asks again as the text changes).
 */
export const scopeLibrariesQueryOptions = (q: string) =>
  queryOptions({
    queryKey: [...tokensKey, "scope-libraries", q] as const,
    queryFn: ({ signal }): Promise<LibraryChoices> => {
      const query = {
        limit: PICKER_LIMIT,
        sort: "id",
        ...(q && { q }),
      } satisfies QueryOf<"/api/v1/libraries">;
      return getJson<components["schemas"]["LibraryList"]>("/v1/libraries", {
        signal,
        query,
      }).then((list) => ({
        options: list.libraries.map((l) => ({ id: l.id, title: l.title, logo: l.logo })),
        total: list.total,
      }));
    },
  });
