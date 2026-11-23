import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, GitBranch, Info, LibraryBig, Settings, Share2 } from "lucide-react";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { usePageTitle } from "@/shared/lib/use-page-title";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/shared/ui/breadcrumb";
import { buttonVariants } from "@/shared/ui/button";
import { EmptyState, Page, PageHeader } from "@/shared/ui/page";
import { kbd } from "@/shared/ui/recipes";
import { LibraryBullet } from "@/shared/ui/route";
import { libraryQueryOptions } from "../api/browse-queries";
import { messages } from "../messages";
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
import { ArticlesTable } from "./articles-table";
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
  const t = useMessages(messages).page;
  return (
    <div className="fade-in max-w-[72ch]">
      <h2 className="text-section font-semibold">
        {t.browsing(<span className="font-mono">{version.ref}</span>)}
      </h2>
      {library.description && (
        <p className="mt-2 text-section text-pretty text-foreground">{library.description}</p>
      )}
      <ul className="mt-6 grid gap-x-8 gap-y-4 border-t border-rule pt-5 text-body text-muted-foreground sm:grid-cols-2">
        <li>
          <span className="block font-medium text-foreground">{t.readArticle}</span>
          {t.readArticleHint(
            <code className="font-mono text-foreground">{shortSha(version.commit_sha)}</code>,
          )}
        </li>
        {searchable && (
          <li>
            <span className="block font-medium text-foreground">
              {t.searchVersion(version.ref)}
            </span>
            {t.searchHint}
            <span className="hidden lg:inline"> {t.press(<kbd className={kbd}>/</kbd>)}</span>.
          </li>
        )}
      </ul>
      <div className="mt-4">
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
  const t = useMessages(messages).page;
  const scope = {
    ref: version.ref,
    sha: version.commit_sha,
    otherRefs: orderVersions(library.versions)
      .filter((v) => v.ref !== version.ref)
      .map((v) => v.ref),
  };
  const searching = slots !== undefined && search.q !== undefined;
  return (
    <div className="grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(17rem,20rem)_minmax(0,1fr)] lg:items-start xl:gap-x-14">
      <FilesAside
        owner={owner}
        repo={repo}
        versions={library.versions}
        version={version}
        pinned={library.default_pinned}
        path={search.path}
        tags={search.tags}
        searchBox={slots?.box(scope)}
        q={slots ? search.q : undefined}
        match={search.match}
      />
      <section aria-label={searching ? t.searchRegion : t.articleRegion} className="min-w-0">
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
          <>
            <Overview library={library} version={version} searchable={slots !== undefined} />
            <ArticlesTable
              owner={owner}
              repo={repo}
              library={library}
              version={version}
              search={search}
            />
          </>
        )}
      </section>
    </div>
  );
}

function UnknownVersion({ missing, shown }: { missing: string; shown: string }) {
  const t = useMessages(messages).page;
  return (
    <div className="reveal mb-6 max-w-2xl">
      <p
        role="status"
        className="flex items-start gap-2 rounded-md bg-route-soft px-3 py-2.5 text-body"
      >
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-route" />
        <span>
          {t.unknownVersion(
            <span className="font-mono">{missing}</span>,
            <span className="font-mono">{shown}</span>,
          )}
        </span>
      </p>
    </div>
  );
}

export function BrowsePage({ owner, repo, search, slots }: BrowsePageProps) {
  const t = useMessages(messages).page;
  const language = useLanguage();
  const { data: library } = useSuspenseQuery(libraryQueryOptions(owner, repo));
  const { version, missing } = resolveVersion(library, search.version);
  const heading = usePageTitle(library.title || library.id);
  const web = repoWebUrl(library.source_url);

  return (
    <Page width="wide">
      <PageHeader
        headingRef={heading}
        title={library.title || library.id}
        icon={<LibraryBig />}
        above={
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to="/" className="-ml-1 inline-flex min-h-11 items-center px-1 lg:min-h-7">
                    {t.libraries}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <LibraryBullet id={library.id} size="sm" />
                <BreadcrumbPage className="font-mono text-mono font-normal">
                  {library.id}
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        }
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {web && (
              <a
                href={web}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-8 max-w-full items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="truncate">{web.replace(/^https?:\/\//, "")}</span>
                <ArrowUpRight
                  aria-hidden="true"
                  data-icon-motion="out"
                  className="size-3 shrink-0"
                />
                <span className="sr-only">{t.opensRepository}</span>
              </a>
            )}
            {version && (
              <span>
                {t.imported(version.kind)}{" "}
                <time
                  dateTime={version.imported_at}
                  title={absoluteTimeWithZone(version.imported_at, language)}
                >
                  {relativeTime(version.imported_at, Date.now(), language)}
                </time>
              </span>
            )}
          </span>
        }
        actions={
          <>
            {/* On a phone the header keeps one button; sharing is linked from the settings. */}
            <Link
              to="/libraries/$owner/$repo/sharing"
              params={{ owner, repo }}
              className={buttonVariants({
                variant: "outline",
                size: "sm",
                className: "max-sm:hidden",
              })}
            >
              <Share2 aria-hidden="true" data-icon-motion="out" />
              {t.share}
            </Link>
            <Link
              to="/libraries/$owner/$repo/settings"
              params={{ owner, repo }}
              className={buttonVariants({
                variant: "outline",
                size: "sm",
                className: "max-sm:w-11 max-sm:px-0",
              })}
            >
              <Settings aria-hidden="true" data-icon-motion="cog" />
              <span className="max-sm:sr-only">{t.settings}</span>
            </Link>
          </>
        }
      />
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
        <EmptyState
          icon={<GitBranch aria-hidden="true" />}
          title={t.nothingImported}
          className="max-w-xl"
        >
          {t.noVersions}
        </EmptyState>
      )}
    </Page>
  );
}
