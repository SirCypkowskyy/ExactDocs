/** The users list's view state: what the URL holds and what the API is asked for. */
const SORT_FIELDS = ["username", "role", "created_at"] as const;

export interface UsersView {
  q?: string | undefined;
  /** An API `sort` value: a field, `-` in front for descending. */
  sort?: string | undefined;
  role?: "admin" | "user" | undefined;
  status?: "active" | "disabled" | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseUsersView(search: Record<string, unknown>): UsersView {
  const q = typeof search.q === "string" ? search.q.trim().slice(0, 256) : "";
  const sort = typeof search.sort === "string" ? search.sort : "";
  return {
    q: q || undefined,
    sort: (SORT_FIELDS as readonly string[]).includes(sort.replace(/^-/, "")) ? sort : undefined,
    role: search.role === "admin" || search.role === "user" ? search.role : undefined,
    status: search.status === "active" || search.status === "disabled" ? search.status : undefined,
  };
}

export const isFiltered = (v: UsersView) => Boolean(v.q || v.role || v.status);

/** The query string of `GET /v1/users` for a view and a page cursor. */
export function usersParams(view: UsersView, cursor?: string | null): string {
  const p = new URLSearchParams({ limit: "50" });
  if (view.q) p.set("q", view.q);
  if (view.sort) p.set("sort", view.sort);
  if (view.role) p.set("role", view.role);
  if (view.status) p.set("disabled", String(view.status === "disabled"));
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}
