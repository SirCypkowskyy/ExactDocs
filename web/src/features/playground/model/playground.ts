import type { components } from "@/shared/lib/api-schema";
import { currentLanguage, type Language, messagesFor } from "@/shared/lib/i18n";
import { messages } from "../messages";

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

/** Why BM25 answered instead of the mode asked for, in a sentence. */
export function fallbackSentence(
  reason: FallbackReason,
  language: Language = currentLanguage(),
): string {
  const t = messagesFor(messages, language).results;
  const words: Partial<Record<FallbackReason, string>> = t.fallbacks;
  return t.fallback(words[reason] ?? reason);
}

/** The ranks a result holds, e.g. `["BM25 #1", "vector #4"]`. */
export function rankLabels(
  hit: Pick<PlaygroundHit, "bm25_rank" | "vector_rank">,
  language: Language = currentLanguage(),
): string[] {
  const t = messagesFor(messages, language).results;
  const labels: string[] = [];
  if (hit.bm25_rank != null) labels.push(t.bm25Rank(hit.bm25_rank));
  if (hit.vector_rank != null) labels.push(t.vectorRank(hit.vector_rank));
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
export function noAnswerSentence(
  reason: NonNullable<AnswerResult["fallback_reason"]>,
  language: Language = currentLanguage(),
): string {
  const words: Partial<Record<FallbackReason, string>> = messagesFor(messages, language).agent
    .noAnswers;
  return words[reason] ?? reason;
}
