import { queryOptions } from "@tanstack/react-query";
import { getJson, sendJson } from "@/shared/lib/http";
import { AI_KEY } from "@/shared/lib/query-keys";
import type { LibraryRetrieval, LibraryRetrievalBody } from "../model/retrieval";

const path = (owner: string, repo: string) =>
  `/v1/libraries/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/retrieval` as const;

/** The library's retrieval mode, AI overrides and own budgets, and what its searches run now. */
export const libraryRetrievalQueryOptions = (owner: string, repo: string) =>
  queryOptions({
    queryKey: [...AI_KEY, "library", owner, repo] as const,
    queryFn: ({ signal }) => getJson<LibraryRetrieval>(path(owner, repo), { signal }),
  });

/** Replace every retrieval setting of the library (admins). */
export const saveLibraryRetrieval = (owner: string, repo: string, body: LibraryRetrievalBody) =>
  sendJson<LibraryRetrieval>("PUT", path(owner, repo), body);
