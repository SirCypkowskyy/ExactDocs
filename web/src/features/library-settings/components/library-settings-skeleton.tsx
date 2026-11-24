import { useParams } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { Page, PageHeader } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { pageMessages } from "../messages/page";
import { pathsMessages } from "../messages/paths";
import { retrievalMessages } from "../messages/retrieval";
import { syncMessages } from "../messages/sync";
import { versionsMessages } from "../messages/versions";
import { SECTIONS, type SectionId } from "../model/sections";
import { SettingsBreadcrumb } from "./library-settings-page";
import { SettingsSection } from "./settings-section";

/** A label and its field, as bars. */
const field = (key: string, tall = false) => (
  <div key={key} className="flex flex-col gap-1.5">
    <Skeleton className="h-4 w-24" />
    <Skeleton className={tall ? "h-24 w-full" : "h-11 w-full fine:h-9"} />
  </div>
);

const button = (width = "w-32") => <Skeleton className={`h-11 fine:h-9 ${width}`} />;

/**
 * The settings page while the library loads (the route's `pendingComponent`, after 150 ms): the
 * final layout, headings and help already in place, grey bars where the values will be.
 */
export function LibrarySettingsSkeleton() {
  const t = useMessages(pageMessages);
  const paths = useMessages(pathsMessages);
  const versions = useMessages(versionsMessages);
  const retrieval = useMessages(retrievalMessages);
  const sync = useMessages(syncMessages);
  const { owner = "", repo = "" } = useParams({ strict: false }) as Record<string, string>;
  const body: Record<SectionId, [ReactNode, ReactNode]> = {
    details: [
      t.details.description,
      <div key="details" className="flex flex-col gap-5">
        {field("title")}
        {field("description", true)}
        {button()}
      </div>,
    ],
    paths: [
      paths.description,
      <div key="paths" className="flex flex-col gap-5">
        {field("include", true)}
        {field("exclude", true)}
        {button()}
      </div>,
    ],
    versions: [
      versions.description,
      <div key="versions" className="flex flex-col gap-4">
        {button("w-36")}
        <Skeleton className="h-11 w-full max-w-md fine:h-9" />
        <Skeleton className="h-48 w-full rounded-lg" />
      </div>,
    ],
    ai: [
      retrieval.description,
      <div key="ai" className="flex flex-col gap-3">
        <Skeleton className="h-28 w-full rounded-lg" />
        {field("mode")}
      </div>,
    ],
    sync: [sync.description, button()],
    sharing: [
      t.sharing.description,
      <div key="sharing" className="flex gap-2">
        {button("w-40")}
        {button("w-32")}
      </div>,
    ],
    danger: [t.danger.description, <Skeleton key="danger" className="h-32 w-full rounded-lg" />],
  };
  return (
    <Page className="pending-in" aria-busy="true">
      <PageHeader
        title={
          <>
            <span className="sr-only">{t.settings}</span>
            <Skeleton className="mt-1 h-7 w-56" />
          </>
        }
        mark={<Skeleton className="size-9 rounded-md" />}
        description={t.description}
        above={<SettingsBreadcrumb owner={owner} repo={repo} id={`/${owner}/${repo}`} />}
      />
      <p role="status" className="sr-only">
        {t.loading}
      </p>
      <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-12">
        <ul aria-hidden="true" className="hidden space-y-0.5 lg:block">
          {SECTIONS.map(([id, key]) => (
            <li
              key={id}
              className="flex min-h-8 items-center px-2.5 text-body text-muted-foreground"
            >
              {t.sections[key]}
            </li>
          ))}
        </ul>
        <div aria-hidden="true">
          {SECTIONS.map(([id, key]) => (
            <SettingsSection key={id} id={key} title={t.sections[key]} description={body[key][0]}>
              {body[key][1]}
            </SettingsSection>
          ))}
        </div>
      </div>
    </Page>
  );
}
