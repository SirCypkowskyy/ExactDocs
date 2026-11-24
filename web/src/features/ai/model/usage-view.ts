import {
  parseFacet,
  parseTableSearch,
  type TableConfig,
  type TableSearch,
} from "@/shared/ui/data-table/table-search";
import { BUDGET_NEAR, budgetUsed, type ScopeUsage } from "./ai";

/*
 * The usage table's view (blocks-map §2.3, "AI usage"): one request brings every scope, so the
 * browser sorts, filters and pages it; the view still lives in the URL.
 */

/** What a scope is: the instance, embedding runs, a library or an account. */
export const SCOPE_KINDS = ["instance", "embedding", "library", "user"] as const;
/** Where a scope stands against its budgets: the tightest one decides. */
export const BUDGET_STATES = ["reached", "near", "within", "none"] as const;

export type ScopeKind = (typeof SCOPE_KINDS)[number];
export type BudgetState = (typeof BUDGET_STATES)[number];

/** Sorted by name, by what was spent today or this month, or by the share of a budget used. */
export const USAGE_TABLE: TableConfig = {
  id: "ai-usage",
  sortFields: ["name", "day", "month", "used"],
};

export interface UsageView extends TableSearch {
  scope?: ScopeKind[] | undefined;
  budget?: BudgetState[] | undefined;
}

/** Anything unknown in a shared or hand-edited URL is dropped. */
export const parseUsageView = (search: Record<string, unknown>): UsageView => ({
  ...parseTableSearch(search, USAGE_TABLE),
  scope: parseFacet(search.scope, SCOPE_KINDS),
  budget: parseFacet(search.budget, BUDGET_STATES),
});

/** The largest share of a budget a scope has used, in whole percent; -1 without a budget. */
export const mostUsed = (s: ScopeUsage): number =>
  s.budgets.length ? Math.max(...s.budgets.map(budgetUsed)) : -1;

/** Used up, near its ceiling (from 80 %), within it, or without any budget. */
export function budgetState(s: ScopeUsage): BudgetState {
  if (s.budgets.length === 0) return "none";
  if (s.budgets.some((b) => b.reached)) return "reached";
  return mostUsed(s) >= BUDGET_NEAR ? "near" : "within";
}
