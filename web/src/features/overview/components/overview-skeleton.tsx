import { LayoutDashboard, ShieldAlert } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Page, PageHeader, Section } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { overviewMessages } from "../messages";
import { ChartSkeleton, card } from "./chart-card";
import { NeedsAttentionSkeleton } from "./needs-attention";
import { StatTilesSkeleton } from "./stat-tiles";

/** The overview before its chunk and data arrive: the final layout, bars where the values go. */
export function OverviewSkeleton() {
  const t = useMessages(overviewMessages);
  return (
    <Page className="pending-in" aria-busy="true">
      <PageHeader
        title={t.title}
        icon={<LayoutDashboard />}
        description={t.description}
        actions={<Skeleton className="h-11 w-60 fine:h-9" />}
      />
      <p role="status" className="sr-only">
        {t.loading}
      </p>
      <div className="flex flex-col gap-10">
        <StatTilesSkeleton />
        <div className="grid gap-4 lg:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className={cn(card, "p-4")}>
              <Skeleton className="h-5 w-36" />
              <Skeleton className="mt-1 h-[2.125rem] w-28" />
              <div className="mt-4">
                <ChartSkeleton />
              </div>
            </div>
          ))}
        </div>
        <Section title={t.attention.title} icon={<ShieldAlert />}>
          <NeedsAttentionSkeleton />
        </Section>
      </div>
    </Page>
  );
}
