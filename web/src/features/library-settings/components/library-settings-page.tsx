import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Page, PageHeader } from "@/shared/ui/page";
import { LibraryBullet } from "@/shared/ui/route";
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

const crumb =
  "-ml-1 inline-flex min-h-11 items-center rounded px-1 outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:min-h-7";

/** [heading id, label, the id its form reports unsaved edits under]. */
const SECTIONS = [
  ["details-heading", "Details", "details"],
  ["paths-heading", "Files and tags", "paths"],
  ["versions-heading", "Versions", "versions"],
  ["ai-heading", "Retrieval and AI", "ai"],
  ["sync-heading", "Re-sync", "sync"],
  ["danger-heading", "Remove library", "danger"],
] as const;

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
  const dirty = useDirtySections();
  const active = useActiveSection();
  return (
    <nav aria-label="On this page" className="hidden lg:block">
      <div className="sticky top-17">
        <ul className="space-y-0.5">
          {SECTIONS.map(([id, label, key]) => (
            <li key={id}>
              <a
                href={`#${id}`}
                aria-current={active === id ? "location" : undefined}
                className={cn(
                  "flex min-h-8 items-center justify-between gap-2 rounded-md px-2.5 text-body text-muted-foreground outline-none transition-colors duration-(--dur-fast) hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
                  active === id && "bg-accent font-medium text-foreground",
                )}
              >
                {label}
                {dirty.has(key) && (
                  <>
                    <span aria-hidden="true" className="size-2 flex-none rounded-full bg-route" />
                    <span className="sr-only">(unsaved changes)</span>
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
            {dirty.size === 1 ? "1 section has" : `${dirty.size} sections have`} unsaved changes.
          </p>
        )}
      </div>
    </nav>
  );
}

/** Everything a person can change about one library, on one page. */
export function LibrarySettingsPage({ owner, repo, library, jobs }: Props) {
  const name = library.title || library.id;
  const heading = usePageTitle(`${name} settings`);
  // Each section clears its old notices when another one starts something.
  const [activity, setActivity] = useState<Activity>({ by: "", n: 0 });
  const start = (by: string) => () => setActivity((a) => ({ by, n: a.n + 1 }));
  return (
    <DirtyProvider>
      <Page>
        <PageHeader
          headingRef={heading}
          title={name}
          description="Library settings"
          above={
            <nav aria-label="Breadcrumb" className="text-body text-muted-foreground">
              <ol className="flex flex-wrap items-center gap-x-1.5">
                <li>
                  <Link to="/" className={crumb}>
                    Libraries
                  </Link>
                </li>
                <li aria-hidden="true">/</li>
                <li className="inline-flex items-center gap-1.5">
                  <LibraryBullet id={library.id} size="sm" />
                  <Link
                    to="/libraries/$owner/$repo"
                    params={{ owner, repo }}
                    className={`${crumb} font-mono text-small`}
                  >
                    {library.id}
                  </Link>
                </li>
                <li aria-hidden="true">/</li>
                <li aria-current="page" className="text-foreground">
                  Settings
                </li>
              </ol>
            </nav>
          }
        />
        <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-12">
          <SectionNav />
          <div>
            <SettingsSection
              id="details"
              title="Details"
              description="The title and description people see for this library."
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
            <DangerSection owner={owner} repo={repo} library={library} onStart={start("danger")} />
          </div>
        </div>
      </Page>
    </DirtyProvider>
  );
}
