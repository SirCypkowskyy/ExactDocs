import type { QueryClient } from "@tanstack/react-query";
import { sendJson } from "@/shared/lib/http";
import { BROWSE_KEY, LIBRARIES_KEY } from "@/shared/lib/query-keys";
import type { LibraryDetail } from "../model/browse";

const seg = encodeURIComponent;
const pinPath = (owner: string, repo: string) =>
  `/v1/libraries/${seg(owner)}/${seg(repo)}/default-version` as const;

/** Pin `ref` as the library's default version; the ref travels in the body (it may hold `/`). */
export const pinDefault = (owner: string, repo: string, ref: string) =>
  sendJson<LibraryDetail>("PUT", pinPath(owner, repo), { ref });

/** Drop the pin: the default follows the default-version rule again. */
export const unpinDefault = (owner: string, repo: string) =>
  sendJson<LibraryDetail>("DELETE", pinPath(owner, repo));

/** The default flag shows on the browse page and in the libraries list: reload both. */
export function refreshDefault(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: BROWSE_KEY });
  void queryClient.invalidateQueries({ queryKey: LIBRARIES_KEY });
}
