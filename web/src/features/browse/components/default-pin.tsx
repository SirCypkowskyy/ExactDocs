import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pin, PinOff } from "lucide-react";
import { HttpError } from "@/shared/lib/http";
import { cn } from "@/shared/lib/utils";
import { pinDefault, refreshDefault, unpinDefault } from "../api/default-pin";
import { pinChoices, type Version } from "../model/browse";

interface DefaultPinProps {
  owner: string;
  repo: string;
  current: Version;
  /** The library's default is pinned by an owner (`default_pinned`). */
  pinned: boolean;
}

const ACTION =
  "flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1 text-left text-sm outline-none transition-colors duration-100 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-progress disabled:opacity-60 lg:min-h-9 [@media(hover:hover)]:hover:bg-accent";

function explain(error: unknown): string {
  if (error instanceof HttpError && error.status === 404)
    return "That version is no longer imported. Reload the page.";
  if (error instanceof HttpError && error.status === 401) return "Sign in again to change this.";
  return "The default could not be changed. Try again.";
}

/** Pin the shown version as the library's default, or unpin it (LIB-10). */
export function DefaultPin({ owner, repo, current, pinned }: DefaultPinProps) {
  const queryClient = useQueryClient();
  const change = useMutation({
    mutationFn: (pin: boolean) =>
      pin ? pinDefault(owner, repo, current.ref) : unpinDefault(owner, repo),
    onSuccess: () => refreshDefault(queryClient),
  });
  const choices = pinChoices(current, pinned);
  const busy = change.isPending;

  return (
    <div className="border-t border-border p-1">
      {choices.pin && (
        <button
          type="button"
          disabled={busy}
          onClick={() => change.mutate(true)}
          className={ACTION}
        >
          <Pin aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1">
            Pin <span className="font-mono font-medium">{current.ref}</span> as default
          </span>
        </button>
      )}
      {choices.unpin && (
        <button
          type="button"
          disabled={busy}
          onClick={() => change.mutate(false)}
          className={ACTION}
        >
          <PinOff aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1">Unpin default</span>
          <span className="text-xs text-muted-foreground">back to automatic</span>
        </button>
      )}
      <p
        role="status"
        className={cn("px-2.5 text-xs text-destructive", change.isError ? "py-1.5" : "sr-only")}
      >
        {change.isError ? explain(change.error) : ""}
      </p>
    </div>
  );
}
