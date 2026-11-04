import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { libraryQueryOptions } from "../api/browse-queries";
import {
  type BrowseSearch,
  type LibraryDetail,
  resolveVersion,
  type Version,
} from "../model/browse";
import { ArticleView, CommitLinks } from "./article-view";
import { FilesAside } from "./files-aside";
import { VersionPicker } from "./version-picker";

interface BrowsePageProps {
  owner: string;
  repo: string;
  search: BrowseSearch;
}

function Overview({ library, version }: { library: LibraryDetail; version: Version }) {
  return (
    <div className="fade-in max-w-2xl">
      <h2 className="font-serif text-2xl font-semibold tracking-tight">
        Browsing <span className="font-mono text-[0.9em]">{version.ref}</span>
      </h2>
      {library.description && <p className="mt-2 text-muted-foreground">{library.description}</p>}
      <p className="mt-4 text-muted-foreground">
        This is the text exactly as imported from commit{" "}
        <code className="font-mono text-foreground">{version.commit_sha.slice(0, 7)}</code>. Pick a
        file from the tree to read it.
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
}: BrowsePageProps & { library: LibraryDetail; version: Version }) {
  return (
    <div className="mt-6 grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] lg:items-start">
      <FilesAside
        owner={owner}
        repo={repo}
        version={version.ref}
        path={search.path}
        tags={search.tags}
      />
      <section aria-label="Article" className="min-w-0">
        {search.path ? (
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
          <Overview library={library} version={version} />
        )}
      </section>
    </div>
  );
}

export function BrowsePage({ owner, repo, search }: BrowsePageProps) {
  const { data: library } = useSuspenseQuery(libraryQueryOptions(owner, repo));
  const { version, missing } = resolveVersion(library, search.version);
  const heading = usePageTitle(library.title || library.id);

  return (
    <main className="mx-auto max-w-[88rem] px-4 py-6 sm:px-6 sm:py-8">
      <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
        <Link
          to="/"
          className="-ml-1 inline-flex min-h-11 items-center rounded px-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8"
        >
          Libraries
        </Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page" className="font-mono">
          {library.id.slice(1)}
        </span>
      </nav>
      <header className="mt-1 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1
            ref={heading}
            tabIndex={-1}
            className="font-serif text-3xl font-semibold tracking-tight outline-none [overflow-wrap:anywhere]"
          >
            {library.title || library.id}
          </h1>
          <a
            href={library.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-0.5 inline-flex max-w-full min-h-8 items-center gap-1 rounded text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="truncate">
              {library.source_url.replace(/^[a-z+]+:\/\//i, "").replace(/\.git$/, "")}
            </span>
            <ArrowUpRight aria-hidden="true" className="size-3 shrink-0" />
            <span className="sr-only">(opens the repository)</span>
          </a>
        </div>
        {version && (
          <div className="flex flex-col gap-1 sm:items-end">
            <VersionPicker
              owner={owner}
              repo={repo}
              versions={library.versions}
              current={version.ref}
              keep={{ path: search.path, tags: search.tags }}
            />
            <p className="text-sm text-muted-foreground">
              {version.kind}
              {" · imported "}
              <time dateTime={version.imported_at}>
                {new Date(version.imported_at).toLocaleDateString(undefined, {
                  dateStyle: "medium",
                })}
              </time>
            </p>
          </div>
        )}
      </header>
      {missing && version && (
        <p
          role="status"
          className="fade-in mt-4 max-w-2xl rounded-md bg-accent px-3 py-2.5 text-sm"
        >
          <span className="font-mono">{missing}</span> is not an imported version of this library.
          Showing <span className="font-mono">{version.ref}</span> instead.
        </p>
      )}
      {version ? (
        <VersionBrowser
          key={version.ref}
          owner={owner}
          repo={repo}
          search={search}
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
