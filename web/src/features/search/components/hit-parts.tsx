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

const bar = "block rounded bg-muted-foreground/[0.14]";

/** Same shape as the real list (optional chip row, count line, rows), so nothing moves when it lands. */
export function Skeleton({ chips = false }: { chips?: boolean }) {
  return (
    <div aria-hidden="true" className="pending-in motion-safe:animate-pulse">
      {chips && (
        <div className="mb-5 flex gap-2">
          {["a", "b", "c"].map((id) => (
            <span key={id} className={`${bar} h-11 w-24 rounded-md lg:h-8`} />
          ))}
        </div>
      )}
      <span className={`${bar} mb-4 h-5 w-28`} />
      <ul className="divide-y divide-border">
        {["a", "b", "c", "d"].map((id) => (
          <li key={id} className="space-y-2 py-3">
            <span className={`${bar} h-5 w-2/5`} />
            <span className={`${bar} h-3 w-1/4`} />
            <span className={`${bar} h-3.5 w-full`} />
            <span className={`${bar} h-3.5 w-4/5`} />
            <span className={`${bar} h-3 w-1/6`} />
          </li>
        ))}
      </ul>
    </div>
  );
}
