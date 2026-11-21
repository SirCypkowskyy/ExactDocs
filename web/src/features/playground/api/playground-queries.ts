import { queryOptions } from "@tanstack/react-query";
import { getJson, type QueryOf } from "@/shared/lib/http";
import { SEARCH_ALL_KEY } from "@/shared/lib/query-keys";
import type {
  AnswerAvailability,
  LibrarySummary,
  PlaygroundMode,
  PlaygroundResults,
} from "../model/playground";

const RESULT_LIMIT = 20;

/** The libraries the caller may read, for the multi-select. */
export const playgroundLibrariesQueryOptions = () =>
  queryOptions({
    queryKey: [...SEARCH_ALL_KEY, "playground", "libraries"] as const,
    queryFn: ({ signal }) => getJson<{ libraries: LibrarySummary[] }>("/v1/libraries", { signal }),
    select: (data) => data.libraries,
  });

/** One mode's search across the chosen libraries (none: every readable one). */
export const playgroundSearchQueryOptions = (
  q: string,
  mode: PlaygroundMode,
  libraries: readonly string[],
) =>
  queryOptions({
    // Under SEARCH_ALL_KEY, so whatever invalidates the global search drops these too.
    queryKey: [...SEARCH_ALL_KEY, "playground", q, mode, [...libraries].sort()] as const,
    queryFn: ({ signal }) => {
      const query: QueryOf<"/api/v1/search"> = {
        q,
        mode,
        limit: RESULT_LIMIT,
        ...(libraries.length > 0 && { library: libraries }),
      };
      return getJson<PlaygroundResults>("/v1/search", { signal, query });
    },
    enabled: q.trim() !== "",
    retry: false,
  });

/** Whether the agent can answer now (an `llm` role is configured), and why not. */
export const answerAvailabilityQueryOptions = () =>
  queryOptions({
    queryKey: [...SEARCH_ALL_KEY, "playground", "answer-availability"] as const,
    queryFn: ({ signal }) => getJson<AnswerAvailability>("/v1/answer", { signal }),
  });
