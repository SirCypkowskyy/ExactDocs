import { queryOptions } from "@tanstack/react-query";
import { getJson, type QueryOf } from "@/shared/lib/http";
import { LIBRARIES_KEY } from "@/shared/lib/query-keys";
import { pageQueryOptions, type ServerSource } from "@/shared/ui/data-table/server-pages";
import { pageOf } from "@/shared/ui/data-table/table-search";
import type { LibraryChoices } from "@/shared/ui/library-combobox";
import { JOBS_TABLE, type JobsView, jobsFilters, jobsParams } from "../model/jobs-view";
import type { Job, JobList, LatestJobs, LibrariesResponse, Library } from "../model/library";
import { LIBRARIES_TABLE, type ListView, listFilters, listParams } from "../model/list-view";

export const librariesKeys = {
  all: LIBRARIES_KEY,
  list: () => [...librariesKeys.all, "list"] as const,
  latestJobs: () => [...librariesKeys.all, "latest-jobs"] as const,
  job: (id: string) => [...librariesKeys.all, "job", id] as const,
};

/**
 * The libraries a view asks for, as a DataTable v2 source: numbered pages by offset (any page in
 * one request), sorted and filtered by the server. `now` anchors a "last imported within" preset.
 */
export function librariesSource(view: ListView, now: number = Date.now()): ServerSource<Library> {
  const filters = listFilters(view, now);
  return {
    // Under `list()`, so a finished import that refreshes the list refreshes every page of it.
    key: [...librariesKeys.list(), filters],
    paging: "offset",
    fetchPage: ({ limit, cursor, offset, signal }) =>
      getJson<LibrariesResponse>(`/v1/libraries?${listParams(filters, limit, cursor, offset)}`, {
        signal,
      }).then((list) => ({
        rows: list.libraries,
        total: list.total,
        nextCursor: list.next_cursor,
      })),
  };
}

/** Libraries offered by the jobs table's library filter per request: the API's largest page. */
const PICKER_LIMIT = 200;

/**
 * The libraries whose ID, title or description holds `q`, by ID, for the jobs table's library
 * filter (the library combobox asks again as the text changes). Under `list()`, so whatever
 * refreshes the libraries list refreshes the picker too.
 */
export const pickerLibrariesQueryOptions = (q: string) =>
  queryOptions({
    queryKey: [...librariesKeys.list(), "picker", q] as const,
    queryFn: ({ signal }): Promise<LibraryChoices> => {
      const query = {
        limit: PICKER_LIMIT,
        sort: "id",
        ...(q && { q }),
      } satisfies QueryOf<"/api/v1/libraries">;
      return getJson<LibrariesResponse>("/v1/libraries", { signal, query }).then((list) => ({
        options: list.libraries.map((l) => ({ id: l.id, title: l.title, logo: l.logo })),
        total: list.total,
      }));
    },
  });

/** The page of libraries a view shows (its page and size from the URL, else this browser's size). */
export const librariesPageQueryOptions = (view: ListView) => {
  const { page, size } = pageOf(view, LIBRARIES_TABLE);
  return pageQueryOptions(librariesSource(view), page, size);
};

/**
 * The jobs a view asks for, as a DataTable v2 source: numbered pages by offset, sorted and
 * filtered by the server. The shown page is asked for again every 2 s while one of its jobs
 * is unfinished. `now` anchors a "queued within" preset (see `jobsFilters`).
 */
export function jobsSource(view: JobsView, now: number = Date.now()): ServerSource<Job> {
  const filters = jobsFilters(view, now);
  return {
    key: [...librariesKeys.all, "jobs", filters],
    paging: "offset",
    fetchPage: ({ limit, cursor, offset, signal }) =>
      getJson<JobList>(`/v1/jobs?${jobsParams(filters, limit, cursor, offset)}`, { signal }).then(
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
