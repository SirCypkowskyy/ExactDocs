import type { components } from "@/shared/lib/api-schema";
import { textParam } from "@/shared/lib/list-sort";
import {
  parseChoice,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/*
 * Every account's API tokens (`GET /v1/users/tokens`, operators): numbered pages sorted and
 * filtered by the server, the view in the URL. The URL's words (`expiry=expired`, `use=unused`)
 * are not JSON, so a link stays readable; the API is asked with its booleans.
 */

export type AccountToken = components["schemas"]["AccountTokenSummary"];
export type AccountTokenList = components["schemas"]["AllTokensList"];

/** Expired (`expired=true`) or still valid (`expired=false`). */
export const TOKEN_EXPIRIES = ["expired", "valid"] as const;
/** Never used (`unused=true`) or used at least once (`unused=false`). */
export const TOKEN_USES = ["unused", "used"] as const;

/** The tokens table (DataTable v2): newest first unless sorted by another of the API's fields. */
export const ALL_TOKENS_TABLE: TableConfig = {
  id: "all-tokens",
  sortFields: ["created_at", "name", "expires_at", "last_used_at", "owner"],
  defaultSort: "-created_at",
};

export interface AllTokensView extends TableSearch {
  /** The owner's account ID. */
  owner?: string | undefined;
  expiry?: (typeof TOKEN_EXPIRIES)[number] | undefined;
  use?: (typeof TOKEN_USES)[number] | undefined;
}

/** An account ID: letters, digits, `-` and `_` (the server's are 32 hex digits). */
const ACCOUNT_ID = /^[\w-]{1,64}$/;

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseAllTokensView(search: Record<string, unknown>): AllTokensView {
  const owner = textParam(typeof search.owner === "number" ? String(search.owner) : search.owner);
  return {
    ...parseTableSearch(search, ALL_TOKENS_TABLE),
    owner: owner && ACCOUNT_ID.test(owner) ? owner : undefined,
    expiry: parseChoice(search.expiry, TOKEN_EXPIRIES),
    use: parseChoice(search.use, TOKEN_USES),
  };
}

/** What `GET /v1/users/tokens` filters and sorts by: the view without its page and size. */
export interface AllTokensFilters {
  q?: string;
  owner_id?: string;
  expired?: boolean;
  unused?: boolean;
  sort?: string;
}

export const allTokensFilters = (view: AllTokensView): AllTokensFilters => ({
  ...(view.q && { q: view.q }),
  ...(view.owner && { owner_id: view.owner }),
  ...(view.expiry && { expired: view.expiry === "expired" }),
  ...(view.use && { unused: view.use === "unused" }),
  ...(view.sort && { sort: view.sort }),
});

/** The query string of `GET /v1/users/tokens` for some filters and one request's page. */
export function allTokensParams(
  filters: AllTokensFilters,
  limit: number,
  cursor?: string | null,
  offset?: number,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (filters.q) p.set("q", filters.q);
  if (filters.owner_id) p.set("owner_id", filters.owner_id);
  if (filters.expired !== undefined) p.set("expired", String(filters.expired));
  if (filters.unused !== undefined) p.set("unused", String(filters.unused));
  if (filters.sort) p.set("sort", filters.sort);
  // A page by offset (0 to 10000) or after a cursor, never both (422 `cursor_with_offset`).
  if (offset !== undefined) p.set("offset", String(offset));
  else if (cursor) p.set("cursor", cursor);
  return p.toString();
}
