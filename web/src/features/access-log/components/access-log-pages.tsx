import { Link, useSearch } from "@tanstack/react-router";
import { ScrollText } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/shared/ui/breadcrumb";
import { Page, PageHeader } from "@/shared/ui/page";
import { accessLogSource, libraryAccessLogSource } from "../api/access-log-query";
import { messages } from "../messages";
import {
  ACCESS_LOG_TABLE,
  LIBRARY_ACCESS_LOG_TABLE,
  parseAccessLogView,
  parseLibraryAccessLogView,
} from "../model/access-log";
import { AccessLogTable } from "./access-log-list";

/** The URL's search, as the route validated it (or as typed, in a test). */
const useRawSearch = () => useSearch({ strict: false }) as Record<string, unknown>;

/** One library's access log, for its admins and the server's operators. */
export function LibraryAccessLogPage({ owner, repo }: { owner: string; repo: string }) {
  const id = `/${owner}/${repo}`;
  const t = useMessages(messages).pages;
  const heading = usePageTitle(t.libraryTitle(id));
  const view = parseLibraryAccessLogView(useRawSearch());
  return (
    <Page>
      <PageHeader
        headingRef={heading}
        icon={<ScrollText />}
        title={t.title}
        description={t.libraryDescription}
        above={
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to="/">{t.libraries}</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbLink asChild className="font-mono text-small">
                  <Link to="/libraries/$owner/$repo" params={{ owner, repo }}>
                    {id}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to="/libraries/$owner/$repo/sharing" params={{ owner, repo }}>
                    {t.sharing}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>{t.title}</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        }
      />
      <AccessLogTable
        view={view}
        config={LIBRARY_ACCESS_LOG_TABLE}
        source={libraryAccessLogSource(owner, repo, view)}
      />
    </Page>
  );
}

/** Every library's access log, removed libraries included: the operators' page. */
export function AccessLogPage() {
  const t = useMessages(messages).pages;
  const heading = usePageTitle(t.title);
  const view = parseAccessLogView(useRawSearch());
  return (
    <Page>
      <PageHeader
        headingRef={heading}
        icon={<ScrollText />}
        title={t.title}
        description={t.description}
      />
      <AccessLogTable
        view={view}
        config={ACCESS_LOG_TABLE}
        source={accessLogSource(view)}
        everyLibrary
      />
    </Page>
  );
}
