import { infiniteQueryOptions, keepPreviousData, queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import { LIBRARIES_KEY } from "@/shared/lib/query-keys";
import { type JobsView, jobsParams } from "../model/jobs-view";
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

/** The jobs a view asks for, a page at a time, sorted and filtered by the server. */
export const jobsQueryOptions = (view: JobsView = {}) =>
  infiniteQueryOptions({
    queryKey: [...librariesKeys.all, "jobs", view] as const,
    queryFn: ({ signal, pageParam }) =>
      getJson<JobList>(`/v1/jobs?${jobsParams(view, pageParam)}`, { signal }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });

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
