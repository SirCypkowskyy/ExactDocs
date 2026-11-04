import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, CircleAlert } from "lucide-react";
import { useState } from "react";
import { relativeTime } from "@/shared/lib/time";
import { Button } from "@/shared/ui/button";
import { FormAlert } from "@/shared/ui/form-alert";
import { refreshLibraries, syncLibrary } from "../api/settings";
import { useNow } from "../hooks/use-now";
import {
  type Activity,
  explainSync,
  type JobViews,
  type Problem,
  type SyncedLibrary,
  type SyncedVersion,
  shortSha,
  statusWords,
  syncHeadline,
} from "../model/settings";
import { secondary, sectionHeading } from "./styles";

interface Props {
  owner: string;
  repo: string;
  Line: JobViews["Line"];
  activity: Activity;
  onStart: () => void;
}

function Row({ v, Line }: { v: SyncedVersion; Line: JobViews["Line"] }) {
  const live = (v.status === "queued" || v.status === "importing") && v.job_id;
  const failed = v.status === "failed";
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="font-mono text-[15px] font-medium [overflow-wrap:anywhere]">{v.ref}</span>
        {/* A live row's own job line says how it is going and when it ends. */}
        {!live && (
          <span className="inline-flex items-center gap-1.5 text-sm">
            {failed && (
              <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-destructive" />
            )}
            {v.status === "up_to_date" && (
              <Check aria-hidden="true" className="size-4 shrink-0 text-mark" />
            )}
            <span className={failed ? "font-medium text-destructive" : undefined}>
              {statusWords(v.status)}
            </span>
          </span>
        )}
      </div>
      {v.status === "queued" && (
        <p className="mt-0.5 flex items-center gap-1.5 font-mono text-[13px] text-muted-foreground">
          {shortSha(v.previous_commit_sha)}
          <ArrowRight aria-hidden="true" className="size-3" />
          {shortSha(v.commit_sha)}
          <span className="sr-only"> (previous commit to new commit)</span>
        </p>
      )}
      {failed && (
        <p className="mt-0.5 text-sm text-muted-foreground">
          The branch is gone from the repository, or its import could not be queued. The version
          keeps serving what it had.
        </p>
      )}
      {live && (
        <div className="mt-2 max-w-sm">
          <Line jobId={v.job_id ?? ""} label={v.ref} />
        </div>
      )}
    </li>
  );
}

/** Asks the remote where each branch is now and shows what each version did, with live progress. */
export function SyncSection({ owner, repo, Line, activity, onStart }: Props) {
  const queryClient = useQueryClient();
  const now = useNow();
  const [result, setResult] = useState<{ data: SyncedLibrary; at: string }>();
  const [problem, setProblem] = useState<Problem>();

  // Something else was started since: last check's news and last failure are old.
  const current = activity.by === "sync";

  const sync = useMutation({
    mutationFn: () => syncLibrary(owner, repo),
    onSuccess: (data) => {
      setProblem(undefined);
      setResult({ data, at: new Date().toISOString() });
      refreshLibraries(queryClient);
    },
    onError: (error) => {
      setResult(undefined);
      setProblem(explainSync(error));
      // A 409 means something is importing: the sync badges on the list should show it.
      refreshLibraries(queryClient);
    },
  });

  const shown = current ? result : undefined;
  const shownProblem = current ? problem : undefined;
  const rows = shown?.data.versions.filter((v) => v.status !== "pinned") ?? [];
  const pinned = shown?.data.versions.filter((v) => v.status === "pinned") ?? [];

  return (
    <section aria-labelledby="sync-heading" className="mt-12 border-t border-border pt-10">
      <h2 id="sync-heading" className={sectionHeading}>
        Re-sync
      </h2>
      <p className="mt-1.5 max-w-prose text-muted-foreground">
        Check the repository for new commits on each branch version and import only what changed.
        Tags and commits are pinned, so they are left alone.
      </p>
      <div className="mt-5">
        <Button
          type="button"
          aria-disabled={sync.isPending}
          aria-busy={sync.isPending}
          onClick={() => {
            if (sync.isPending) return;
            onStart();
            sync.mutate();
          }}
          className={`${secondary} min-w-32`}
        >
          {sync.isPending ? "Checking" : "Re-sync now"}
        </Button>
      </div>
      <div className={shownProblem ? "mt-4" : undefined}>
        <FormAlert
          id="sync-alert"
          message={shownProblem?.message}
          link={shownProblem?.link}
          tone={shownProblem?.tone}
        />
      </div>
      {/* Only the headline is announced; the live job lines below would chatter on every poll. */}
      <p role="status" className={shown ? "mt-4 font-medium" : undefined}>
        {shown && (
          <span className="fade-in">
            {syncHeadline(shown.data)}{" "}
            <span className="font-normal text-muted-foreground">
              Checked <time dateTime={shown.at}>{relativeTime(shown.at, now)}</time>.
            </span>
          </span>
        )}
      </p>
      {rows.length > 0 && (
        <ul aria-label="Versions" className="fade-in mt-2 divide-y divide-border">
          {rows.map((v) => (
            <Row key={v.ref} v={v} Line={Line} />
          ))}
        </ul>
      )}
      {pinned.length > 0 && (
        <p className="fade-in mt-3 text-sm text-muted-foreground [overflow-wrap:anywhere]">
          {pinned.map((v) => v.ref).join(", ")} {pinned.length === 1 ? "is" : "are"} pinned and{" "}
          {pinned.length === 1 ? "never changes" : "never change"}.
        </p>
      )}
    </section>
  );
}
