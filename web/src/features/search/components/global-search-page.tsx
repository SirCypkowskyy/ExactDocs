import { type UseQueryResult, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronDown, CircleAlert, RotateCcw, Search, SearchX } from "lucide-react";
import { useId } from "react";
import { HttpError } from "@/shared/lib/http";
import { common, formatNumber, useLanguage, useMessages } from "@/shared/lib/i18n";
import { normalizeQuery } from "@/shared/lib/search-query";
import { cn } from "@/shared/lib/utils";
import { Button, buttonVariants } from "@/shared/ui/button";
import { LibraryCombobox } from "@/shared/ui/library-combobox";
import { LibraryMark } from "@/shared/ui/library-mark";
import { EmptyState, Page, PageHeader } from "@/shared/ui/page";
import { kbd } from "@/shared/ui/recipes";
import { Commit } from "@/shared/ui/route";
import { globalSearchQueryOptions } from "../api/global-search-queries";
import { messages } from "../messages";
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
import { focusGlobalInput, onArrows } from "./keyboard";

/** Chips shown before "+N more"; the selected library always stays visible. */
const VISIBLE_FACETS = 8;

const chip =
  "inline-flex h-11 max-w-full min-w-0 cursor-pointer items-center gap-2 rounded-md px-3 text-body outline-none transition-[background-color,scale] duration-(--dur-fast) focus-visible:ring-2 focus-visible:ring-ring motion-safe:active:scale-[0.97] lg:h-9 lg:w-full lg:justify-between";

const chipTone = (selected: boolean) =>
  selected
    ? "bg-route text-route-foreground"
    : "bg-secondary text-secondary-foreground can-hover:hover:bg-accent";

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
  const t = useMessages(messages);
  const language = useLanguage();
  const selected = library === f.library;
  return (
    <li className="max-w-full min-w-0 lg:w-full">
      <Link
        to="/search"
        search={{ q, library: f.library }}
        title={f.library}
        aria-label={t.facets.library(f.library, f.matches)}
        aria-current={selected ? "page" : undefined}
        className={cn(chip, chipTone(selected))}
      >
        <span className="flex min-w-0 items-center gap-2">
          <LibraryMark id={f.library} size="sm" />
          <LibraryName id={f.library} />
        </span>
        <span aria-hidden="true" className="shrink-0 tabular-nums opacity-80">
          {formatNumber(f.matches, language)}
        </span>
      </Link>
    </li>
  );
}

/** Libraries with matches: chips above the hits on a phone, a column beside them from `lg`. */
function Facets({ data, q, library }: { data: GlobalResults; q: string; library?: string }) {
  const t = useMessages(messages);
  const language = useLanguage();
  const navigate = useNavigate();
  const total = data.libraries.reduce((sum, f) => sum + f.matches, 0);
  const shown = data.libraries.filter((f, i) => i < VISIBLE_FACETS || f.library === library);
  const shownIds = new Set(shown.map((f) => f.library));
  const rest = data.libraries.filter((f) => !shownIds.has(f.library));
  return (
    <nav aria-label={t.facets.label} className="space-y-2">
      <ul className="flex flex-wrap gap-x-2 gap-y-2 lg:flex-col lg:gap-y-1">
        <li className="lg:w-full">
          <Link
            to="/search"
            search={{ q }}
            aria-label={t.facets.allLabel(total)}
            aria-current={library ? undefined : "page"}
            className={cn(chip, chipTone(!library))}
          >
            <span>{t.facets.all}</span>
            <span aria-hidden="true" className="tabular-nums opacity-80">
              {formatNumber(total, language)}
            </span>
          </Link>
        </li>
        {shown.map((f) => (
          <FacetLink key={f.library} f={f} q={q} {...(library && { library })} />
        ))}
      </ul>
      {rest.length > 0 && (
        // The rest of the libraries with matches, in the library combobox: typed to, not scrolled.
        <LibraryCombobox
          label={t.facets.label}
          options={rest.map((f) => ({
            id: f.library,
            detail: formatNumber(f.matches, language),
            detailLabel: t.facets.matches(f.matches),
          }))}
          value={undefined}
          onChange={(id) => id && void navigate({ to: "/search", search: { q, library: id } })}
        >
          <Button
            variant="ghost"
            size="sm"
            className="px-1 font-normal text-muted-foreground can-hover:hover:text-foreground lg:min-h-9"
          >
            {t.facets.more(rest.length)}
            <ChevronDown aria-hidden="true" />
          </Button>
        </LibraryCombobox>
      )}
    </nav>
  );
}

interface Group {
  library: string;
  version: string;
  commit: string;
  hits: GlobalHit[];
}

/** Hits per library, in the order each library first appears (best hit first). */
function groupByLibrary(hits: readonly GlobalHit[]): Group[] {
  const groups = new Map<string, Group>();
  for (const hit of hits) {
    const key = `${hit.library}@${hit.version}`;
    const group = groups.get(key);
    if (group) group.hits.push(hit);
    else
      groups.set(key, {
        library: hit.library,
        version: hit.version,
        commit: hit.commit_sha,
        hits: [hit],
      });
  }
  return [...groups.values()];
}

function Hit({ hit }: { hit: GlobalHit }) {
  const { owner, repo } = splitLibrary(hit.library);
  return (
    // The whole row is the target (the title link stretches over it).
    <li className="row-in relative rounded-lg px-3 py-4 transition-colors duration-(--dur-fast) can-hover:hover:bg-raised">
      <Link
        data-result=""
        to="/libraries/$owner/$repo"
        params={{ owner, repo }}
        search={{ version: hit.version, path: hit.article_path }}
        {...(hit.anchor ? { hash: hit.anchor } : {})}
        className="rounded-md outline-none after:absolute after:inset-0 after:rounded-md after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring"
      >
        <Crumbs hit={hit} />
        <span className="mt-0.5 block font-mono text-small text-muted-foreground [overflow-wrap:anywhere]">
          {hit.article_path}
        </span>
      </Link>
      <Snippet hit={hit} />
    </li>
  );
}

/** One library's hits under its route: library, version, commit. */
function HitGroup({ group }: { group: Group }) {
  const t = useMessages(messages);
  const { owner, repo } = splitLibrary(group.library);
  return (
    <li>
      <h2 className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-body font-medium">
        <LibraryMark id={group.library} size="sm" />
        <Link
          to="/libraries/$owner/$repo"
          params={{ owner, repo }}
          search={{ version: group.version }}
          className="min-w-0 truncate rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          {owner}/{repo}
        </Link>
        <span
          aria-hidden="true"
          className="route-draw h-0.5 w-4 flex-none rounded-full bg-route/60"
        />
        <span className="font-mono text-small">
          <span className="sr-only">{t.results.version}</span>
          {group.version}
        </span>
        <span
          aria-hidden="true"
          className="route-draw h-0.5 w-4 flex-none rounded-full bg-route/60"
        />
        <span>
          <span className="sr-only">{t.results.commit}</span>
          <Commit sha={group.commit} />
        </span>
      </h2>
      <ul className="-mx-3 mt-2 divide-y divide-rule">
        {group.hits.map((hit) => (
          <Hit key={`${hit.library}:${hit.chunk_id}`} hit={hit} />
        ))}
      </ul>
    </li>
  );
}

function Notes({ data, library }: { data: GlobalResults; library: string | undefined }) {
  const t = useMessages(messages);
  const all = data.libraries_searched + data.libraries_omitted;
  return (
    <>
      {!data.coverage.complete && (
        <p className="mt-6 text-body text-muted-foreground">
          {t.results.bestOfAll(data.results.length, Boolean(library))}
        </p>
      )}
      {data.libraries_omitted > 0 && (
        <p className="mt-2 text-body text-muted-foreground">
          {t.results.omitted(
            data.libraries_searched,
            all,
            data.libraries_omitted,
            <Link to="/" className="underline underline-offset-2 hover:text-foreground">
              {t.results.browseLink}
            </Link>,
          )}
        </p>
      )}
    </>
  );
}

/** Nothing found, or a library that cannot be searched: says why and how to widen. */
function NoResults({
  q,
  library,
  unavailable = false,
}: {
  q: string;
  library: string | undefined;
  unavailable?: boolean;
}) {
  const t = useMessages(messages);
  return (
    <EmptyState
      icon={<SearchX aria-hidden="true" />}
      headingLevel={2}
      className="max-w-2xl"
      title={
        unavailable
          ? t.empty.unavailableTitle
          : library
            ? t.empty.noResultsIn(library)
            : t.empty.noResults
      }
      action={
        library && (
          <Link to="/search" search={{ q }} className={buttonVariants({ variant: "outline" })}>
            <Search aria-hidden="true" data-icon-motion="tilt" />
            {t.box.searchAll}
          </Link>
        )
      }
    >
      {unavailable
        ? t.empty.unavailable(
            <span className="font-mono text-foreground [overflow-wrap:anywhere]">{library}</span>,
          )
        : t.empty.nothing(
            <span className="font-medium text-foreground [overflow-wrap:anywhere]">
              {t.results.quote(q)}
            </span>,
            Boolean(library),
          )}
    </EmptyState>
  );
}

type GlobalQuery = UseQueryResult<GlobalResults>;

/** Before a query: what the box searches and what to type into it. */
function Prompt() {
  const t = useMessages(messages);
  return (
    <EmptyState icon={<Search aria-hidden="true" />} title={t.prompt.title} className="max-w-2xl">
      {t.prompt.body(
        <span className="font-mono text-foreground">retry policy</span>,
        <span className="font-mono text-foreground">401 unauthorized</span>,
      )}
      <span className="mt-2 hidden lg:block">{t.prompt.slash(<kbd className={kbd}>/</kbd>)}</span>
    </EmptyState>
  );
}

function Failed({ onRetry, pending }: { onRetry: () => void; pending: boolean }) {
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
        <Button variant="outline" size="sm" pending={pending} onClick={onRetry}>
          {!pending && <RotateCcw aria-hidden="true" data-icon-motion="refresh" />}
          {c.retry}
        </Button>
      }
    >
      {t.failed.all}
    </EmptyState>
  );
}

function Results({
  data,
  library,
  stale,
}: {
  data: GlobalResults;
  library: string | undefined;
  stale: boolean;
}) {
  const t = useMessages(messages);
  const language = useLanguage();
  const groups = groupByLibrary(data.results);
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: arrow keys move between the links inside
    <div onKeyDown={onArrows(focusGlobalInput)}>
      <p aria-hidden="true" className="mb-4 flex h-5 items-center text-body text-muted-foreground">
        <span className="font-medium text-foreground">
          {countLine(
            data.results.length,
            totalMatches(data, library),
            data.coverage.complete,
            language,
          )}
        </span>
        &nbsp;{t.results.inLibraries(groups.length)}
        <span className="ml-3 hidden text-small lg:inline">
          {t.results.moveHint(<kbd className={kbd}>↓</kbd>)}
        </span>
      </p>
      <ol
        className={cn(
          "space-y-8 transition-opacity duration-(--dur)",
          stale && "opacity-60 delay-150",
        )}
      >
        {groups.map((group) => (
          <HitGroup key={`${group.library}@${group.version}`} group={group} />
        ))}
      </ol>
      <Notes data={data} library={library} />
    </div>
  );
}

/** What sits under the box: the prompt, the skeleton, the error, the empty state or the hits. */
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

  if (q === undefined) return <Prompt />;
  if (result.isError && !stale) {
    return refused && library ? (
      <NoResults q={q} library={library} unavailable />
    ) : (
      <Failed onRetry={() => void result.refetch()} pending={result.isFetching} />
    );
  }
  if (!data) return <Skeleton chips />;

  const hits = data.results.length > 0;
  return (
    <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)] lg:items-start lg:gap-10">
      {data.libraries.length > 0 && (
        <div className="lg:sticky lg:top-20">
          <Facets data={data} q={q} {...(library && { library })} />
        </div>
      )}
      <div className={cn("min-w-0 max-w-[72ch]", data.libraries.length === 0 && "lg:col-span-2")}>
        {hits ? (
          <Results data={data} library={library} stale={stale} />
        ) : (
          settled && <NoResults q={q} library={library} />
        )}
      </div>
    </div>
  );
}

/** Results of the global search: hits from every library, grouped per library, with counts. */
export function GlobalSearchPage({ q: raw, library }: { q: string | undefined; library?: string }) {
  const t = useMessages(messages);
  const language = useLanguage();
  const heading = useId();
  const q = normalizeQuery(raw);
  const result = useQuery({
    ...globalSearchQueryOptions({ q: q ?? "", library }),
    enabled: q !== undefined,
  });

  const data = result.data;
  const settled = data !== undefined && !result.isPlaceholderData;
  return (
    <Page>
      <PageHeader
        icon={<Search />}
        title={
          q ? t.page.title(<span className="[overflow-wrap:anywhere]">{q}</span>) : t.box.searchAll
        }
        description={t.page.description}
      />
      {/* The band's box steps aside on this page (the CSS in GlobalSearchBox): this is the one field.
          Focused while there is no query (Back from an article must not bring the keyboard up). */}
      <GlobalSearchBox place="page" prominent autoFocus={q === undefined} className="mb-8" />
      <section
        id={GLOBAL_RESULTS_ID}
        aria-labelledby={heading}
        aria-busy={result.isFetching}
        className="min-w-0"
      >
        <h2 id={heading} className="sr-only">
          {t.results.heading}
        </h2>
        <p role="status" className="sr-only">
          {settled && q
            ? statusLine(data.results.length, q, library, data.coverage.complete, language)
            : ""}
        </p>
        <Body q={q} library={library} result={result} />
      </section>
    </Page>
  );
}
