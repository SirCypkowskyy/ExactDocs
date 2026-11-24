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

/**
 * One library's access log, a page at a time (library admins and operators), newest first unless
 * the view sorts it otherwise.
 */
export function libraryAccessLogSource(
  owner: string,
  repo: string,
  view: AccessLogView,
  now: number = Date.now(),
): ServerSource<AccessEvent> {
  // A library's own log has no library filter.
  const filters = accessLogFilters({ ...view, library: undefined }, now);
  const lib = `/v1/libraries/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}` as const;
  return {
    key: [...accessLogKey, "library", owner, repo, filters],
    paging: "offset",
    fetchPage: ({ limit, cursor, offset, signal }) =>
      getJson<AccessLogPage>(
        `${lib}/access-log?${accessLogParams(filters, limit, cursor, offset)}`,
        { signal },
      ).then(rowsOf),
  };
}

/**
 * Every library's access log, removed ones included (operators). `now` anchors a "within" preset
 * (see `whenBounds`).
 */
export function accessLogSource(
  view: AccessLogView,
  now: number = Date.now(),
): ServerSource<AccessEvent> {
  const filters = accessLogFilters(view, now);
  return {
    key: [...accessLogKey, "all", filters],
    paging: "offset",
    fetchPage: ({ limit, cursor, offset, signal }) =>
      getJson<AccessLogPage>(`/v1/access-log?${accessLogParams(filters, limit, cursor, offset)}`, {
        signal,
      }).then(rowsOf),
  };
}
