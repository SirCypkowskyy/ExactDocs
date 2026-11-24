import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import { type Board, type Leaderboard, LIMIT, type UsageSettings } from "../model/leaderboard";

const STATS_KEY = ["stats"] as const;

/** Whether the operator turned the people board on, and how long counts are kept (#510). */
export const statsSettingsQueryOptions = () =>
  queryOptions({
    queryKey: [...STATS_KEY, "settings"] as const,
    queryFn: ({ signal }) => getJson<UsageSettings>("/v1/stats/settings", { signal }),
    staleTime: 5 * 60_000,
  });

/**
 * One board over the current period so far. Switching keeps the previous board on screen until
 * the next arrives, so the columns move from where they are instead of emptying first.
 */
export const leaderboardQueryOptions = (board: Board) =>
  queryOptions({
    queryKey: [...STATS_KEY, "leaderboard", board.subject, board.metric, board.period] as const,
    queryFn: ({ signal }) =>
      getJson<Leaderboard>("/v1/stats/leaderboard", { signal, query: { ...board, limit: LIMIT } }),
    placeholderData: keepPreviousData,
  });
