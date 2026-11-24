import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { formatMoney } from "@/shared/lib/format";
import { formatNumber, useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Meter } from "@/shared/ui/meter";
import { Skeleton } from "@/shared/ui/skeleton";
import {
  aiUsageQueryOptions,
  jobStatsQueryOptions,
  libraryCountsQueryOptions,
  weekUsageQueryOptions,
} from "../api/overview";
import { overviewMessages } from "../messages";
import { BUDGET_NEAR, monthSpendOf, todayOf } from "../model/overview";
import { card } from "./chart-card";

type Status = "pending" | "error" | "success";

/**
 * One stat tile: a label, the figure (`text-figure`, no colour unless something is wrong), a line.
 * The figure stands alone, so its figures are proportional: tabular ones widen this face's full stop.
 */
function Tile({
  label,
  status,
  figure,
  children,
}: {
  label: string;
  status: Status;
  figure?: ReactNode;
  children?: ReactNode;
}) {
  const t = useMessages(overviewMessages).tiles;
  return (
    <li className={cn(card, "flex min-w-0 flex-col gap-1 p-4")}>
      <p className="text-small text-muted-foreground">{label}</p>
      {status === "pending" && (
        <>
          <Skeleton className="h-[2.125rem] w-20" />
          <Skeleton className="h-4 w-32" />
        </>
      )}
      {status === "error" && (
        <p role="alert" className="text-body text-destructive-ink">
          {t.failed}
        </p>
      )}
      {status === "success" && (
        <>
          <p className="text-figure">{figure}</p>
          <div className="text-small text-muted-foreground">{children}</div>
        </>
      )}
    </li>
  );
}

const tilesGrid = "grid gap-3 sm:grid-cols-2 xl:grid-cols-4";

/** The tiles' frame before anything is known: the same grid, bars where the values go. */
export function StatTilesSkeleton() {
  const t = useMessages(overviewMessages).tiles;
  return (
    <ul aria-label={t.label} className={tilesGrid}>
      {[t.libraries, t.jobsToday, t.spend, t.reads].map((label) => (
        <Tile key={label} label={label} status="pending" />
      ))}
    </ul>
  );
}

function LibrariesTile() {
  const t = useMessages(overviewMessages).tiles;
  const language = useLanguage();
  const { status, data } = useQuery(libraryCountsQueryOptions());
  return (
    <Tile
      label={t.libraries}
      status={status}
      figure={data && formatNumber(data.libraries, language)}
    >
      {data && t.holding(data.versions, data.articles)}
    </Tile>
  );
}

function JobsTile({ from }: { from: string }) {
  const t = useMessages(overviewMessages).tiles;
  const language = useLanguage();
  const { status, data } = useQuery(jobStatsQueryOptions(from));
  const today = data && todayOf(data);
  return (
    <Tile label={t.jobsToday} status={status} figure={today && formatNumber(today.total, language)}>
      {today && today.failed > 0 && (
        <Link
          to="/jobs"
          search={{ state: ["failed"], created: "24h" }}
          aria-label={`${t.failedToday(today.failed)}. ${t.showFailed}`}
          className="font-medium text-destructive-ink underline-offset-4 outline-none focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring can-hover:hover:underline"
        >
          {t.failedToday(today.failed)}
        </Link>
      )}
      {today && today.failed === 0 && t.failedToday(0)}
    </Tile>
  );
}

function SpendTile() {
  const t = useMessages(overviewMessages).tiles;
  const language = useLanguage();
  const { status, data } = useQuery(aiUsageQueryOptions());
  const spend = data && monthSpendOf(data);
  const used = spend?.limit ? Math.round((spend.usd / spend.limit) * 100) : null;
  const tone =
    used === null
      ? "route"
      : used >= 100
        ? "destructive"
        : used >= BUDGET_NEAR
          ? "warning"
          : "route";
  return (
    <Tile label={t.spend} status={status} figure={spend && formatMoney(spend.usd, language)}>
      {spend && (spend.limit === null || used === null) && t.noBudget}
      {spend && spend.limit !== null && used !== null && (
        <span className="flex flex-col gap-1.5">
          <span>{t.budget(formatMoney(spend.limit, language))}</span>
          <Meter role="meter" value={used} label={t.budgetUsed} tone={tone} />
        </span>
      )}
    </Tile>
  );
}

function ReadsTile() {
  const t = useMessages(overviewMessages).tiles;
  const language = useLanguage();
  const { status, data } = useQuery(weekUsageQueryOptions());
  return (
    <Tile label={t.reads} status={status} figure={data && formatNumber(data.total.reads, language)}>
      {data && t.readsBreakdown(data.total.searches, data.total.answers)}
    </Tile>
  );
}

/** Libraries, today's jobs, this month's AI spend and this week's reads, each loading on its own. */
export function StatTiles({ jobsFrom }: { jobsFrom: string }) {
  const t = useMessages(overviewMessages).tiles;
  return (
    <ul aria-label={t.label} className={tilesGrid}>
      <LibrariesTile />
      <JobsTile from={jobsFrom} />
      <SpendTile />
      <ReadsTile />
    </ul>
  );
}
