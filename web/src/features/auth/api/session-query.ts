import { type QueryClient, queryOptions } from "@tanstack/react-query";
import { getJson, sendJson } from "@/shared/lib/http";
import type { Account, Credentials, SessionState } from "../model/session";

const sessionKey = ["session"] as const;

export const sessionQueryOptions = () =>
  queryOptions({
    queryKey: sessionKey,
    queryFn: ({ signal }) => getJson<SessionState>("/v1/session", { signal }),
    staleTime: 30_000,
  });

/** Always asks the server: the guard must notice an expired session on every navigation. */
export function fetchSession(queryClient: QueryClient) {
  return queryClient.fetchQuery({ ...sessionQueryOptions(), staleTime: 0 });
}

export async function signIn(queryClient: QueryClient, credentials: Credentials) {
  const state = await sendJson<SessionState>("POST", "/v1/session", credentials);
  queryClient.setQueryData(sessionKey, state);
  return state;
}

/** Creates the first admin, then signs them in (setup itself sets no cookie). */
export async function setUp(queryClient: QueryClient, credentials: Credentials) {
  await sendJson<Account>("POST", "/v1/setup", credentials);
  return signIn(queryClient, credentials);
}

export async function signOut(queryClient: QueryClient) {
  await sendJson<void>("DELETE", "/v1/session");
  // Nothing fetched for the old account may outlive it.
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== sessionKey[0] });
  queryClient.setQueryData<SessionState>(sessionKey, { state: "signed_out" });
}
