import { useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowUpRight, ChevronRight, FolderTree } from "lucide-react";
import { useCallback, useState } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { libraryQueryOptions } from "../api/browse-queries";
import {
  type ArticleSummary,
  type BrowseSearch,
  type LibraryDetail,
  parseTags,
  resolveVersion,
  type Version,
} from "../model/browse";
import { ArticleView, CommitLinks } from "./article-view";
import { TagFilter } from "./tag-filter";
import { TreePane } from "./tree-pane";
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
  const navigate = useNavigate();
  const tags = parseTags(search.tags);
  const [filesOpen, setFilesOpen] = useState(!search.path);
  const [facetCounts, setFacetCounts] = useState<ReadonlyMap<string, number>>(new Map());

  // Remember every tag seen while browsing, so narrowing by one tag keeps the others on offer.
  const onFacets = useCallback((articles: Iterable<ArticleSummary>) => {
    setFacetCounts((prev) => {
      const next = new Map(prev);
      const counts = new Map<string, number>();
      for (const a of articles) for (const t of a.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
      let changed = false;
      for (const [t, n] of counts) {
        if ((next.get(t) ?? 0) < n) {
          next.set(t, n);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);
  const facets = [...facetCounts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([t]) => t);
  for (const t of tags)
    if (!facets.some((f) => f.toLowerCase() === t.toLowerCase())) facets.unshift(t);

  const setTags = (next: string | undefined) =>
    navigate({
      to: "/libraries/$owner/$repo",
      params: { owner, repo },
      search: { version: version.ref, path: search.path, tags: next },
      replace: true,
    });

  return (
    <div className="mt-6 grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] lg:items-start">
      <aside aria-label="Files" className="min-w-0 lg:sticky lg:top-4">
        <button
          type="button"
          aria-expanded={filesOpen}
          aria-controls="file-tree"
          onClick={() => setFilesOpen(!filesOpen)}
          className="flex h-11 w-full cursor-pointer items-center gap-2 rounded-md bg-secondary px-3 text-sm font-medium outline-none ring-1 ring-inset ring-border focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.99] lg:hidden"
        >
          <FolderTree aria-hidden="true" className="size-4 text-muted-foreground" />
          {search.path ? "Files" : "Browse files"}
          {tags.length > 0 && (
            <span className="font-normal text-muted-foreground">
              filtered by {tags.length === 1 ? "1 tag" : `${tags.length} tags`}
            </span>
          )}
          <ChevronRight
            aria-hidden="true"
            className={cn(
              "ml-auto size-4 text-muted-foreground transition-transform duration-150 motion-reduce:transition-none",
              filesOpen && "rotate-90",
            )}
          />
        </button>
        <div id="file-tree" className={cn("mt-3 space-y-3 lg:mt-0", !filesOpen && "max-lg:hidden")}>
          <TagFilter facets={facets.slice(0, 14)} selected={tags} onChange={setTags} />
          <div className="max-h-[min(70dvh,32rem)] overflow-y-auto overscroll-contain lg:max-h-[calc(100dvh-12rem)]">
            <TreePane
              key={search.tags ?? ""}
              owner={owner}
              repo={repo}
              version={version.ref}
              tags={tags}
              tagsParam={search.tags}
              selected={search.path}
              onFacets={onFacets}
              onClearTags={() => setTags(undefined)}
              onOpen={() => setFilesOpen(false)}
            />
          </div>
        </div>
      </aside>
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
