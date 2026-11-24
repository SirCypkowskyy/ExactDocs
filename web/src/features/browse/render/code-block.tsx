import { type ReactNode, useEffect, useRef, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { messages } from "../messages";
import { CopyButton } from "./copy-button";
import { type Budget, inTurn } from "./limits";
import { tokensOf } from "./tokens";

const LABELS: Record<string, string> = {
  ts: "TypeScript",
  typescript: "TypeScript",
  tsx: "TSX",
  js: "JavaScript",
  javascript: "JavaScript",
  jsx: "JSX",
  py: "Python",
  python: "Python",
  sh: "Shell",
  bash: "Shell",
  shell: "Shell",
  zsh: "Shell",
  json: "JSON",
  yaml: "YAML",
  yml: "YAML",
  toml: "TOML",
  html: "HTML",
  css: "CSS",
  sql: "SQL",
  diff: "Diff",
  go: "Go",
  rust: "Rust",
  rs: "Rust",
  md: "Markdown",
  mdx: "MDX",
};

/** The name shown above a block: a known language in full, anything else as written, `plain` for none. */
const languageLabel = (language: string | undefined, plain: string) =>
  language
    ? Object.hasOwn(LABELS, language.toLowerCase())
      ? LABELS[language.toLowerCase()]
      : language
    : plain;

/**
 * A fenced block: the language, a copy button, and the code, coloured when the browser is idle and
 * its grammar has loaded. A block that is too long, or past the article's budget, stays plain.
 */
export function CodeBlock({
  code,
  language,
  budget,
}: {
  code: string;
  language?: string | undefined;
  budget?: Budget | undefined;
}) {
  const t = useMessages(messages).render;
  const [marked, setMarked] = useState<{ code: string; nodes: ReactNode[] }>();
  const pre = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (!language || (budget && !budget.take(code.length))) return;
    let live = true;
    inTurn(async () => {
      if (!live) return;
      const markup = await import("./highlight").then((m) => m.highlight(code, language));
      if (live && markup) setMarked({ code, nodes: tokensOf(markup) });
    }).catch(() => {}); // the plain text stays
    return () => {
      live = false;
    };
  }, [code, language, budget]);
  const text = code.replace(/\n$/, "");
  return (
    <figure className="doc-code">
      <figcaption>
        <span>{languageLabel(language, t.plainText)}</span>
        <CopyButton text={text} target={pre} />
      </figcaption>
      {/* A scrollable region has to be reachable by keyboard. */}
      {/* biome-ignore lint/a11y/noNoninteractiveTabindex: scrollable code */}
      <pre ref={pre} tabIndex={0}>
        <code>{marked?.code === code ? marked.nodes : text}</code>
      </pre>
    </figure>
  );
}
