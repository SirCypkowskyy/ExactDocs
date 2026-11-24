import type { components } from "@/shared/lib/api-schema";
import {
  parseChoice,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";

/*
 * The leaderboard (blocks-map §5.3, #510): libraries or people ranked by reads, searches or agent
 * answers over a UTC day, ISO week, month or year. The board's choice lives in the URL, beside
 * the view of the table that lists ranks 11 and up.
 */

export type Leaderboard = components["schemas"]["Leaderboard"];
export type Entry = components["schemas"]["LeaderboardEntryOut"];
export type UsageSettings = components["schemas"]["UsageSettingsOut"];

export const SUBJECTS = ["libraries", "people"] as const;
export const METRICS = ["reads", "searches", "answers"] as const;
export const PERIODS = ["day", "week", "month", "year"] as const;
export type Subject = (typeof SUBJECTS)[number];
export type Metric = (typeof METRICS)[number];
export type Period = (typeof PERIODS)[number];

/** What the page shows when the URL names nothing (never written to the URL). */
export const DEFAULTS = { subject: "libraries", metric: "reads", period: "week" } as const;

/** The columns show the first ten; the table the rest of what the API lists. */
export const TOP = 10;
/** How many entries the page asks for (the API's default; it allows up to 200). */
export const LIMIT = 100;

/** Ranks 11 to 100 in the browser: sorted by rank (the default), name or value. */
export const LEADERBOARD_TABLE: TableConfig = {
  id: "leaderboard",
  sortFields: ["rank", "name", "value"],
  defaultSort: "rank",
  maxRows: LIMIT - TOP,
};

export interface LeaderboardView extends TableSearch {
  subject?: Subject | undefined;
  metric?: Metric | undefined;
  period?: Period | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped; a default is left out. */
export function parseLeaderboardView(search: Record<string, unknown>): LeaderboardView {
  const pick = <T extends string>(value: unknown, options: readonly T[], fallback: T) => {
    const chosen = parseChoice(value, options);
    return chosen === fallback ? undefined : chosen;
  };
  return {
    ...parseTableSearch(search, LEADERBOARD_TABLE),
    subject: pick(search.subject, SUBJECTS, DEFAULTS.subject),
    metric: pick(search.metric, METRICS, DEFAULTS.metric),
    period: pick(search.period, PERIODS, DEFAULTS.period),
  };
}

export interface Board {
  subject: Subject;
  metric: Metric;
  period: Period;
}

/** The board to show: people only while the operator has the people board on. */
export const boardOf = (view: LeaderboardView, peopleOn: boolean): Board => ({
  subject: view.subject === "people" && peopleOn ? "people" : "libraries",
  metric: view.metric ?? DEFAULTS.metric,
  period: view.period ?? DEFAULTS.period,
});

/** The entry's name: the library ID or the username. */
export const nameOf = (e: Entry): string => e.library ?? e.username ?? "";

/** The entry's key: the library ID or the account ID (a username can be renamed). */
export const keyOf = (e: Entry): string => e.library ?? e.account_id ?? e.username ?? "";

/** How the rank moved against the previous period. */
export type Movement =
  | { kind: "up" | "down"; by: number; from: number }
  | { kind: "same"; from: number }
  | { kind: "new" };

export function movementOf(e: Entry): Movement {
  const from = e.previous_rank;
  if (from === null) return { kind: "new" };
  if (from === e.rank) return { kind: "same", from };
  return from > e.rank
    ? { kind: "up", by: from - e.rank, from }
    : { kind: "down", by: e.rank - from, from };
}

/** An entry's share of the whole period, in whole percent (0 when nothing was counted). */
export const shareOf = (value: number, total: number): number =>
  total > 0 ? Math.round((value / total) * 100) : 0;

/** A column's fill against the top value, 0 to 1 (a value of 0 still shows as empty). */
export const fillOf = (value: number, max: number): number => (max > 0 ? value / max : 0);
