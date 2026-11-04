import type { ReactNode } from "react";

const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#x27;": "'",
};
const decode = (text: string) =>
  text.replace(/&(?:amp|lt|gt|quot|#x27);/g, (e) => ENTITIES[e] ?? e);

/**
 * highlight.js's markup as elements. It only ever contains escaped text and `<span class="hljs-…">`,
 * so this reads those two and nothing else; no HTML string is ever handed to the DOM.
 */
export function tokensOf(markup: string): ReactNode[] {
  const root: ReactNode[] = [];
  const stack: { class: string; nodes: ReactNode[] }[] = [];
  for (const part of markup.split(/(<span class="[^"]*">|<\/span>)/)) {
    const open = /^<span class="([^"]*)">$/.exec(part);
    if (open) {
      stack.push({ class: open[1] ?? "", nodes: [] });
    } else if (part === "</span>") {
      const done = stack.pop();
      const parent = stack.at(-1)?.nodes ?? root;
      if (done) {
        parent.push(
          <span key={parent.length} className={done.class}>
            {done.nodes}
          </span>,
        );
      }
    } else if (part) {
      (stack.at(-1)?.nodes ?? root).push(decode(part));
    }
  }
  return root;
}
