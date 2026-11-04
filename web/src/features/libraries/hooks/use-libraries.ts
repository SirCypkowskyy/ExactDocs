import { useQueries, useSuspenseQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { jobsQueryOptions, librariesQueryOptions } from "../api/libraries-query";
import { type Library, type Sync, syncOf } from "../model/library";

export function useLibraries() {
  return useSuspenseQuery(librariesQueryOptions());
}

export type SyncState = { status: "pending" } | { status: "error"; retry: () => void } | Sync;

/** One jobs query per library; the catalog list carries no job state. Keyed by library ID. */
export function useSyncStates(libraries: readonly Library[]): Map<string, SyncState> {
  return useQueries({
    queries: libraries.map((l) => jobsQueryOptions(l.id)),
    combine: (results) =>
      new Map(
        results.map((r, i): [string, SyncState] => [
          libraries[i]?.id ?? "",
          r.isError
            ? { status: "error", retry: () => void r.refetch() }
            : r.data
              ? syncOf(r.data)
              : { status: "pending" },
        ]),
      ),
  });
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
