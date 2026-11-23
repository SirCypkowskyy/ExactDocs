import { cn } from "@/shared/lib/utils";

const fill = {
  route: "bg-route",
  warning: "bg-warning",
  destructive: "bg-destructive",
} as const;

/**
 * A thin determinate bar: the fill grows with `transform: scaleX` (DESIGN.md, Motion). `value` is a
 * whole percent; `null` means the total is not known yet, and the fill travels the track (`sweep`,
 * breathing in place with reduced motion). The tone is `route` for progress; budgets turn
 * `warning` or `destructive` only when they are near or over. Used by AI budgets, job progress
 * and the dashboard's stat tiles.
 */
export function Meter({
  value,
  label,
  tone = "route",
  role = "progressbar",
  className,
}: {
  value: number | null;
  label: string;
  tone?: keyof typeof fill;
  role?: "progressbar" | "meter";
  className?: string;
}) {
  const track = cn("h-1.5 w-full overflow-hidden rounded-full bg-secondary", className);
  if (value === null) {
    return (
      <div role="progressbar" aria-label={label} className={track}>
        <div className={cn("sweep h-full w-1/3 rounded-full", fill[tone])} />
      </div>
    );
  }
  const clamped = Math.max(0, Math.min(100, value));
  return (
    // biome-ignore lint/a11y/useAriaPropsSupportedByRole: role is progressbar or meter, both take these
    <div
      role={role}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      className={track}
    >
      <div
        className={cn(
          "h-full origin-left rounded-full transition-transform duration-(--dur-slow) ease-(--ease-out) motion-reduce:transition-none",
          fill[tone],
        )}
        style={{ transform: `scaleX(${clamped / 100})` }}
      />
    </div>
  );
}
