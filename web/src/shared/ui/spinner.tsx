import { cn } from "@/shared/lib/utils";

/** The one busy mark: a ring in the current text colour. Breathes instead of turning under reduced motion. */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "spin inline-block size-4 shrink-0 rounded-full border-2 border-current/30 border-t-current",
        className,
      )}
    />
  );
}
