import { Check, Copy } from "lucide-react";
import { type RefObject, useEffect, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { messages } from "../messages";
import "./copy-button.css";

type State = "idle" | "copied" | "select" | "failed";

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
  /** What is copied, said after the label to a screen reader. */
  what?: "code" | "file";
}) {
  const t = useMessages(messages).render;
  const c = useMessages(common);
  const label: Record<State, string> = {
    idle: c.copy,
    copied: c.copied,
    select: t.pressCtrlC,
    failed: t.copyFailed,
  };
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
        {label[state]}
      </span>
      <span className="sr-only">{t[what]}</span>
    </button>
  );
}
