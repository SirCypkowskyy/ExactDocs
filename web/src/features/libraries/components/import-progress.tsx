import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, CircleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { buttonVariants } from "@/shared/ui/button";
import { importJobQueryOptions } from "../api/add-library";
import { type AddedLibrary, summarizeProblems } from "../model/add-library";
import { type Job, shortSha } from "../model/library";
import { SkippedList } from "./skipped-list";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One sentence per phase, so a screen reader hears the import start and end, never every file. */
function phaseText(state: string | undefined, done: number, skipped: number, error: string | null) {
  switch (state) {
    case "queued":
      return "Import queued.";
    case "running":
      return "Importing.";
    case "succeeded":
      return `Import finished. ${plural(done, "file", "files")} imported, ${plural(skipped, "file", "files")} skipped.`;
    case "failed":
      return `Import failed. ${error ?? ""}`.trim();
    default:
      return "";
  }
}

interface Props {
  added: AddedLibrary;
  onAddAnother: () => void;
}

interface MeterProps {
  id: string;
  job: Job | undefined;
  state: string;
  finished: boolean;
  lostContact: boolean;
}

function Status({
  job,
  state,
  known,
  finished,
}: {
  job: Job | undefined;
  state: string;
  known: boolean;
  finished: boolean;
}) {
  return (
    <p className="tabular-nums" aria-hidden={finished}>
      {state === "queued" && "Waiting for a free worker"}
      {state === "running" &&
        (known ? `${job?.done} of ${job?.total} files` : "Reading the repository")}
      {state === "succeeded" && (
        <span className="inline-flex items-center gap-1.5">
          <Check aria-hidden="true" className="size-4 text-mark" />
          {plural(job?.done ?? 0, "file", "files")} imported
        </span>
      )}
      {state === "failed" && (
        <span className="inline-flex items-center gap-1.5 font-medium text-destructive">
          <CircleAlert aria-hidden="true" className="size-4" />
          Stopped after {job?.done ?? 0} files
        </span>
      )}
    </p>
  );
}

function Meter({ id, job, state, finished, lostContact }: MeterProps) {
  const known = (job?.total ?? 0) > 0;
  const pct = known && job ? Math.min(1, job.done / job.total) : finished ? 1 : 0;
  return (
    <div className="mt-6">
      <div className="flex items-baseline justify-between gap-4 text-sm">
        <Status job={job} state={state} known={known} finished={finished} />
        {lostContact && <p className="text-muted-foreground">Lost contact, retrying…</p>}
      </div>
      <div
        role="progressbar"
        aria-label={`Import progress for ${id}`}
        aria-valuemin={0}
        aria-valuemax={known ? job?.total : undefined}
        aria-valuenow={known ? job?.done : finished ? 1 : undefined}
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-secondary"
      >
        <div
          className={cn(
            "h-full origin-left rounded-full transition-transform duration-500 ease-out motion-reduce:transition-none",
            state === "failed" ? "bg-destructive" : "bg-mark",
            !known && !finished && "w-1/3 motion-safe:animate-pulse",
          )}
          style={known || finished ? { transform: `scaleX(${pct})`, width: "100%" } : undefined}
        />
      </div>
    </div>
  );
}

/** Watches the import job of a library that was just added, including the files it skipped. */
export function ImportProgress({ added, onAddAnother }: Props) {
  const { data: job, isError } = useQuery(importJobQueryOptions(added.job_id));
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus({ preventScroll: true }), []);

  const state = job?.state ?? "queued";
  const finished = state === "succeeded" || state === "failed";
  const summary = summarizeProblems(job?.problems ?? []);

  // The announcement changes with the phase only, not with the counter.
  const [announced, setAnnounced] = useState("");
  const phase = phaseText(state, job?.done ?? 0, summary.skipped, job?.error ?? null);
  useEffect(() => setAnnounced(phase), [phase]);

  return (
    <section aria-labelledby="progress-title" className="fade-in">
      <h2
        id="progress-title"
        ref={heading}
        tabIndex={-1}
        className="font-serif text-2xl font-semibold tracking-tight outline-none [overflow-wrap:anywhere]"
      >
        {state === "failed" ? "Import failed" : finished ? "Imported" : "Importing"}{" "}
        <span className="font-mono text-[0.8em] font-normal">{added.library_id}</span>
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

      <Meter
        id={added.library_id}
        job={job}
        state={state}
        finished={finished}
        lostContact={isError && !finished}
      />

      {state === "failed" && (
        <pre className="mt-5 overflow-x-auto whitespace-pre-wrap rounded-md bg-secondary px-3 py-3 font-mono text-xs [overflow-wrap:anywhere]">
          {job?.error ?? "No reason was recorded."}
        </pre>
      )}

      {finished && <SkippedList summary={summary} />}

      {finished && (
        <div className="fade-in mt-8 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onAddAnother}
            className={cn(buttonVariants({ variant: "ghost" }))}
          >
            Add another
          </button>
          <Link to="/" className={cn(buttonVariants())}>
            Back to libraries
          </Link>
        </div>
      )}
      {!finished && (
        <p className="mt-6 text-sm text-muted-foreground">
          You can leave this page. The import keeps running, and the library list shows how it went.
        </p>
      )}
    </section>
  );
}
