import { sendJson } from "@/shared/lib/http";
import type { SyncedLibrary } from "../model/library";

const seg = encodeURIComponent;

/** Sync a library now: import its branch versions whose tip moved (tags never move this way). */
export const syncLibrary = (library: string) => {
  const [, owner = "", repo = ""] = library.split("/");
  return sendJson<SyncedLibrary | null>("POST", `/v1/libraries/${seg(owner)}/${seg(repo)}/sync`);
};
