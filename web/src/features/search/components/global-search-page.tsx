import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { type ReactNode, useId } from "react";
import { normalizeQuery } from "@/shared/lib/search-query";
import { cn } from "@/shared/lib/utils";
import { globalSearchQueryOptions } from "../api/global-search-queries";
import { type GlobalHit, type GlobalResults, splitLibrary } from "../model/global";
import { resultsNoun } from "../model/search";
import { GLOBAL_INPUT_ID } from "./global-search-box";
import { Crumbs, onArrows, retry, Snippet } from "./hit-parts";
import { RESULTS_ID } from "./search-box";

const chip =
  "inline-flex min-h-11 max-w-full cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-sm outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8";

function Facets({ data, q, library }: { data: GlobalResults; q: string; library?: string }) {
  const total = data.libraries.reduce((sum, f) => sum + f.matches, 0);
  const item = (selected: boolean) =>
    cn(
      chip,
      selected
        ? "bg-mark text-primary-foreground"
        : "bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent",
    );
  return (
    <nav aria-label="Libraries with matches">
      <ul className="flex flex-wrap gap-2">
        <li>
          <Link
            to="/search"
            search={{ q }}
            aria-current={library ? undefined : "true"}
            className={item(!library)}
          >
            All libraries <span className="tabular-nums opacity-80">{total}</span>
          </Link>
        </li>
        {data.libraries.map((f) => (
          <li key={f.library} className="min-w-0">
            <Link
              to="/search"
              search={{ q, library: f.library }}
              aria-current={library === f.library ? "true" : undefined}
              className={item(library === f.library)}
            >
              <span className="font-mono [overflow-wrap:anywhere]">{f.library}</span>
              <span className="tabular-nums opacity-80">{f.matches}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Hit({ hit }: { hit: GlobalHit }) {
  const { owner, repo } = splitLibrary(hit.library);
  return (
    <li className="relative px-2 py-3 transition-colors duration-150 [@media(hover:hover)]:hover:bg-accent/70">
      <p className="mb-0.5 font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {hit.library} <span aria-hidden="true">·</span> <span className="sr-only">version </span>
        {hit.version}
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

function Notes({ data }: { data: GlobalResults }) {
  return (
    <>
      {!data.coverage.complete && (
        <p className="mt-4 text-sm text-muted-foreground">
          Showing the best {data.results.length}. More sections match: use a library above or a more
          specific word.
        </p>
      )}
      {data.libraries_omitted > 0 && (
        <p className="mt-2 text-sm text-muted-foreground">
          {data.libraries_omitted} {data.libraries_omitted === 1 ? "library was" : "libraries were"}{" "}
          not searched (searched {data.libraries_searched}).
        </p>
      )}
    </>
  );
}

function Empty({ q, library }: { q: string; library: string | undefined }) {
  return (
    <div className="max-w-xl">
      <h2 className="font-serif text-2xl font-semibold tracking-tight">
        {library ? `No results in ${library}` : "No results"}
      </h2>
      <p className="mt-2 text-muted-foreground">
        Nothing {library ? "there" : "in any library's default version"} matches{" "}
        <span className="font-medium text-foreground [overflow-wrap:anywhere]">“{q}”</span>. Try
        fewer or different words.
      </p>
      {library && (
        <Link to="/search" search={{ q }} className={cn(retry, "mt-4")}>
          Search all libraries
        </Link>
      )}
    </div>
  );
}

/** Results of the header's search: hits from every library, a library facet with counts. */
export function GlobalSearchPage({ q: raw, library }: { q: string | undefined; library?: string }) {
  const heading = useId();
  const q = normalizeQuery(raw);
  const result = useQuery({
    ...globalSearchQueryOptions({ q: q ?? "", library }),
    enabled: q !== undefined,
  });

  const data = result.data;
  const stale = result.isPlaceholderData;
  const settled = data !== undefined && !stale;

  let body: ReactNode = (
    <p className="text-muted-foreground" aria-hidden={q === undefined ? undefined : true}>
      {q === undefined
        ? "Type a word, an identifier or an error message to search every library."
        : "Searching…"}
    </p>
  );
  if (q !== undefined && result.isError && !stale) {
    body = (
      <div role="alert" className="max-w-xl">
        <h2 className="font-serif text-2xl font-semibold tracking-tight">Search failed</h2>
        <p className="mt-2 text-muted-foreground">
          Couldn't search. Check your connection or try again.
        </p>
        <button type="button" className={cn(retry, "mt-3")} onClick={() => void result.refetch()}>
          Try again
        </button>
      </div>
    );
  } else if (q !== undefined && data) {
    body = (
      <div className="space-y-5">
        {data.libraries.length > 0 && <Facets data={data} q={q} {...(library && { library })} />}
        {data.results.length > 0 ? (
          // biome-ignore lint/a11y/noStaticElementInteractions: arrow keys move between the links inside
          <div onKeyDown={onArrows(GLOBAL_INPUT_ID)}>
            <p aria-hidden="true" className="mb-2 text-sm font-medium">
              {resultsNoun(data.results.length, data.coverage.complete)}
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
            <Notes data={data} />
          </div>
        ) : (
          settled && <Empty q={q} library={library} />
        )}
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
      <section
        id={RESULTS_ID}
        aria-labelledby={heading}
        aria-busy={result.isFetching}
        className="min-w-0"
      >
        <h1 id={heading} className="font-serif text-3xl font-semibold tracking-tight">
          {q ? (
            <>
              Search: <span className="[overflow-wrap:anywhere]">{q}</span>
            </>
          ) : (
            "Search all libraries"
          )}
        </h1>
        <p role="status" className="sr-only">
          {settled
            ? `${data.results.length === 0 ? "No results" : resultsNoun(data.results.length, data.coverage.complete)} for “${q}”${library ? ` in ${library}` : " in all libraries"}`
            : ""}
        </p>
        <div className="mt-5">{body}</div>
      </section>
    </main>
  );
}
