import { cn } from "@/shared/lib/utils";

/**
 * A flat grey bar at the size of the value that will replace it (DESIGN.md, States): no shimmer,
 * no pulse, so a slow load reads as "coming" rather than "busy". A span, so it fits in text too.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("block rounded-md bg-secondary", className)}
      {...props}
    />
  );
}

export { Skeleton };
