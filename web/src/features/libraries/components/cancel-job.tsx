import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { useRef, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { cancelJob } from "../api/cancel-job";
import { librariesKeys } from "../api/libraries-query";
import { progressMessages } from "../messages/progress";
import { explainCancel } from "../model/cancel";

/** The fields of a job (full or latest) that decide whether and how it can be cancelled. */
interface Cancellable {
  id: string;
  state: string;
  cancellable?: boolean;
  cancelled_at?: string | null;
}

/**
 * Cancel a queued or running job, behind a confirmation (DESIGN.md, "Confirm with AlertDialog").
 * Shown only when the server says the caller may (`cancellable`: the contributor role on the
 * library); a job being cancelled says so instead. The dialog stays until the server answers, so
 * a refusal is said inside it; once the job is cancelling, focus lands on that sentence.
 */
export function CancelJob({ job, label }: { job: Cancellable; label: string }) {
  const t = useMessages(progressMessages).cancel;
  const c = useMessages(common);
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const status = useRef<HTMLParagraphElement>(null);
  const cancel = useMutation({
    mutationFn: () => cancelJob(job.id),
    onSuccess: () => setAsking(false),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: librariesKeys.all }),
  });
  const live = job.state === "queued" || job.state === "running";
  if (!live) return null;
  const cancelling = Boolean(job.cancelled_at) || cancel.isSuccess;
  if (!cancelling && !job.cancellable) return null;
  return (
    <div className="mt-1 text-body">
      {cancelling ? (
        <p ref={status} role="status" tabIndex={-1} className="text-muted-foreground outline-none">
          {t.cancelling}
        </p>
      ) : (
        <Button variant="ghost" size="sm" className="-ml-3" onClick={() => setAsking(true)}>
          <Ban aria-hidden="true" data-icon-motion="warn" />
          {c.cancel} <span className="sr-only">{label}</span>
        </Button>
      )}
      <ConfirmDialog
        open={asking}
        onOpenChange={(open) => {
          if (!open) {
            setAsking(false);
            cancel.reset();
          }
        }}
        title={t.ask(label)}
        description={job.state === "queued" ? t.willNotStart : t.stopsAfterStep}
        confirmLabel={t.confirm}
        cancelLabel={t.keep}
        icon={<Ban aria-hidden="true" data-icon-motion="warn" />}
        pending={cancel.isPending}
        error={cancel.isError ? explainCancel(cancel.error, t) : undefined}
        onConfirm={() => {
          if (!cancel.isPending) cancel.mutate();
        }}
        onCloseAutoFocus={(event) => {
          // The button that asked is gone once the job is cancelling: the sentence takes focus.
          if (status.current) {
            event.preventDefault();
            status.current.focus();
          }
        }}
      />
    </div>
  );
}
