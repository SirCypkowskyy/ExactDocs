import type { AiProvider, AiRole, ThinkingLevel } from "@/shared/lib/ai-queries";
import type { components } from "@/shared/lib/api-schema";
import { currentLanguage, type Language, messagesFor } from "@/shared/lib/i18n";
import { retrievalMessages } from "../messages/retrieval";

export type LibraryRetrieval = components["schemas"]["LibraryRetrievalOut"];
export type LibraryRetrievalBody = components["schemas"]["LibraryRetrievalIn"];
type Budgets = components["schemas"]["LibraryBudgets"];
type RetrievalMode = components["schemas"]["RetrievalMode"];
type ModelRole = components["schemas"]["ModelRole"];
type FallbackReason = components["schemas"]["FallbackReason"];
export type RerankWith = components["schemas"]["RerankWith"];

/** The ways a library's searches may be reranked; their labels are in `messages/retrieval`. */
export const RERANK_WITH: readonly RerankWith[] = ["cross_encoder", "judge"];

export type RepoGuidance = components["schemas"]["RepoGuidance"];

/** What the repository's AGENTS.md / CLAUDE.md do for the agent, in the order of trust. */
export const REPO_GUIDANCE: readonly RepoGuidance[] = ["off", "notes", "trusted"];

/** The roles a library may override. Never the embedding model: one per instance. */
export const OVERRIDABLE = ["llm", "judge", "reranker"] as const;
export type OverridableRole = (typeof OVERRIDABLE)[number];

type Words = (typeof retrievalMessages)[Language];
type Step = Exclude<keyof Words["steps"], "reranker" | "judge">;

/** What each mode does, in the order a search runs it; the words are in `messages/retrieval`. */
const MODE_STEPS: Record<RetrievalMode, readonly Step[]> = {
  bm25: ["keyword"],
  vector: ["vector"],
  hybrid: ["keyword", "vector", "merged"],
  hybrid_hyde: ["hyde", "keyword", "vector", "merged"],
  agentic: ["agentBrowses", "agentChecked"],
};

/** The model roles each mode's pipeline calls; the reranker is a stage of its own. */
const MODE_ROLES: Record<RetrievalMode, readonly ModelRole[]> = {
  bm25: [],
  vector: ["embedding"],
  hybrid: ["embedding"],
  hybrid_hyde: ["embedding", "llm"],
  agentic: ["llm"],
};

/** The fallbacks said in words of their own; any other is named by its code. */
const FALLBACKS: readonly FallbackReason[] = [
  "agent_limit_reached",
  "agent_failed",
  "agent_loop_detected",
  "mode_unavailable",
  "vector_store_unavailable",
];
type WordedFallback = Exclude<keyof Words["fallback"], "other">;
const worded = (reason: FallbackReason): reason is WordedFallback & FallbackReason =>
  FALLBACKS.includes(reason);

export const MAX_RERANK_TOP_N = 200;

/** Where the effective mode comes from, in words. */
export function modeSource(r: LibraryRetrieval, language: Language = currentLanguage()): string {
  const m = messagesFor(retrievalMessages, language);
  if (r.fallback_reason) {
    return worded(r.fallback_reason)
      ? m.fallback[r.fallback_reason]
      : m.fallback.other(r.fallback_reason);
  }
  if (!r.ai_enabled) return m.source.aiOff;
  if (r.mode) return m.source.library;
  if (r.instance_mode) return m.source.instance;
  return m.source.best;
}

/** The steps the effective pipeline runs, the reranker or the LLM judge last when one reranks. */
export function pipelineSteps(
  r: LibraryRetrieval,
  language: Language = currentLanguage(),
): string[] {
  const m = messagesFor(retrievalMessages, language).steps;
  const steps = MODE_STEPS[r.effective_mode].map((step) => m[step]);
  if (r.effective_mode === "agentic" && r.repo_guidance !== "off") {
    steps.splice(1, 0, r.repo_guidance === "trusted" ? m.guidanceTrusted : m.guidanceNotes);
  }
  const top = r.effective_rerank_top_n;
  if (r.effective_reranker === "cross_encoder") {
    steps.push(m.reranker(top));
  } else if (r.effective_reranker === "judge") {
    steps.push(m.judge(top));
  }
  return steps;
}

/** The role that reranks the library's searches now, if one does. */
const RERANK_ROLE: Record<RerankWith, ModelRole> = { cross_encoder: "reranker", judge: "judge" };

export interface RoleInUse {
  role: ModelRole;
  model: string | undefined;
  from: "library" | "instance";
}

/**
 * The model each role the effective pipeline calls resolves to: the library's override, else the instance's
 * (the judge: else the LLM). `roles` is undefined when the instance's roles could not be read.
 */
export function rolesInUse(r: LibraryRetrieval, roles: readonly AiRole[] | undefined): RoleInUse[] {
  const instance = (role: ModelRole) => roles?.find((x) => x.role === role)?.model ?? undefined;
  const used = new Set<ModelRole>(MODE_ROLES[r.effective_mode]);
  if (r.effective_reranker) used.add(RERANK_ROLE[r.effective_reranker]);
  return r.configured_roles
    .filter((role) => used.has(role))
    .map((role) => {
      const own = role === "embedding" ? null : r[role];
      if (own) return { role, model: own, from: "library" };
      const model = instance(role) ?? (role === "judge" ? instance("llm") : undefined);
      return { role, model, from: "instance" };
    });
}

/** One override as edited: no profile means the instance's model. */
export interface RoleDraft {
  profile: string;
  model: string;
}

export interface RetrievalDraft {
  /** `""`: the instance's mode. */
  mode: string;
  aiEnabled: boolean;
  llm: RoleDraft;
  judge: RoleDraft;
  reranker: RoleDraft;
  /** `""`: the instance's level. */
  llmThinking: "" | ThinkingLevel;
  /** `""`: the instance's level. */
  judgeThinking: "" | ThinkingLevel;
  rerankTopN: string;
  /** `""`: the instance's choice. */
  rerankWith: "" | RerankWith;
  repoGuidance: RepoGuidance;
  dailyUsd: string;
  monthlyUsd: string;
  dailyTokens: string;
  monthlyTokens: string;
}

export type DraftErrors = Partial<
  Record<
    Exclude<keyof RetrievalDraft, "aiEnabled" | "repoGuidance" | "llmThinking" | "judgeThinking">,
    string
  >
>;

/** The roles whose model takes a thinking level, and their draft field (#421). */
export const THINKING_ROLES = [
  ["llm", "llmThinking"],
  ["judge", "judgeThinking"],
] as const;

/** What a library's empty thinking level means: the instance's level for the role, in words. */
export function instanceThinking(
  role: "llm" | "judge",
  roles: readonly AiRole[] | undefined,
  label: (level: ThinkingLevel) => string,
  language: Language = currentLanguage(),
): string {
  const m = messagesFor(retrievalMessages, language);
  const level = roles?.find((x) => x.role === role)?.thinking;
  return level ? m.instanceLevelOf(label(level)) : m.instanceLevel;
}

const roleDraft = (ref: string | null): RoleDraft => {
  if (!ref) return { profile: "", model: "" };
  const at = ref.indexOf(":");
  return { profile: ref.slice(0, at), model: ref.slice(at + 1) };
};

const text = (n: number | null | undefined) => (n === null || n === undefined ? "" : String(n));

export function retrievalDraftOf(r: LibraryRetrieval): RetrievalDraft {
  const b = r.budgets ?? {};
  return {
    mode: r.mode ?? "",
    aiEnabled: r.ai_enabled,
    llm: roleDraft(r.llm),
    judge: roleDraft(r.judge),
    reranker: roleDraft(r.reranker),
    llmThinking: r.llm_thinking ?? "",
    judgeThinking: r.judge_thinking ?? "",
    rerankTopN: text(r.rerank_top_n),
    rerankWith: r.rerank_with ?? "",
    repoGuidance: r.repo_guidance,
    dailyUsd: text(b.daily_usd),
    monthlyUsd: text(b.monthly_usd),
    dailyTokens: text(b.daily_tokens),
    monthlyTokens: text(b.monthly_tokens),
  };
}

const ref = (d: RoleDraft) => (d.profile ? `${d.profile}:${d.model.trim()}` : null);
const num = (s: string) => (s.trim() === "" ? null : Number(s));

/** The request body: every setting, since a save replaces what the library had. */
export function bodyOf(d: RetrievalDraft): LibraryRetrievalBody {
  return {
    mode: d.mode || null,
    ai_enabled: d.aiEnabled,
    llm: ref(d.llm),
    judge: ref(d.judge),
    reranker: ref(d.reranker),
    llm_thinking: d.llmThinking || null,
    judge_thinking: d.judgeThinking || null,
    rerank_top_n: num(d.rerankTopN),
    rerank_with: d.rerankWith || null,
    repo_guidance: d.repoGuidance,
    budgets: {
      daily_usd: num(d.dailyUsd),
      monthly_usd: num(d.monthlyUsd),
      daily_tokens: num(d.dailyTokens),
      monthly_tokens: num(d.monthlyTokens),
    },
  };
}

export function sameDraft(a: RetrievalDraft, b: RetrievalDraft): boolean {
  return JSON.stringify(bodyOf(a)) === JSON.stringify(bodyOf(b));
}

/**
 * The modes the select offers. Only what can run: the server's list, or BM25 alone once AI is
 * switched off in the form. A stored mode that can no longer run stays visible, marked.
 */
export function modeOptions(
  r: LibraryRetrieval,
  d: RetrievalDraft,
  language: Language = currentLanguage(),
) {
  const words = messagesFor(retrievalMessages, language);
  const available: readonly RetrievalMode[] = d.aiEnabled ? r.available_modes : ["bm25"];
  const options = available.map((m) => ({ value: m, label: words.modes[m], disabled: false }));
  const stored = r.mode;
  if (stored && !available.includes(stored)) {
    options.push({ value: stored, label: words.cantRunNow(words.modes[stored]), disabled: true });
  }
  return options;
}

/**
 * The profiles an override may name: only those this server can call. A profile an override
 * still names that is gone or unsupported stays listed, marked, so the form shows the truth.
 */
export function profileOptions(
  providers: readonly AiProvider[] | undefined,
  current: string,
  language: Language = currentLanguage(),
) {
  // Not read yet (or not readable): offer the stored one as it is, never call it missing.
  if (providers === undefined) return current ? [{ value: current, note: "" }] : [];
  const usable = providers.filter((p) => !p.unsupported).map((p) => ({ value: p.name, note: "" }));
  if (current && !usable.some((p) => p.value === current)) {
    usable.push({ value: current, note: messagesFor(retrievalMessages, language).notAvailable });
  }
  return usable;
}

/** What a budget is counted in. */
type BudgetUnit = "USD" | "tokens";

const ceilingWord = (n: number | null | undefined, unit: BudgetUnit, m: Words) =>
  n === null || n === undefined ? undefined : m.amount[unit](n);

const over = (value: number | null | undefined, most: number | null | undefined) =>
  value !== null && value !== undefined && most !== null && most !== undefined && value > most;

/**
 * The most each budget may be, as a hint. A stored budget the instance's limit was lowered
 * below since is said plainly: the instance's limit is what applies.
 */
export function ceilingHint(
  ceilings: Budgets | undefined,
  key: keyof Budgets,
  unit: BudgetUnit,
  stored?: Budgets,
  language: Language = currentLanguage(),
) {
  const m = messagesFor(retrievalMessages, language);
  const most = ceilingWord(ceilings?.[key], unit, m);
  if (most && over(stored?.[key], ceilings?.[key])) return m.ceilingAbove(most);
  return most ? m.ceilingAtMost(most) : m.noCeiling;
}

const BUDGET_FIELDS = [
  ["dailyUsd", "daily_usd", "USD", false],
  ["monthlyUsd", "monthly_usd", "USD", false],
  ["dailyTokens", "daily_tokens", "tokens", true],
  ["monthlyTokens", "monthly_tokens", "tokens", true],
] as const;

/** The checks that need no server; the server stays the authority. */
export function validateRetrieval(
  d: RetrievalDraft,
  ceilings: Budgets | undefined,
  stored?: Budgets,
  language: Language = currentLanguage(),
): DraftErrors {
  const m = messagesFor(retrievalMessages, language);
  const errors: DraftErrors = {};
  for (const role of OVERRIDABLE) {
    if (d[role].profile && !d[role].model.trim()) errors[role] = m.nameModel;
  }
  const top = d.rerankTopN.trim();
  if (top && !(/^\d+$/.test(top) && Number(top) >= 1 && Number(top) <= MAX_RERANK_TOP_N)) {
    errors.rerankTopN = m.wholeTopN(MAX_RERANK_TOP_N);
  }
  for (const [field, key, unit, whole] of BUDGET_FIELDS) {
    const raw = d[field].trim();
    if (!raw) continue;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || (whole && !Number.isInteger(value))) {
      errors[field] = whole ? m.wholeTokens : m.amountAbove;
      continue;
    }
    const most = ceilings?.[key];
    // A stored budget above a since-lowered limit may stay, or come down; never go up.
    const kept = stored?.[key];
    const allowed = kept !== null && kept !== undefined && value <= kept;
    if (over(value, most) && !allowed) {
      errors[field] = m.instanceAllows(ceilingWord(most, unit, m) ?? "");
    }
  }
  return errors;
}
