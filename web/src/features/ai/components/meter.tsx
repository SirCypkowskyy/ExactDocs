import { cn } from "@/shared/lib/utils";

const fill = {
  route: "bg-route",
  warning: "bg-warning",
  destructive: "bg-destructive",
} as const;

/**
 * A thin determinate bar: the fill grows with `transform: scaleX` (DESIGN.md, Motion). `value` is a
 * whole percent. The tone is `route` for progress; budgets turn `warning` or `destructive` only
 * when they are near or over.
 */
export function Meter({
  value,
  label,
  tone = "route",
  role = "progressbar",
  className,
}: {
  value: number;
  label: string;
  tone?: keyof typeof fill;
  role?: "progressbar" | "meter";
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    // biome-ignore lint/a11y/useAriaPropsSupportedByRole: role is progressbar or meter, both take these
    <div
      role={role}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-secondary", className)}
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
