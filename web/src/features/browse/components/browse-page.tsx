import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Info } from "lucide-react";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { libraryQueryOptions } from "../api/browse-queries";
import {
  type BrowseSearch,
  type LibraryDetail,
  orderVersions,
  repoWebUrl,
  resolveVersion,
  type SearchSlots,
  shortSha,
  type Version,
} from "../model/browse";
import { ArticleView, CommitLinks } from "./article-view";
import { FilesAside } from "./files-aside";

interface BrowsePageProps {
  owner: string;
  repo: string;
  search: BrowseSearch;
  /** The search box and results, composed by the route (a feature never imports another). */
  slots?: SearchSlots | undefined;
}

function Overview({
  library,
  version,
  searchable,
}: {
  library: LibraryDetail;
  version: Version;
  searchable: boolean;
}) {
  return (
    <div className="fade-in max-w-3xl">
      <h2 className="font-serif text-2xl font-semibold tracking-tight">
        Browsing <span className="font-mono text-[0.9em]">{version.ref}</span>
      </h2>
      {library.description && <p className="mt-2 text-muted-foreground">{library.description}</p>}
      <p className="mt-4 text-muted-foreground">
        This is the text exactly as imported from commit{" "}
        <code className="font-mono text-foreground">{shortSha(version.commit_sha)}</code>. Pick a
        file from the tree to read it.
        {searchable && (
          <>
            {" "}
            Or search every article in{" "}
            <span className="font-mono text-foreground">{version.ref}</span>
            <span className="hidden lg:inline">
              {" "}
              (press <kbd className="rounded bg-secondary px-1 font-mono text-xs">/</kbd>)
            </span>
            .
          </>
        )}
      </p>
      <div className="mt-2">
        <CommitLinks library={library} version={version} />
      </div>
    </div>
  );
}

/** Everything that depends on the version: remount it (with a `key`) when the version changes. */
function VersionBrowser({
  owner,
  repo,
  library,
  version,
  search,
  slots,
}: BrowsePageProps & { library: LibraryDetail; version: Version }) {
  const scope = {
    ref: version.ref,
    sha: version.commit_sha,
    otherRefs: orderVersions(library.versions)
      .filter((v) => v.ref !== version.ref)
      .map((v) => v.ref),
  };
  const searching = slots !== undefined && search.q !== undefined;
  return (
    <div className="mt-6 grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] lg:items-start">
      <FilesAside
        owner={owner}
        repo={repo}
        versions={library.versions}
        version={version}
        path={search.path}
        tags={search.tags}
        searchBox={slots?.box(scope)}
        q={slots ? search.q : undefined}
        match={search.match}
      />
      <section aria-label={searching ? "Search" : "Article"} className="min-w-0">
        {searching ? (
          slots.results(scope)
        ) : search.path ? (
          <ArticleView
            key={search.path}
            owner={owner}
            repo={repo}
            library={library}
            version={version}
            path={search.path}
            tags={search.tags}
          />
        ) : (
          <Overview library={library} version={version} searchable={slots !== undefined} />
        )}
      </section>
    </div>
  );
}

function UnknownVersion({ missing, shown }: { missing: string; shown: string }) {
  return (
    <div className="expand-in mt-4 grid max-w-2xl">
      <p
        role="status"
        className="flex items-start gap-2 overflow-hidden rounded-md bg-accent px-3 py-2.5 text-sm"
      >
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
        <span>
          <span className="font-mono">{missing}</span> is not an imported version of this library.
          Showing <span className="font-mono">{shown}</span> instead.
        </span>
      </p>
    </div>
  );
}

export function BrowsePage({ owner, repo, search, slots }: BrowsePageProps) {
  const { data: library } = useSuspenseQuery(libraryQueryOptions(owner, repo));
  const { version, missing } = resolveVersion(library, search.version);
  const heading = usePageTitle(library.title || library.id);
  const web = repoWebUrl(library.source_url);

  return (
    <main className="px-4 py-6 sm:px-6 sm:py-8 2xl:mx-auto 2xl:max-w-[96rem]">
      <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
        <Link
          to="/"
          className="-ml-1 inline-flex min-h-11 items-center rounded px-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8"
        >
          Libraries
        </Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page" className="font-mono">
          {library.id}
        </span>
      </nav>
      <h1
        ref={heading}
        tabIndex={-1}
        className="mt-1 font-serif text-3xl font-semibold tracking-tight outline-none [overflow-wrap:anywhere]"
      >
        {library.title || library.id}
      </h1>
      <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
        {web && (
          <a
            href={web}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 max-w-full items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="truncate">{web.replace(/^https?:\/\//, "")}</span>
            <ArrowUpRight aria-hidden="true" className="size-3 shrink-0" />
            <span className="sr-only">(opens the repository)</span>
          </a>
        )}
        {version && (
          <span>
            {version.kind === "tag" ? "Imported" : `${capitalize(version.kind)} · imported`}{" "}
            <time dateTime={version.imported_at} title={absoluteTimeWithZone(version.imported_at)}>
              {relativeTime(version.imported_at, Date.now())}
            </time>
          </span>
        )}
      </p>
      {missing && version && <UnknownVersion missing={missing} shown={version.ref} />}
      {version ? (
        <VersionBrowser
          key={`${version.ref}@${version.commit_sha}`}
          owner={owner}
          repo={repo}
          search={search}
          slots={slots}
          library={library}
          version={version}
        />
      ) : (
        <div className="mt-8 max-w-xl">
          <h2 className="font-serif text-2xl font-semibold tracking-tight">Nothing imported yet</h2>
          <p className="mt-2 text-muted-foreground">
            This library has no versions. Once its first import finishes they appear here.
          </p>
        </div>
      )}
    </main>
  );
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
