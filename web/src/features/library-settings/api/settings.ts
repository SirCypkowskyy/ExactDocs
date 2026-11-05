import type { QueryClient } from "@tanstack/react-query";
import { sendJson } from "@/shared/lib/http";
import { BROWSE_KEY, LIBRARIES_KEY } from "@/shared/lib/query-keys";
import type {
  AddedVersion,
  ReimportedVersion,
  RemovalResult,
  SettingsLibrary,
  SyncedLibrary,
} from "../model/settings";

const seg = encodeURIComponent;
const lib = (owner: string, repo: string) => `/v1/libraries/${seg(owner)}/${seg(repo)}` as const;
/** A ref may hold slashes (`release/2`): the route takes the rest of the path, so keep them. */
const refPath = (ref: string) => ref.split("/").map(seg).join("/");

export const saveDetails = (
  owner: string,
  repo: string,
  patch: { title?: string; description?: string },
) => sendJson<SettingsLibrary>("PATCH", lib(owner, repo), patch);

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
