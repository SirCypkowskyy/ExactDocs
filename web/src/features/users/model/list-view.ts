import {
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/** The users table's view state: what the URL holds and what `GET /v1/users` is asked for. */
export const USER_ROLES = ["admin", "user"] as const;
export const USER_STATUSES = ["active", "disabled"] as const;
/** The `provider` filter's value for an account that signs in with a password. */
export const PASSWORD = "password";
/** A sign-in provider's name, as the server allows it (`password` is never one). */
const PROVIDER_NAME = /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/;

/** The users table (DataTable v2): sorted by the API's fields, oldest first as the API does. */
export const USERS_TABLE: TableConfig = {
  id: "users",
  sortFields: ["username", "role", "created_at", "last_active_at", "token_count"],
  defaultSort: "created_at",
};

export interface UsersView extends TableSearch {
  role?: (typeof USER_ROLES)[number][] | undefined;
  status?: (typeof USER_STATUSES)[number][] | undefined;
  /** `password` and provider names: the providers configured now are not known here. */
  provider?: string[] | undefined;
}

/** The sign-in methods in a URL: `password` or provider names, each once, in the URL's order. */
function parseProviders(value: unknown): string[] | undefined {
  const raw = Array.isArray(value) ? value : typeof value === "string" ? value.split(",") : [];
  const names = raw
    .filter((v): v is string => typeof v === "string")
    .map((v) => v.trim())
    .filter((v) => PROVIDER_NAME.test(v));
  const unique = [...new Set(names)];
  return unique.length ? unique : undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped, never sent to the API. */
export function parseUsersView(search: Record<string, unknown>): UsersView {
  return {
    ...parseTableSearch(search, USERS_TABLE),
    role: parseFacet(search.role, USER_ROLES),
    status: parseFacet(search.status, USER_STATUSES),
    provider: parseProviders(search.provider),
  };
}

/** What `GET /v1/users` filters and sorts by: the view without its page and size. */
export interface UsersFilters {
  q?: string;
  role?: readonly string[];
  /** Absent with both states picked: that is no filter at all. */
  disabled?: boolean;
  provider?: readonly string[];
  sort?: string;
}

export function usersFilters(view: UsersView): UsersFilters {
  const status = view.status?.length === 1 ? view.status[0] : undefined;
  return {
    ...(view.q && { q: view.q }),
    ...(view.role && view.role.length < USER_ROLES.length && { role: view.role }),
    ...(status && { disabled: status === "disabled" }),
    ...(view.provider && { provider: view.provider }),
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
  for (const provider of filters.provider ?? []) p.append("provider", provider);
  if (filters.sort) p.set("sort", filters.sort);
  // A page by offset (0 to 10000) or after a cursor, never both (422 `cursor_with_offset`).
  if (offset !== undefined) p.set("offset", String(offset));
  else if (cursor) p.set("cursor", cursor);
  return p.toString();
}
