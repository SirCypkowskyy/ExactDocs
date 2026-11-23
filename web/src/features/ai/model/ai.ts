import type { AiProvider } from "@/shared/lib/ai-queries";
import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";
import { currentLanguage, type Language, messagesFor } from "@/shared/lib/i18n";
import { messages } from "../messages";

export type ModelCheck = components["schemas"]["ModelCheckOut"];
export type ModelChecks = components["schemas"]["ModelChecksOut"];
export type EmbeddingProgress = components["schemas"]["EmbeddingProgressOut"];
export type SpaceProgress = components["schemas"]["EmbeddingSpaceProgressOut"];
export type AiUsage = components["schemas"]["AiUsageOut"];
export type ScopeUsage = components["schemas"]["ScopeUsageOut"];
export type Budget = components["schemas"]["BudgetOut"];

/** Where a profile's key comes from. The key itself never reaches the browser. */
export function keyWords(p: AiProvider, language: Language = currentLanguage()): string {
  const t = messagesFor(messages, language).providers.key;
  switch (p.key) {
    case "sealed":
      return t.sealed;
    case "file":
      return t.file;
    case "environment":
      return t.environment;
    default:
      return t.none;
  }
}

export function originWords(p: AiProvider, language: Language = currentLanguage()): string {
  const t = messagesFor(messages, language).providers;
  return p.origin === "configuration" ? t.fromConfiguration : t.fromApi;
}

/** A share of a whole as a whole percent; 100 only when nothing is left. */
export function percent(part: number, whole: number): number {
  if (whole <= 0) return 100;
  const p = Math.floor((part / whole) * 100);
  return part >= whole ? 100 : Math.min(p, 99);
}

export function scopeName(s: ScopeUsage, language: Language = currentLanguage()): string {
  const t = messagesFor(messages, language).usage.scopes;
  switch (s.scope) {
    case "instance":
      return t.instance;
    case "embedding":
      return t.embedding;
    case "library":
      return t.library(s.id);
    default:
      return t.account(s.id);
  }
}

/** One budget in words: its ceilings and what is left of them. */
export function budgetWords(b: Budget, language: Language = currentLanguage()): string {
  const t = messagesFor(messages, language);
  const parts: string[] = [];
  if (b.usd_limit !== null) parts.push(t.usage.usdLeft(t.usd(b.usd_left ?? 0), t.usd(b.usd_limit)));
  if (b.tokens_limit !== null) parts.push(t.usage.tokensLeft(b.tokens_left ?? 0, b.tokens_limit));
  return t.usage.budget(b.window === "day" ? "day" : "month", parts.join(", "));
}

/** Why a library's budget is lower than the one it set: the instance's lower limit applies. */
export function ownBudgetNote(b: Budget, language: Language = currentLanguage()): string | null {
  const t = messagesFor(messages, language);
  const own: string[] = [];
  if (b.own_usd_limit != null) own.push(t.usd(b.own_usd_limit));
  if (b.own_tokens_limit != null) own.push(t.usage.tokens(b.own_tokens_limit));
  if (own.length === 0) return null;
  return t.usage.ownBudget(own.join(", "));
}

export function checkWords(c: ModelCheck, language: Language = currentLanguage()): string {
  const t = messagesFor(messages, language).providers;
  if (c.status === "error") return c.error ?? t.callFailed;
  return t.answered(Math.round(c.latency_ms), c.served_model, c.dimensions);
}

/** A failed read or check, in words. */
export function explainAiError(error: unknown, language: Language = currentLanguage()): string {
  const t = messagesFor(messages, language).errors;
  if (!(error instanceof HttpError)) return t.offline;
  if (error.status === 401) return t.sessionEnded;
  if (error.status === 403) return t.adminsOnly;
  if (error.code === "vector_store_unavailable") return error.message;
  if (error.status === 404 || error.status === 422) return error.message;
  return t.other(error.status);
}

/** How much of a budget is used, as a whole percent: the tighter of its dollar and token ceilings. */
export function budgetUsed(b: Budget): number {
  if (b.reached) return 100;
  const shares: number[] = [];
  if (b.usd_limit) shares.push(1 - (b.usd_left ?? 0) / b.usd_limit);
  if (b.tokens_limit) shares.push(1 - (b.tokens_left ?? 0) / b.tokens_limit);
  return Math.round(Math.max(0, ...shares) * 100);
}

/** A budget is near its ceiling from this share of it on. */
export const BUDGET_NEAR = 80;
