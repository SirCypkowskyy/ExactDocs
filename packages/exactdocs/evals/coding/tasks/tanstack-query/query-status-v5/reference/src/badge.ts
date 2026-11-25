import type { QueryObserverResult } from "@tanstack/query-core";

/** What a status badge shows for a query. */
export type Badge = "waiting" | "failed" | "ok";

/** The badge of a query, from its status. */
export function badge(result: QueryObserverResult<unknown, unknown>): Badge {
  switch (result.status) {
    case "pending":
      return "waiting";
    case "error":
      return "failed";
    case "success":
      return "ok";
  }
}
