import { skipToken } from "@tanstack/query-core";

/** A user. */
export type User = { id: number; name: string };

/** The query of a user, which does not run while there is no user ID. */
export function userOptions(fetchUser: (id: number) => Promise<User>, userId: number | undefined) {
  return {
    queryKey: ["user", userId],
    queryFn: userId === undefined ? skipToken : () => fetchUser(userId),
  };
}
