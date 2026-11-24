import { Activity } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { DataTableSkeleton } from "@/shared/ui/data-table/states";
import { Page, PageHeader } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { jobsMessages } from "../messages/jobs";

/** The jobs page before its first page of jobs: the final layout, bars where the values go. */
export function JobsSkeleton() {
  const t = useMessages(jobsMessages);
  const c = t.columns;
  return (
    <Page width="wide" className="pending-in" aria-busy="true">
      <PageHeader
        title={t.title}
        icon={<Activity />}
        description={<Skeleton className="h-5 w-20" />}
      />
      <p role="status" className="sr-only">
        {t.loading}
      </p>
      <DataTableSkeleton
        filters={4}
        columns={[
          { id: "id", header: "#", shape: "mono", className: "max-lg:hidden" },
          { id: "library", header: c.library, shape: "avatar" },
          { id: "version", header: c.version, shape: "mono" },
          { id: "kind", header: c.kind, shape: "pill" },
          { id: "state", header: c.state, shape: "pill" },
          { id: "progress", header: c.progress, shape: "meter", className: "max-md:hidden" },
          { id: "origin", header: c.origin, className: "max-xl:hidden" },
          { id: "created_by", header: c.startedBy, shape: "avatar", className: "max-lg:hidden" },
          { id: "queued", header: c.queued },
          { id: "took", header: c.took, className: "max-md:hidden" },
        ]}
      />
    </Page>
  );
}
