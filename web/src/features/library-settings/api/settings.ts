import { type QueryClient, queryOptions } from "@tanstack/react-query";
import { getJson, sendJson } from "@/shared/lib/http";
import { BROWSE_KEY, LIBRARIES_KEY } from "@/shared/lib/query-keys";
import type {
  AddedVersion,
  JobList,
  LibraryAccess,
  ReimportedVersion,
  RemovalResult,
  SavedSettings,
  SelectionDraft,
  SettingsLibrary,
  SyncedLibrary,
} from "../model/settings";
import { settingsOf } from "../model/settings";

const seg = encodeURIComponent;
const lib = (owner: string, repo: string) => `/v1/libraries/${seg(owner)}/${seg(repo)}` as const;
/** A ref may hold slashes (`release/2`): the route takes the rest of the path, so keep them. */
const refPath = (ref: string) => ref.split("/").map(seg).join("/");

export const saveDetails = (
  owner: string,
  repo: string,
  patch: { title?: string; description?: string },
) => sendJson<SettingsLibrary>("PATCH", lib(owner, repo), patch);

/** How many of the library's newest jobs are read to find its last re-processing. */
const RECENT_JOBS = 50;

/**
 * The library's newest `reprocess` or `retag` job, or null: one that failed is offered again.
 * Under the browse key, so every library refresh (and a finished job line) reloads it.
 */
export const lastReprocessQueryOptions = (owner: string, repo: string) =>
  queryOptions({
    queryKey: [...BROWSE_KEY, owner, repo, "reprocess"] as const,
    queryFn: async ({ signal }) => {
      const { jobs } = await getJson<JobList>(`${lib(owner, repo)}/jobs`, {
        signal,
        query: { limit: RECENT_JOBS },
      });
      return jobs.find((j) => j.kind === "reprocess" || j.kind === "retag") ?? null;
    },
  });

/** Whether the library has a stored credential: a preview cannot use it yet. */
export const accessQueryOptions = (owner: string, repo: string) =>
  queryOptions({
    queryKey: [...BROWSE_KEY, owner, repo, "access"] as const,
    queryFn: ({ signal }) => getJson<LibraryAccess>(`${lib(owner, repo)}/access`, { signal }),
    staleTime: 60_000,
  });

/** Replace the paths and tag rules as a whole; a 202 carries the job re-processing every version. */
export const saveSelection = (owner: string, repo: string, draft: SelectionDraft) =>
  sendJson<SavedSettings>("PUT", `${lib(owner, repo)}/settings`, settingsOf(draft));

export const addVersion = (owner: string, repo: string, ref: string) =>
  sendJson<AddedVersion>("POST", `${lib(owner, repo)}/versions`, { ref });

/** The ref goes in the body: a ref may hold slashes, so nothing could follow it in the path. */
export const reimportVersion = (owner: string, repo: string, ref: string) =>
  sendJson<ReimportedVersion>("POST", `${lib(owner, repo)}/versions/reimport`, { ref });

export const syncLibrary = (owner: string, repo: string) =>
  sendJson<SyncedLibrary>("POST", `${lib(owner, repo)}/sync`);

export const removeVersion = (owner: string, repo: string, ref: string) =>
  sendJson<RemovalResult>("DELETE", `${lib(owner, repo)}/versions/${refPath(ref)}`);

export const removeLibrary = (owner: string, repo: string) =>
  sendJson<RemovalResult>("DELETE", lib(owner, repo));

/** Everything that shows a library's versions, text or sync state must reload after a change. */
export function refreshLibraries(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: LIBRARIES_KEY });
  void queryClient.invalidateQueries({ queryKey: BROWSE_KEY });
}

/**
 * After a library is removed: drop what was cached for it and reload the list. Call this after
 * leaving the library's pages, or the page still mounted would refetch a library that is gone.
 */
export function forgetLibrary(queryClient: QueryClient, owner: string, repo: string) {
  queryClient.removeQueries({ queryKey: [...BROWSE_KEY, owner, repo] });
  void queryClient.invalidateQueries({ queryKey: LIBRARIES_KEY });
}
