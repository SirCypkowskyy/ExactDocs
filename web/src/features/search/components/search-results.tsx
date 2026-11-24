import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CircleAlert, FunnelX, RotateCcw, Search, SearchX } from "lucide-react";
import { type ReactNode, useId } from "react";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { parseTags } from "@/shared/lib/tags";
import { cn } from "@/shared/lib/utils";
import { Button, buttonVariants } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/page";
import { kbd, pill, pillTone } from "@/shared/ui/recipes";
import { searchQueryOptions } from "../api/search-queries";
import { useSearchNav } from "../hooks/use-search-nav";
import { messages } from "../messages";
import type { SearchContext } from "../model/context";
import {
  countLabel,
  type SearchHit,
  type SearchResults as SearchResultData,
} from "../model/search";
import { Crumbs, Skeleton, Snippet } from "./hit-parts";

/** A secondary action under a search state (retry, widen, another version). */
const retry = buttonVariants({ variant: "outline", size: "sm" });

import { onArrows } from "./keyboard";
import { INPUT_ID, RESULTS_ID } from "./search-box";

function Hit({ hit, ctx }: { hit: SearchHit; ctx: SearchContext }) {
  const t = useMessages(messages);
  return (
    // The whole row is the target (the title link stretches over it), so the hover tint covers the tags too.
    <li className="row-in relative rounded-lg px-3 py-4 transition-colors duration-(--dur-fast) can-hover:hover:bg-raised">
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
        <span className="mt-0.5 block font-mono text-small text-muted-foreground [overflow-wrap:anywhere]">
          {hit.article_path}
        </span>
      </Link>
      <Snippet hit={hit} />
      {hit.tags.length > 0 && (
        <ul aria-label={t.tags.label} className="relative mt-2 flex flex-wrap gap-1.5">
          {hit.tags.map((tag) => (
            <li key={tag} className={cn(pill, pillTone.neutral)}>
              {tag}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function NoResults({ ctx, q }: { ctx: SearchContext; q: string }) {
  const t = useMessages(messages);
  const update = useSearchNav(ctx.owner, ctx.repo);
  const tags = parseTags(ctx.tags);
  const others = ctx.otherRefs.slice(0, 3);
  return (
    <EmptyState
      icon={<SearchX aria-hidden="true" />}
      headingLevel={2}
      title={t.empty.noResultsIn(ctx.ref)}
      className="max-w-xl"
      action={
        (tags.length > 0 || others.length > 0) && (
          <div className="flex flex-wrap gap-2">
            {tags.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void update({ tags: undefined, match: undefined })}
              >
                <FunnelX aria-hidden="true" data-icon-motion="tilt" />
                {t.empty.removeTagFilter}
              </Button>
            )}
            {others.map((ref) => (
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
                <Search aria-hidden="true" data-icon-motion="tilt" />
                {t.empty.searchInstead(<span className="font-mono">{ref}</span>)}
              </Link>
            ))}
          </div>
        )
      }
    >
      {t.empty.nothingIn(
        <span className="font-mono text-foreground">{ctx.ref}</span>,
        <span className="font-medium text-foreground [overflow-wrap:anywhere]">
          {t.results.quote(q)}
        </span>,
        tags,
        ctx.match === "all",
      )}
    </EmptyState>
  );
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
  const t = useMessages(messages);
  const count = data.results.length;
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: arrow keys move between the links inside
    <div onKeyDown={onArrows(() => document.getElementById(INPUT_ID)?.focus())}>
      <p aria-hidden="true" className="mb-3 flex h-5 items-center text-body text-muted-foreground">
        <span className="font-medium text-foreground">
          {t.results.count(count, data.coverage.complete)}
        </span>
        {t.results.inRef(<span className="font-mono">{ctx.ref}</span>)}
        <span className="ml-3 hidden text-small lg:inline">
          {t.results.moveHint(<kbd className={kbd}>↓</kbd>)}
        </span>
      </p>
      {/* The dim waits 150 ms (transition-delay applies only when it starts): a quick answer never blinks. */}
      <ul
        className={cn(
          "-mx-3 divide-y divide-rule transition-opacity duration-(--dur)",
          stale && "opacity-60 delay-150",
        )}
      >
        {data.results.map((hit) => (
          <Hit key={hit.chunk_id} hit={hit} ctx={ctx} />
        ))}
      </ul>
      {!data.coverage.complete && (
        <p className="mt-4 text-body text-muted-foreground">{t.results.bestOfVersion(count)}</p>
      )}
    </div>
  );
}

function Failed({ refName, onRetry }: { refName: string; onRetry: () => void }) {
  const t = useMessages(messages);
  const c = useMessages(common);
  return (
    <EmptyState
      role="alert"
      icon={<CircleAlert aria-hidden="true" />}
      headingLevel={2}
      title={t.failed.title}
      className="max-w-xl"
      action={
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCcw aria-hidden="true" data-icon-motion="refresh" />
          {c.retry}
        </Button>
      }
    >
      {t.failed.version(refName)}
    </EmptyState>
  );
}

/** The hits for the URL's query in the selected version. */
export function SearchResults({ ctx }: { ctx: SearchContext }) {
  const t = useMessages(messages);
  const language = useLanguage();
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
      className="min-h-[24rem] max-w-[72ch] min-w-0"
    >
      <h2 id={heading} className="sr-only">
        {t.results.heading}
      </h2>
      {/* Announced once per settled result set; the visible summary is not live. */}
      <p role="status" className="sr-only">
        {settled
          ? countLabel(data.results.length, q, ctx.ref, data.coverage.complete, language)
          : ""}
      </p>
      {body}
    </section>
  );
}
