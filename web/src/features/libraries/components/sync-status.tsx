import { ChevronRight } from "lucide-react";
import { cn } from "@/shared/lib/utils";
import type { SyncState } from "../hooks/use-libraries";
import type { Job } from "../model/library";
import { absoluteTime, relativeTime } from "../model/time";

export function FailureDetail({ job, now }: { job: Job; now: number }) {
  const finished = job.finished_at ?? job.created_at;
  return (
    <div className="fade-in mt-3 rounded-md bg-secondary px-3 py-3 text-sm">
      <p className="text-muted-foreground">
        {job.version ? `Version ${job.version}` : "Sync"} failed{" "}
        <time dateTime={finished} title={absoluteTime(finished)}>
          {relativeTime(finished, now)} ({absoluteTime(finished)})
        </time>
      </p>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap [overflow-wrap:anywhere] font-mono text-xs">
        {job.error ?? "No reason was recorded."}
      </pre>
      {job.problems.length > 0 && (
        <>
          <p className="mt-3 text-muted-foreground">Skipped files</p>
          <ul className="mt-1 space-y-1">
            {job.problems.slice(0, 5).map((p) => (
              <li key={p.path} className="[overflow-wrap:anywhere]">
                <span className="font-medium">{p.path}</span>
                <span className="text-muted-foreground"> {p.reason}</span>
              </li>
            ))}
          </ul>
          {job.problems.length > 5 && (
            <p className="mt-1 text-muted-foreground">and {job.problems.length - 5} more</p>
          )}
        </>
      )}
    </div>
  );
}

const muted = "text-sm text-muted-foreground";

function Unknown({ sync }: { sync: Extract<SyncState, { status: string }> }) {
  if (sync.status === "pending") {
    return <span aria-hidden="true" className="h-4 w-20 animate-pulse rounded bg-secondary" />;
  }
  return (
    <p className={muted}>
      Status unavailable{" "}
      <button
        type="button"
        onClick={sync.retry}
        className="rounded underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        Retry
      </button>
    </p>
  );
}

function Running({ job }: { job: Job }) {
  const known = job.total > 0;
  const label = job.state === "queued" ? "Queued" : "Importing";
  return (
    <div className="text-sm">
      <p>{known && job.state === "running" ? `${label} ${job.done} of ${job.total}` : label}</p>
      <progress
        className="mt-1.5 block h-1 w-full max-w-40 overflow-hidden rounded-full [&::-moz-progress-bar]:bg-mark [&::-webkit-progress-bar]:bg-secondary [&::-webkit-progress-value]:bg-mark"
        aria-label={`Import progress for ${job.library}`}
        {...(known && { value: job.done, max: job.total })}
      />
    </div>
  );
}

interface FailedProps {
  job: Job;
  now: number;
  open: boolean;
  onToggle: () => void;
  panel: string;
}

function Failed({ job, now, open, onToggle, panel }: FailedProps) {
  return (
    <div className="min-w-0 text-sm">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={onToggle}
        className="-ml-1 flex min-h-8 max-w-full items-center gap-1.5 rounded-md px-1 text-left outline-none transition-colors duration-150 hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-destructive" />
        <span className="font-medium">Sync failed</span>
        <span className="text-muted-foreground">
          {relativeTime(job.finished_at ?? job.created_at, now)}
        </span>
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform duration-150",
            open && "rotate-90",
          )}
        />
        <span className="sr-only">{open ? "Hide details" : "Show details"}</span>
      </button>
      {job.error && !open && (
        <p className="truncate text-xs text-muted-foreground" title={job.error}>
          {job.error}
        </p>
      )}
    </div>
  );
}

interface SyncStatusProps {
  sync: SyncState;
  now: number;
  open: boolean;
  onToggle: () => void;
  panel: string;
}

export function SyncStatus({ sync, now, open, onToggle, panel }: SyncStatusProps) {
  if ("status" in sync) return <Unknown sync={sync} />;
  switch (sync.kind) {
    case "none":
      return <p className={muted}>Not synced yet</p>;
    case "running":
      return <Running job={sync.job} />;
    case "failed":
      return <Failed job={sync.job} now={now} open={open} onToggle={onToggle} panel={panel} />;
    case "ok":
      return (
        <p className={muted}>
          <span className="sr-only">Last sync </span>Synced{" "}
          {relativeTime(sync.job.finished_at ?? sync.job.created_at, now)}
        </p>
      );
  }
}
