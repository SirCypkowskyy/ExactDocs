import { queryOptions } from "@tanstack/react-query";
import type { components } from "@/shared/lib/api-schema";
import { getJson, sendJson } from "@/shared/lib/http";
import type { NewUser, User } from "../model/user";

export const usersKey = ["users"] as const;

export const usersQueryOptions = () =>
  queryOptions({
    queryKey: usersKey,
    queryFn: ({ signal }) => getJson<components["schemas"]["UserList"]>("/v1/users", { signal }),
    select: (data) => data.users,
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
