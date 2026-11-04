import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, CircleAlert } from "lucide-react";
import { Fragment, type ReactNode, useEffect, useRef } from "react";
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

function Failure({
  job,
  variant,
  id,
}: {
  job: Job | undefined;
  variant: "library" | "version";
  id: string;
}) {
  const [, owner = "", repo = ""] = id.split("/");
  return (
    <div className="mt-5">
      <p>
        {variant === "library" ? (
          <>
            The library was created, but this version did not finish importing, so it has no
            articles yet. Fix the cause below, then sync it again from the library's{" "}
            <Link
              to="/libraries/$owner/$repo/settings"
              params={{ owner, repo }}
              className="rounded underline decoration-mark/40 underline-offset-4 outline-none hover:decoration-mark focus-visible:ring-2 focus-visible:ring-ring"
            >
              settings page
            </Link>
            .
          </>
        ) : (
          "This version did not finish importing, so it was not added. Fix the cause below, then add it again."
        )}
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
  /** A new library, or a version added to one: both answer with the same fields. */
  added: Pick<AddedLibrary, "library_id" | "ref" | "commit_sha" | "job_id">;
  /** Present when a whole new library was added: offers another one once this import is done. */
  onAddAnother?: (() => void) | undefined;
  /** Shown in place of the default buttons once the import is over. */
  finish?: ReactNode;
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
  finish,
}: {
  over: boolean;
  succeeded: boolean;
  onAddAnother: (() => void) | undefined;
  finish: ReactNode;
}) {
  return over && finish ? (
    <div className="fade-in mt-8 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      {finish}
    </div>
  ) : over ? (
    <div className="fade-in mt-8 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      {succeeded && onAddAnother && (
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

/** A new library names the library; a version added to one names the version (we are on the library already). */
function Heading({
  ref,
  version,
  verb,
  refName,
  libraryId,
}: {
  ref: React.Ref<HTMLHeadingElement>;
  version: boolean;
  verb: string;
  refName: string;
  libraryId: string;
}) {
  const Tag = version ? "h3" : "h2";
  return (
    <Tag
      id="progress-title"
      ref={ref}
      tabIndex={-1}
      className={cn(
        "font-semibold outline-none",
        version ? "text-lg" : "font-serif text-2xl tracking-tight",
      )}
    >
      {verb}{" "}
      <span className="font-mono text-[0.9em] font-normal [overflow-wrap:anywhere]">
        {version ? refName : <LibraryId id={libraryId} />}
      </span>
    </Tag>
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
  variant: "library" | "version";
}

/** What the job has to say right now: progress, the failure, or the files it skipped. */
function Outcome({ id, job, state, skipped, summary, gone, lostContact, variant }: OutcomeProps) {
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
      {state === "failed" && <Failure job={job} variant={variant} id={id} />}
      {finished && <SkippedList summary={summary} />}
    </>
  );
}

/** Watches the import job of a library that was just added, including the files it skipped. */
export function ImportProgress({ added, onAddAnother, finish }: Props) {
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
      <Heading
        ref={heading}
        version={!onAddAnother}
        verb={state === "failed" ? "Import failed" : finished ? "Imported" : "Importing"}
        refName={added.ref}
        libraryId={added.library_id}
      />
      <p className="mt-2 text-muted-foreground">
        {!onAddAnother && (
          <>
            <span className="font-mono text-[13px]">{added.library_id}</span>
            <span aria-hidden="true"> · </span>
          </>
        )}
        {onAddAnother && (
          <>
            <span className="font-mono text-[13px]">{added.ref}</span>
            <span aria-hidden="true"> · </span>
          </>
        )}
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
        variant={onAddAnother ? "library" : "version"}
      />

      <Actions
        over={finished || gone}
        succeeded={state === "succeeded"}
        onAddAnother={onAddAnother}
        finish={finish}
      />
    </section>
  );
}

/** One import job as a single quiet line with its bar, for a list of jobs (a re-sync queues one per branch). */
export function JobLine({
  jobId,
  label,
  onFinish,
}: {
  jobId: string;
  label: string;
  /** Called once when the job ends, so a row that listed it can say it is over. */
  onFinish?: ((state: "succeeded" | "failed") => void) | undefined;
}) {
  const { data: job, error } = useQuery(importJobQueryOptions(jobId));
  const state = job?.state ?? "queued";
  const finished = state === "succeeded" || state === "failed";
  const gone = error instanceof HttpError && error.status < 500 && !job;
  const known = (job?.total ?? 0) > 0;
  const skipped = skippedLabel(summarizeProblems(job?.problems ?? []));
  useRefreshListsWhen(finished);
  useEffect(() => {
    if (state === "succeeded" || state === "failed") onFinish?.(state);
  }, [state, onFinish]);
  if (gone) return <p className="text-sm text-muted-foreground">Progress for {label} is gone.</p>;
  return (
    <div className="text-sm">
      {/* Heard once per phase, never per file. */}
      <p role="status" className="sr-only">
        {finished && `${label}: ${phaseText(state, job?.done ?? 0, skipped, job?.error ?? null)}`}
      </p>
      <Status job={job} state={state} known={known} skipped={skipped} />
      {!finished && <Meter id={label} job={job} state={state} known={known} />}
      {state === "failed" && job?.error && (
        <p className="mt-1 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">
          {job.error}
        </p>
      )}
    </div>
  );
}
