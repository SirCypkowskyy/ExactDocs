// This module is the lazy chunk itself (chart-card.tsx imports it with `lazy()`).
// react-doctor-disable-next-line react-doctor/prefer-dynamic-import
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartRow } from "../model/overview";

/*
 * A bar chart for the overview's chart cards (after the free shadcnblocks chart-card3 (`chart-card3`),
 * on Recharts, MIT). This module is the only one that imports Recharts and is loaded lazily
 * (chart-card.tsx), so Recharts stays in its own chunk, out of the entry bundle.
 *
 * DESIGN.md, Charts: one grey (`chart-series`) for a series, state colours for states, the grid in
 * `rule`, axes in `text-small` muted, the tooltip in the inverted `tip`. Recharts tweens geometry,
 * which DESIGN does not allow, so every animation is off; the card fades in instead. The chart is
 * a picture (`role="img"` on its frame, named and described by the card), so Recharts' own
 * keyboard layer is off: "Show as table" gives the same numbers to everyone.
 */

export interface ChartSeries {
  key: string;
  label: string;
  /** A CSS colour, a token: `var(--chart-series)`, `var(--destructive)`. */
  color: string;
}

export interface BarChartProps {
  rows: readonly ChartRow[];
  series: readonly ChartSeries[];
  /** Stack the series in one bar per day (jobs by state) instead of one bar each. */
  stacked?: boolean;
  formatDay: (day: string) => string;
  formatValue: (value: number) => string;
  /** The value axis' labels, short (compact money); `formatValue` when left out. */
  formatTick?: ((value: number) => string) | undefined;
}

const AXIS = { fill: "var(--muted-foreground)", fontSize: 12 } as const;

function Tip({
  active,
  payload,
  label,
  formatDay,
  formatValue,
}: {
  active?: boolean | undefined;
  payload?:
    | readonly { dataKey?: unknown; name?: unknown; value?: unknown; color?: string | undefined }[]
    | undefined;
  label?: unknown;
} & Pick<BarChartProps, "formatDay" | "formatValue">) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md bg-tip px-2.5 py-1.5 text-small text-tip-foreground shadow-none">
      <p className="font-medium">{formatDay(String(label))}</p>
      <ul className="mt-0.5 grid gap-0.5">
        {payload.map((item) => (
          <li key={String(item.dataKey)} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="size-2 flex-none rounded-[2px]"
              style={{ background: item.color }}
            />
            <span>{String(item.name)}</span>
            <span className="num ml-auto pl-3">{formatValue(Number(item.value ?? 0))}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function OverviewBarChart({
  rows,
  series,
  stacked = false,
  formatDay,
  formatValue,
  formatTick = formatValue,
}: BarChartProps) {
  const last = series.length - 1;
  return (
    <BarChart
      responsive
      data={rows as ChartRow[]}
      accessibilityLayer={false}
      margin={{ top: 4, right: 0, bottom: 0, left: 0 }}
      barCategoryGap="20%"
      style={{ width: "100%", height: "12rem" }}
    >
      <CartesianGrid vertical={false} stroke="var(--rule)" />
      <XAxis
        dataKey="day"
        tickFormatter={formatDay}
        tickLine={false}
        axisLine={false}
        tick={AXIS}
        minTickGap={24}
      />
      <YAxis
        width={56}
        tickLine={false}
        axisLine={false}
        tick={AXIS}
        tickFormatter={(v: number) => formatTick(v)}
        allowDecimals={false}
      />
      <Tooltip
        cursor={{ fill: "var(--secondary)" }}
        isAnimationActive={false}
        content={({ active, payload, label }) => (
          <Tip
            active={active}
            payload={payload}
            label={label}
            formatDay={formatDay}
            formatValue={formatValue}
          />
        )}
      />
      {series.map((s, i) => (
        <Bar
          key={s.key}
          dataKey={s.key}
          name={s.label}
          fill={s.color}
          isAnimationActive={false}
          {...(stacked ? { stackId: "day" } : {})}
          radius={!stacked || i === last ? [3, 3, 0, 0] : 0}
        />
      ))}
    </BarChart>
  );
}
