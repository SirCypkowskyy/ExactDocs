import type { AiProvider } from "@/shared/lib/ai-queries";
import type { components } from "@/shared/lib/api-schema";
import { HttpError } from "@/shared/lib/http";

export type ModelCheck = components["schemas"]["ModelCheckOut"];
export type ModelChecks = components["schemas"]["ModelChecksOut"];
export type EmbeddingProgress = components["schemas"]["EmbeddingProgressOut"];
export type SpaceProgress = components["schemas"]["EmbeddingSpaceProgressOut"];
export type AiUsage = components["schemas"]["AiUsageOut"];
export type ScopeUsage = components["schemas"]["ScopeUsageOut"];
export type Budget = components["schemas"]["BudgetOut"];

/** Where a profile's key comes from. The key itself never reaches the browser. */
export function keyWords(p: AiProvider): string {
  switch (p.key) {
    case "sealed":
      return "Key stored, sealed";
    case "file":
      return "Key read from a file";
    case "environment":
      return "Key from the environment";
    default:
      return "No key";
  }
}

export function originWords(p: AiProvider): string {
  return p.origin === "configuration" ? "Configuration (read-only)" : "Added over the API";
}

const usdFormat = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});
const countFormat = new Intl.NumberFormat("en-US");

export const usd = (n: number) => usdFormat.format(n);
export const count = (n: number) => countFormat.format(n);

/** A share of a whole as a whole percent; 100 only when nothing is left. */
export function percent(part: number, whole: number): number {
  if (whole <= 0) return 100;
  const p = Math.floor((part / whole) * 100);
  return part >= whole ? 100 : Math.min(p, 99);
}

export function scopeName(s: ScopeUsage): string {
  switch (s.scope) {
    case "instance":
      return "The instance";
    case "embedding":
      return "Embedding runs";
    case "library":
      return `Library ${s.id}`;
    default:
      return `Account ${s.id}`;
  }
}

/** One budget in words: its ceilings and what is left of them. */
export function budgetWords(b: Budget): string {
  const parts: string[] = [];
  if (b.usd_limit !== null) parts.push(`${usd(b.usd_left ?? 0)} of ${usd(b.usd_limit)} left`);
  if (b.tokens_limit !== null) {
    parts.push(`${count(b.tokens_left ?? 0)} of ${count(b.tokens_limit)} tokens left`);
  }
  return `${b.window === "day" ? "Today" : "This month"}: ${parts.join(", ")}`;
}

export function checkWords(c: ModelCheck): string {
  if (c.status === "error") return c.error ?? "The call failed.";
  const extra = c.dimensions ? `, ${c.dimensions} dimensions` : "";
  return `Answered in ${Math.round(c.latency_ms)} ms${c.served_model ? ` by ${c.served_model}` : ""}${extra}`;
}

/** A failed read or check, in words. */
export function explainAiError(error: unknown): string {
  if (!(error instanceof HttpError)) return "Can't reach the server. Check your connection.";
  if (error.status === 401) return "Your session ended. Sign in again.";
  if (error.status === 403) return "Only admins can see the instance's AI settings.";
  if (error.code === "vector_store_unavailable") return error.message;
  if (error.status === 404 || error.status === 422) return error.message;
  return `Something went wrong on the server (${error.status}). Try again in a moment.`;
}
