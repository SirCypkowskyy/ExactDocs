import { queryOptions } from "@tanstack/react-query";
import { getJson, HttpError, sendJson } from "@/shared/lib/http";
import type {
  AddedLibrary,
  AddLibraryCommand,
  CheckedRepository,
  RepositoryRefs,
} from "../model/add-library";
import type { Job } from "../model/library";
import { librariesKeys } from "./libraries-query";

export const checkRepository = (url: string) =>
  sendJson<CheckedRepository>("POST", "/v1/repositories/check", { url });

export const addLibrary = (command: AddLibraryCommand) =>
  sendJson<AddedLibrary>("POST", "/v1/libraries", command);

export const repositoryRefsQueryOptions = (url: string) =>
  queryOptions({
    queryKey: [...librariesKeys.all, "refs", url] as const,
    queryFn: ({ signal }) =>
      getJson<RepositoryRefs>(`/v1/repositories/refs?url=${encodeURIComponent(url)}`, { signal }),
    staleTime: 60_000,
  });

const live = (state: string | undefined) => state === "queued" || state === "running";

/** One import job with its problems, polled until it finishes. */
export const importJobQueryOptions = (id: string) =>
  queryOptions({
    queryKey: [...librariesKeys.job(id), "progress"] as const,
    queryFn: ({ signal }) => getJson<Job>(`/v1/jobs/${encodeURIComponent(id)}`, { signal }),
    refetchInterval: (query) => {
      const { data, error } = query.state;
      // A 4xx will not fix itself; only a live job or a network/server hiccup is worth polling.
      if (error instanceof HttpError && error.status < 500) return false;
      return data && !live(data.state) ? false : 1500;
    },
  });
