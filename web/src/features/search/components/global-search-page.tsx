import { type UseQueryResult, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { type ReactNode, useId } from "react";
import { HttpError } from "@/shared/lib/http";
import { normalizeQuery } from "@/shared/lib/search-query";
import { cn } from "@/shared/lib/utils";
import { buttonVariants } from "@/shared/ui/button";
import { globalSearchQueryOptions } from "../api/global-search-queries";
import {
  countLine,
  type GlobalHit,
  type GlobalResults,
  splitLibrary,
  statusLine,
  totalMatches,
} from "../model/global";
import { GLOBAL_RESULTS_ID, GlobalSearchBox } from "./global-search-box";
import { Crumbs, Skeleton, Snippet } from "./hit-parts";

/** A secondary action under a search state (retry, widen, another version). */
const retry = buttonVariants({ variant: "outline", size: "sm" });

import { focusGlobalInput, onArrows } from "./keyboard";

/** Chips shown before "+N more"; the selected library always stays visible. */
const VISIBLE_FACETS = 8;

const chip =
  "inline-flex h-11 max-w-full min-w-0 cursor-pointer items-center gap-2 rounded-md px-3 text-sm outline-none transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] lg:h-8";

const chipTone = (selected: boolean) =>
  selected
    ? "bg-route text-route-foreground"
    : "bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent";

/** `owner/repo` with the owner softer and the repo firm; the owner gives way first when it is long. */
function LibraryName({ id }: { id: string }) {
  const { owner, repo } = splitLibrary(id);
  return (
    <span className="flex min-w-0 items-baseline">
      <span className="min-w-0 shrink truncate opacity-70">{owner}/</span>
      <span className="max-w-full shrink-0 truncate font-medium">{repo}</span>
    </span>
  );
}

function FacetLink({
  f,
  q,
  library,
}: {
  f: GlobalResults["libraries"][number];
  q: string;
  library?: string;
}) {
  const selected = library === f.library;
  return (
    <li className="min-w-0 max-w-full">
      <Link
        to="/search"
        search={{ q, library: f.library }}
        title={f.library}
        aria-label={`${f.library}, ${f.matches} ${f.matches === 1 ? "match" : "matches"}`}
        aria-current={selected ? "page" : undefined}
        className={cn(chip, chipTone(selected))}
      >
        <LibraryName id={f.library} />
        <span aria-hidden="true" className="shrink-0 tabular-nums opacity-80">
          {f.matches}
        </span>
      </Link>
    </li>
  );
}

function Facets({ data, q, library }: { data: GlobalResults; q: string; library?: string }) {
  const total = data.libraries.reduce((sum, f) => sum + f.matches, 0);
  const shown = data.libraries.filter((f, i) => i < VISIBLE_FACETS || f.library === library);
  const shownIds = new Set(shown.map((f) => f.library));
  const rest = data.libraries.filter((f) => !shownIds.has(f.library));
  return (
    <nav aria-label="Libraries with matches" className="space-y-2">
      <ul className="flex flex-wrap gap-x-2 gap-y-2">
        <li>
          <Link
            to="/search"
            search={{ q }}
            aria-label={`All libraries, ${total} matches`}
            aria-current={library ? undefined : "page"}
            className={cn(chip, chipTone(!library))}
          >
            All libraries{" "}
            <span aria-hidden="true" className="tabular-nums opacity-80">
              {total}
            </span>
          </Link>
        </li>
        {shown.map((f) => (
          <FacetLink key={f.library} f={f} q={q} {...(library && { library })} />
        ))}
      </ul>
      {rest.length > 0 && (
        <details>
          <summary className="inline-flex h-11 cursor-pointer items-center rounded-md px-1 text-sm text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring lg:h-8 [@media(hover:hover)]:hover:text-foreground">
            +{rest.length} more libraries
          </summary>
          <ul className="mt-1 flex flex-wrap gap-x-2 gap-y-2">
            {rest.map((f) => (
              <FacetLink key={f.library} f={f} q={q} {...(library && { library })} />
            ))}
          </ul>
        </details>
      )}
    </nav>
  );
}

function Hit({ hit }: { hit: GlobalHit }) {
  const { owner, repo } = splitLibrary(hit.library);
  return (
    <li className="relative px-2 py-3 transition-colors duration-150 [@media(hover:hover)]:hover:bg-accent/70">
      <p className="mb-0.5 text-[13px] font-medium text-foreground/80 [overflow-wrap:anywhere]">
        {owner}/{repo}{" "}
        <span className="font-mono text-xs font-normal text-muted-foreground">
          <span className="sr-only">version </span>
          {hit.version}
        </span>
      </p>
      <Link
        data-result=""
        to="/libraries/$owner/$repo"
        params={{ owner, repo }}
        search={{ version: hit.version, path: hit.article_path }}
        {...(hit.anchor ? { hash: hit.anchor } : {})}
        className="rounded-md outline-none after:absolute after:inset-0 after:rounded-md after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring"
      >
        <Crumbs hit={hit} />
        <span className="mt-0.5 block font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {hit.article_path}
        </span>
      </Link>
      <Snippet hit={hit} />
    </li>
  );
}

function Notes({ data, library }: { data: GlobalResults; library: string | undefined }) {
  const all = data.libraries_searched + data.libraries_omitted;
  return (
    <>
      {!data.coverage.complete && (
        <p className="mt-4 text-sm text-muted-foreground">
          Showing the best {data.results.length}. More sections match:{" "}
          {library ? "use a more specific word." : "use a library above or a more specific word."}
        </p>
      )}
      {data.libraries_omitted > 0 && (
        <p className="mt-2 text-sm text-muted-foreground">
          Searched {data.libraries_searched} of {all} libraries; the other {data.libraries_omitted}{" "}
          are not searched here.{" "}
          <Link to="/" className="underline underline-offset-2 hover:text-foreground">
            Browse them on the Libraries page
          </Link>
          .
        </p>
      )}
    </>
  );
}

function Empty({
  q,
  library,
  unavailable = false,
}: {
  q: string;
  library: string | undefined;
  unavailable?: boolean;
}) {
  return (
    <div className="max-w-xl">
      <h2 className="text-2xl font-semibold tracking-tight">
        {unavailable
          ? "Library not available"
          : library
            ? `No results in ${library}`
            : "No results"}
      </h2>
      <p className="mt-2 text-muted-foreground">
        {unavailable ? (
          <>
            <span className="font-mono text-foreground [overflow-wrap:anywhere]">{library}</span>{" "}
            can't be searched: it was removed, or it has no imported version.
          </>
        ) : (
          <>
            Nothing {library ? "there" : "in any library's default version"} matches{" "}
            <span className="font-medium text-foreground [overflow-wrap:anywhere]">“{q}”</span>. Try
            fewer or different words.
            {!library && " To search another version, open the library and use its search box."}
          </>
        )}
      </p>
      {library && (
        <Link to="/search" search={{ q }} className={cn(retry, "mt-4")}>
          Search all libraries
        </Link>
      )}
    </div>
  );
}

type GlobalQuery = UseQueryResult<GlobalResults>;

/** What sits under the title: the prompt, the skeleton, the error, the empty state or the hits. */
function Body({
  q,
  library,
  result,
}: {
  q: string | undefined;
  library: string | undefined;
  result: GlobalQuery;
}) {
  const data = result.data;
  const stale = result.isPlaceholderData;
  const settled = data !== undefined && !stale;
  const refused =
    result.error instanceof HttpError && result.error.status >= 400 && result.error.status < 500;

  let body: ReactNode = <Skeleton chips />;
  if (q === undefined) {
    body = (
      <p className="max-w-xl text-muted-foreground">
        Searches the default version of every library.{" "}
        <span className="hidden lg:inline">
          Press <kbd className="rounded bg-secondary px-1.5 font-mono text-xs">/</kbd> to start
          typing.
        </span>
      </p>
    );
  } else if (result.isError && !stale) {
    body =
      refused && library ? (
        <Empty q={q} library={library} unavailable />
      ) : (
        <div role="alert" className="max-w-xl">
          <h2 className="text-2xl font-semibold tracking-tight">Search failed</h2>
          <p className="mt-2 text-muted-foreground">
            Couldn't search. Check your connection or try again.
          </p>
          <button type="button" className={cn(retry, "mt-3")} onClick={() => void result.refetch()}>
            Try again
          </button>
        </div>
      );
  } else if (data) {
    body = (
      <div className="space-y-5">
        {data.libraries.length > 0 && <Facets data={data} q={q} {...(library && { library })} />}
        {data.results.length > 0 ? (
          // biome-ignore lint/a11y/noStaticElementInteractions: arrow keys move between the links inside
          <div onKeyDown={onArrows(focusGlobalInput)}>
            <p aria-hidden="true" className="mb-2 flex items-center text-sm">
              <span className="font-medium">
                {countLine(
                  data.results.length,
                  totalMatches(data, library),
                  data.coverage.complete,
                )}
              </span>
              <span className="ml-3 hidden text-xs text-muted-foreground lg:inline">
                <kbd className="font-mono">↓</kbd> to move through results
              </span>
            </p>
            <ul
              className={cn(
                "-mx-2 divide-y divide-border transition-opacity duration-150",
                stale && "opacity-60 delay-150",
              )}
            >
              {data.results.map((hit) => (
                <Hit key={`${hit.library}:${hit.chunk_id}`} hit={hit} />
              ))}
            </ul>
            <Notes data={data} library={library} />
          </div>
        ) : (
          settled && <Empty q={q} library={library} />
        )}
      </div>
    );
  }
  return body;
}

/** Results of the global search: hits from every library, a library facet with counts. */
export function GlobalSearchPage({ q: raw, library }: { q: string | undefined; library?: string }) {
  const heading = useId();
  const q = normalizeQuery(raw);
  const result = useQuery({
    ...globalSearchQueryOptions({ q: q ?? "", library }),
    enabled: q !== undefined,
  });

  const data = result.data;
  const settled = data !== undefined && !result.isPlaceholderData;
  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
      {/* A phone's header holds only an icon; the box sits here, focused while there is no query
          (Back from an article to its results must not bring the keyboard up again). */}
      <GlobalSearchBox place="page" autoFocus={q === undefined} className="mb-6 sm:hidden" />
      <section
        id={GLOBAL_RESULTS_ID}
        aria-labelledby={heading}
        aria-busy={result.isFetching}
        className="min-w-0"
      >
        <h1 id={heading} className="text-3xl font-semibold tracking-tight">
          {q ? (
            <>
              Search: <span className="[overflow-wrap:anywhere]">{q}</span>
            </>
          ) : (
            "Search all libraries"
          )}
        </h1>
        <p role="status" className="sr-only">
          {settled && q ? statusLine(data.results.length, q, library, data.coverage.complete) : ""}
        </p>
        <div className="mt-5">
          <Body q={q} library={library} result={result} />
        </div>
      </section>
    </main>
  );
}
