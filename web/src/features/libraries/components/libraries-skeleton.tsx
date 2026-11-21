import { Page, PageHeader } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";

const rows = ["a", "b", "c", "d", "e"];

/** The list's final layout with grey bars where the values will be, so nothing jumps when they land. */
export function LibrariesSkeleton() {
  return (
    <Page className="pending-in" aria-busy="true">
      <PageHeader title="Libraries" description={<Skeleton className="h-5 w-24" />} />
      <p role="status" className="sr-only">
        Loading libraries
      </p>
      <ul aria-hidden="true" className="divide-y divide-rule">
        {rows.map((key) => (
          <li key={key} className="flex items-start gap-3 py-4 md:min-h-[76px]">
            <Skeleton className="size-9 rounded-full" />
            <div className="flex min-w-0 flex-1 flex-col gap-2 md:flex-row md:gap-6">
              <div className="flex flex-col gap-1.5 md:w-1/3">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-4 w-28" />
              </div>
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-20 md:ml-auto" />
            </div>
          </li>
        ))}
      </ul>
    </Page>
  );
}
