import { cn } from "@/shared/lib/utils";

/** The product's sign: a station on the route, in the route colour. */
export function Mark({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      className={cn("size-5 flex-none text-route", className)}
    >
      <circle cx="10" cy="10" r="9" fill="currentColor" />
      <circle cx="10" cy="10" r="3.75" className="fill-background" />
    </svg>
  );
}

/** Mark and name, as the band and the auth pages show them. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-section font-semibold tracking-[-0.01em]",
        className,
      )}
    >
      <Mark />
      ExactDocs
    </span>
  );
}
