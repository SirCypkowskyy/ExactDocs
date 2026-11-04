import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, CircleAlert } from "lucide-react";
import { Fragment, useEffect, useRef } from "react";
import { HttpError } from "@/shared/lib/http";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { cn } from "@/shared/lib/utils";
import { buttonVariants } from "@/shared/ui/button";
import { importJobQueryOptions } from "../api/add-library";
import { librariesKeys } from "../api/libraries-query";
import {
  type AddedLibrary,
  type ProblemSummary,
  skippedLabel,
  summarizeProblems,
} from "../model/add-library";
import { type Job, shortSha } from "../model/library";
import { SkippedList } from "./skipped-list";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One sentence per phase, so a screen reader hears the import start and end, never every file. */
function phaseText(state: string | undefined, done: number, skipped: string, error: string | null) {
  switch (state) {
    case "queued":
      return "Import queued.";
    case "running":
      return "Importing.";
    case "succeeded":
      return `Import finished. ${plural(done, "file", "files")} imported, ${skipped} skipped.`;
    case "failed":
      return `Import failed. ${error ?? ""}`.trim();
    default:
      return "";
  }
}

/** `/acme/payments`, breaking after each slash on a narrow screen instead of mid-word. */
function LibraryId({ id }: { id: string }) {
  return id
    .split("/")
    .slice(1)
    .map((part) => (
      <Fragment key={part}>
        /<wbr />
        {part}
      </Fragment>
    ));
}

interface StatusProps {
  job: Job | undefined;
  state: string;
  known: boolean;
  skipped: string;
}

function Status({ job, state, known, skipped }: StatusProps) {
  const done = job?.done ?? 0;
  if (state === "queued") return <p>Waiting for a free worker</p>;
  if (state === "running") {
    return (
      <p className="tabular-nums">
        {known ? `${done} of ${job?.total} files` : "Reading the repository"}
      </p>
    );
  }
  if (state === "succeeded") {
    return (
      <p className="inline-flex items-center gap-1.5 text-base font-medium">
        <Check aria-hidden="true" className="size-4 text-mark" />
        {plural(done, "file", "files")} imported
        {skipped !== "0" && `, ${skipped} skipped`}
      </p>
    );
  }
  return (
    <p className="inline-flex items-center gap-1.5 text-base font-medium text-destructive">
      <CircleAlert aria-hidden="true" className="size-4" />
      Stopped after {done}
      {known ? ` of ${job?.total}` : ""} files
    </p>
  );
}

interface MeterProps {
  id: string;
  job: Job | undefined;
  state: string;
  known: boolean;
}

/** The bar is for waiting; once the import is over the status line says everything. */
function Meter({ id, job, state, known }: MeterProps) {
  const pct = known && job ? Math.min(1, job.done / job.total) : 0;
  return (
    <div
      role="progressbar"
      aria-label={`Import progress for ${id}`}
      aria-valuemin={0}
      aria-valuemax={known ? job?.total : undefined}
      aria-valuenow={known ? job?.done : undefined}
      className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-secondary"
    >
      <div
        className={cn(
          "h-full rounded-full bg-mark",
          known
            ? "origin-left transition-transform duration-500 ease-out motion-reduce:transition-none"
            : state === "queued" || state === "running"
              ? "sweep w-1/3"
              : "",
        )}
        style={known ? { transform: `scaleX(${pct})`, width: "100%" } : undefined}
      />
    </div>
  );
}

function Failure({ job }: { job: Job | undefined }) {
  return (
    <div className="mt-5">
      <p>
        The library was created, but this version did not finish importing, so it has no articles
        yet. Fix the cause below, then sync it again from the libraries page.
      </p>
      <p className="mt-4 text-sm font-medium">Details from the server</p>
      <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap rounded-md bg-secondary px-3 py-3 font-mono text-[13px] [overflow-wrap:anywhere]">
        {job?.error ?? "No reason was recorded."}
      </pre>
    </div>
  );
}

const backLink = (primary: boolean) => cn(buttonVariants(primary ? {} : { variant: "ghost" }));

interface Props {
  added: AddedLibrary;
  onAddAnother: () => void;
}

/** The list and its sync badges must not show the old state once the import is over. */
function useRefreshListsWhen(finished: boolean) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!finished) return;
    void queryClient.invalidateQueries({ queryKey: librariesKeys.list() });
    void queryClient.invalidateQueries({ queryKey: librariesKeys.latestJobs() });
    void queryClient.invalidateQueries({ queryKey: BROWSE_KEY });
  }, [finished, queryClient]);
}

function Actions({
  over,
  succeeded,
  onAddAnother,
}: {
  over: boolean;
  succeeded: boolean;
  onAddAnother: () => void;
}) {
  return over ? (
    <div className="fade-in mt-8 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      {succeeded && (
        <button type="button" onClick={onAddAnother} className={backLink(false)}>
          Add another
        </button>
      )}
      <Link to="/" className={backLink(true)}>
        Back to libraries
      </Link>
    </div>
  ) : (
    <div className="mt-6">
      <p className="text-sm text-muted-foreground">
        You can leave this page. The import keeps running, and the library list shows how it went.
      </p>
      <Link to="/" className={cn(backLink(false), "-ml-3 mt-2")}>
        Back to libraries
      </Link>
    </div>
  );
}

interface OutcomeProps {
  id: string;
  job: Job | undefined;
  state: string;
  skipped: string;
  summary: ProblemSummary;
  gone: boolean;
  lostContact: boolean;
}

/** What the job has to say right now: progress, the failure, or the files it skipped. */
function Outcome({ id, job, state, skipped, summary, gone, lostContact }: OutcomeProps) {
  const finished = state === "succeeded" || state === "failed";
  const known = (job?.total ?? 0) > 0;
  return (
    <>
      {gone ? (
        <p role="alert" className="mt-6 text-destructive">
          We can't find this import any more, so its progress can't be shown. The library list shows
          where things stand.
        </p>
      ) : (
        <div className="mt-6">
          <div className="flex items-baseline justify-between gap-4 text-sm">
            <Status job={job} state={state} known={known} skipped={skipped} />
            {lostContact && <p className="text-muted-foreground">Lost contact, retrying…</p>}
          </div>
          {!finished && <Meter id={id} job={job} state={state} known={known} />}
        </div>
      )}
      {state === "failed" && <Failure job={job} />}
      {finished && <SkippedList summary={summary} />}
    </>
  );
}

/** Watches the import job of a library that was just added, including the files it skipped. */
export function ImportProgress({ added, onAddAnother }: Props) {
  const { data: job, error } = useQuery(importJobQueryOptions(added.job_id));
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus({ preventScroll: true }), []);

  const state = job?.state ?? "queued";
  const finished = state === "succeeded" || state === "failed";
  const summary = summarizeProblems(job?.problems ?? []);
  const skipped = skippedLabel(summary);
  // A 4xx will not fix itself (the job is gone, or we are signed out): stop and say so.
  const gone = error instanceof HttpError && error.status < 500 && !job;
  const lostContact = Boolean(error) && !finished && !gone;

  useRefreshListsWhen(finished);

  // The text changes with the phase only, never with the counter.
  const announced = phaseText(state, job?.done ?? 0, skipped, job?.error ?? null);

  return (
    <section aria-labelledby="progress-title" className="fade-in">
      <h2
        id="progress-title"
        ref={heading}
        tabIndex={-1}
        className="font-serif text-2xl font-semibold tracking-tight outline-none"
      >
        {state === "failed" ? "Import failed" : finished ? "Imported" : "Importing"}{" "}
        <span className="font-mono text-[0.8em] font-normal">
          <LibraryId id={added.library_id} />
        </span>
      </h2>
      <p className="mt-2 text-muted-foreground">
        <span className="font-mono text-[13px]">{added.ref}</span>
        <span aria-hidden="true"> · </span>
        <span className="font-mono text-[13px]">{shortSha(added.commit_sha)}</span>
        <span className="sr-only"> commit</span>
      </p>
      <p role="status" className="sr-only">
        {announced}
      </p>

      <Outcome
        id={added.library_id}
        job={job}
        state={state}
        skipped={skipped}
        summary={summary}
        gone={gone}
        lostContact={lostContact}
      />

      <Actions
        over={finished || gone}
        succeeded={state === "succeeded"}
        onAddAnother={onAddAnother}
      />
    </section>
  );
}
