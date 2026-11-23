import { infiniteQueryOptions, keepPreviousData } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import { type AccessLogPage, type AccessLogView, accessLogQuery } from "../model/access-log";

const accessLogKey = ["access-log"] as const;

const pages = {
  initialPageParam: null as string | null,
  getNextPageParam: (last: AccessLogPage) => last.next_cursor,
  placeholderData: keepPreviousData,
};

/** One library's access log, newest first, a page at a time (library admins and operators). */
export const libraryAccessLogQueryOptions = (owner: string, repo: string, view: AccessLogView) =>
  infiniteQueryOptions({
    queryKey: [...accessLogKey, "library", owner, repo, view.change ?? null] as const,
    queryFn: ({ signal, pageParam }) =>
      getJson<AccessLogPage>(
        `/v1/libraries/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/access-log`,
        { signal, query: accessLogQuery({ change: view.change }, pageParam) },
      ),
    ...pages,
  });

/** Every library's access log, removed ones included (operators). */
export const accessLogQueryOptions = (view: AccessLogView) =>
  infiniteQueryOptions({
    queryKey: [...accessLogKey, "all", view.change ?? null, view.library ?? null] as const,
    queryFn: ({ signal, pageParam }) =>
      getJson<AccessLogPage>("/v1/access-log", { signal, query: accessLogQuery(view, pageParam) }),
    ...pages,
  });
