import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
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
 * Cancel a queued or running job, after a confirmation. Shown only when the server says the caller
 * may (`cancellable`: the contributor role on the library); a job being cancelled says so instead.
 */
export function CancelJob({ job, label }: { job: Cancellable; label: string }) {
  const t = useMessages(progressMessages).cancel;
  const c = useMessages(common);
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const cancel = useMutation({
    mutationFn: () => cancelJob(job.id),
    onSettled: () => {
      setAsking(false);
      void queryClient.invalidateQueries({ queryKey: librariesKeys.all });
    },
  });
  const live = job.state === "queued" || job.state === "running";
  if (!live) return null;
  if (job.cancelled_at || cancel.isSuccess) {
    return (
      <p role="status" className="text-body text-muted-foreground">
        {t.cancelling}
      </p>
    );
  }
  if (!job.cancellable) return null;
  return (
    <div className="mt-1 text-body">
      {asking ? (
        <fieldset aria-label={t.ask(label)} className="fade-in flex flex-wrap items-center gap-2">
          <span className="max-w-[56ch]">{job.state === "queued" ? t.queued : t.running}</span>
          <Button
            variant="destructive"
            size="sm"
            pending={cancel.isPending}
            onClick={() => {
              if (!cancel.isPending) cancel.mutate();
            }}
          >
            {t.confirm}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setAsking(false)}>
            {t.keep}
          </Button>
        </fieldset>
      ) : (
        <Button variant="ghost" size="sm" className="-ml-3" onClick={() => setAsking(true)}>
          {c.cancel} <span className="sr-only">{label}</span>
        </Button>
      )}
      {cancel.isError && (
        <p role="alert" className="mt-1 font-medium text-destructive">
          {explainCancel(cancel.error, t)}
        </p>
      )}
    </div>
  );
}
