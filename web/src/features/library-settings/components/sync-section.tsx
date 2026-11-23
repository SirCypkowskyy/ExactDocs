import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, CircleAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { relativeTime } from "@/shared/lib/time";
import { Button } from "@/shared/ui/button";
import { FormAlert } from "@/shared/ui/form-alert";
import { refreshLibraries, reimportVersion, syncLibrary } from "../api/settings";
import { useNow } from "../hooks/use-now";
import { pageMessages } from "../messages/page";
import { sharedMessages } from "../messages/shared";
import { syncMessages } from "../messages/sync";
import {
  type Activity,
  explainReimport,
  explainSync,
  failureWords,
  type JobViews,
  type Problem,
  type ReimportedVersion,
  reimportedRow,
  type SyncedLibrary,
  type SyncedVersion,
  shortSha,
  statusWords,
  syncHeadline,
} from "../model/settings";
import { SettingsSection } from "./settings-section";
import { secondary } from "./styles";

interface Props {
  owner: string;
  repo: string;
  Line: JobViews["Line"];
  activity: Activity;
  onStart: () => void;
}

/** The confirmation a moved tag waits for: re-import it at the commit it names now. */
function Reimport({
  owner,
  repo,
  v,
  onReimported,
}: {
  owner: string;
  repo: string;
  v: SyncedVersion;
  onReimported: (r: ReimportedVersion) => void;
}) {
  const language = useLanguage();
  const t = syncMessages[language];
  const shared = sharedMessages[language];
  const queryClient = useQueryClient();
  const [problem, setProblem] = useState<Problem>();
  const reimport = useMutation({
    mutationFn: () => reimportVersion(owner, repo, v.ref),
    onSuccess: (data) => {
      setProblem(undefined);
      onReimported(data);
      refreshLibraries(queryClient);
    },
    onError: (error) => setProblem(explainReimport(error, language)),
  });
  return (
    <div className="mt-2">
      {/* After a refusal that a retry cannot change, there is nothing left to press. */}
      {!problem?.final && (
        <Button
          type="button"
          aria-disabled={reimport.isPending}
          aria-busy={reimport.isPending}
          onClick={() => {
            if (!reimport.isPending) reimport.mutate();
          }}
          className={`${secondary} min-w-32`}
        >
          {reimport.isPending ? shared.queueing : t.reimport}{" "}
          <span className="sr-only">{t.reimportOf(v.ref)}</span>
        </Button>
      )}
      <div className={problem ? "mt-3" : undefined}>
        <FormAlert
          id={`reimport-alert-${v.ref}`}
          message={problem?.message}
          link={problem?.link}
          tone={problem?.tone}
        />
      </div>
    </div>
  );
}

interface RowProps {
  owner: string;
  repo: string;
  v: SyncedVersion;
  Line: JobViews["Line"];
  onReimported: (r: ReimportedVersion) => void;
}

function Row({ owner, repo, v, Line, onReimported }: RowProps) {
  const language = useLanguage();
  const t = syncMessages[language];
  const live = (v.status === "queued" || v.status === "importing") && v.job_id;
  const failed = v.status === "failed";
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="font-mono text-body font-medium [overflow-wrap:anywhere]">{v.ref}</span>
        {/* A live row's own job line says how it is going and when it ends. */}
        {!live && (
          <span className="inline-flex items-center gap-1.5 text-body">
            {failed && (
              <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-destructive" />
            )}
            {v.status === "up_to_date" && (
              <Check aria-hidden="true" className="size-4 shrink-0 text-route" />
            )}
            <span className={failed ? "font-medium text-destructive" : undefined}>
              {statusWords(v.status, language)}
            </span>
          </span>
        )}
      </div>
      {v.status === "queued" && (
        <p className="mt-0.5 flex items-center gap-1.5 font-mono text-small text-muted-foreground">
          {shortSha(v.previous_commit_sha)}
          <ArrowRight aria-hidden="true" className="size-3" />
          {shortSha(v.commit_sha)}
          <span className="sr-only"> {t.commitChange}</span>
        </p>
      )}
      {failed && (
        <p className="mt-0.5 text-body text-muted-foreground">{failureWords(v, language)}</p>
      )}
      {failed && v.error_code === "tag_moved" && (
        <Reimport owner={owner} repo={repo} v={v} onReimported={onReimported} />
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
  const language = useLanguage();
  const t = syncMessages[language];
  const { sections } = useMessages(pageMessages);
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
      toast.success(t.finished, { description: syncHeadline(data, language) });
      refreshLibraries(queryClient);
    },
    onError: (error) => {
      setResult(undefined);
      const p = explainSync(error, language);
      setProblem(p);
      toast.error(t.failed, { description: p.message });
      // A 409 means something is importing: the sync badges on the list should show it.
      refreshLibraries(queryClient);
    },
  });

  const shown = current ? result : undefined;
  const shownProblem = current ? problem : undefined;
  const rows = shown?.data.versions.filter((v) => v.status !== "pinned") ?? [];
  const pinned = shown?.data.versions.filter((v) => v.status === "pinned") ?? [];

  return (
    <SettingsSection id="sync" title={sections.sync} description={t.description}>
      <div>
        <Button
          type="button"
          variant="outline"
          pending={sync.isPending}
          aria-disabled={sync.isPending}
          onClick={() => {
            if (sync.isPending) return;
            onStart();
            sync.mutate();
          }}
          className="min-w-32"
        >
          {sync.isPending ? t.checking : t.syncNow}
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
            {syncHeadline(shown.data, language)}{" "}
            <span className="font-normal text-muted-foreground">
              {t.checked(<time dateTime={shown.at}>{relativeTime(shown.at, now, language)}</time>)}
            </span>
          </span>
        )}
      </p>
      {rows.length > 0 && (
        <ul aria-label={t.versions} className="fade-in mt-2 divide-y divide-rule">
          {rows.map((v) => (
            <Row
              key={v.ref}
              owner={owner}
              repo={repo}
              v={v}
              Line={Line}
              onReimported={(r) =>
                setResult(
                  (was) =>
                    was && {
                      ...was,
                      data: {
                        ...was.data,
                        versions: was.data.versions.map((x) =>
                          x.ref === r.ref ? reimportedRow(x, r) : x,
                        ),
                      },
                    },
                )
              }
            />
          ))}
        </ul>
      )}
      {pinned.length > 0 && (
        <p className="fade-in mt-3 text-body text-muted-foreground [overflow-wrap:anywhere]">
          {t.pinned(pinned.map((v) => v.ref).join(", "), pinned.length)}
        </p>
      )}
    </SettingsSection>
  );
}
