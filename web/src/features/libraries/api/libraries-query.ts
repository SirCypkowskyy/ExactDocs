import { queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import { LIBRARIES_KEY } from "@/shared/lib/query-keys";
import type { Job, LatestJobs, LibrariesResponse } from "../model/library";

export const librariesKeys = {
  all: LIBRARIES_KEY,
  list: () => [...librariesKeys.all, "list"] as const,
  latestJobs: () => [...librariesKeys.all, "latest-jobs"] as const,
  job: (id: string) => [...librariesKeys.all, "job", id] as const,
};

export const librariesQueryOptions = () =>
  queryOptions({
    queryKey: librariesKeys.list(),
    queryFn: ({ signal }) => getJson<LibrariesResponse>("/v1/libraries", { signal }),
    select: (data) => data.libraries,
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
