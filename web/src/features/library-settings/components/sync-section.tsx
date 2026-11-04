import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, CircleAlert } from "lucide-react";
import { useState } from "react";
import { Button } from "@/shared/ui/button";
import { FormAlert } from "@/shared/ui/form-alert";
import { refreshLibraries, syncLibrary } from "../api/settings";
import {
  explainSync,
  type JobViews,
  type Problem,
  type SyncedLibrary,
  type SyncedVersion,
  shortSha,
  statusWords,
  syncHeadline,
} from "../model/settings";
import { secondary } from "./styles";

interface Props {
  owner: string;
  repo: string;
  Line: JobViews["Line"];
}

function Row({ v, Line }: { v: SyncedVersion; Line: JobViews["Line"] }) {
  const live = (v.status === "queued" || v.status === "importing") && v.job_id;
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="font-mono text-[15px] font-medium [overflow-wrap:anywhere]">{v.ref}</span>
        <span className="inline-flex items-center gap-1.5 text-sm">
          {v.status === "failed" ? (
            <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-destructive" />
          ) : v.status === "up_to_date" ? (
            <Check aria-hidden="true" className="size-4 shrink-0 text-mark" />
          ) : null}
          <span className={v.status === "failed" ? "font-medium text-destructive" : undefined}>
            {statusWords(v.status)}
          </span>
        </span>
      </div>
      {v.status === "queued" && (
        <p className="mt-0.5 flex items-center gap-1.5 font-mono text-[13px] text-muted-foreground">
          {shortSha(v.previous_commit_sha)}
          <ArrowRight aria-hidden="true" className="size-3" />
          {shortSha(v.commit_sha)}
          <span className="sr-only"> (previous commit to new commit)</span>
        </p>
      )}
      {v.status === "failed" && (
        <p className="mt-0.5 text-sm text-muted-foreground">
          The branch is gone from the repository, or its import could not be queued. The version
          keeps serving what it had.
        </p>
      )}
      {v.status === "pinned" && (
        <p className="mt-0.5 text-sm text-muted-foreground">
          Tags and commits point at one commit for good, so there is nothing to update.
        </p>
      )}
      {live && (
        <div className="mt-2 max-w-sm">
          <Line jobId={v.job_id as string} label={v.ref} />
        </div>
      )}
    </li>
  );
}

/** Asks the remote where each branch is now and shows what each version did, with live progress. */
export function SyncSection({ owner, repo, Line }: Props) {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<SyncedLibrary>();
  const [problem, setProblem] = useState<Problem>();

  const sync = useMutation({
    mutationFn: () => syncLibrary(owner, repo),
    onSuccess: (data) => {
      setProblem(undefined);
      setResult(data);
      refreshLibraries(queryClient);
    },
    onError: (error) => {
      setResult(undefined);
      setProblem(explainSync(error));
      // A 409 means something is importing: the sync badges on the list should show it.
      refreshLibraries(queryClient);
    },
  });

  return (
    <section aria-labelledby="sync-heading" className="mt-12 border-t border-border pt-10">
      <h2
        id="sync-heading"
        className="font-serif text-2xl font-semibold tracking-tight [scroll-margin-top:1rem]"
      >
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
          onClick={() => !sync.isPending && sync.mutate()}
          className={`${secondary} min-w-32`}
        >
          {sync.isPending ? "Checking" : "Re-sync now"}
        </Button>
      </div>
      <div className="mt-4 max-w-xl">
        <FormAlert id="sync-alert" message={problem?.message} link={problem?.link} />
        {problem?.detail && (
          <p className="-mt-2 mb-5 text-sm text-muted-foreground [overflow-wrap:anywhere]">
            {problem.detail}
          </p>
        )}
      </div>
      <div className="max-w-xl">
        {/* Only the headline is announced; the live job lines below would chatter on every poll. */}
        <p role="status" className="min-h-6 font-medium">
          {result && <span className="fade-in">{syncHeadline(result)}</span>}
        </p>
        {result && result.versions.length > 0 && (
          <ul aria-label="Versions" className="fade-in mt-2 divide-y divide-border">
            {result.versions.map((v) => (
              <Row key={v.ref} v={v} Line={Line} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
