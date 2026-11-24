import {
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/** The users table's view state: what the URL holds and what `GET /v1/users` is asked for. */
export const USER_ROLES = ["admin", "user"] as const;
export const USER_STATUSES = ["active", "disabled"] as const;

/** The users table (DataTable v2): sorted by the API's fields, oldest first as the API does. */
export const USERS_TABLE: TableConfig = {
  id: "users",
  sortFields: ["username", "role", "created_at"],
  defaultSort: "created_at",
};

export interface UsersView extends TableSearch {
  role?: (typeof USER_ROLES)[number][] | undefined;
  status?: (typeof USER_STATUSES)[number][] | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseUsersView(search: Record<string, unknown>): UsersView {
  return {
    ...parseTableSearch(search, USERS_TABLE),
    role: parseFacet(search.role, USER_ROLES),
    status: parseFacet(search.status, USER_STATUSES),
  };
}

/** What `GET /v1/users` filters and sorts by: the view without its page and size. */
export interface UsersFilters {
  q?: string;
  role?: readonly string[];
  /** Absent with both states picked: that is no filter at all. */
  disabled?: boolean;
  sort?: string;
}

export function usersFilters(view: UsersView): UsersFilters {
  const status = view.status?.length === 1 ? view.status[0] : undefined;
  return {
    ...(view.q && { q: view.q }),
    ...(view.role && view.role.length < USER_ROLES.length && { role: view.role }),
    ...(status && { disabled: status === "disabled" }),
    ...(view.sort && { sort: view.sort }),
  };
}

/** The query string of `GET /v1/users` for some filters and one request's `limit` and offset or cursor. */
export function usersParams(
  filters: UsersFilters,
  limit: number,
  cursor?: string | null,
  offset?: number,
): string {
  const p = new URLSearchParams({ limit: String(limit) });
  if (filters.q) p.set("q", filters.q);
  for (const role of filters.role ?? []) p.append("role", role);
  if (filters.disabled !== undefined) p.set("disabled", String(filters.disabled));
  if (filters.sort) p.set("sort", filters.sort);
  // A page by offset (0 to 10000) or after a cursor, never both (422 `cursor_with_offset`).
  if (offset !== undefined) p.set("offset", String(offset));
  else if (cursor) p.set("cursor", cursor);
  return p.toString();
}
