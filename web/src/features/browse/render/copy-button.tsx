import { Check, Copy } from "lucide-react";
import { type RefObject, useEffect, useState } from "react";
import "./copy-button.css";

type State = "idle" | "copied" | "select" | "failed";
const LABEL: Record<State, string> = {
  idle: "Copy",
  copied: "Copied",
  select: "Press Ctrl+C",
  failed: "Copy failed",
};

function select(element: HTMLElement | null) {
  const selection = window.getSelection();
  if (!(element && selection)) return;
  const range = document.createRange();
  range.selectNodeContents(element);
  selection.removeAllRanges();
  selection.addRange(range);
}

/**
 * Copies `text`. The clipboard API only exists in a secure context, and a self-hosted instance is
 * often served over plain http: there the text is selected instead and the label says what to press.
 */
export function CopyButton({
  text,
  target,
  what = "code",
}: {
  text: string;
  /** The element to select when the clipboard API is missing. */
  target: RefObject<HTMLElement | null>;
  what?: string;
}) {
  const [state, setState] = useState<State>("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 1800);
    return () => clearTimeout(timer);
  }, [state]);
  async function copy() {
    if (!navigator.clipboard) {
      select(target.current);
      setState("select");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      select(target.current);
      setState("failed");
    }
  }
  const Icon = state === "copied" ? Check : Copy;
  return (
    <button type="button" className="doc-copy" onClick={() => void copy()}>
      <Icon aria-hidden="true" className="size-3.5" />
      <span role="status" className="min-w-[4.5rem] text-left">
        {LABEL[state]}
      </span>
      <span className="sr-only">{what}</span>
    </button>
  );
}
