import { highlightPieces } from "./search";

/*
 * A search snippet is a slice of the article's Markdown source. Shown as is, it reads as markup
 * (`### retry_policy`, fences, `> [!NOTE]`, pipe tables). These blocks keep every word and every
 * match but drop the markup: headings go (the hit's crumbs already name the section), fences and
 * table rows become code lines, quotes and callouts become a quote with their label, and inline
 * `code` is marked as code.
 */

export interface Span {
  /** A key unique within the snippet (the offset where the span starts, or a negative id). */
  key: number;
  text: string;
  hit: boolean;
  code: boolean;
}

export interface Line {
  key: number;
  spans: Span[];
}

export type Block =
  | { kind: "text"; key: number; spans: Span[] }
  | { kind: "quote"; key: number; label: string | undefined; spans: Span[] }
  | { kind: "code"; key: number; lines: Line[] };

const CALLOUT = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION|DANGER)\]\s*/i;
const TABLE_RULE = /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** Splits the highlighted pieces into lines, each a list of spans keyed by their offsets. */
function splitLines(snippet: string, highlights: readonly { start: number; end: number }[]) {
  const out: { key: number; text: string; spans: Span[] }[] = [{ key: 0, text: "", spans: [] }];
  for (const piece of highlightPieces(snippet, highlights)) {
    let at = piece.at;
    piece.text.split("\n").forEach((part, i) => {
      if (i > 0) out.push({ key: at, text: "", spans: [] });
      const line = out[out.length - 1];
      if (line && part) {
        line.text += part;
        line.spans.push({ key: at, text: part, hit: piece.hit, code: false });
      }
      at += Array.from(part).length + 1;
    });
  }
  return out;
}

/** Drops the first `n` characters of a line's spans (a `> ` or `[!NOTE]` prefix). */
function dropPrefix(spans: Span[], n: number): Span[] {
  const out: Span[] = [];
  let left = n;
  for (const span of spans) {
    const chars = Array.from(span.text);
    if (left >= chars.length) {
      left -= chars.length;
      continue;
    }
    out.push({ ...span, key: span.key + left, text: chars.slice(left).join("") });
    left = 0;
  }
  return out;
}

/** Marks text between backticks as code and drops the backticks. */
function inlineCode(spans: Span[]): Span[] {
  const out: Span[] = [];
  let code = false;
  for (const span of spans) {
    let at = span.key;
    span.text.split("`").forEach((part, i) => {
      if (i > 0) code = !code;
      if (part) out.push({ ...span, key: at, text: part, code });
      at += Array.from(part).length + 1;
    });
  }
  return out;
}

export function snippetBlocks(
  snippet: string,
  highlights: readonly { start: number; end: number }[],
): Block[] {
  const blocks: Block[] = [];
  let fence: Line[] | null = null;
  // A quote goes on over its following `>` lines until a blank line.
  let inQuote = false;
  let spaces = 0;
  const push = (block: Block) => {
    inQuote = block.kind === "quote";
    blocks.push(block);
  };
  /** Appends spans to a block's text, a space between the lines it joins. */
  const join = (target: Span[], spans: Span[]) => {
    if (target.length > 0 && spans.length > 0) {
      spaces -= 1;
      target.push({ key: spaces, text: " ", hit: false, code: false });
    }
    target.push(...spans);
  };

  for (const line of splitLines(snippet, highlights)) {
    const trimmed = line.text.trim();
    const last = blocks[blocks.length - 1];
    if (/^(```|~~~)/.test(trimmed)) {
      if (fence) fence = null;
      else {
        fence = [];
        push({ kind: "code", key: line.key, lines: fence });
      }
      continue;
    }
    if (fence) {
      fence.push({ key: line.key, spans: line.spans });
      continue;
    }
    if (trimmed === "") {
      inQuote = false;
      continue;
    }
    if (/^#{1,6}\s/.test(trimmed)) continue;
    if (trimmed.startsWith("|")) {
      if (TABLE_RULE.test(trimmed)) continue;
      if (last?.kind === "code") last.lines.push({ key: line.key, spans: line.spans });
      else push({ kind: "code", key: line.key, lines: [{ key: line.key, spans: line.spans }] });
      continue;
    }
    if (trimmed.startsWith(">")) {
      const start = line.text.trimStart();
      let body = start.replace(/^>\s?/, "");
      let spans = dropPrefix(line.spans, line.text.length - body.length);
      const callout = CALLOUT.exec(body);
      let label: string | undefined;
      if (callout) {
        const word = callout[1] ?? "";
        label = word.charAt(0) + word.slice(1).toLowerCase();
        spans = dropPrefix(spans, callout[0].length);
        body = body.slice(callout[0].length);
      }
      if (inQuote && last?.kind === "quote" && !label) join(last.spans, inlineCode(spans));
      else push({ kind: "quote", key: line.key, label, spans: inlineCode(spans) });
      continue;
    }
    const spans = inlineCode(line.spans);
    if (last?.kind === "text") join(last.spans, spans);
    else push({ kind: "text", key: line.key, spans });
  }
  return blocks.filter((b) =>
    b.kind === "code" ? b.lines.length > 0 : b.spans.length > 0 || b.kind === "quote",
  );
}

/** The snippet stops mid-sentence: the reader should see that more follows. */
export const isCut = (snippet: string) => !/[.!?:)\]`"'”]\s*$/.test(snippet.trim());
