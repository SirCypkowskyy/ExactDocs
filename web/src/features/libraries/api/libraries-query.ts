import { queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import type { JobList, LibrariesResponse } from "../model/library";

const librariesKeys = {
  all: ["libraries"] as const,
  list: () => [...librariesKeys.all, "list"] as const,
  jobs: (id: string) => [...librariesKeys.all, "jobs", id] as const,
};

export const librariesQueryOptions = () =>
  queryOptions({
    queryKey: librariesKeys.list(),
    queryFn: ({ signal }) => getJson<LibrariesResponse>("/v1/libraries", { signal }),
    select: (data) => data.libraries,
  });

/** The newest jobs of one library (`id` is `/owner/repo`). Polls while one is unfinished. */
export const jobsQueryOptions = (id: string) =>
  queryOptions({
    queryKey: librariesKeys.jobs(id),
    queryFn: ({ signal }) =>
      getJson<JobList>(`/v1/libraries/${id.slice(1)}/jobs?limit=5`, { signal }),
    select: (data) => data.jobs,
    refetchInterval: (query) =>
      query.state.data?.jobs.some((j) => j.state === "queued" || j.state === "running")
        ? 2000
        : false,
  });
