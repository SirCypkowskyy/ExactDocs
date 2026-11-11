import type { AiProvider, AiRole } from "@/shared/lib/ai-queries";
import type { components } from "@/shared/lib/api-schema";

export type LibraryRetrieval = components["schemas"]["LibraryRetrievalOut"];
export type LibraryRetrievalBody = components["schemas"]["LibraryRetrievalIn"];
type Budgets = components["schemas"]["LibraryBudgets"];
export type RetrievalMode = components["schemas"]["RetrievalMode"];
type ModelRole = components["schemas"]["ModelRole"];
type FallbackReason = components["schemas"]["FallbackReason"];

/** The roles a library may override. Never the embedding model: one per instance. */
export const OVERRIDABLE = ["llm", "judge", "reranker"] as const;
export type OverridableRole = (typeof OVERRIDABLE)[number];

export const MODE_LABEL: Record<RetrievalMode, string> = {
  bm25: "BM25",
  hybrid: "Hybrid",
  hybrid_hyde: "Hybrid with HyDE",
  agentic: "Agentic",
};

/** What each mode does, in the order a search runs it. */
const MODE_STEPS: Record<RetrievalMode, readonly string[]> = {
  bm25: ["Keyword search (BM25)"],
  hybrid: ["Keyword search (BM25)", "Vector search with the embedding model", "Results merged"],
  hybrid_hyde: [
    "The LLM writes a hypothetical answer (HyDE)",
    "Keyword search (BM25)",
    "Vector search with the embedding model",
    "Results merged",
  ],
  agentic: ["An LLM agent opens and reads the docs"],
};

const FALLBACK_WORDS: Partial<Record<FallbackReason, string>> = {
  mode_unavailable: "The mode set for it can't run now: a model role it needs is not configured.",
  vector_store_unavailable: "The vector store can't be loaded, so the vector modes are off.",
};

export const MAX_RERANK_TOP_N = 200;

/** Where the effective mode comes from, in words. */
export function modeSource(r: LibraryRetrieval): string {
  if (r.fallback_reason) {
    return FALLBACK_WORDS[r.fallback_reason] ?? `It fell back (${r.fallback_reason}).`;
  }
  if (!r.ai_enabled) return "AI is off for this library.";
  if (r.mode) return "Set for this library.";
  if (r.instance_mode) return "The instance's default.";
  return "The best mode the instance has configured.";
}

/** The steps the effective pipeline runs, a reranker last when one is configured. */
export function pipelineSteps(r: LibraryRetrieval): string[] {
  const steps = [...MODE_STEPS[r.effective_mode]];
  if (r.configured_roles.includes("reranker")) {
    steps.push(`The reranker reorders the best ${r.effective_rerank_top_n}`);
  }
  return steps;
}

export interface RoleInUse {
  role: ModelRole;
  model: string | undefined;
  from: "library" | "instance";
}

/**
 * The model each role a search may use resolves to: the library's override, else the instance's
 * (the judge: else the LLM). `roles` is undefined when the instance's roles could not be read.
 */
export function rolesInUse(r: LibraryRetrieval, roles: readonly AiRole[] | undefined): RoleInUse[] {
  const instance = (role: ModelRole) => roles?.find((x) => x.role === role)?.model ?? undefined;
  return r.configured_roles.map((role) => {
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
  rerankTopN: string;
  dailyUsd: string;
  monthlyUsd: string;
  dailyTokens: string;
  monthlyTokens: string;
}

export type DraftErrors = Partial<Record<Exclude<keyof RetrievalDraft, "aiEnabled">, string>>;

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
    rerankTopN: text(r.rerank_top_n),
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
    rerank_top_n: num(d.rerankTopN),
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
export function modeOptions(r: LibraryRetrieval, d: RetrievalDraft) {
  const available: readonly RetrievalMode[] = d.aiEnabled ? r.available_modes : ["bm25"];
  const options = available.map((m) => ({ value: m, label: MODE_LABEL[m], disabled: false }));
  const stored = r.mode;
  if (stored && !available.includes(stored)) {
    options.push({ value: stored, label: `${MODE_LABEL[stored]} (can't run now)`, disabled: true });
  }
  return options;
}

/**
 * The profiles an override may name: only those this server can call. A profile an override
 * still names that is gone or unsupported stays listed, marked, so the form shows the truth.
 */
export function profileOptions(providers: readonly AiProvider[], current: string) {
  const usable = providers.filter((p) => !p.unsupported).map((p) => ({ value: p.name, note: "" }));
  if (current && !usable.some((p) => p.value === current)) {
    usable.push({ value: current, note: " (not available)" });
  }
  return usable;
}

const ceilingWord = (n: number | null | undefined, unit: string) =>
  n === null || n === undefined ? undefined : `${n.toLocaleString("en-US")} ${unit}`;

/** The most each budget may be, as a hint. */
export function ceilingHint(ceilings: Budgets | undefined, key: keyof Budgets, unit: string) {
  const most = ceilingWord(ceilings?.[key], unit);
  return most ? `At most ${most}, the instance's limit.` : "The instance sets no limit here.";
}

const BUDGET_FIELDS = [
  ["dailyUsd", "daily_usd", "USD", false],
  ["monthlyUsd", "monthly_usd", "USD", false],
  ["dailyTokens", "daily_tokens", "tokens", true],
  ["monthlyTokens", "monthly_tokens", "tokens", true],
] as const;

/** The checks that need no server; the server stays the authority. */
export function validateRetrieval(d: RetrievalDraft, ceilings: Budgets | undefined): DraftErrors {
  const errors: DraftErrors = {};
  for (const role of OVERRIDABLE) {
    if (d[role].profile && !d[role].model.trim()) errors[role] = "Name the model to use.";
  }
  const top = d.rerankTopN.trim();
  if (top && !(/^\d+$/.test(top) && Number(top) >= 1 && Number(top) <= MAX_RERANK_TOP_N)) {
    errors.rerankTopN = `Enter a whole number from 1 to ${MAX_RERANK_TOP_N}, or leave it empty.`;
  }
  for (const [field, key, unit, whole] of BUDGET_FIELDS) {
    const raw = d[field].trim();
    if (!raw) continue;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || (whole && !Number.isInteger(value))) {
      errors[field] = whole
        ? "Enter a whole number of tokens above 0, or leave it empty."
        : "Enter an amount above 0, or leave it empty.";
      continue;
    }
    const most = ceilings?.[key];
    if (most !== null && most !== undefined && value > most) {
      errors[field] = `The instance allows a library at most ${ceilingWord(most, unit)}.`;
    }
  }
  return errors;
}
