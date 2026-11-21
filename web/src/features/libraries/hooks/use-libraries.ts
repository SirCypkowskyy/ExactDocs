import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import {
  latestJobsQueryOptions,
  librariesKeys,
  librariesQueryOptions,
} from "../api/libraries-query";
import { type LatestJob, type Library, type Sync, syncOf } from "../model/library";
import type { ListView } from "../model/list-view";

/** The pages loaded so far, flattened, with the server's total for the current filters. */
export function useLibraries(view: ListView) {
  const query = useInfiniteQuery(librariesQueryOptions(view));
  const pages = query.data?.pages ?? [];
  return {
    query,
    libraries: pages.flatMap((p) => p.libraries),
    total: pages.at(-1)?.total ?? 0,
  };
}

export type SyncState = { status: "pending" } | { status: "error" } | Sync;

export interface SyncStates {
  syncs: ReadonlyMap<string, SyncState>;
  /** True when the jobs could not be loaded; the list itself is fine. */
  failedToLoad: boolean;
  /** True until the first answer; counts of failures are not known before. */
  loading: boolean;
  retry: () => void;
}

const isLive = (j: LatestJob) => j.state === "queued" || j.state === "running";

/**
 * One request for every library's sync state (the catalog list carries no job state).
 * When a library stops importing, the list is refetched so its "last imported" is fresh.
 */
export function useSyncStates(libraries: readonly Library[]): SyncStates {
  const queryClient = useQueryClient();
  const query = useQuery(latestJobsQueryOptions());
  const importing = useRef(new Set<string>());
  useEffect(() => {
    const now = new Set((query.data ?? []).filter(isLive).map((j) => j.library));
    if ([...importing.current].some((id) => !now.has(id))) {
      void queryClient.invalidateQueries({ queryKey: librariesKeys.list() });
      // A finished import may have changed what an open browse page shows.
      void queryClient.invalidateQueries({ queryKey: BROWSE_KEY });
    }
    importing.current = now;
  }, [query.data, queryClient]);
  const { data, isError, refetch } = query;
  const syncs = useMemo(() => {
    const byLibrary = new Map<string, LatestJob[]>();
    for (const j of data ?? []) byLibrary.set(j.library, [...(byLibrary.get(j.library) ?? []), j]);
    return new Map<string, SyncState>(
      libraries.map((l) => [
        l.id,
        isError && !data
          ? { status: "error" }
          : data
            ? syncOf(byLibrary.get(l.id) ?? [])
            : { status: "pending" },
      ]),
    );
  }, [libraries, data, isError]);
  return {
    syncs,
    failedToLoad: isError && !data,
    loading: !data && !isError,
    retry: () => void refetch(),
  };
}

/** The clock, refreshed every minute so "3 minutes ago" stays true on a page left open. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);
  return now;
}
