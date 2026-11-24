import { BarChart3, Table2 } from "lucide-react";
import { lazy, type ReactNode, Suspense, useId, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { Skeleton } from "@/shared/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableRowHeader,
} from "@/shared/ui/table";
import { overviewMessages } from "../messages";
import type { ChartRow } from "../model/overview";
import type { BarChartProps, ChartSeries } from "./bar-chart";
import { BlockProblem } from "./block-problem";

// Recharts lives only in this lazily loaded chunk (owner's decision; blocks-map §5.2).
const OverviewBarChart = lazy(() => import("./bar-chart"));

export const card = "rounded-lg border border-border bg-raised";

/** The chart's frame while its data or its chunk loads: the final size, no pulse. */
export function ChartSkeleton() {
  return <Skeleton className="h-48 w-full" />;
}

type Status = "pending" | "error" | "success";

interface ChartData {
  rows: readonly ChartRow[];
  series: readonly ChartSeries[];
  formatDay: BarChartProps["formatDay"];
  formatValue: BarChartProps["formatValue"];
  formatTick?: BarChartProps["formatTick"];
}

/** The same numbers as the chart, one row per day. */
function ChartTable({
  rows,
  series,
  formatDay,
  formatValue,
  titleId,
}: ChartData & { titleId: string }) {
  const t = useMessages(overviewMessages).charts;
  return (
    <Table containerClassName="max-h-72 overflow-y-auto" aria-labelledby={titleId}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t.day}</TableHead>
          {series.map((s) => (
            <TableHead key={s.key} scope="col" className="text-right">
              {s.label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.day}>
            <TableRowHeader>{formatDay(row.day)}</TableRowHeader>
            {series.map((s) => (
              <TableCell key={s.key} className="num text-right">
                {formatValue(Number(row[s.key] ?? 0))}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** The chart as a picture named by the card's title and described by its summary, and a legend. */
function ChartPicture({
  titleId,
  summaryId,
  stacked,
  ...data
}: ChartData & { titleId: string; summaryId: string; stacked: boolean }) {
  const legend = stacked || data.series.length > 1;
  return (
    <div className="fade-in">
      <div role="img" aria-labelledby={titleId} aria-describedby={summaryId}>
        <Suspense fallback={<ChartSkeleton />}>
          <OverviewBarChart {...data} stacked={stacked} />
        </Suspense>
      </div>
      {legend && (
        <ul aria-hidden="true" className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-small">
          {data.series.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-2.5 flex-none rounded-[2px]" style={{ background: s.color }} />
              {s.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The card's body for its status: a skeleton, the failure, nothing counted, the chart or table. */
function ChartBody({
  status,
  rows,
  asTable,
  onRetry,
  ...rest
}: Omit<ChartData, "rows"> & {
  status: Status;
  rows: readonly ChartRow[] | undefined;
  asTable: boolean;
  onRetry: () => void;
  titleId: string;
  summaryId: string;
  stacked: boolean;
}) {
  const t = useMessages(overviewMessages).charts;
  if (status === "pending") return <ChartSkeleton />;
  if (status === "error") return <BlockProblem message={t.failed} onRetry={onRetry} />;
  if (!rows || rows.length === 0)
    return <p className="text-body text-muted-foreground">{t.empty}</p>;
  return asTable ? <ChartTable rows={rows} {...rest} /> : <ChartPicture rows={rows} {...rest} />;
}

/** The title and the headline figure (a bar while it loads). */
function ChartHeading({
  titleId,
  title,
  figure,
  status,
}: {
  titleId: string;
  title: string;
  figure: ReactNode;
  status: Status;
}) {
  return (
    <div className="min-w-0">
      <h3 id={titleId} className="text-section font-semibold">
        {title}
      </h3>
      {status === "pending" && <Skeleton className="mt-1 h-[2.125rem] w-28" />}
      {status === "success" && <p className="num mt-1 text-figure">{figure}</p>}
    </div>
  );
}

/**
 * One chart card (after the free shadcnblocks chart-card1 / chart-card3): a title, the headline
 * figure, the chart, and "Show as table" for the same numbers. The chart is an image named by the
 * title and described by a one-sentence summary; the table is the accessible twin for everyone.
 */
export function ChartCard({
  title,
  figure,
  summary,
  rows,
  stacked = false,
  status,
  onRetry,
  ...data
}: Omit<ChartData, "rows"> & {
  title: string;
  figure: ReactNode;
  summary: string;
  rows: readonly ChartRow[] | undefined;
  stacked?: boolean;
  status: Status;
  onRetry: () => void;
}) {
  const t = useMessages(overviewMessages).charts;
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  const titleId = `${id}-title`;
  const summaryId = `${id}-summary`;
  const ready = status === "success" && rows !== undefined && rows.length > 0;
  return (
    <section aria-labelledby={titleId} className={`${card} flex min-w-0 flex-col p-4`}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <ChartHeading titleId={titleId} title={title} figure={figure} status={status} />
        {ready && (
          <Button
            variant="ghost"
            size="sm"
            aria-pressed={asTable}
            onClick={() => setAsTable((v) => !v)}
          >
            {asTable ? (
              <BarChart3 aria-hidden="true" data-icon-motion="pop" />
            ) : (
              <Table2 aria-hidden="true" data-icon-motion="pop" />
            )}
            {t.showTable}
          </Button>
        )}
      </div>
      <div className="mt-4 min-w-0">
        <ChartBody
          {...data}
          status={status}
          rows={rows}
          asTable={asTable}
          onRetry={onRetry}
          titleId={titleId}
          summaryId={summaryId}
          stacked={stacked}
        />
        {status === "success" && (
          <p id={summaryId} className="mt-2 text-small text-muted-foreground">
            {summary}
          </p>
        )}
      </div>
    </section>
  );
}
