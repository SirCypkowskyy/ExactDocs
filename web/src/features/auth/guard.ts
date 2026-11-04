import type { QueryClient } from "@tanstack/react-query";
import { fetchSession } from "./api/session-query";
import { type Area, type GuardTarget, resolveGuard } from "./model/session";

/** For a route's `beforeLoad`: the redirect to throw, or `null` to let the page render. */
export async function guard(
  queryClient: QueryClient,
  area: Area,
  here: string,
): Promise<GuardTarget | null> {
  const { state } = await fetchSession(queryClient);
  return resolveGuard(state, area, here);
}
