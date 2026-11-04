import { useQuery } from "@tanstack/react-query";
import { sessionQueryOptions } from "../api/session-query";

/** The current session, or `undefined` while it is still loading or could not be read. */
export function useSession() {
  return useQuery(sessionQueryOptions()).data;
}
