import type { components } from "@/shared/lib/api-schema";
import { getJson, sendJson } from "@/shared/lib/http";
import type { ServerSource } from "@/shared/ui/data-table/server-pages";
import { type UsersView, usersFilters, usersParams } from "../model/list-view";
import type { NewUser, User } from "../model/user";

type UserList = components["schemas"]["UserList"];

export const usersKey = ["users"] as const;

/** The accounts a view shows, a numbered page at a time (by offset), sorted and filtered by the server. */
export function usersSource(view: UsersView): ServerSource<User> {
  const filters = usersFilters(view);
  return {
    key: [...usersKey, "list", filters],
    paging: "offset",
    fetchPage: ({ limit, cursor, offset, signal }) =>
      getJson<UserList>(`/v1/users?${usersParams(filters, limit, cursor, offset)}`, {
        signal,
      }).then((list) => ({ rows: list.users, total: list.total, nextCursor: list.next_cursor })),
  };
}

export const createUser = (user: NewUser) => sendJson<User>("POST", "/v1/users", user);

export const setUserDisabled = (id: string, disabled: boolean) =>
  sendJson<User>("POST", `/v1/users/${encodeURIComponent(id)}/${disabled ? "disable" : "enable"}`);

export const resetUserPassword = (id: string, password: string) =>
  sendJson<components["schemas"]["PasswordReset"]>(
    "PUT",
    `/v1/users/${encodeURIComponent(id)}/password`,
    { password },
  );
