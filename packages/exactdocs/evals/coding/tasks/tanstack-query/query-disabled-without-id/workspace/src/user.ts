/** A user. */
export type User = { id: number; name: string };

/** The query of a user, which does not run while there is no user ID. */
export function userOptions(fetchUser: (id: number) => Promise<User>, userId: number | undefined) {
  throw new Error("not implemented");
}
