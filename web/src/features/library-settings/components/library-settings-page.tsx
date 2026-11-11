import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import type { Activity, JobViews, SettingsLibrary } from "../model/settings";
import { AiSection } from "./ai-section";
import { DangerSection } from "./danger-section";
import { DetailsForm } from "./details-form";
import { PathsSection } from "./paths-section";
import { sectionHeading } from "./styles";
import { SyncSection } from "./sync-section";
import { VersionsSection } from "./versions-section";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  jobs: JobViews;
}

const crumb =
  "-ml-1 inline-flex min-h-11 items-center rounded px-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8";

const SECTIONS = [
  ["details-heading", "Details"],
  ["paths-heading", "Files and tags"],
  ["versions-heading", "Versions"],
  ["ai-heading", "Retrieval and AI"],
  ["sync-heading", "Re-sync"],
  ["danger-heading", "Remove library"],
] as const;

/** Everything a person can change about one library, on one page. */
export function LibrarySettingsPage({ owner, repo, library, jobs }: Props) {
  const name = library.title || library.id;
  const heading = usePageTitle(`${name} settings`);
  // Each section clears its old notices when another one starts something.
  const [activity, setActivity] = useState<Activity>({ by: "", n: 0 });
  const start = (by: string) => () => setActivity((a) => ({ by, n: a.n + 1 }));
  return (
    <main className="px-4 py-6 pb-12 sm:px-6 sm:py-8 sm:pb-16 2xl:mx-auto 2xl:max-w-[96rem]">
      <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
        <Link to="/" className={crumb}>
          Libraries
        </Link>
        <span aria-hidden="true"> / </span>
        <Link
          to="/libraries/$owner/$repo"
          params={{ owner, repo }}
          className={`${crumb} font-mono`}
        >
          {library.id}
        </Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page">Settings</span>
      </nav>
      <h1
        ref={heading}
        tabIndex={-1}
        className="mt-1 font-serif text-4xl font-semibold tracking-tight outline-none [overflow-wrap:anywhere]"
      >
        {name}
      </h1>
      <p className="mt-0.5 text-sm text-muted-foreground">Library settings</p>
      <div className="mt-8 lg:grid lg:grid-cols-[12rem_minmax(0,36rem)] lg:gap-12">
        <nav aria-label="On this page" className="hidden lg:block">
          <ul className="sticky top-6 space-y-0.5">
            {SECTIONS.map(([id, label]) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  className="block rounded-md px-2 py-1.5 text-sm text-muted-foreground outline-none transition-colors duration-150 hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div>
          <section aria-labelledby="details-heading">
            <h2 id="details-heading" className={sectionHeading}>
              Details
            </h2>
            <DetailsForm
              owner={owner}
              repo={repo}
              library={library}
              activity={activity}
              onStart={start("details")}
            />
          </section>
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
    </main>
  );
}
