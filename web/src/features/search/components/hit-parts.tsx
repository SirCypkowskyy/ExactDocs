import { cn } from "@/shared/lib/utils";
import { codeWell } from "@/shared/ui/recipes";
import { Skeleton as Bar } from "@/shared/ui/skeleton";
import type { SearchHit } from "../model/search";
import { isCut, type Span, snippetBlocks } from "../model/snippet";

const inlineCode = "rounded-[3px] bg-code px-0.5 font-mono text-mono";

function Spans({ spans }: { spans: readonly Span[] }) {
  // No horizontal padding on a match: one inside a word ("RetryPolicy") must not open a gap in it.
  return spans.map((span) =>
    span.hit ? (
      <mark
        key={span.key}
        className="rounded-[3px] bg-route/[0.22] text-foreground [box-decoration-break:clone]"
      >
        {span.code ? <code className={inlineCode}>{span.text}</code> : span.text}
      </mark>
    ) : span.code ? (
      <code key={span.key} className={inlineCode}>
        {span.text}
      </code>
    ) : (
      <span key={span.key}>{span.text}</span>
    ),
  );
}

/** The matched passage as text: headings, fences, quotes and table markup read as what they are. */
export function Snippet({ hit }: { hit: Pick<SearchHit, "snippet" | "highlights"> }) {
  const blocks = snippetBlocks(hit.snippet, hit.highlights);
  const cut = isCut(hit.snippet);
  const lastKey = blocks.at(-1)?.key;
  return (
    <div className="mt-2 space-y-1.5 text-body leading-[1.6] text-foreground [overflow-wrap:anywhere]">
      {blocks.map((block) => {
        const more = cut && block.key === lastKey ? "…" : null;
        if (block.kind === "code") {
          const lastLine = block.lines.at(-1)?.key;
          return (
            <pre
              key={block.key}
              className={cn(
                codeWell,
                // Wraps instead of scrolling: a snippet is a glimpse, the article has the full line.
                "py-1.5 whitespace-pre-wrap",
              )}
            >
              {block.lines.map((line) => (
                <span key={line.key} className="block">
                  <Spans spans={line.spans} />
                  {line.key === lastLine && more}
                </span>
              ))}
            </pre>
          );
        }
        if (block.kind === "quote") {
          return (
            <p key={block.key} className="rounded-md bg-raised px-3 py-1.5 text-muted-foreground">
              {block.label && (
                <span className="mr-1.5 font-medium text-foreground">{block.label}:</span>
              )}
              <Spans spans={block.spans} />
              {more}
            </p>
          );
        }
        return (
          <p key={block.key} className="line-clamp-4">
            <Spans spans={block.spans} />
            {more}
          </p>
        );
      })}
    </div>
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
      className="block text-section leading-snug font-semibold [overflow-wrap:anywhere]"
    >
      {crumbs.map((crumb, i) => (
        <span
          key={crumbs.slice(0, i + 1).join("\u0000")}
          className={i < crumbs.length - 1 ? "font-normal text-muted-foreground" : ""}
        >
          {i > 0 && (
            <>
              <span aria-hidden="true" className="px-1.5 text-muted-foreground">
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

/** Same shape as the real list (optional chip row, count line, rows), so nothing moves when it lands. */
export function Skeleton({ chips = false }: { chips?: boolean }) {
  return (
    <div aria-hidden="true" className="pending-in">
      {chips && (
        <div className="mb-5 flex gap-2">
          {["a", "b", "c"].map((id) => (
            <Bar key={id} className="h-11 w-24 lg:h-8" />
          ))}
        </div>
      )}
      <Bar className="mb-4 h-5 w-28" />
      <ul className="divide-y divide-rule">
        {["a", "b", "c", "d"].map((id) => (
          <li key={id} className="space-y-2 py-4">
            <Bar className="h-5 w-2/5" />
            <Bar className="h-3 w-1/4" />
            <Bar className="h-3.5 w-full" />
            <Bar className="h-3.5 w-4/5" />
          </li>
        ))}
      </ul>
    </div>
  );
}
