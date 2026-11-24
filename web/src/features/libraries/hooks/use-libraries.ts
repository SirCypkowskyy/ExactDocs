import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { latestJobsQueryOptions, librariesKeys } from "../api/libraries-query";
import { type LatestJob, type Sync, syncOf } from "../model/library";

export type SyncState = { status: "pending" } | { status: "error" } | Sync;

export interface SyncStates {
  /** A library's sync, from the newest job of each of its versions. */
  syncOf: (library: string) => SyncState;
  /** Libraries whose sync failed, and those importing now, across every library (not one page). */
  failed: number;
  running: number;
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
export function useSyncStates(): SyncStates {
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
    return new Map([...byLibrary].map(([id, jobs]) => [id, syncOf(jobs)]));
  }, [data]);
  const kinds = [...syncs.values()].map((s) => s.kind);
  return {
    syncOf: (library) =>
      data
        ? (syncs.get(library) ?? { kind: "none" })
        : isError
          ? { status: "error" }
          : { status: "pending" },
    failed: kinds.filter((k) => k === "failed").length,
    running: kinds.filter((k) => k === "running").length,
    failedToLoad: isError && !data,
    loading: !data && !isError,
    retry: () => void refetch(),
  };
}
