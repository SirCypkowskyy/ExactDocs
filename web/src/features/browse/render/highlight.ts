import type { LanguageFn } from "highlight.js";
import hljs from "highlight.js/lib/core";
import { MAX_BLOCK } from "./limits";

// Each grammar is its own chunk, fetched the first time a block of that language is shown.
const GRAMMARS: Record<string, () => Promise<{ default: LanguageFn }>> = {
  bash: () => import("highlight.js/lib/languages/bash"),
  c: () => import("highlight.js/lib/languages/c"),
  cpp: () => import("highlight.js/lib/languages/cpp"),
  csharp: () => import("highlight.js/lib/languages/csharp"),
  css: () => import("highlight.js/lib/languages/css"),
  diff: () => import("highlight.js/lib/languages/diff"),
  dockerfile: () => import("highlight.js/lib/languages/dockerfile"),
  go: () => import("highlight.js/lib/languages/go"),
  ini: () => import("highlight.js/lib/languages/ini"),
  java: () => import("highlight.js/lib/languages/java"),
  javascript: () => import("highlight.js/lib/languages/javascript"),
  json: () => import("highlight.js/lib/languages/json"),
  markdown: () => import("highlight.js/lib/languages/markdown"),
  php: () => import("highlight.js/lib/languages/php"),
  python: () => import("highlight.js/lib/languages/python"),
  ruby: () => import("highlight.js/lib/languages/ruby"),
  rust: () => import("highlight.js/lib/languages/rust"),
  sql: () => import("highlight.js/lib/languages/sql"),
  typescript: () => import("highlight.js/lib/languages/typescript"),
  xml: () => import("highlight.js/lib/languages/xml"),
  yaml: () => import("highlight.js/lib/languages/yaml"),
};

const ALIASES: Record<string, string> = {
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  "c++": "cpp",
  "c#": "csharp",
  cs: "csharp",
  golang: "go",
  toml: "ini",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  node: "javascript",
  json5: "json",
  jsonc: "json",
  md: "markdown",
  mdx: "javascript",
  py: "python",
  python3: "python",
  rb: "ruby",
  rs: "rust",
  ts: "typescript",
  tsx: "typescript",
  html: "xml",
  svg: "xml",
  vue: "xml",
  yml: "yaml",
};

/** The grammar that highlights a fence's language, or undefined when there is none (plain text). */
export function grammarOf(language: string): string | undefined {
  const name = language.toLowerCase();
  const grammar = (Object.hasOwn(ALIASES, name) ? ALIASES[name] : undefined) ?? name;
  return Object.hasOwn(GRAMMARS, grammar) ? grammar : undefined;
}

/** highlight.js's markup for `code`: escaped text and `<span class="hljs-…">` only. */
export async function highlight(code: string, language: string): Promise<string | undefined> {
  const grammar = code.length > MAX_BLOCK ? undefined : grammarOf(language);
  const load = grammar && GRAMMARS[grammar];
  if (!(grammar && load)) return undefined;
  if (!hljs.getLanguage(grammar)) hljs.registerLanguage(grammar, (await load()).default);
  return hljs.highlight(code, { language: grammar, ignoreIllegals: true }).value;
}
