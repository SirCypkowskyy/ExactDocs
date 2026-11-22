import { infiniteQueryOptions, keepPreviousData } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { getJson, sendJson } from "@/shared/lib/http";
import { type UsersView, usersParams } from "../model/list-view";
import type { NewUser, User } from "../model/user";

export const usersKey = ["users"] as const;

/** One page at a time; the next page is fetched on demand, sorted and filtered by the server. */
export const usersQueryOptions = (view: UsersView = {}) =>
  infiniteQueryOptions({
    queryKey: [...usersKey, "list", view] as const,
    queryFn: ({ signal, pageParam }) =>
      getJson<components["schemas"]["UserList"]>(`/v1/users?${usersParams(view, pageParam)}`, {
        signal,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });

export const createUser = (user: NewUser) => sendJson<User>("POST", "/v1/users", user);

export const setUserDisabled = (id: string, disabled: boolean) =>
  sendJson<User>("POST", `/v1/users/${encodeURIComponent(id)}/${disabled ? "disable" : "enable"}`);

export const resetUserPassword = (id: string, password: string) =>
  sendJson<components["schemas"]["PasswordReset"]>(
    "PUT",
    `/v1/users/${encodeURIComponent(id)}/password`,
    { password },
  );
