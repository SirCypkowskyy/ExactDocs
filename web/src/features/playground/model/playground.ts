import type { components } from "@/shared/lib/api-schema";

export type PlaygroundResults = components["schemas"]["SearchAllResult"];
export type PlaygroundHit = components["schemas"]["LibrarySearchResultOut"];
export type LibrarySummary = components["schemas"]["LibrarySummary"];
export type FallbackReason = NonNullable<PlaygroundResults["fallback_reason"]>;

/** The retrieval modes a search across libraries can run in. */
export const PLAYGROUND_MODES = ["bm25", "vector", "hybrid"] as const;
export type PlaygroundMode = (typeof PLAYGROUND_MODES)[number];

export const MODE_LABEL: Record<PlaygroundMode, string> = {
  bm25: "BM25 (keywords)",
  vector: "Vector (embeddings)",
  hybrid: "Hybrid (BM25 + vectors)",
};

/** What the playground runs: one query, the chosen libraries (none: all) and one or two modes. */
export interface PlaygroundRun {
  q: string;
  libraries: readonly string[];
  first: PlaygroundMode;
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
