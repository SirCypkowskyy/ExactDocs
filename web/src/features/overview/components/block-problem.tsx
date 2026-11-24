import { RefreshCw } from "lucide-react";
import { common, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";

/** A block that failed to load: one sentence inside the block, with a way to retry. */
export function BlockProblem({ message, onRetry }: { message: string; onRetry: () => void }) {
  const c = useMessages(common);
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-destructive-soft py-1.5 pr-1.5 pl-4"
    >
      <p className="text-body font-medium text-destructive-ink">{message}</p>
      <Button variant="ghost" size="sm" onClick={onRetry}>
        <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
        {c.retry}
      </Button>
    </div>
  );
}
