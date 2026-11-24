import { Link } from "@tanstack/react-router";
import { History, Settings, Share2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/shared/ui/breadcrumb";
import { buttonVariants } from "@/shared/ui/button";
import { Page, PageHeader } from "@/shared/ui/page";
import { LibraryBullet } from "@/shared/ui/route";
import { pageMessages } from "../messages/page";
import { SECTIONS } from "../model/sections";
import type { Activity, JobViews, SettingsLibrary } from "../model/settings";
import { AiSection } from "./ai-section";
import { DangerSection } from "./danger-section";
import { DetailsForm } from "./details-form";
import { DirtyProvider, useDirtySections } from "./dirty";
import { PathsSection } from "./paths-section";
import { SettingsSection } from "./settings-section";
import { SyncSection } from "./sync-section";
import { VersionsSection } from "./versions-section";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  jobs: JobViews;
}

/** The section being read: the last heading above the top third of the viewport. */
function useActiveSection(): string {
  const [active, setActive] = useState<string>(SECTIONS[0][0]);
  useEffect(() => {
    const update = () => {
      const line = window.innerHeight * 0.33;
      let current: string = SECTIONS[0][0];
      for (const [id] of SECTIONS) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= line) current = id;
      }
      setActive(current);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);
  return active;
}

function SectionNav() {
  const t = useMessages(pageMessages);
  const dirty = useDirtySections();
  const active = useActiveSection();
  return (
    <nav aria-label={t.onThisPage} className="hidden lg:block">
      <div className="sticky top-17">
        <ul className="space-y-0.5">
          {SECTIONS.map(([id, key]) => (
            <li key={id}>
              <a
                href={`#${id}`}
                aria-current={active === id ? "location" : undefined}
                className={cn(
                  "flex min-h-8 items-center justify-between gap-2 rounded-md px-2.5 text-body text-muted-foreground outline-none transition-colors duration-(--dur-fast) hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
                  active === id && "bg-accent font-medium text-foreground",
                )}
              >
                {t.sections[key]}
                {dirty.has(key) && (
                  <>
                    <span aria-hidden="true" className="size-2 flex-none rounded-full bg-route" />
                    <span className="sr-only">{t.unsavedMark}</span>
                  </>
                )}
              </a>
            </li>
          ))}
        </ul>
        {dirty.size > 0 && (
          <p
            role="status"
            className="mt-4 rounded-md bg-route-soft px-2.5 py-2 text-small text-foreground"
          >
            {t.unsaved(dirty.size)}
          </p>
        )}
      </div>
    </nav>
  );
}

/** Libraries / the library's ID / Settings. */
export function SettingsBreadcrumb({
  owner,
  repo,
  id,
}: {
  owner: string;
  repo: string;
  id: string;
}) {
  const t = useMessages(pageMessages);
  return (
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink asChild>
            <Link to="/">{t.libraries}</Link>
          </BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem>
          <LibraryBullet id={id} size="sm" />
          <BreadcrumbLink asChild>
            <Link
              to="/libraries/$owner/$repo"
              params={{ owner, repo }}
              className="font-mono text-small [overflow-wrap:anywhere]"
            >
              {id}
            </Link>
          </BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem>
          <BreadcrumbPage>{t.settings}</BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
  );
}

/** Everything a person can change about one library, on one page. */
export function LibrarySettingsPage({ owner, repo, library, jobs }: Props) {
  const t = useMessages(pageMessages);
  const name = library.title || library.id;
  const heading = usePageTitle(t.title(name));
  // Each section clears its old notices when another one starts something.
  const [activity, setActivity] = useState<Activity>({ by: "", n: 0 });
  const start = (by: string) => () => setActivity((a) => ({ by, n: a.n + 1 }));
  return (
    <DirtyProvider>
      <Page>
        <PageHeader
          headingRef={heading}
          title={name}
          description={t.description}
          icon={<Settings />}
          above={<SettingsBreadcrumb owner={owner} repo={repo} id={library.id} />}
        />
        <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-12">
          <SectionNav />
          <div>
            <SettingsSection
              id="details"
              title={t.sections.details}
              description={t.details.description}
            >
              <DetailsForm
                owner={owner}
                repo={repo}
                library={library}
                activity={activity}
                onStart={start("details")}
              />
            </SettingsSection>
            <PathsSection
              owner={owner}
              repo={repo}
              library={library}
              Line={jobs.Line}
              Preview={jobs.Preview}
              activity={activity}
              onStart={start("paths")}
            />
            <VersionsSection
              owner={owner}
              repo={repo}
              library={library}
              Import={jobs.Import}
              activity={activity}
              onStart={start("versions")}
            />
            <AiSection owner={owner} repo={repo} activity={activity} onStart={start("ai")} />
            <SyncSection
              owner={owner}
              repo={repo}
              Line={jobs.Line}
              activity={activity}
              onStart={start("sync")}
            />
            <SettingsSection
              id="sharing"
              title={t.sections.sharing}
              description={t.sharing.description}
            >
              <div className="flex flex-wrap gap-2">
                <Link
                  to="/libraries/$owner/$repo/sharing"
                  params={{ owner, repo }}
                  className={buttonVariants({ variant: "outline" })}
                >
                  <Share2 aria-hidden="true" data-icon-motion="out" />
                  {t.sharing.manage}
                </Link>
                <Link
                  to="/libraries/$owner/$repo/access-log"
                  params={{ owner, repo }}
                  className={buttonVariants({ variant: "outline" })}
                >
                  <History aria-hidden="true" data-icon-motion="refresh" />
                  {t.sharing.accessLog}
                </Link>
              </div>
            </SettingsSection>
            <DangerSection owner={owner} repo={repo} library={library} onStart={start("danger")} />
          </div>
        </div>
      </Page>
    </DirtyProvider>
  );
}
