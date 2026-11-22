import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, CircleAlert } from "lucide-react";
import { Fragment, type ReactNode, useEffect, useRef } from "react";
import { toast } from "sonner";
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
import { CancelJob } from "./cancel-job";
import { SkippedList } from "./skipped-list";

/** Whether a job has ended: succeeded, failed or cancelled. */
const isOver = (state: string) =>
  state === "succeeded" || state === "failed" || state === "cancelled";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What a job counts and what it is called: an import counts files; re-processing a library counts versions. */
interface JobWords {
  unit: "file" | "version";
  /** “Import”, “Re-processing”: the start of each phase sentence. */
  noun: string;
  /** “imported”: what a counted item is once done. */
  done: string;
}

const IMPORT_WORDS: JobWords = { unit: "file", noun: "Import", done: "imported" };

/** A `reprocess`, `rechunk` or `retag` job (a library's settings were edited) counts versions. */
function wordsOf(kind: string | undefined): JobWords {
  if (kind === "reprocess") return { unit: "version", noun: "Re-processing", done: "re-processed" };
  if (kind === "rechunk") return { unit: "version", noun: "Re-chunking", done: "re-chunked" };
  if (kind === "retag") return { unit: "version", noun: "Re-tagging", done: "re-tagged" };
  return IMPORT_WORDS;
}

const units = (w: JobWords, n: number) => (n === 1 ? w.unit : `${w.unit}s`);

/** One sentence per phase, so a screen reader hears the import start and end, never every file. */
function phaseText(
  state: string | undefined,
  done: number,
  skipped: string,
  error: string | null,
  w: JobWords = IMPORT_WORDS,
) {
  switch (state) {
    case "queued":
      return `${w.noun} queued.`;
    case "running":
      return w === IMPORT_WORDS ? "Importing." : `${w.noun}.`;
    case "succeeded":
      return w.unit === "file"
        ? `${w.noun} finished. ${plural(done, "file", "files")} ${w.done}, ${skipped} skipped.`
        : `${w.noun} finished. ${done} ${units(w, done)} ${w.done}.`;
    case "failed":
      return `${w.noun} failed. ${error ?? ""}`.trim();
    case "cancelled":
      return `${w.noun} cancelled.`;
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
  words?: JobWords;
}

function Status({ job, state, known, skipped, words: w = IMPORT_WORDS }: StatusProps) {
  const done = job?.done ?? 0;
  const total = job?.total ?? 0;
  if (state === "queued") return <p>Waiting for a free worker</p>;
  if (state === "running") {
    return (
      <p className="tabular-nums">
        {known
          ? `${done} of ${total} ${units(w, total)}`
          : w.unit === "file"
            ? "Reading the repository"
            : "Starting"}
      </p>
    );
  }
  if (state === "succeeded") {
    return (
      <p className="inline-flex items-center gap-1.5 text-body font-medium">
        <Check aria-hidden="true" className="size-4 text-route" />
        {done} {units(w, done)} {w.done}
        {w.unit === "file" && skipped !== "0" && `, ${skipped} skipped`}
      </p>
    );
  }
  return <Ended job={job} done={done} total={total} known={known} w={w} />;
}

/** A job that stopped before its end: someone cancelled it, or it failed. */
function Ended(props: {
  job: Job | undefined;
  done: number;
  total: number;
  known: boolean;
  w: JobWords;
}) {
  const { job, done, total, known, w } = props;
  if (job?.state !== "cancelled") return <Failed done={done} total={total} known={known} w={w} />;
  const by = job.cancelled_by ? ` by ${job.cancelled_by}` : "";
  return (
    <p className="text-section font-medium">
      {`Cancelled${by} after ${done}${known ? ` of ${total}` : ""} ${units(w, known ? total : done)}`}
    </p>
  );
}

/** How a failed job ended. A version-counted job goes on past a failed version: at its end, it did not stop. */
function Failed({
  done,
  total,
  known,
  w,
}: {
  done: number;
  total: number;
  known: boolean;
  w: JobWords;
}) {
  const triedAll = w.unit === "version" && known && done >= total;
  return (
    <p className="inline-flex items-center gap-1.5 text-body font-medium text-destructive">
      <CircleAlert aria-hidden="true" className="size-4" />
      {triedAll
        ? `Failed: all ${total} ${units(w, total)} tried, not every one could be ${w.done}`
        : `Stopped after ${done}${known ? ` of ${total}` : ""} ${units(w, known ? total : done)}`}
    </p>
  );
}

interface MeterProps {
  id: string;
  /** “Import”, “Re-processing”: names the bar. */
  noun?: string;
  job: Job | undefined;
  state: string;
  known: boolean;
}

/** The bar is for waiting; once the import is over the status line says everything. */
function Meter({ id, job, state, known, noun = "Import" }: MeterProps) {
  const pct = known && job ? Math.min(1, job.done / job.total) : 0;
  return (
    <div
      role="progressbar"
      aria-label={`${noun} progress for ${id}`}
      aria-valuemin={0}
      aria-valuemax={known ? job?.total : undefined}
      aria-valuenow={known ? job?.done : undefined}
      aria-valuetext={known && job ? `${job.done} of ${job.total}` : undefined}
      className="mt-2 h-2 w-full overflow-hidden rounded-full bg-secondary"
    >
      <div
        className={cn(
          "h-full rounded-full bg-route",
          known
            ? "origin-left transition-transform duration-(--dur-slow) ease-(--ease-out) motion-reduce:transition-none"
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
              className="rounded underline decoration-route/40 underline-offset-4 outline-none hover:decoration-route focus-visible:ring-2 focus-visible:ring-ring"
            >
              settings page
            </Link>
            .
          </>
        ) : (
          "This version did not finish importing, so it was not added. Fix the cause below, then add it again."
        )}
      </p>
      <p className="mt-4 text-body font-medium">Details from the server</p>
      <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap rounded-md bg-secondary px-3 py-3 font-mono text-mono [overflow-wrap:anywhere]">
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
  /** More to watch under this import (older versions queued with it), above the buttons. */
  children?: ReactNode;
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

/** The result of an import is said once as a toast too: the person may have left the page. */
function useToastWhenOver(
  state: string,
  job: Job | undefined,
  skipped: string,
  libraryId: string,
  ref: string,
  library: boolean,
) {
  const told = useRef(false);
  useEffect(() => {
    if (told.current || (state !== "succeeded" && state !== "failed")) return;
    told.current = true;
    const what = library ? libraryId : ref;
    if (state === "succeeded") {
      const done = job?.done ?? 0;
      toast.success(`Imported ${what}`, {
        description: `${plural(done, "file", "files")} imported${skipped !== "0" ? `, ${skipped} skipped` : ""}.`,
      });
    } else {
      toast.error(`Import of ${what} failed`, { description: job?.error ?? undefined });
    }
  }, [state, job, skipped, libraryId, ref, library]);
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
  // Inside another page the exit is that page's own (Close), from the first second.
  return finish ? (
    <div
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        over ? "fade-in mt-8" : "mt-6",
      )}
    >
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
      <p className="text-body text-muted-foreground">
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
        version ? "text-section" : "text-title tracking-[-0.01em]",
      )}
    >
      {verb}{" "}
      <span className="font-mono font-normal [overflow-wrap:anywhere]">
        {version ? refName : <LibraryId id={libraryId} />}
      </span>
    </Tag>
  );
}

/** Under the heading: the ref and commit; for a version, the library it belongs to instead of its ref. */
function Subline({ added, library }: { added: Props["added"]; library: boolean }) {
  return (
    <p className="mt-2 text-muted-foreground">
      <span className="font-mono text-mono">{library ? added.ref : added.library_id}</span>
      <span aria-hidden="true"> · </span>
      <span className="font-mono text-mono">{shortSha(added.commit_sha)}</span>
      <span className="sr-only"> commit</span>
    </p>
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
  const finished = isOver(state);
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
          <div className="flex items-baseline justify-between gap-4 text-body">
            <Status job={job} state={state} known={known} skipped={skipped} />
            {lostContact && <p className="text-muted-foreground">Lost contact, retrying…</p>}
            {state === "running" && known && job && (
              <p className="text-muted-foreground tabular-nums">
                {Math.round((job.done / job.total) * 100)}%
              </p>
            )}
          </div>
          {!finished && <Meter id={id} job={job} state={state} known={known} />}
          {job && <CancelJob job={job} label={`the import of ${id}`} />}
        </div>
      )}
      {state === "failed" && <Failure job={job} variant={variant} id={id} />}
      {finished && <SkippedList summary={summary} />}
    </>
  );
}

/** Watches the import job of a library that was just added, including the files it skipped. */
export function ImportProgress({ added, onAddAnother, finish, children }: Props) {
  const { data: job, error } = useQuery(importJobQueryOptions(added.job_id));
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus({ preventScroll: true }), []);

  const state = job?.state ?? "queued";
  const finished = isOver(state);
  const summary = summarizeProblems(job?.problems ?? []);
  const skipped = skippedLabel(summary);
  // A 4xx will not fix itself (the job is gone, or we are signed out): stop and say so.
  const gone = error instanceof HttpError && error.status < 500 && !job;
  const lostContact = Boolean(error) && !finished && !gone;

  useRefreshListsWhen(finished);
  useToastWhenOver(state, job, skipped, added.library_id, added.ref, Boolean(onAddAnother));

  // The text changes with the phase only, never with the counter.
  const announced = phaseText(state, job?.done ?? 0, skipped, job?.error ?? null);

  return (
    <section aria-labelledby="progress-title" className="fade-in">
      <Heading
        ref={heading}
        version={!onAddAnother}
        verb={
          state === "failed"
            ? "Import failed"
            : state === "cancelled"
              ? "Import cancelled"
              : finished
                ? "Imported"
                : "Importing"
        }
        refName={added.ref}
        libraryId={added.library_id}
      />
      <Subline added={added} library={Boolean(onAddAnother)} />
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
      {children}

      <Actions
        over={finished || gone}
        succeeded={state === "succeeded"}
        onAddAnother={onAddAnother}
        finish={finish}
      />
    </section>
  );
}

/** One job (an import, or a library re-processed) as a single quiet line with its bar, for a list of jobs (a re-sync queues one per branch). */
export function JobLine({ jobId, label }: { jobId: string; label: string }) {
  const { data: job, error } = useQuery(importJobQueryOptions(jobId));
  const state = job?.state ?? "queued";
  const finished = isOver(state);
  const gone = error instanceof HttpError && error.status < 500 && !job;
  const known = (job?.total ?? 0) > 0;
  const skipped = skippedLabel(summarizeProblems(job?.problems ?? []));
  const words = wordsOf(job?.kind);
  useRefreshListsWhen(finished);
  if (gone) return <p className="text-body text-muted-foreground">Progress for {label} is gone.</p>;
  return (
    <div className="text-body">
      {/* Heard once per phase, never per file. */}
      <p role="status" className="sr-only">
        {finished &&
          `${label}: ${phaseText(state, job?.done ?? 0, skipped, job?.error ?? null, words)}`}
      </p>
      <Status job={job} state={state} known={known} skipped={skipped} words={words} />
      {!finished && <Meter id={label} job={job} state={state} known={known} noun={words.noun} />}
      {job && <CancelJob job={job} label={label} />}
      {state === "failed" && job?.error && (
        <p className="mt-1 text-small text-muted-foreground [overflow-wrap:anywhere]">
          {job.error}
        </p>
      )}
    </div>
  );
}
