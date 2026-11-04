import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { type KeyboardEvent, type ReactNode, useId } from "react";
import { parseTags } from "@/shared/lib/tags";
import { cn } from "@/shared/lib/utils";
import { searchQueryOptions } from "../api/search-queries";
import { useSearchNav } from "../hooks/use-search-nav";
import type { SearchContext } from "../model/context";
import {
  countLabel,
  highlightPieces,
  resultsNoun,
  type SearchHit,
  type SearchResults as SearchResultData,
} from "../model/search";
import { INPUT_ID, RESULTS_ID } from "./search-box";

const retry =
  "inline-flex h-11 cursor-pointer items-center rounded-md bg-secondary px-3 text-sm font-medium outline-none transition-[background-color,transform] duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] lg:h-9";

function Snippet({ hit }: { hit: SearchHit }) {
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
function Crumbs({ hit }: { hit: SearchHit }) {
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

function Hit({ hit, ctx }: { hit: SearchHit; ctx: SearchContext }) {
  return (
    // The whole row is the target (the title link stretches over it), so the hover tint covers the tags too.
    <li className="relative rounded-md px-2 py-3 transition-colors duration-150 [@media(hover:hover)]:hover:bg-accent/70">
      <Link
        data-result=""
        to="/libraries/$owner/$repo"
        params={{ owner: ctx.owner, repo: ctx.repo }}
        // Back returns to the results (the query is in the previous entry), so the article link
        // carries only the version and the path.
        search={{ version: ctx.ref, path: hit.article_path }}
        {...(hit.anchor ? { hash: hit.anchor } : {})}
        className="rounded-md outline-none after:absolute after:inset-0 after:rounded-md after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring"
      >
        <Crumbs hit={hit} />
        <span className="mt-0.5 block font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {hit.article_path}
        </span>
      </Link>
      <Snippet hit={hit} />
      {hit.tags.length > 0 && (
        <ul className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
          {hit.tags.map((tag) => (
            <li key={tag}>{tag}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** Same rows as the real list (count line, title, path, two text lines, tags), so nothing moves when it lands. */
function Skeleton() {
  return (
    <div aria-hidden="true" className="pending-in motion-safe:animate-pulse">
      <span className="mb-4 block h-5 w-28 rounded bg-muted-foreground/[0.14]" />
      <ul className="divide-y divide-border">
        {["a", "b", "c", "d"].map((id) => (
          <li key={id} className="space-y-2 py-3">
            <span className="block h-5 w-2/5 rounded bg-muted-foreground/[0.14]" />
            <span className="block h-3 w-1/4 rounded bg-muted-foreground/[0.14]" />
            <span className="block h-3.5 w-full rounded bg-muted-foreground/[0.14]" />
            <span className="block h-3.5 w-4/5 rounded bg-muted-foreground/[0.14]" />
            <span className="block h-3 w-1/6 rounded bg-muted-foreground/[0.14]" />
          </li>
        ))}
      </ul>
    </div>
  );
}

function NoResults({ ctx, q }: { ctx: SearchContext; q: string }) {
  const update = useSearchNav(ctx.owner, ctx.repo);
  const tags = parseTags(ctx.tags);
  return (
    <div className="max-w-xl">
      <h2 className="font-serif text-2xl font-semibold tracking-tight">No results in {ctx.ref}</h2>
      <p className="mt-2 text-muted-foreground">
        Nothing in <span className="font-mono text-foreground">{ctx.ref}</span> matches{" "}
        <span className="font-medium text-foreground [overflow-wrap:anywhere]">“{q}”</span>
        {tags.length > 0 &&
          ` among articles tagged ${tags.join(ctx.match === "all" ? " and " : " or ")}`}
        . Try fewer or different words.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {tags.length > 0 && (
          <button
            type="button"
            className={retry}
            onClick={() => void update({ tags: undefined, match: undefined })}
          >
            Remove tag filter
          </button>
        )}
        {ctx.otherRefs.slice(0, 3).map((ref) => (
          <Link
            key={ref}
            to="/libraries/$owner/$repo"
            params={{ owner: ctx.owner, repo: ctx.repo }}
            search={{
              version: ref,
              q,
              tags: ctx.tags,
              match: ctx.match === "all" ? "all" : undefined,
            }}
            className={retry}
          >
            Search&nbsp;<span className="font-mono">{ref}</span>&nbsp;instead
          </Link>
        ))}
      </div>
    </div>
  );
}

function onArrows(event: KeyboardEvent<HTMLElement>) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const links = [...event.currentTarget.querySelectorAll<HTMLElement>("a[data-result]")];
  const at = links.indexOf(document.activeElement as HTMLElement);
  if (at < 0) return;
  event.preventDefault();
  if (event.key === "ArrowUp" && at === 0) document.getElementById(INPUT_ID)?.focus();
  else
    links[
      Math.min(Math.max(at + (event.key === "ArrowDown" ? 1 : -1), 0), links.length - 1)
    ]?.focus();
}

function HitList({
  data,
  ctx,
  stale,
}: {
  data: SearchResultData;
  ctx: SearchContext;
  stale: boolean;
}) {
  const count = data.results.length;
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: arrow keys move between the links inside
    <div onKeyDown={onArrows}>
      <p aria-hidden="true" className="mb-4 flex h-5 items-center text-sm text-muted-foreground">
        <span className="font-medium text-foreground">
          {resultsNoun(count, data.coverage.complete)}
        </span>
        &nbsp;in&nbsp;<span className="font-mono">{ctx.ref}</span>
        <span className="ml-3 hidden text-xs lg:inline">
          <kbd className="font-mono">↓</kbd> to move through results
        </span>
      </p>
      {/* The dim waits 150 ms (transition-delay applies only when it starts): a quick answer never blinks. */}
      <ul
        className={cn(
          "-mx-2 divide-y divide-border transition-opacity duration-150",
          stale && "opacity-60 delay-150",
        )}
      >
        {data.results.map((hit) => (
          <Hit key={hit.chunk_id} hit={hit} ctx={ctx} />
        ))}
      </ul>
      {!data.coverage.complete && (
        <p className="mt-4 text-sm text-muted-foreground">
          Showing the best {count}. More sections match: add a tag or a more specific word.
        </p>
      )}
    </div>
  );
}

function Failed({ refName, onRetry }: { refName: string; onRetry: () => void }) {
  return (
    <div role="alert" className="max-w-xl">
      <h2 className="font-serif text-2xl font-semibold tracking-tight">Search failed</h2>
      <p className="mt-2 text-muted-foreground">
        Couldn't search {refName}. Check your connection or try again.
      </p>
      <button type="button" className={cn(retry, "mt-3")} onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

/** The hits for the URL's query in the selected version. */
export function SearchResults({ ctx }: { ctx: SearchContext }) {
  const heading = useId();
  const { q } = ctx;
  const result = useQuery({
    ...searchQueryOptions({ ...ctx, q: q ?? "" }),
    enabled: q !== undefined,
  });
  if (q === undefined) return null;

  const data = result.data;
  // Old hits stay (dimmed) only while a new query loads. A background refetch of the same query
  // neither dims nor re-announces them.
  const stale = result.isPlaceholderData;
  const settled = data !== undefined && !stale;

  let body: ReactNode = <Skeleton />;
  if (result.isError && !stale) {
    body = <Failed refName={ctx.ref} onRetry={() => void result.refetch()} />;
  } else if (data && data.results.length > 0) {
    body = <HitList data={data} ctx={ctx} stale={stale} />;
  } else if (data && settled) {
    body = <NoResults ctx={ctx} q={q} />;
  }

  return (
    <section
      id={RESULTS_ID}
      aria-labelledby={heading}
      aria-busy={result.isFetching}
      className="min-h-[24rem] max-w-2xl min-w-0"
    >
      <h2 id={heading} className="sr-only">
        Search results
      </h2>
      {/* Announced once per settled result set; the visible summary is not live. */}
      <p role="status" className="sr-only">
        {settled ? countLabel(data.results.length, q, ctx.ref, data.coverage.complete) : ""}
      </p>
      {body}
    </section>
  );
}
