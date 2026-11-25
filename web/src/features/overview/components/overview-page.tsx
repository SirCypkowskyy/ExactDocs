import { type UseQueryResult, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { LayoutDashboard } from "lucide-react";
import { useMemo, useState } from "react";
import { formatMoney } from "@/shared/lib/format";
import { formatNumber, type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { LibraryMark } from "@/shared/ui/library-mark";
import { Meter } from "@/shared/ui/meter";
import { Page, PageHeader } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/shared/ui/toggle-group";
import { jobStatsQueryOptions, spendHistoryQueryOptions, usageQueryOptions } from "../api/overview";
import { overviewMessages } from "../messages";
import {
  type ChartRow,
  daysOf,
  firstDayOf,
  JOB_STATES,
  type JobState,
  jobRows,
  OVERVIEW_DAYS,
  type OverviewDays,
  parseOverviewView,
  peakOf,
  spendRows,
  sumOf,
  type UsageStats,
  usageRows,
} from "../model/overview";
import type { ChartSeries } from "./bar-chart";
import { BlockProblem } from "./block-problem";
import { ChartCard, card } from "./chart-card";
import { NeedsAttention } from "./needs-attention";
import { StatTiles } from "./stat-tiles";

/** Job states in their own colours (DESIGN.md, Charts: state series use the state tokens). */
const STATE_COLOURS: Record<JobState, string> = {
  succeeded: "var(--positive)",
  failed: "var(--destructive)",
  running: "var(--route)",
  queued: "var(--chart-series)",
  cancelled: "var(--border)",
};

const dayFormats = new Map<Language, Intl.DateTimeFormat>();
/** "Nov 24" / "24 lis": a UTC day, short. */
function formatDay(day: string, language: Language): string {
  let format = dayFormats.get(language);
  if (!format) {
    format = new Intl.DateTimeFormat(language, { month: "short", day: "numeric", timeZone: "UTC" });
    dayFormats.set(language, format);
  }
  return format.format(new Date(`${day}T00:00:00Z`));
}

/** The range switch in the page header: 7, 30 or 90 days, kept in the URL. */
function RangeSwitch({ days }: { days: OverviewDays }) {
  const t = useMessages(overviewMessages);
  const navigate = useNavigate();
  return (
    <ToggleGroup
      type="single"
      aria-label={t.range}
      value={String(days)}
      onValueChange={(value) => {
        if (!value) return;
        const next = Number(value) as OverviewDays;
        void navigate({
          to: ".",
          search: (prev: Record<string, unknown>) => ({
            ...prev,
            days: next === 30 ? undefined : next,
          }),
          replace: true,
          resetScroll: false,
        } as never);
      }}
    >
      {OVERVIEW_DAYS.map((d) => (
        <ToggleGroupItem key={d} value={String(d)}>
          {t.days(d)}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** The libraries read most in the range, as horizontal bars (after the free leaderboard1). */
function TopLibraries({ usage }: { usage: UseQueryResult<UsageStats> }) {
  const m = useMessages(overviewMessages);
  const t = m.top;
  const groups = (usage.data?.groups ?? []).filter((g) => g.reads > 0);
  const most = Math.max(1, ...groups.map((g) => g.reads));
  return (
    <section aria-labelledby="top-libraries" className={cn(card, "flex min-w-0 flex-col p-4")}>
      <h3 id="top-libraries" className="text-section font-semibold">
        {t.title}
      </h3>
      <div className="mt-4">
        {usage.isPending ? (
          <ul className="grid gap-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <li key={i} className="grid gap-1.5">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-1.5 w-full" />
              </li>
            ))}
          </ul>
        ) : usage.isError ? (
          <BlockProblem message={m.charts.failed} onRetry={() => void usage.refetch()} />
        ) : groups.length === 0 ? (
          <p className="text-body text-muted-foreground">{t.empty}</p>
        ) : (
          <ol className="grid gap-3">
            {groups.map((g) => {
              const id = g.library ?? "";
              const [, owner = "", repo = ""] = id.split("/");
              return (
                <li key={id || "several"} className="grid gap-1.5">
                  <span className="flex min-w-0 items-center gap-2">
                    {id ? (
                      <>
                        <LibraryMark id={id} size="sm" />
                        <Link
                          to="/libraries/$owner/$repo"
                          params={{ owner, repo }}
                          title={id}
                          className="min-w-0 truncate rounded-sm font-mono text-mono underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring can-hover:hover:underline"
                        >
                          {id}
                        </Link>
                      </>
                    ) : (
                      <span className="text-muted-foreground">{t.several}</span>
                    )}
                    <span className="num ml-auto flex-none text-small text-muted-foreground">
                      {t.reads(g.reads)}
                    </span>
                  </span>
                  <Meter
                    role="meter"
                    value={Math.round((g.reads / most) * 100)}
                    label={t.share(id || t.several)}
                  />
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}

/** Admin → Overview: stat tiles, chart cards and what needs attention (blocks-map §5.2). */
export function OverviewPage() {
  const t = useMessages(overviewMessages);
  const language = useLanguage();
  const heading = usePageTitle(t.title);
  const view = parseOverviewView(useSearch({ strict: false }) as Record<string, unknown>);
  const days = daysOf(view);
  // The range ends today (UTC); fixed once per mount so a page left open past midnight keeps its
  // queries (a reload or a range switch moves it on).
  const [now] = useState(() => Date.now());
  const from = firstDayOf(days, now);

  const jobs = useQuery(jobStatsQueryOptions(from));
  const spend = useQuery(spendHistoryQueryOptions(from));
  const usage = useQuery(usageQueryOptions(days));

  const day = (d: string) => formatDay(d, language);
  const count = (n: number) => formatNumber(n, language);
  const money = (n: number) => formatMoney(n, language);
  // The axis has room for "$4" or "4 USD", not "$4.00" or "4,00 USD".
  const moneyTick = (n: number) =>
    formatNumber(n, language, {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: 1,
    });
  const peakDay = (rows: readonly ChartRow[] | undefined, key: string) => {
    const peak = rows && peakOf(rows, key);
    return peak ? day(peak.day) : null;
  };

  const jobData = useMemo(() => jobs.data && jobRows(jobs.data), [jobs.data]);
  const spendData = useMemo(() => spend.data && spendRows(spend.data), [spend.data]);
  const usageData = useMemo(() => usage.data && usageRows(usage.data), [usage.data]);

  const jobSeries: ChartSeries[] = JOB_STATES.map((s) => ({
    key: s,
    label: t.charts.states[s],
    color: STATE_COLOURS[s],
  }));
  const jobTotal = jobData ? JOB_STATES.reduce((sum, s) => sum + sumOf(jobData, s), 0) : 0;
  const jobPeak = jobData
    ? peakOf(
        jobData.map((r) => ({
          day: r.day,
          total: JOB_STATES.reduce((n, s) => n + Number(r[s]), 0),
        })),
        "total",
      )
    : undefined;
  const spendTotal = spendData ? sumOf(spendData, "usd") : 0;
  const readsTotal = usageData ? sumOf(usageData, "reads") : 0;

  return (
    <Page>
      <PageHeader
        title={t.title}
        icon={<LayoutDashboard />}
        headingRef={heading}
        description={t.description}
        actions={<RangeSwitch days={days} />}
      />
      <div className="flex flex-col gap-10">
        <StatTiles jobsFrom={from} />
        <section aria-labelledby="charts-title">
          <h2 id="charts-title" className="sr-only">
            {t.charts.label}
          </h2>
          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard
              title={t.charts.reads.title}
              figure={t.charts.reads.figure(readsTotal)}
              summary={t.charts.reads.summary(readsTotal, days, peakDay(usageData, "reads"))}
              rows={usageData}
              series={[{ key: "reads", label: t.charts.reads.reads, color: "var(--chart-series)" }]}
              formatDay={day}
              formatValue={count}
              status={usage.status}
              onRetry={() => void usage.refetch()}
            />
            <ChartCard
              title={t.charts.spend.title}
              figure={money(spendTotal)}
              summary={t.charts.spend.summary(money(spendTotal), days, peakDay(spendData, "usd"))}
              rows={spendData}
              series={[{ key: "usd", label: t.charts.usd, color: "var(--chart-series)" }]}
              formatDay={day}
              formatValue={money}
              formatTick={moneyTick}
              status={spend.status}
              onRetry={() => void spend.refetch()}
            />
            <ChartCard
              title={t.charts.jobs.title}
              figure={t.charts.jobs.figure(jobTotal)}
              summary={t.charts.jobs.summary(jobTotal, days, jobPeak ? day(jobPeak.day) : null)}
              rows={jobData}
              series={jobSeries}
              stacked
              formatDay={day}
              formatValue={count}
              status={jobs.status}
              onRetry={() => void jobs.refetch()}
            />
            <TopLibraries usage={usage} />
          </div>
        </section>
        <NeedsAttention />
      </div>
    </Page>
  );
}
