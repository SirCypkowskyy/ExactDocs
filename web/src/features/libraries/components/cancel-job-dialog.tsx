import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { toast } from "sonner";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { restoreRowFocus } from "@/shared/ui/data-table/row-actions";
import { cancelJob } from "../api/cancel-job";
import { librariesKeys } from "../api/libraries-query";
import { jobsMessages } from "../messages/jobs";
import { progressMessages } from "../messages/progress";
import { explainCancel } from "../model/cancel";
import type { Job } from "../model/library";

/**
 * Cancelling a job from the jobs table, behind a confirmation (DESIGN.md, "Confirm with
 * AlertDialog"): a queued job never starts, a running one stops after its current step. The
 * dialog stays until the server answers; a refusal is said inside it. Focus goes back to the row's
 * menu button.
 */
export function CancelJobDialog({ job, onClose }: { job: Job | undefined; onClose: () => void }) {
  const t = useMessages(jobsMessages);
  const language = useLanguage();
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: (id: string) => cancelJob(id),
    onSuccess: (ended) => {
      toast.success(ended.state === "cancelled" ? t.cancel.cancelled : t.cancel.stopping);
      onClose();
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: librariesKeys.all }),
  });
  const what = job && (
    <span className="font-mono text-foreground">
      {job.library}
      {job.version ? ` ${job.version}` : ""}
    </span>
  );
  return (
    <ConfirmDialog
      open={job !== undefined}
      onOpenChange={(open) => {
        if (!open) {
          cancel.reset();
          onClose();
        }
      }}
      title={t.cancel.title}
      description={
        job && (
          <>
            {t.kinds[job.kind as keyof typeof t.kinds] ?? job.kind}: {what}.{" "}
            {job.state === "queued" ? t.cancel.queued : t.cancel.running}
          </>
        )
      }
      confirmLabel={t.cancel.confirm}
      cancelLabel={t.cancel.keep}
      icon={<Ban aria-hidden="true" data-icon-motion="warn" />}
      pending={cancel.isPending}
      error={
        cancel.isError ? explainCancel(cancel.error, progressMessages[language].cancel) : undefined
      }
      onConfirm={() => {
        if (job && !cancel.isPending) cancel.mutate(job.id);
      }}
      onCloseAutoFocus={restoreRowFocus}
    />
  );
}
