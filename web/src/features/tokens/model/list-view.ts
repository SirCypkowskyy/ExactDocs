/** The token list's view state: what the URL holds and what the API is asked for. */
const SORT_FIELDS = ["name", "created_at", "expires_at", "last_used_at"] as const;

export interface TokensView {
  q?: string | undefined;
  /** An API `sort` value: a field, `-` in front for descending. */
  sort?: string | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseTokensView(search: Record<string, unknown>): TokensView {
  const q = typeof search.q === "string" ? search.q.trim().slice(0, 256) : "";
  const sort = typeof search.sort === "string" ? search.sort : "";
  return {
    q: q || undefined,
    sort: (SORT_FIELDS as readonly string[]).includes(sort.replace(/^-/, "")) ? sort : undefined,
  };
}

/** The query string of `GET /v1/tokens` for a view and a page cursor. */
export function tokensParams(view: TokensView, cursor?: string | null): string {
  const p = new URLSearchParams({ limit: "50" });
  if (view.q) p.set("q", view.q);
  if (view.sort) p.set("sort", view.sort);
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}
