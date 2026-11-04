import { Link } from "@tanstack/react-router";
import { usePageTitle } from "@/shared/lib/use-page-title";
import type { JobViews, SettingsLibrary } from "../model/settings";
import { DangerSection } from "./danger-section";
import { DetailsForm } from "./details-form";
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

/** Everything a person can change about one library, on one page. */
export function LibrarySettingsPage({ owner, repo, library, jobs }: Props) {
  const heading = usePageTitle(`${library.title || library.id} settings`);
  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
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
        className="mt-1 font-serif text-3xl font-semibold tracking-tight outline-none [overflow-wrap:anywhere]"
      >
        Settings
      </h1>
      <div className="max-w-xl">
        <section aria-labelledby="details-heading" className="mt-8">
          <h2 id="details-heading" className="font-serif text-2xl font-semibold tracking-tight">
            Details
          </h2>
          <DetailsForm owner={owner} repo={repo} library={library} />
        </section>
        <VersionsSection owner={owner} repo={repo} library={library} Import={jobs.Import} />
        <SyncSection owner={owner} repo={repo} Line={jobs.Line} />
        <DangerSection owner={owner} repo={repo} library={library} />
      </div>
    </main>
  );
}
