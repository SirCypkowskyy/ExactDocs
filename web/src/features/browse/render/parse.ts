import MarkdownIt, { type Token } from "markdown-it";

/**
 * The parser. It is the one the backend chunker uses (markdown-it, CommonMark plus tables), so a
 * heading has the same text, and so the same anchor, here as in `markdown_chunker.py`. Raw HTML
 * is parsed as `html_inline` / `html_block` tokens and the renderer shows it as text: it is never
 * turned into elements.
 */
export const md = new MarkdownIt("commonmark").enable(["table", "strikethrough"]);

/** Heading text without markup: ``The `x` *option*`` -> `The x option` (`_plain` in the chunker). */
function plainText(inline: Token): string {
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
function slug(text: string, used: Set<string>): string {
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

type StateBlock = Parameters<Parameters<typeof md.block.ruler.before>[2]>[0];

// `!!! note "Title"` (MkDocs, Material) and `??? tip` / `???+ tip` (collapsible) with an indented body.
const MKDOCS = /^(!!!|\?\?\?\+?)[ \t]+([\w-]+)(?:[ \t]+"([^"]*)")?[ \t]*$/;

md.block.ruler.before(
  "paragraph",
  "mkdocs_admonition",
  (state: StateBlock, startLine: number, endLine: number, silent: boolean) => {
    const indent = (line: number) => (state.sCount[line] ?? 0) - state.blkIndent;
    if (indent(startLine) >= 4) return false;
    const from = (state.bMarks[startLine] ?? 0) + (state.tShift[startLine] ?? 0);
    const m = MKDOCS.exec(state.src.slice(from, state.eMarks[startLine]));
    const [, marker = "", kind = "", title] = m ?? [];
    if (!m) return false;
    if (silent) return true;
    const body: string[] = [];
    let last = startLine;
    for (let line = startLine + 1; line < endLine; line++) {
      if (state.isEmpty(line)) {
        body.push("");
        continue;
      }
      if (indent(line) < 4) break;
      body.push(state.getLines(line, line + 1, state.blkIndent + 4, false));
      last = line;
    }
    const token = state.push("admonition", "div", 0);
    token.block = true;
    token.map = [startLine, last + 1];
    token.info = kind.toLowerCase();
    token.content = body.slice(0, last - startLine).join("\n");
    token.meta = { title, collapsible: marker.startsWith("???"), open: marker === "???+" };
    state.line = last + 1;
    return true;
  },
);

// GitHub alerts: a block quote that starts with `[!NOTE]` (TIP, IMPORTANT, WARNING, CAUTION).
const ALERT = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\n|$)/i;

md.core.ruler.after("block", "github_alerts", (state) => {
  const tokens = state.tokens;
  for (let i = 0; i + 2 < tokens.length; i++) {
    const [quote, paragraph, inline] = [tokens[i], tokens[i + 1], tokens[i + 2]];
    if (quote?.type !== "blockquote_open" || paragraph?.type !== "paragraph_open") continue;
    const m = inline?.type === "inline" ? ALERT.exec(inline.content) : null;
    if (!(m && inline)) continue;
    quote.meta = { alert: (m[1] ?? "note").toLowerCase() };
    inline.content = inline.content.slice(m[0].length);
  }
});

export type Variant = "note" | "tip" | "warning" | "danger";

const VARIANTS: Record<string, Variant> = {
  tip: "tip",
  hint: "tip",
  success: "tip",
  check: "tip",
  done: "tip",
  warning: "warning",
  important: "warning",
  caution: "danger",
  attention: "warning",
  danger: "danger",
  error: "danger",
  failure: "danger",
  fail: "danger",
  missing: "danger",
  bug: "danger",
};

/** The four looks every admonition kind of either syntax maps to; unknown kinds are notes. */
export const variantOf = (kind: string): Variant => VARIANTS[kind.toLowerCase()] ?? "note";

/**
 * MDX is never run: a line that starts an `import`, an `export` or a component (`<Tabs>`,
 * `</Tab>`) is moved into a code block, so it shows as code. The Markdown around it still renders.
 */
const MDX_BLOCK = /^ {0,3}(?:(?:import|export)\s|<\/?(?:[A-Z][\w.]*|)(?:\s|\/|>|$))/;
const FENCE = /^ {0,3}(`{3,}|~{3,})/;

export function inertMdx(source: string): string {
  const out: string[] = [];
  let fence: string | undefined;
  let block: string[] | undefined;
  const flush = () => {
    if (block) out.push("````jsx", ...block, "````");
    block = undefined;
  };
  for (const line of source.split("\n")) {
    const marker = FENCE.exec(line)?.[1];
    if (fence) {
      if (marker && marker[0] === fence[0] && marker.length >= fence.length) fence = undefined;
      out.push(line);
    } else if (marker) {
      flush();
      fence = marker;
      out.push(line);
    } else if (line.trim() === "") {
      flush();
      out.push(line);
    } else if (block || MDX_BLOCK.test(line)) {
      block = [...(block ?? []), line];
    } else {
      out.push(line);
    }
  }
  flush();
  return out.join("\n");
}

// Task lists: `- [ ] todo` / `- [x] done`. The marker leaves the text and the item remembers it.
md.core.ruler.after("inline", "task_items", (state) => {
  const tokens = state.tokens;
  for (let i = 0; i + 2 < tokens.length; i++) {
    const [item, paragraph, inline] = [tokens[i], tokens[i + 1], tokens[i + 2]];
    if (item?.type !== "list_item_open" || paragraph?.type !== "paragraph_open") continue;
    const first = inline?.children?.[0];
    const m = first?.type === "text" ? /^\[( |x|X)\]\s/.exec(first.content) : null;
    if (!(m && first)) continue;
    item.meta = { task: m[1] === " " ? "todo" : "done" };
    first.content = first.content.slice(m[0].length);
  }
});
