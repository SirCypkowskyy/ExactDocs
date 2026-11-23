import {
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";
import { MAX_TOKENS, type Token } from "./token";

/*
 * The token table's view state (blocks-map §2.3, API tokens): an account holds at most 50 tokens,
 * so they arrive in one request and are sorted, filtered and paged in the browser. The URL holds
 * the view all the same, so a reload or a shared link shows the same rows.
 */

/** Which libraries a token reaches: all the account can, some, or none. */
export const TOKEN_SCOPES = ["all", "some", "none"] as const;
/** The expiry filter's choices. */
export const TOKEN_EXPIRIES = ["expired", "soon", "never"] as const;
/** The last-use filter's choices. */
export const TOKEN_USES = ["recent", "never"] as const;

export type TokenScope = (typeof TOKEN_SCOPES)[number];
/** A token's expiry as the filter sorts it ("later": more than a week away). */
export type TokenExpiry = (typeof TOKEN_EXPIRIES)[number] | "later";
/** A token's last use as the filter sorts it ("older": more than 30 days ago). */
export type TokenUse = (typeof TOKEN_USES)[number] | "older";

/** The token table (DataTable v2, client mode): newest first, no page larger than the cap. */
export const TOKENS_TABLE: TableConfig = {
  id: "tokens",
  sortFields: ["name", "created", "expires", "used"],
  defaultSort: "-created",
  maxRows: MAX_TOKENS,
};

export interface TokensView extends TableSearch {
  libraries?: TokenScope[] | undefined;
  expires?: (typeof TOKEN_EXPIRIES)[number][] | undefined;
  used?: (typeof TOKEN_USES)[number][] | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped. */
export function parseTokensView(search: Record<string, unknown>): TokensView {
  return {
    ...parseTableSearch(search, TOKENS_TABLE),
    libraries: parseFacet(search.libraries, TOKEN_SCOPES),
    expires: parseFacet(search.expires, TOKEN_EXPIRIES),
    used: parseFacet(search.used, TOKEN_USES),
  };
}

const DAY = 86_400_000;
/** A token that expires within this is about to. */
const SOON = 7 * DAY;
/** A token used within this is in use. */
const RECENT = 30 * DAY;

export const scopeOf = (token: Token): TokenScope =>
  token.library_ids == null ? "all" : token.library_ids.length > 0 ? "some" : "none";

export function expiryOf(token: Token, now: number): TokenExpiry {
  if (token.expires_at === null) return "never";
  const at = Date.parse(token.expires_at);
  return at <= now ? "expired" : at - now <= SOON ? "soon" : "later";
}

export function lastUseOf(token: Token, now: number): TokenUse {
  if (token.last_used_at === null) return "never";
  return now - Date.parse(token.last_used_at) <= RECENT ? "recent" : "older";
}

/**
 * A time to sort by: a token that never expires or was never used sorts first ascending, as the
 * API sorts them.
 */
export const sortTime = (iso: string | null): number =>
  iso === null ? Number.NEGATIVE_INFINITY : Date.parse(iso);
