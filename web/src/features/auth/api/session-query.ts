import { type QueryClient, queryOptions } from "@tanstack/react-query";
import { getJson, sendJson } from "@/shared/lib/http";
import { AdminCreated } from "../model/errors";
import type { Account, Credentials, SessionState } from "../model/session";

const sessionKey = ["session"] as const;

export const sessionQueryOptions = () =>
  queryOptions({
    queryKey: sessionKey,
    queryFn: ({ signal }) => getJson<SessionState>("/v1/session", { signal }),
    staleTime: 30_000,
  });

/** Asks the server on every navigation, but collapses a burst (link-hover preloads) into one call. */
export function fetchSession(queryClient: QueryClient) {
  return queryClient.fetchQuery({ ...sessionQueryOptions(), staleTime: 5_000 });
}

/** Nothing fetched for one account may outlive it: sign-in, sign-out and expiry all clear it. */
function forgetAccountData(queryClient: QueryClient) {
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== sessionKey[0] });
}

export async function signIn(queryClient: QueryClient, credentials: Credentials) {
  const state = await sendJson<SessionState>("POST", "/v1/session", credentials);
  forgetAccountData(queryClient);
  queryClient.setQueryData(sessionKey, state);
  return state;
}

/** Creates the first admin, then signs them in (setup itself sets no cookie). */
export async function setUp(queryClient: QueryClient, credentials: Credentials) {
  await sendJson<Account>("POST", "/v1/setup", credentials);
  try {
    return await signIn(queryClient, credentials);
  } catch {
    throw new AdminCreated();
  }
}

export async function signOut(queryClient: QueryClient) {
  await sendJson<void>("DELETE", "/v1/session");
  forgetAccountData(queryClient);
  queryClient.setQueryData<SessionState>(sessionKey, { state: "signed_out" });
}
