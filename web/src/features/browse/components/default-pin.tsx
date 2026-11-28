import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pin, PinOff } from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { HttpError } from "@/shared/lib/http";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Spinner } from "@/shared/ui/spinner";
import { pinDefault, refreshDefault, unpinDefault } from "../api/default-pin";
import { messages } from "../messages";
import { pinChoices, type Version } from "../model/browse";

interface DefaultPinProps {
  owner: string;
  repo: string;
  current: Version;
  /** The library's default is pinned by an owner (`default_pinned`). */
  pinned: boolean;
}

const ACTION =
  "flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1 text-left text-body outline-none transition-[color,background-color,scale] duration-(--dur-fast) ease-(--ease-out) motion-safe:active:scale-[0.99] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring aria-disabled:cursor-progress aria-disabled:opacity-60 lg:min-h-9 can-hover:hover:bg-accent";

type Texts = (typeof messages)["en"]["versions"];

function explain(error: unknown, t: Texts): string {
  if (error instanceof HttpError && error.status === 404) return t.gone;
  if (error instanceof HttpError && error.status === 401) return t.signIn;
  return t.changeFailed;
}

interface PinActionProps {
  busy: boolean;
  working: boolean;
  icon: typeof Pin;
  label: ReactNode;
  hint?: string;
  onRun: () => void;
}

function PinAction({ busy, working, icon: Icon, label, hint, onRun }: PinActionProps) {
  return (
    <button
      type="button"
      aria-disabled={busy || undefined}
      aria-busy={working || undefined}
      onClick={() => !busy && onRun()}
      className={ACTION}
    >
      {working ? (
        <Spinner className="text-muted-foreground" />
      ) : (
        <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      )}
      <span className="min-w-0 flex-1">{label}</span>
      {hint && <span className="text-small text-muted-foreground">{hint}</span>}
    </button>
  );
}

/** Pin the shown version as the library's default, or unpin it (LIB-10). */
export function DefaultPin({ owner, repo, current, pinned }: DefaultPinProps) {
  const t = useMessages(messages).versions;
  const c = useMessages(common);
  const queryClient = useQueryClient();
  const change = useMutation({
    mutationFn: (pin: boolean) =>
      pin ? pinDefault(owner, repo, current.ref) : unpinDefault(owner, repo),
    onSuccess: (_saved, pin) => {
      refreshDefault(queryClient);
      toast.success(pin ? t.setToast : t.unpinnedToast, {
        description: pin ? current.ref : t.followsRule,
      });
    },
    onError: (error, pin) =>
      // The inline line under the buttons says the same; the toast offers the retry.
      toast.error(explain(error, t), {
        action: { label: c.retry, onClick: () => change.mutate(pin) },
      }),
  });
  const choices = pinChoices(current, pinned);
  const busy = change.isPending;
  const pinning = busy && change.variables === true;
  const unpinning = busy && change.variables === false;
  const doneLine = change.isSuccess ? (change.variables ? t.setTo(current.ref) : t.unpinned) : "";

  return (
    <div className="border-t border-border p-1">
      {choices.pin && (
        <PinAction
          busy={busy}
          working={pinning}
          icon={Pin}
          onRun={() => change.mutate(true)}
          label={t.pinAs(<span className="font-mono font-medium">{current.ref}</span>)}
        />
      )}
      {choices.unpin && (
        <PinAction
          busy={busy}
          working={unpinning}
          icon={PinOff}
          onRun={() => change.mutate(false)}
          label={t.unpin}
          hint={t.backToAutomatic}
        />
      )}
      <p
        role="status"
        className={cn(
          "px-2.5 text-small",
          change.isError ? "py-1.5 text-destructive" : "text-muted-foreground",
          !change.isError && !doneLine && "sr-only",
          !change.isError && doneLine && "py-1.5",
        )}
      >
        {change.isError ? explain(change.error, t) : doneLine}
      </p>
    </div>
  );
}
