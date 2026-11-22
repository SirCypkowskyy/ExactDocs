import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Page, PageHeader } from "@/shared/ui/page";
import { accessLogQueryOptions, libraryAccessLogQueryOptions } from "../api/access-log-query";
import type { AccessLogView } from "../model/access-log";
import { AccessLogList } from "./access-log-list";

const crumb =
  "-ml-1 inline-flex min-h-11 items-center rounded px-1 outline-none transition-colors duration-(--dur-fast) hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:min-h-7";

const NO_VIEW: AccessLogView = {};
const ignore = () => {};

interface ViewProps {
  /** The filter, held in the URL by the route. */
  view?: AccessLogView;
  onView?: (view: AccessLogView) => void;
}

/** One library's access log, for its admins and the server's operators. */
export function LibraryAccessLogPage({
  owner,
  repo,
  view = NO_VIEW,
  onView = ignore,
}: ViewProps & { owner: string; repo: string }) {
  const id = `/${owner}/${repo}`;
  const heading = usePageTitle(`${id} access log`);
  const log = useInfiniteQuery(libraryAccessLogQueryOptions(owner, repo, view));
  return (
    <Page>
      <PageHeader
        headingRef={heading}
        title="Access log"
        description="Who created, shared, unshared or handed over this library, and when. Newest first."
        above={
          <nav aria-label="Breadcrumb" className="text-body text-muted-foreground">
            <ol className="flex flex-wrap items-center gap-x-1.5">
              <li>
                <Link to="/" className={crumb}>
                  Libraries
                </Link>
              </li>
              <li aria-hidden="true">/</li>
              <li>
                <Link
                  to="/libraries/$owner/$repo"
                  params={{ owner, repo }}
                  className={`${crumb} font-mono text-small`}
                >
                  {id}
                </Link>
              </li>
              <li aria-hidden="true">/</li>
              <li>
                <Link
                  to="/libraries/$owner/$repo/settings"
                  params={{ owner, repo }}
                  className={crumb}
                >
                  Settings
                </Link>
              </li>
              <li aria-hidden="true">/</li>
              <li aria-current="page" className="text-foreground">
                Access log
              </li>
            </ol>
          </nav>
        }
      />
      <AccessLogList log={log} view={{ change: view.change }} onView={onView} />
    </Page>
  );
}

/** Every library's access log, removed libraries included: the operators' page. */
export function AccessLogPage({ view = NO_VIEW, onView = ignore }: ViewProps) {
  const heading = usePageTitle("Access log");
  const log = useInfiniteQuery(accessLogQueryOptions(view));
  return (
    <Page>
      <PageHeader
        headingRef={heading}
        title="Access log"
        description="Every library's creations, role changes, ownership transfers and removals, with who made them and when. Removed libraries keep their log here. Newest first."
      />
      <AccessLogList log={log} view={view} onView={onView} everyLibrary />
    </Page>
  );
}
