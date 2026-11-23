import type { components } from "@/shared/lib/api-schema";

export type PlaygroundResults = components["schemas"]["SearchAllResult"];
export type PlaygroundHit = components["schemas"]["LibrarySearchResultOut"];
export type LibrarySummary = components["schemas"]["LibrarySummary"];
export type FallbackReason = NonNullable<PlaygroundResults["fallback_reason"]>;
export type AnswerResult = components["schemas"]["AnswerResult"];
export type AnswerSource = components["schemas"]["AnswerSourceOut"];
export type AnswerAvailability = components["schemas"]["AnswerAvailabilityOut"];

/** The retrieval modes a search across libraries can run in. */
export const PLAYGROUND_MODES = ["bm25", "vector", "hybrid"] as const;
export type PlaygroundMode = (typeof PLAYGROUND_MODES)[number];

export const MODE_LABEL: Record<PlaygroundMode, string> = {
  bm25: "BM25 (keywords)",
  vector: "Vector (embeddings)",
  hybrid: "Hybrid (BM25 + vectors)",
};

/** The agent writes an answer instead of ranking chunks; it is not a retrieval mode. */
export const AGENT = "agent" as const;
export type PlaygroundChoice = PlaygroundMode | typeof AGENT;

/** What the playground runs: one query, the chosen libraries (none: all) and one or two modes. */
export interface PlaygroundRun {
  q: string;
  libraries: readonly string[];
  first: PlaygroundChoice;
  /** The mode compared side by side, if any. */
  second?: PlaygroundMode;
}

const FALLBACK_WORDS: Partial<Record<FallbackReason, string>> = {
  embedding_in_progress: "No chosen library is embedded with the current model yet.",
  embedding_unavailable: "The embedding model failed on the query.",
  vector_store_unavailable: "The vector store can't be loaded here.",
  llm_budget_reached: "A budget the query embedding counts to is used up.",
  mode_unavailable: "The mode can't run now.",
};

/** Why BM25 answered instead of the mode asked for, in a sentence. */
export function fallbackSentence(reason: FallbackReason): string {
  return `BM25 answered instead: ${FALLBACK_WORDS[reason] ?? reason}`;
}

/** The ranks a result holds, e.g. `["BM25 #1", "vector #4"]`. */
export function rankLabels(hit: Pick<PlaygroundHit, "bm25_rank" | "vector_rank">): string[] {
  const labels: string[] = [];
  if (hit.bm25_rank != null) labels.push(`BM25 #${hit.bm25_rank}`);
  if (hit.vector_rank != null) labels.push(`vector #${hit.vector_rank}`);
  return labels;
}

/**
 * How many libraries a search ranked its results from: the chosen ones, or every one searched
 * when none is chosen. `libraries_searched` alone is not it: it counts every library whose
 * matches are counted, and those counts are never narrowed to the chosen libraries (#479).
 */
export function librariesRanked(
  chosen: readonly string[],
  data: Pick<PlaygroundResults, "libraries_searched">,
): number {
  if (chosen.length === 0) return data.libraries_searched;
  return new Set(chosen.map((id) => id.toLowerCase())).size; // the API takes each library once
}

/** Libraries that can be searched: those with a default version, by ID. */
export function searchableLibraries(libraries: readonly LibrarySummary[]): string[] {
  return libraries
    .filter((l) => l.default_version !== null)
    .map((l) => l.id)
    .sort();
}

/** `/owner/repo` as route params. */
export function splitLibrary(id: string): { owner: string; repo: string } {
  const [owner = "", repo = ""] = id.split("/").filter(Boolean);
  return { owner, repo };
}

/** What an agent run has made so far, out of what it may make. */
export interface AnswerProgress {
  toolCalls: number;
  maxToolCalls: number;
}

/** Why the agent did not answer, in a sentence. */
const NO_ANSWER_WORDS: Partial<Record<NonNullable<AnswerResult["fallback_reason"]>, string>> = {
  agent_limit_reached: "The agent used up its tool calls or time before it could answer.",
  agent_loop_detected: "The agent repeated itself and was stopped.",
  agent_failed: "The agent failed.",
  llm_budget_reached: "A budget this run counts to is used up.",
  llm_rate_limited: "Too many LLM searches this minute.",
  mode_unavailable: "No chosen library may be sent to the LLM (AI is off for it).",
};

export function noAnswerSentence(reason: NonNullable<AnswerResult["fallback_reason"]>): string {
  return NO_ANSWER_WORDS[reason] ?? reason;
}

/** Tokens and, when the model has a price, what they cost. */
export function spendSentence(usage: AnswerResult["usage"]): string {
  const tokens = `${usage.input_tokens.toLocaleString("en-US")} in / ${usage.output_tokens.toLocaleString("en-US")} out tokens`;
  const cost = usage.cost_usd === null ? "" : `, $${usage.cost_usd.toFixed(4)}`;
  return `${usage.requests} model request${usage.requests === 1 ? "" : "s"}, ${tokens}${cost}`;
}
