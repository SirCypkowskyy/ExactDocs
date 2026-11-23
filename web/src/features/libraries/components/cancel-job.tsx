import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { Button } from "@/shared/ui/button";
import { cancelJob } from "../api/cancel-job";
import { librariesKeys } from "../api/libraries-query";

/** The fields of a job (full or latest) that decide whether and how it can be cancelled. */
interface Cancellable {
  id: string;
  state: string;
  cancellable?: boolean;
  cancelled_at?: string | null;
}

function explain(error: unknown): string {
  if (!(error instanceof HttpError)) return "Can't reach the server. Try again.";
  if (error.status === 403) return "Your role on this library doesn't allow cancelling jobs.";
  if (error.status === 409) return "The job ended before it could be cancelled.";
  return `Something went wrong on the server (${error.status}). Try again.`;
}

/**
 * Cancel a queued or running job, after a confirmation. Shown only when the server says the caller
 * may (`cancellable`: the contributor role on the library); a job being cancelled says so instead.
 */
export function CancelJob({ job, label }: { job: Cancellable; label: string }) {
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
        Cancelling after the current step…
      </p>
    );
  }
  if (!job.cancellable) return null;
  return (
    <div className="mt-1 text-body">
      {asking ? (
        <fieldset
          aria-label={`Cancel ${label}?`}
          className="fade-in flex flex-wrap items-center gap-2"
        >
          <span className="max-w-[56ch]">
            {job.state === "queued"
              ? "Cancel this job? It will not start."
              : "Cancel this job? It stops after the current step and keeps what it finished."}
          </span>
          <Button
            variant="destructive"
            size="sm"
            pending={cancel.isPending}
            onClick={() => {
              if (!cancel.isPending) cancel.mutate();
            }}
          >
            Yes, cancel
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setAsking(false)}>
            Keep it
          </Button>
        </fieldset>
      ) : (
        <Button variant="ghost" size="sm" className="-ml-3" onClick={() => setAsking(true)}>
          Cancel <span className="sr-only">{label}</span>
        </Button>
      )}
      {cancel.isError && (
        <p role="alert" className="mt-1 font-medium text-destructive">
          {explain(cancel.error)}
        </p>
      )}
    </div>
  );
}
