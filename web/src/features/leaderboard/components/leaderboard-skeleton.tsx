import { ListOrdered, Trophy } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { DataTableSkeleton } from "@/shared/ui/data-table/states";
import { Page, PageHeader, Section } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { leaderboardMessages } from "../messages";
import { PodiumSkeleton } from "./podium";

/** The leaderboard before its chunk and settings arrive: the final layout, bars for the values. */
export function LeaderboardSkeleton() {
  const t = useMessages(leaderboardMessages);
  const c = t.columns;
  return (
    <Page className="pending-in" aria-busy="true">
      <PageHeader title={t.title} icon={<Trophy />} description={t.description} />
      <p role="status" className="sr-only">
        {t.loading}
      </p>
      <div className="flex flex-col gap-8">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          {[t.metric, t.period].map((label) => (
            <div key={label} className="flex flex-col gap-1.5">
              <span className="text-small text-muted-foreground">{label}</span>
              <Skeleton className="h-11 w-64 fine:h-9" />
            </div>
          ))}
        </div>
        <Section title={t.top} icon={<Trophy />}>
          <PodiumSkeleton />
        </Section>
        <Section title={t.rest} icon={<ListOrdered />}>
          <DataTableSkeleton
            filters={0}
            actions={false}
            rows={5}
            columns={[
              { id: "rank", header: c.rank, shape: "number" },
              { id: "name", header: c.library, shape: "avatar" },
              { id: "value", header: c.value, shape: "number" },
              { id: "share", header: c.share, shape: "meter", className: "max-md:hidden" },
              { id: "change", header: c.change },
            ]}
          />
        </Section>
      </div>
    </Page>
  );
}
