import MarkdownIt, { type Token } from "markdown-it";

/**
 * The parser. It is the one the backend chunker uses (markdown-it, CommonMark plus tables), so a
 * heading has the same text, and so the same anchor, here as in `markdown_chunker.py`. Raw HTML
 * is parsed as `html_inline` / `html_block` tokens and the renderer shows it as text: it is never
 * turned into elements.
 */
export const md = new MarkdownIt("commonmark").enable(["table", "strikethrough"]);

/** Heading text without markup: ``The `x` *option*`` -> `The x option` (`_plain` in the chunker). */
export function plainText(inline: Token): string {
  let out = "";
  for (const child of inline.children ?? []) {
    if (child.type === "text" || child.type === "code_inline") out += child.content;
    else if (child.type === "image" && child.content) out += child.content;
    else if (child.type === "softbreak" || child.type === "hardbreak") out += " ";
  }
  return out.trim();
}

// Python's `\w` is every letter and number plus `_`; the chunker drops the rest but `-` and space.
const DROP = /[^\p{L}\p{N}_\- ]/gu;

/**
 * GitHub's slug (github-slugger), as `_anchor` in the chunker: lower-case, no punctuation, dashes
 * for spaces; a taken slug gets `-1`, `-2`... and every issued slug is remembered.
 */
export function slug(text: string, used: Set<string>): string {
  const base = text.toLowerCase().replace(DROP, "").replaceAll(" ", "-");
  let anchor = base;
  for (let n = 1; used.has(anchor); n++) anchor = `${base}-${n}`;
  used.add(anchor);
  return anchor;
}

export interface HeadingAnchor {
  text: string;
  anchor: string;
  /** Only top-level headings start a chunk; the others (in quotes, lists) still take a slug. */
  topLevel: boolean;
}

/** The anchor of every heading of a token stream, in document order, deduplicated across it. */
export function anchorsOf(tokens: readonly Token[]): Map<Token, HeadingAnchor> {
  const used = new Set<string>();
  const found = new Map<Token, HeadingAnchor>();
  tokens.forEach((token, i) => {
    const inline = tokens[i + 1];
    if (token.type !== "heading_open" || inline?.type !== "inline") return;
    const text = plainText(inline);
    found.set(token, { text, anchor: slug(text, used), topLevel: token.level === 0 });
  });
  return found;
}

export const headingAnchors = (markdown: string): HeadingAnchor[] => [
  ...anchorsOf(md.parse(markdown, {})).values(),
];
