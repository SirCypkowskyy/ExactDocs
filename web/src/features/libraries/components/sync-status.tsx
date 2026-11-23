import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown, CircleX, ListChecks, RefreshCw, TriangleAlert } from "lucide-react";
import { useContext, useId, useState } from "react";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { absoluteTime, absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { useNow } from "@/shared/lib/use-now";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { Button, buttonVariants } from "@/shared/ui/button";
import { StateBadge } from "@/shared/ui/data-table/cells";
import { FormAlert } from "@/shared/ui/form-alert";
import { Meter } from "@/shared/ui/meter";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { Skeleton } from "@/shared/ui/skeleton";
import { jobQueryOptions, librariesKeys } from "../api/libraries-query";
import { reimportVersion } from "../api/reimport";
import { SyncContext } from "../hooks/sync-context";
import type { SyncState } from "../hooks/use-libraries";
import { listMessages } from "../messages/list";
import { explainReimport, type LatestJob } from "../model/library";
import { CancelJob } from "./cancel-job";

/*
 * The Sync column of the libraries table: what the newest job of each version says, as a state
 * badge. A failed sync opens its details (the reason, the skipped files, the way to fix it) in a
 * popover from the badge, so the row keeps its height.
 */

const SKIPPED_SHOWN = 5;

function SkippedFiles({ job }: { job: LatestJob }) {
  const t = useMessages(listMessages).failure;
  const [all, setAll] = useState(false);
  const { data } = useQuery(jobQueryOptions(job.id, job.skipped > 0));
  if (job.skipped === 0) return null;
  // notes on imported files (e.g. front matter) are not skips; the count above excludes them
  const problems = (data?.problems ?? []).filter((p) => p.is_skip);
  return (
    <>
      <p className="mt-3 text-muted-foreground">{t.skippedFiles(job.skipped)}</p>
      <ul className="mt-1 space-y-1">
        {(all ? problems : problems.slice(0, SKIPPED_SHOWN)).map((p) => (
          <li key={p.path} className="[overflow-wrap:anywhere]">
            <span className="font-mono text-mono">{p.path}</span>
            <span className="text-muted-foreground"> {p.reason}</span>
          </li>
        ))}
      </ul>
      {!all && problems.length > SKIPPED_SHOWN && (
        <Button variant="ghost" size="sm" className="mt-1 -ml-3" onClick={() => setAll(true)}>
          <ListChecks aria-hidden="true" />
          {t.showMore(problems.length - SKIPPED_SHOWN)}
        </Button>
      )}
    </>
  );
}

/** The confirmation a moved tag waits for, right on its error: re-import the new commit. */
function ReimportMovedTag({ library, version }: { library: string; version: string }) {
  const language = useLanguage();
  const t = listMessages[language].reimport;
  const queryClient = useQueryClient();
  const alertId = useId();
  const reimport = useMutation({
    mutationFn: () => reimportVersion(library, version),
    // The queued import is the version's newest job now: the list shows it instead of the error.
    onSettled: () => queryClient.invalidateQueries({ queryKey: librariesKeys.all }),
  });
  const problem = reimport.isError ? explainReimport(reimport.error, language) : undefined;
  if (reimport.isSuccess) {
    // Until the refetch replaces this error with the queued job: no second press, no 409.
    return (
      <p role="status" className="mt-3 font-medium">
        {t.queuedNew(version)}
      </p>
    );
  }
  return (
    <div className="mt-3 flex flex-col items-start gap-2">
      {!problem?.final && (
        <Button
          size="sm"
          pending={reimport.isPending}
          aria-disabled={reimport.isPending}
          onClick={() => {
            if (!reimport.isPending) reimport.mutate();
          }}
        >
          {!reimport.isPending && <RefreshCw aria-hidden="true" data-icon-motion="refresh" />}
          {reimport.isPending ? t.queueing : t.button}{" "}
          <span className="sr-only">{t.ofVersion(version)}</span>
        </Button>
      )}
      <FormAlert
        id={alertId}
        message={problem?.message}
        tone={problem?.tone === "info" ? "info" : "error"}
      />
    </div>
  );
}

/** Why the newest failed job of a library failed, and how to fix it. */
function FailureDetail({ job }: { job: LatestJob }) {
  const language = useLanguage();
  const t = listMessages[language].failure;
  const finished = job.finished_at ?? job.created_at;
  const [, owner = "", repo = ""] = job.library.split("/");
  const moved = job.error_code === "tag_moved";
  return (
    <div className="text-body">
      <p className="text-muted-foreground">
        {t.failedAt(
          <span className="font-mono text-mono">{job.version ?? t.sync}</span>,
          <time dateTime={finished} title={absoluteTimeWithZone(finished, language)}>
            {absoluteTime(finished, language)}
          </time>,
        )}
      </p>
      <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-secondary px-3 py-2 font-mono text-small whitespace-pre-wrap [overflow-wrap:anywhere]">
        {job.error ?? t.noReason}
      </pre>
      <SkippedFiles job={job} />
      {moved && job.version && <ReimportMovedTag library={job.library} version={job.version} />}
      <Link
        to="/libraries/$owner/$repo/settings"
        params={{ owner, repo }}
        hash="sync-heading"
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-3")}
      >
        <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
        {moved ? t.reviewMovedTag : t.openSettings}
      </Link>
    </div>
  );
}

/** A failed sync: the badge opens what went wrong; the error code stays visible under it. */
function Failed({ job, failures }: { job: LatestJob; failures: number }) {
  const language = useLanguage();
  const t = listMessages[language].sync;
  const now = useNow();
  const moved = job.error_code === "tag_moved";
  const Icon = moved ? TriangleAlert : CircleX;
  return (
    <span className="flex flex-col items-start gap-0.5">
      <Popover>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="-mx-2 h-auto min-h-11 max-w-full flex-wrap justify-start gap-x-1.5 gap-y-0.5 px-2 py-1 text-left whitespace-normal data-[state=open]:bg-accent fine:min-h-8"
          >
            <Badge tone={moved ? "warning" : "destructive"}>
              <Icon aria-hidden="true" className="size-3" />
              {moved ? t.tagMoved : failures > 1 ? t.versionsFailed(failures) : t.failed}
            </Badge>
            <span className="text-small font-normal whitespace-nowrap text-muted-foreground">
              {relativeTime(job.finished_at ?? job.created_at, now, language)}
            </span>
            <ChevronDown
              aria-hidden="true"
              className="text-muted-foreground transition-transform duration-(--dur-fast) ease-(--ease-out) in-data-[state=open]:rotate-180 motion-reduce:transition-none"
            />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-96 max-w-[calc(100vw-2rem)]"
          aria-label={t.detailsOf(job.library)}
        >
          <FailureDetail job={job} />
        </PopoverContent>
      </Popover>
      {job.error_code && !moved && (
        <span className="font-mono text-small text-muted-foreground">{job.error_code}</span>
      )}
    </span>
  );
}

function Running({ job }: { job: LatestJob }) {
  const t = useMessages(listMessages).sync;
  const known = job.total > 0;
  return (
    <span className="flex min-w-36 flex-col items-start gap-1.5">
      {job.state === "queued" ? (
        <StateBadge state="queued" label={t.queued} />
      ) : (
        <>
          <StateBadge
            state="running"
            label={known ? t.importingOf(job.done, job.total) : t.importing}
          />
          <Meter
            value={known ? Math.round((job.done / job.total) * 100) : null}
            label={t.progressFor(job.library)}
            className="max-w-40"
          />
        </>
      )}
      <CancelJob job={job} label={t.cancelLabel(job.version ?? job.library)} />
    </span>
  );
}

const muted = "text-muted-foreground";

/** A library's sync state in its row (the Sync column). */
export function SyncCell({ library }: { library: string }) {
  const t = useMessages(listMessages).sync;
  const states = useContext(SyncContext);
  const sync: SyncState = states?.syncOf(library) ?? { status: "pending" };
  if ("status" in sync) {
    return sync.status === "pending" ? (
      <>
        <Skeleton className="h-5 w-20 rounded-full" />
        <span className="sr-only">{t.checking}</span>
      </>
    ) : (
      <span className={muted}>
        <span aria-hidden="true">–</span>
        <span className="sr-only">{t.unavailable}</span>
      </span>
    );
  }
  switch (sync.kind) {
    case "none":
      return <span className={muted}>{t.none}</span>;
    case "running":
      return <Running job={sync.job} />;
    case "failed":
      return <Failed job={sync.job} failures={sync.failures} />;
    case "cancelled":
      return <StateBadge state="cancelled" label={t.cancelled(sync.job.cancelled_by ?? null)} />;
    case "ok":
      return (
        <StateBadge
          state="succeeded"
          label={sync.skipped > 0 ? t.syncedSkipped(sync.skipped) : t.synced}
        />
      );
  }
}
