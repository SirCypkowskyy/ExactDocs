import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";
import { type KeyboardEvent, useId } from "react";
import { cn } from "@/shared/lib/utils";
import { searchQueryOptions } from "../api/search-queries";
import { useSearchNav } from "../hooks/use-search-nav";
import type { SearchContext } from "../model/context";
import { countLabel, highlightPieces, parseTags, type SearchHit } from "../model/search";
import { INPUT_ID, RESULTS_ID } from "./search-box";

const retry =
  "mt-3 inline-flex h-11 cursor-pointer items-center rounded-md bg-secondary px-3 text-sm font-medium outline-none transition-[background-color,transform] duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] lg:h-9";

/** Only http(s) links from repository data. */
const safeUrl = (url: string | null): string | undefined =>
  url && /^https?:\/\//i.test(url) ? url : undefined;

function Snippet({ hit }: { hit: SearchHit }) {
  return (
    <p className="mt-1.5 text-sm leading-relaxed whitespace-pre-line text-foreground/90 [overflow-wrap:anywhere]">
      {highlightPieces(hit.snippet, hit.highlights).map((piece) =>
        piece.hit ? (
          <mark key={piece.at} className="rounded-sm bg-mark/[0.18] px-0.5 text-foreground">
            {piece.text}
          </mark>
        ) : (
          <span key={piece.at}>{piece.text}</span>
        ),
      )}
    </p>
  );
}

function Hit({ hit, ctx }: { hit: SearchHit; ctx: SearchContext }) {
  const crumbs =
    hit.heading_path.length > 0
      ? hit.heading_path
      : [hit.article_path.split("/").pop() ?? hit.article_path];
  const source = safeUrl(hit.source_url);
  return (
    <li className="py-4 first:pt-0">
      <Link
        data-result=""
        to="/libraries/$owner/$repo"
        params={{ owner: ctx.owner, repo: ctx.repo }}
        search={{ version: ctx.ref, path: hit.article_path, tags: ctx.tags }}
        {...(hit.anchor ? { hash: hit.anchor } : {})}
        className="-mx-2 block rounded-md px-2 py-1.5 outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring [@media(hover:hover)]:hover:bg-accent/60"
      >
        <span className="block font-serif text-lg leading-snug font-semibold [overflow-wrap:anywhere]">
          {crumbs.map((crumb, i) => (
            <span
              key={crumbs.slice(0, i + 1).join("\u0000")}
              className={i < crumbs.length - 1 ? "font-normal text-muted-foreground" : ""}
            >
              {i > 0 && (
                <span aria-hidden="true" className="px-1.5 text-muted-foreground/70">
                  ›
                </span>
              )}
              {crumb}
            </span>
          ))}
        </span>
        <span className="mt-0.5 block font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {hit.article_path}
        </span>
        <Snippet hit={hit} />
      </Link>
      {(hit.tags.length > 0 || source) && (
        <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
          {hit.tags.length > 0 && <span>{hit.tags.join(" · ")}</span>}
          {source && (
            <a
              href={source}
              target="_blank"
              rel="noopener noreferrer"
              className="-my-2 inline-flex min-h-11 items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8"
            >
              View at commit
              <ArrowUpRight aria-hidden="true" className="size-3" />
              <span className="sr-only">(opens the repository)</span>
            </a>
          )}
        </p>
      )}
    </li>
  );
}

function Skeleton() {
  return (
    <ul aria-hidden="true" className="divide-y divide-border motion-safe:animate-pulse">
      {["a", "b", "c", "d"].map((id) => (
        <li key={id} className="space-y-2 py-4 first:pt-0">
          <span className="block h-5 w-2/5 rounded bg-muted-foreground/[0.14]" />
          <span className="block h-3 w-1/4 rounded bg-muted-foreground/[0.14]" />
          <span className="block h-3.5 w-full rounded bg-muted-foreground/[0.14]" />
          <span className="block h-3.5 w-4/5 rounded bg-muted-foreground/[0.14]" />
        </li>
      ))}
    </ul>
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
        . Results always come from the version you selected.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
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
            className={cn(retry, "font-mono")}
          >
            Try {ref}
          </Link>
        ))}
      </div>
    </div>
  );
}

/** The hits for the URL's query in the selected version. */
export function SearchResults({ ctx }: { ctx: SearchContext }) {
  const heading = useId();
  const { q } = ctx;
  const result = useQuery({
    ...searchQueryOptions({ ...ctx, q: q ?? "", tags: parseTags(ctx.tags) }),
    enabled: q !== undefined,
  });
  if (q === undefined) return null;

  const data = result.data;
  // After a failed refetch the old hits may be for another query: never show them under this one.
  const stale = data !== undefined && (result.isPlaceholderData || result.isFetching);
  const settled = data !== undefined && !stale;

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
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

  let body: React.ReactNode;
  if (result.isError && !stale) {
    body = (
      <div role="alert" className="max-w-xl">
        <h2 className="font-serif text-2xl font-semibold tracking-tight">Search failed</h2>
        <p className="mt-2 text-muted-foreground">
          Couldn't search {ctx.ref}. Your query is kept; try again in a moment.
        </p>
        <button type="button" className={retry} onClick={() => void result.refetch()}>
          Try again
        </button>
      </div>
    );
  } else if (data === undefined) {
    body = <Skeleton />;
  } else if (data.results.length === 0) {
    body = settled ? <NoResults ctx={ctx} q={q} /> : <Skeleton />;
  } else {
    body = (
      // biome-ignore lint/a11y/noStaticElementInteractions: arrow keys move between the links inside
      <div onKeyDown={onKeyDown}>
        <ul
          className={cn(
            "divide-y divide-border transition-opacity duration-150",
            stale && "opacity-60",
          )}
        >
          {data.results.map((hit) => (
            <Hit key={hit.chunk_id} hit={hit} ctx={ctx} />
          ))}
        </ul>
        {!data.coverage.complete && (
          <p className="mt-4 text-sm text-muted-foreground">
            Showing the best {data.results.length}. More sections match: add a tag or a more
            specific word.
          </p>
        )}
      </div>
    );
  }

  const count = data?.results.length ?? 0;
  const countText = `${data && !data.coverage.complete ? "Top " : ""}${count} ${count === 1 ? "result" : "results"}`;
  return (
    <section
      id={RESULTS_ID}
      aria-labelledby={heading}
      aria-busy={stale || result.isPending}
      className="min-h-[24rem] max-w-3xl min-w-0"
    >
      <h2 id={heading} className="sr-only">
        Search results
      </h2>
      {/* Announced once per settled result set; the visible summary below is not live. */}
      <p role="status" className="sr-only">
        {settled && data ? countLabel(count, q, ctx.ref, data.coverage.complete) : ""}
      </p>
      {data && data.results.length > 0 && (
        <p aria-hidden="true" className="mb-4 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{countText}</span> in{" "}
          <span className="font-mono">{ctx.ref}</span>
        </p>
      )}
      {body}
    </section>
  );
}
