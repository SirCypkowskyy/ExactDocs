import type { components } from "@/shared/lib/api-schema";

/*
 * The instance overview for operators (blocks-map §5.2): what the API answers, and the pure
 * shaping the page and its charts need. Days are UTC days (`YYYY-MM-DD`), as the API counts them.
 */

export type JobStats = components["schemas"]["JobStats"];
export type SpendHistory = components["schemas"]["SpendHistoryOut"];
export type UsageStats = components["schemas"]["UsageStats"];
export type AiUsage = components["schemas"]["AiUsageOut"];
type ScopeUsage = components["schemas"]["ScopeUsageOut"];
type Budget = components["schemas"]["BudgetOut"];
export type LibrarySummary = components["schemas"]["LibrarySummary"];
export type LibraryList = components["schemas"]["LibraryList"];

/** The chart ranges the page offers, in days. */
export const OVERVIEW_DAYS = [7, 30, 90] as const;
export type OverviewDays = (typeof OVERVIEW_DAYS)[number];
/** The range shown when the URL names none (it is never written to the URL). */
const DEFAULT_DAYS: OverviewDays = 30;

/** The page's view in the URL: `days=7|90` (30 is the default and left out). */
export interface OverviewView {
  days?: OverviewDays | undefined;
}

export function parseOverviewView(search: Record<string, unknown>): OverviewView {
  const days = Number(search.days);
  return {
    days:
      OVERVIEW_DAYS.includes(days as OverviewDays) && days !== DEFAULT_DAYS
        ? (days as OverviewDays)
        : undefined,
  };
}

export const daysOf = (view: OverviewView): OverviewDays => view.days ?? DEFAULT_DAYS;

const DAY_MS = 86_400_000;

/** The UTC day of a moment, as the API writes it. */
const utcDay = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/** The first day of a range of `days` UTC days that ends today (both included). */
export const firstDayOf = (days: number, now: number): string => utcDay(now - (days - 1) * DAY_MS);

/** One bar group of a chart: the day and a count per series. */
export type ChartRow = { day: string } & Record<string, number | string>;

export const JOB_STATES = ["succeeded", "failed", "running", "queued", "cancelled"] as const;
export type JobState = (typeof JOB_STATES)[number];

/** Jobs queued per day, by the state they are in now. */
export const jobRows = (stats: JobStats): ChartRow[] =>
  stats.days.map((d) => {
    const row: ChartRow = { day: d.day };
    for (const state of JOB_STATES) row[state] = d.by_state[state] ?? 0;
    return row;
  });

/** What the instance spent per day, in US dollars. */
export const spendRows = (history: SpendHistory): ChartRow[] =>
  history.entries.map((e) => ({ day: e.window_start, usd: e.usd }));

/** Reads, searches and agent answers per day. */
export const usageRows = (usage: UsageStats): ChartRow[] =>
  usage.series.map((b) => ({
    day: b.start,
    reads: b.reads,
    searches: b.searches,
    answers: b.answers,
  }));

/** The sum of one series over every row. */
export const sumOf = (rows: readonly ChartRow[], key: string): number =>
  rows.reduce((sum, row) => sum + Number(row[key] ?? 0), 0);

/** The row with the most of one series; the latest of equal ones. Undefined when all are 0. */
export function peakOf(rows: readonly ChartRow[], key: string): ChartRow | undefined {
  let peak: ChartRow | undefined;
  for (const row of rows) {
    const value = Number(row[key] ?? 0);
    if (value > 0 && (!peak || value >= Number(peak[key] ?? 0))) peak = row;
  }
  return peak;
}

/** The latest day's jobs: how many were queued and how many of them failed. */
export function todayOf(stats: JobStats): { total: number; failed: number } {
  const last = stats.days.at(-1);
  return { total: last?.total ?? 0, failed: last?.by_state.failed ?? 0 };
}

/** Libraries, and the versions and articles they hold, over every page of `GET /libraries`. */
export interface LibraryCounts {
  libraries: number;
  versions: number;
  articles: number;
}

export function countsOf(libraries: readonly LibrarySummary[], total: number): LibraryCounts {
  return {
    libraries: total,
    versions: libraries.reduce((sum, l) => sum + l.version_count, 0),
    articles: libraries.reduce((sum, l) => sum + l.article_count, 0),
  };
}

/** How much of a budget is used, as a whole percent: the tighter of its dollar and token ceilings. */
function budgetUsed(b: Budget): number {
  if (b.reached) return 100;
  const shares: number[] = [];
  if (b.usd_limit) shares.push(1 - (b.usd_left ?? 0) / b.usd_limit);
  if (b.tokens_limit) shares.push(1 - (b.tokens_left ?? 0) / b.tokens_limit);
  return Math.min(100, Math.round(Math.max(0, ...shares) * 100));
}

/** A budget counts as near its ceiling from this share of it on (as on the AI page). */
export const BUDGET_NEAR = 80;

export interface BudgetAlert {
  scope: ScopeUsage["scope"];
  id: string;
  window: "day" | "month";
  used: number;
  reached: boolean;
}

/** Every budget that is reached or near its ceiling, the fullest first. */
export function budgetAlerts(usage: AiUsage): BudgetAlert[] {
  const alerts: BudgetAlert[] = [];
  for (const s of usage.scopes) {
    for (const b of s.budgets) {
      const used = budgetUsed(b);
      if (b.reached || used >= BUDGET_NEAR) {
        alerts.push({
          scope: s.scope,
          id: s.id,
          window: b.window === "day" ? "day" : "month",
          used,
          reached: b.reached,
        });
      }
    }
  }
  return alerts.sort((a, b) => b.used - a.used);
}

/** The instance's spend this month and its monthly dollar budget, when one is set. */
export function monthSpendOf(usage: AiUsage): { usd: number; limit: number | null } {
  const instance = usage.scopes.find((s) => s.scope === "instance");
  const monthly = instance?.budgets.find((b) => b.window === "month" && b.usd_limit !== null);
  return { usd: instance?.month.usd ?? 0, limit: monthly?.usd_limit ?? null };
}
