import type { KeyboardEvent } from "react";
import { highlightPieces, type SearchHit } from "../model/search";

export const retry =
  "inline-flex h-11 cursor-pointer items-center rounded-md bg-secondary px-3 text-sm font-medium outline-none transition-[background-color,transform] duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] lg:h-9";

export function Snippet({ hit }: { hit: Pick<SearchHit, "snippet" | "highlights"> }) {
  return (
    <p className="mt-1.5 text-[15px] leading-[1.6] whitespace-pre-line text-foreground/90 [overflow-wrap:anywhere]">
      {highlightPieces(hit.snippet, hit.highlights).map((piece) =>
        piece.hit ? (
          // No horizontal padding: a match inside a word ("RetryPolicy") must not open a gap in it.
          <mark
            key={piece.at}
            className="rounded-[3px] bg-mark/[0.22] text-foreground [box-decoration-break:clone]"
          >
            {piece.text}
          </mark>
        ) : (
          <span key={piece.at}>{piece.text}</span>
        ),
      )}
    </p>
  );
}

/** `A › B › C`; deeper than three levels shows `A › … › C` (the full path is the tooltip). */
export function Crumbs({ hit }: { hit: Pick<SearchHit, "heading_path" | "article_path"> }) {
  const path = hit.heading_path;
  const all = path.length > 0 ? path : [hit.article_path.split("/").pop() ?? hit.article_path];
  const crumbs = all.length > 3 ? [all[0] ?? "", "…", all[all.length - 1] ?? ""] : all;
  return (
    <span
      title={all.length > 3 ? all.join(" › ") : undefined}
      className="block font-serif text-lg leading-snug font-semibold [overflow-wrap:anywhere]"
    >
      {crumbs.map((crumb, i) => (
        <span
          key={crumbs.slice(0, i + 1).join("\u0000")}
          className={i < crumbs.length - 1 ? "font-normal text-muted-foreground" : ""}
        >
          {i > 0 && (
            <>
              <span aria-hidden="true" className="px-1.5 text-muted-foreground/70">
                ›
              </span>
              <span className="sr-only"> / </span>
            </>
          )}
          {crumb}
        </span>
      ))}
    </span>
  );
}

export const onArrows = (inputId: string) => (event: KeyboardEvent<HTMLElement>) => {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const links = [...event.currentTarget.querySelectorAll<HTMLElement>("a[data-result]")];
  const at = links.indexOf(document.activeElement as HTMLElement);
  if (at < 0) return;
  event.preventDefault();
  if (event.key === "ArrowUp" && at === 0) document.getElementById(inputId)?.focus();
  else
    links[
      Math.min(Math.max(at + (event.key === "ArrowDown" ? 1 : -1), 0), links.length - 1)
    ]?.focus();
};
