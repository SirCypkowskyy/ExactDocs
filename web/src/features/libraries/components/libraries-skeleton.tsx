import { LibraryBig } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { Page, PageHeader } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { listMessages } from "../messages/list";
import { TableSkeleton } from "./table-skeleton";

/** The list's final layout with grey bars where the values will be, so nothing jumps when they land. */
export function LibrariesSkeleton() {
  const t = useMessages(listMessages);
  const c = t.columns;
  return (
    <Page className="pending-in" aria-busy="true">
      <PageHeader
        title={t.title}
        icon={<LibraryBig />}
        description={<Skeleton className="h-5 w-24" />}
        actions={<Skeleton className="h-11 w-36 fine:h-9" />}
      />
      <p role="status" className="sr-only">
        {t.loading}
      </p>
      <TableSkeleton
        filters={3}
        columns={[
          { id: "library", header: c.library, shape: "avatar" },
          { id: "default", header: c.defaultVersion, shape: "mono" },
          { id: "versions", header: c.versions, shape: "number", className: "max-lg:hidden" },
          { id: "imported", header: c.lastImported },
          { id: "sync", header: c.sync, shape: "pill" },
        ]}
      />
    </Page>
  );
}
