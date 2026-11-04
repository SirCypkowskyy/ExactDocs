import { Check, Copy } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { tokensOf } from "./tokens";

function CopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);
  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard
          ?.writeText(code)
          .then(() => setCopied(true))
          .catch(() => {});
      }}
      className="doc-copy"
    >
      <Icon aria-hidden="true" className="size-3.5" />
      <span className="min-w-[3.25rem] text-left">{copied ? "Copied" : "Copy"}</span>
      <span className="sr-only">code</span>
    </button>
  );
}

/** A fenced block: the language, a copy button, and the code, coloured once its grammar has loaded. */
export function CodeBlock({ code, language }: { code: string; language?: string | undefined }) {
  const [marked, setMarked] = useState<{ code: string; nodes: ReactNode[] }>();
  useEffect(() => {
    if (!language) return;
    let live = true;
    import("./highlight")
      .then((m) => m.highlight(code, language))
      .then((markup) => {
        if (live && markup) setMarked({ code, nodes: tokensOf(markup) });
      })
      .catch(() => {}); // the plain text stays
    return () => {
      live = false;
    };
  }, [code, language]);
  const text = code.replace(/\n$/, "");
  return (
    <figure className="doc-code">
      <figcaption>
        <span>{language || "text"}</span>
        <CopyButton code={text} />
      </figcaption>
      {/* A scrollable region has to be reachable by keyboard. */}
      {/* biome-ignore lint/a11y/noNoninteractiveTabindex: scrollable code */}
      <pre tabIndex={0}>
        <code>{marked?.code === code ? marked.nodes : text}</code>
      </pre>
    </figure>
  );
}
