import { queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import { AI_KEY, LIBRARIES_KEY } from "@/shared/lib/query-keys";
import {
  type AiUsage,
  countsOf,
  type JobStats,
  type LibraryList,
  type LibrarySummary,
  type SpendHistory,
  type UsageStats,
} from "../model/overview";

/*
 * One queryOptions per endpoint the overview reads. Everything here is for operators: the API
 * answers anyone else 403, and the route shows them nothing.
 */

const OVERVIEW_KEY = ["overview"] as const;

/** The API's page size ceiling for `GET /libraries`. */
const LIBRARY_PAGE = 200;
/** Stop walking after this many pages (40,000 libraries): the tile then counts what it read. */
const MAX_LIBRARY_PAGES = 200;

/** Jobs queued per UTC day from `from` to today, by state and kind (#512). */
export const jobStatsQueryOptions = (from: string) =>
  queryOptions({
    queryKey: [...OVERVIEW_KEY, "jobs", from] as const,
    queryFn: ({ signal }) =>
      getJson<JobStats>("/v1/stats/jobs", { signal, query: { bucket: "day", from } }),
  });

/** What the whole instance spent on AI per UTC day from `from` to today (#511). */
export const spendHistoryQueryOptions = (from: string) =>
  queryOptions({
    queryKey: [...AI_KEY, "history", "instance", "day", from] as const,
    queryFn: ({ signal }) =>
      getJson<SpendHistory>("/v1/ai/usage/history", {
        signal,
        query: { scope: "instance", window: "day", from },
      }),
  });

/** Reads, searches and answers per UTC day over the last `days` days, by library (#510). */
export const usageQueryOptions = (days: number) =>
  queryOptions({
    queryKey: [...OVERVIEW_KEY, "usage", "day", days] as const,
    queryFn: ({ signal }) =>
      getJson<UsageStats>("/v1/stats/usage", {
        signal,
        query: { period: "day", periods: days, by: "library", limit: 5 },
      }),
  });

/** This ISO week's reads, searches and answers so far (#510). */
export const weekUsageQueryOptions = () =>
  queryOptions({
    queryKey: [...OVERVIEW_KEY, "usage", "week"] as const,
    queryFn: ({ signal }) =>
      getJson<UsageStats>("/v1/stats/usage", {
        signal,
        query: { period: "week", periods: 1, by: "none", limit: 1 },
      }),
  });

/** Spend today and this month and the budgets left, per scope (the AI page reads the same). */
export const aiUsageQueryOptions = () =>
  queryOptions({
    queryKey: [...AI_KEY, "usage"] as const,
    queryFn: ({ signal }) => getJson<AiUsage>("/v1/ai/usage", { signal }),
  });

/**
 * How many libraries there are, and the versions and articles (of each default version) they
 * hold (#513): the library list carries both counts, so the pages are walked and summed.
 */
export const libraryCountsQueryOptions = () =>
  queryOptions({
    queryKey: [...LIBRARIES_KEY, "overview-counts"] as const,
    queryFn: async ({ signal }) => {
      const libraries: LibrarySummary[] = [];
      let cursor: string | null = null;
      let total = 0;
      for (let page = 0; page < MAX_LIBRARY_PAGES; page++) {
        const list: LibraryList = await getJson<LibraryList>("/v1/libraries", {
          signal,
          query: { limit: LIBRARY_PAGE, cursor },
        });
        libraries.push(...list.libraries);
        total = list.total;
        cursor = list.next_cursor;
        if (!cursor) break;
      }
      return countsOf(libraries, total);
    },
  });

/** How many libraries are listed under "needs attention" before "and N more". */
export const FAILING_SHOWN = 5;

/** Libraries whose latest sync (their newest import or refresh) failed (#512). */
export const failingLibrariesQueryOptions = () =>
  queryOptions({
    queryKey: [...LIBRARIES_KEY, "overview-failing"] as const,
    queryFn: ({ signal }) =>
      getJson<LibraryList>("/v1/libraries", {
        signal,
        query: { sync_state: ["failed"], limit: FAILING_SHOWN, sort: "-last_imported_at" },
      }),
  });
