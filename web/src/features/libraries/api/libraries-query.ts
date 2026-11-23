import { infiniteQueryOptions, keepPreviousData, queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import { LIBRARIES_KEY } from "@/shared/lib/query-keys";
import { pageQueryOptions, type ServerSource } from "@/shared/ui/data-table/server-pages";
import { pageOf } from "@/shared/ui/data-table/table-search";
import { JOBS_TABLE, type JobsView, jobsFilters, jobsParams } from "../model/jobs-view";
import type { Job, JobList, LatestJobs, LibrariesResponse } from "../model/library";
import { type ListView, listParams } from "../model/list-view";

export const librariesKeys = {
  all: LIBRARIES_KEY,
  list: () => [...librariesKeys.all, "list"] as const,
  latestJobs: () => [...librariesKeys.all, "latest-jobs"] as const,
  job: (id: string) => [...librariesKeys.all, "job", id] as const,
};

/** One page at a time; the next page is fetched on demand, sorted and filtered by the server. */
export const librariesQueryOptions = (view: ListView = {}) =>
  infiniteQueryOptions({
    queryKey: [...librariesKeys.list(), view] as const,
    queryFn: ({ signal, pageParam }) =>
      getJson<LibrariesResponse>(`/v1/libraries?${listParams(view, pageParam)}`, { signal }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });

/**
 * The jobs a view asks for, as a DataTable v2 source: numbered pages over the cursor API, sorted
 * and filtered by the server. The shown page is asked for again every 2 s while one of its jobs
 * is unfinished. `now` anchors a "queued within" preset (see `jobsFilters`).
 */
export function jobsSource(view: JobsView, now: number = Date.now()): ServerSource<Job> {
  const filters = jobsFilters(view, now);
  return {
    key: [...librariesKeys.all, "jobs", filters],
    fetchPage: ({ limit, cursor, signal }) =>
      getJson<JobList>(`/v1/jobs?${jobsParams(filters, limit, cursor)}`, { signal }).then(
        (list) => ({ rows: list.jobs, total: list.total, nextCursor: list.next_cursor }),
      ),
    refetchInterval: (page) =>
      page?.rows.some((j) => j.state === "queued" || j.state === "running") ? 2000 : false,
  };
}

/** The page of jobs a view shows (its page and size from the URL, else this browser's size). */
export const jobsPageQueryOptions = (view: JobsView) => {
  const { page, size } = pageOf(view, JOBS_TABLE);
  return pageQueryOptions(jobsSource(view), page, size);
};

/** The newest job of every library version, in one call. Polls while any job is unfinished. */
export const latestJobsQueryOptions = () =>
  queryOptions({
    queryKey: librariesKeys.latestJobs(),
    queryFn: ({ signal }) => getJson<LatestJobs>("/v1/jobs/latest", { signal }),
    select: (data) => data.jobs,
    refetchInterval: (query) =>
      query.state.data?.jobs.some((j) => j.state === "queued" || j.state === "running")
        ? 2000
        : false,
  });

/** One job with its skipped files; fetched only when a failure is opened. */
export const jobQueryOptions = (id: string, enabled: boolean) =>
  queryOptions({
    queryKey: librariesKeys.job(id),
    queryFn: ({ signal }) => getJson<Job>(`/v1/jobs/${encodeURIComponent(id)}`, { signal }),
    enabled,
  });
