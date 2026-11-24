import type { components } from "@/shared/lib/api-schema";
import { currentLanguage, type Language, messagesFor } from "@/shared/lib/i18n";
import { messages } from "../messages";

export type SearchResults = components["schemas"]["SearchDocsResult"];
export type SearchHit = components["schemas"]["SearchResultOut"];
export type TagMatch = "any" | "all";

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
 * overlapping ones merged. The result is text only; React escapes it. A span may split a base
 * character from its combining mark: that renders as two nodes and reads the same.
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

/** The count and where it was found, as one sentence for the live region. */
export function countLabel(
  count: number,
  q: string,
  ref: string,
  complete: boolean,
  language: Language = currentLanguage(),
): string {
  return messagesFor(messages, language).status.version(count, q, ref, complete);
}
