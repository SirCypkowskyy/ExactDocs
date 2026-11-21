import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, ChevronRight, CircleAlert } from "lucide-react";
import { useState } from "react";
import { absoluteTime, absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { jobQueryOptions, librariesKeys } from "../api/libraries-query";
import { reimportVersion } from "../api/reimport";
import type { SyncState } from "../hooks/use-libraries";
import { explainReimport, type LatestJob } from "../model/library";
import { CancelJob } from "./cancel-job";

const SKIPPED_SHOWN = 5;

function SkippedFiles({ job, open }: { job: LatestJob; open: boolean }) {
  const [all, setAll] = useState(false);
  const { data } = useQuery(jobQueryOptions(job.id, open && job.skipped > 0));
  if (job.skipped === 0) return null;
  // notes on imported files (e.g. front matter) are not skips; the count above excludes them
  const problems = (data?.problems ?? []).filter((p) => p.is_skip);
  return (
    <>
      <p className="mt-3 text-muted-foreground">Skipped files ({job.skipped})</p>
      <ul className="mt-1 space-y-1">
        {(all ? problems : problems.slice(0, SKIPPED_SHOWN)).map((p) => (
          <li key={p.path} className="[overflow-wrap:anywhere]">
            <span className="font-mono text-[13px]">{p.path}</span>
            <span className="text-muted-foreground"> {p.reason}</span>
          </li>
        ))}
      </ul>
      {!all && problems.length > SKIPPED_SHOWN && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-1 min-h-11 rounded text-muted-foreground underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
        >
          Show {problems.length - SKIPPED_SHOWN} more
        </button>
      )}
    </>
  );
}

/** The confirmation a moved tag waits for, right on its error: re-import the new commit. */
function ReimportMovedTag({ library, version }: { library: string; version: string }) {
  const queryClient = useQueryClient();
  const reimport = useMutation({
    mutationFn: () => reimportVersion(library, version),
    // The queued import is the version's newest job now: the list shows it instead of the error.
    onSettled: () => queryClient.invalidateQueries({ queryKey: librariesKeys.all }),
  });
  const problem = reimport.isError ? explainReimport(reimport.error) : undefined;
  if (reimport.isSuccess) {
    // Until the refetch replaces this error with the queued job: no second press, no 409.
    return (
      <p role="status" className="mt-3 font-medium">
        Queued: the new commit of {version} is being imported.
      </p>
    );
  }
  return (
    <div className="mt-3">
      {!problem?.final && (
        <button
          type="button"
          aria-disabled={reimport.isPending}
          aria-busy={reimport.isPending}
          onClick={() => {
            if (!reimport.isPending) reimport.mutate();
          }}
          className="inline-flex min-h-11 items-center rounded-md bg-foreground px-3 font-medium text-background outline-none transition-colors duration-(--dur-fast) hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
        >
          {reimport.isPending ? "Queueing" : "Re-import the new commit"}{" "}
          <span className="sr-only">of {version}</span>
        </button>
      )}
      <p role="alert" className={problem ? "mt-2" : undefined}>
        {problem && (
          <span className={problem.tone === "info" ? "text-foreground" : "text-destructive"}>
            {problem.message}
          </span>
        )}
      </p>
    </div>
  );
}

export function FailureDetail({ job, open }: { job: LatestJob; open: boolean }) {
  const finished = job.finished_at ?? job.created_at;
  const [, owner = "", repo = ""] = job.library.split("/");
  const moved = job.error_code === "tag_moved";
  return (
    <div className="mt-3 rounded-md bg-secondary px-3 py-3 text-body">
      <p className="text-muted-foreground">
        <span className="font-mono text-[13px]">{job.version ?? "Sync"}</span> failed{" "}
        <time dateTime={finished} title={absoluteTimeWithZone(finished)}>
          {absoluteTime(finished)}
        </time>
      </p>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap [overflow-wrap:anywhere] font-mono text-small">
        {job.error ?? "No reason was recorded."}
      </pre>
      <SkippedFiles job={job} open={open} />
      {moved && job.version && <ReimportMovedTag library={job.library} version={job.version} />}
      <Link
        to="/libraries/$owner/$repo/settings"
        params={{ owner, repo }}
        hash="sync-heading"
        className="mt-3 inline-flex min-h-11 items-center rounded-md bg-background px-3 font-medium outline-none ring-1 ring-inset ring-border transition-colors duration-(--dur-fast) hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
      >
        {moved ? "Review the moved tag in settings" : "Open settings to sync again"}
      </Link>
    </div>
  );
}

const muted = "text-body text-muted-foreground";

function Unknown({ sync }: { sync: Extract<SyncState, { status: string }> }) {
  if (sync.status === "pending") {
    return (
      <>
        <span
          aria-hidden="true"
          className="h-4 w-20 rounded bg-muted-foreground/10 motion-safe:animate-pulse"
        />
        <span className="sr-only">Checking sync status</span>
      </>
    );
  }
  return (
    <p className={muted}>
      <span aria-hidden="true">-</span>
      <span className="sr-only">Sync status unavailable</span>
    </p>
  );
}

function Running({ job }: { job: LatestJob }) {
  const label = `the sync of ${job.version ?? job.library}`;
  if (job.state === "queued") {
    return (
      <div className="text-body">
        <p>Queued</p>
        <CancelJob job={job} label={label} />
      </div>
    );
  }
  const known = job.total > 0;
  return (
    <div className="text-body">
      <p className="tabular-nums">
        {known ? `Importing ${job.done} of ${job.total}` : "Importing"}
      </p>
      <div
        role="progressbar"
        aria-label={`Import progress for ${job.library}`}
        aria-valuemin={0}
        aria-valuemax={known ? job.total : undefined}
        aria-valuenow={known ? job.done : undefined}
        className="mt-1.5 h-1 w-full max-w-40 overflow-hidden rounded-full bg-secondary"
      >
        <div
          className={cn(
            "h-full origin-left bg-route transition-transform duration-(--dur-slow) ease-(--ease-out)",
            !known && "w-1/3 motion-safe:animate-pulse",
          )}
          style={
            known ? { transform: `scaleX(${job.done / job.total})`, width: "100%" } : undefined
          }
        />
      </div>
      <CancelJob job={job} label={label} />
    </div>
  );
}

interface FailedProps {
  job: LatestJob;
  failures: number;
  now: number;
  open: boolean;
  onToggle: () => void;
  panel: string;
}

function Failed({ job, failures, now, open, onToggle, panel }: FailedProps) {
  return (
    <div className="min-w-0 text-body">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={onToggle}
        className="-ml-1 flex min-h-11 max-w-full items-center gap-1.5 rounded-md px-1 text-left outline-none transition-colors duration-(--dur-fast) hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
      >
        <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-destructive" />
        <span className="whitespace-nowrap font-medium text-destructive">
          {failures > 1 ? `${failures} versions failed` : "Sync failed"}
        </span>
        <span className="whitespace-nowrap text-muted-foreground">
          {relativeTime(job.finished_at ?? job.created_at, now)}
        </span>
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform duration-(--dur-fast) ease-out",
            open && "rotate-90",
          )}
        />
      </button>
      {job.error && !open && (
        <p className="line-clamp-2 text-small text-muted-foreground" title={job.error}>
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
      return (
        <Failed
          job={sync.job}
          failures={sync.failures}
          now={now}
          open={open}
          onToggle={onToggle}
          panel={panel}
        />
      );
    case "cancelled":
      return (
        <p className={muted}>
          Sync cancelled{sync.job.cancelled_by ? ` by ${sync.job.cancelled_by}` : ""}
        </p>
      );
    case "ok":
      return (
        <p className={cn(muted, "flex items-center gap-1")}>
          <Check aria-hidden="true" className="size-3.5 shrink-0" />
          {sync.skipped > 0 ? `Synced, ${sync.skipped} skipped` : "Synced"}
        </p>
      );
  }
}
