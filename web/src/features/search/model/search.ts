import type { components } from "@/shared/lib/api-schema";

export type SearchResults = components["schemas"]["SearchDocsResult"];
export type SearchHit = components["schemas"]["SearchResultOut"];
export type TagMatch = "any" | "all";
export type TagCount = components["schemas"]["TagList"];

/** The API's input caps (docs/rest-api.md): the query is 1000 characters, a filter 20 tags. */
export const MAX_QUERY = 1000;
const MAX_TAGS = 20;
const MAX_TAG_LENGTH = 100;

/** The query as sent: surrounding space dropped, capped; `undefined` when nothing is left. */
export function normalizeQuery(raw: string | undefined): string | undefined {
  const text = (raw ?? "").trim().slice(0, MAX_QUERY).trim();
  return text === "" ? undefined : text;
}

export const parseTags = (tags: string | undefined): string[] =>
  (tags ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

/** Tags as sent: what the API accepts, at most 20. */
export const sendableTags = (tags: readonly string[]): string[] =>
  tags.filter((t) => t.length <= MAX_TAG_LENGTH).slice(0, MAX_TAGS);

export interface Piece {
  /** Where it starts in the snippet (in characters): a stable key. */
  at: number;
  text: string;
  hit: boolean;
}

/**
 * Cuts a snippet into plain and highlighted pieces from `[start, end)` spans. The API counts
 * characters (code points), JavaScript strings count UTF-16 units, so the cut goes by code
 * point: an emoji before a match must not shift it. Spans outside the text are clipped,
 * overlapping ones merged. The result is text only; React escapes it.
 */
export function highlightPieces(
  snippet: string,
  spans: readonly { start: number; end: number }[],
): Piece[] {
  const chars = Array.from(snippet);
  const clip = (n: number) => Math.min(Math.max(n, 0), chars.length);
  const merged: [number, number][] = [];
  const sorted = spans
    .map((s) => [clip(s.start), clip(s.end)] as [number, number])
    .filter(([a, b]) => b > a)
    .sort((x, y) => x[0] - y[0]);
  for (const [a, b] of sorted) {
    const last = merged[merged.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else merged.push([a, b]);
  }
  const pieces: Piece[] = [];
  let at = 0;
  for (const [a, b] of merged) {
    if (a > at) pieces.push({ at, text: chars.slice(at, a).join(""), hit: false });
    pieces.push({ at: a, text: chars.slice(a, b).join(""), hit: true });
    at = b;
  }
  if (at < chars.length) pieces.push({ at, text: chars.slice(at).join(""), hit: false });
  return pieces;
}

/** "the match count, once": one sentence for the live region. */
export function countLabel(count: number, q: string, ref: string, complete: boolean): string {
  if (count === 0) return `No results for “${q}” in ${ref}`;
  const noun = count === 1 ? "result" : "results";
  return `${complete ? count : `Top ${count}`} ${noun} for “${q}” in ${ref}`;
}
