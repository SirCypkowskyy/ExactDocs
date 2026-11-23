import { getJson } from "@/shared/lib/http";
import type { ServerSource } from "@/shared/ui/data-table/server-pages";
import {
  type AccessEvent,
  type AccessLogPage,
  type AccessLogView,
  accessLogFilters,
  accessLogParams,
} from "../model/access-log";

const accessLogKey = ["access-log"] as const;

const rowsOf = (page: AccessLogPage) => ({
  rows: page.events,
  total: page.total,
  nextCursor: page.next_cursor,
});

// #509: both logs set `paging: "offset"` once their endpoints take an `offset` (Last, jumps).

/** One library's access log, newest first, a page at a time (library admins and operators). */
export function libraryAccessLogSource(
  owner: string,
  repo: string,
  view: AccessLogView,
): ServerSource<AccessEvent> {
  const filters = accessLogFilters({ change: view.change });
  const lib = `/v1/libraries/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}` as const;
  return {
    key: [...accessLogKey, "library", owner, repo, filters],
    fetchPage: ({ limit, cursor, signal }) =>
      getJson<AccessLogPage>(`${lib}/access-log?${accessLogParams(filters, limit, cursor)}`, {
        signal,
      }).then(rowsOf),
  };
}

/** Every library's access log, removed ones included (operators). */
export function accessLogSource(view: AccessLogView): ServerSource<AccessEvent> {
  const filters = accessLogFilters(view);
  return {
    key: [...accessLogKey, "all", filters],
    fetchPage: ({ limit, cursor, signal }) =>
      getJson<AccessLogPage>(`/v1/access-log?${accessLogParams(filters, limit, cursor)}`, {
        signal,
      }).then(rowsOf),
  };
}
