import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, RotateCcw, Save } from "lucide-react";
import { type FormEvent, type Ref, useRef, useState } from "react";
import { toast } from "sonner";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { Button } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { FormAlert } from "@/shared/ui/form-alert";
import { PathFields, TagRules } from "@/shared/ui/path-selection";
import {
  accessQueryOptions,
  refreshLibraries,
  reprocessJobsQueryOptions,
  saveSelection,
} from "../api/settings";
import { pageMessages } from "../messages/page";
import { pathsMessages } from "../messages/paths";
import { sharedMessages } from "../messages/shared";
import {
  type Activity,
  draftOf,
  effectiveChange,
  explainSettings,
  type JobViews,
  type Problem,
  type ReprocessJob,
  reprocessWarning,
  type SavedSettings,
  type SelectionDraft,
  type SettingsChange,
  type SettingsLibrary,
  savedHeadline,
  saveHint,
  selectionChange,
  unhealedJob,
  validateSelection,
} from "../model/settings";
import { useReportDirty } from "./dirty";
import { SettingsSection } from "./settings-section";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  Line: JobViews["Line"];
  Preview: JobViews["Preview"];
  activity: Activity;
  onStart: () => void;
}

interface ConfirmProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  change: SettingsChange;
  /** The newest re-processing failed: this one runs in full. */
  afterFailure: boolean;
  refs: readonly string[];
  pending: boolean;
  onConfirm: () => void;
  onCloseAutoFocus: (event: Event) => void;
}

/** The warning saving waits for: every version is re-processed. It cannot close mid-request. */
function ReprocessConfirm({ change, afterFailure, refs, ...p }: ConfirmProps) {
  const language = useLanguage();
  const words = reprocessWarning(change, refs, afterFailure, language);
  const shared = sharedMessages[language];
  return (
    <ConfirmDialog
      {...p}
      tone="default"
      icon={<RefreshCw aria-hidden="true" data-icon-motion="refresh" />}
      title={words.title}
      description={<span className="text-foreground [overflow-wrap:anywhere]">{words.what}</span>}
      confirmLabel={words.confirm}
      pendingLabel={shared.saving}
    >
      <p className="mt-1.5">{words.safe}</p>
    </ConfirmDialog>
  );
}

interface SaveRowProps {
  ref: Ref<HTMLButtonElement>;
  /** Saving now would do nothing: a request is out, or nothing changed. */
  blocked: boolean;
  busy: boolean;
  hint: string;
}

function SaveRow({ ref, blocked, busy, hint }: SaveRowProps) {
  const t = useMessages(pathsMessages);
  const shared = useMessages(sharedMessages);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Button
        ref={ref}
        type="submit"
        pending={busy}
        aria-disabled={blocked}
        aria-describedby="paths-save-hint"
        className="min-w-32 aria-disabled:cursor-default"
      >
        {!busy && <Save aria-hidden="true" data-icon-motion="pop" />}
        {busy ? shared.saving : t.save}
      </Button>
      <p id="paths-save-hint" className="text-body text-muted-foreground">
        {hint}
      </p>
    </div>
  );
}

/** What saving did, and the job re-processing every version as it runs. Focus lands here after. */
function SavedStatus({
  saved,
  Line,
}: {
  saved: SavedSettings | undefined;
  Line: JobViews["Line"];
}) {
  const language = useLanguage();
  const t = pathsMessages[language];
  return (
    <div
      id="paths-status"
      tabIndex={-1}
      className={saved ? "mt-5 rounded outline-none" : "outline-none"}
    >
      <p role="status" className={saved ? "font-medium" : undefined}>
        {saved && <span className="fade-in">{savedHeadline(saved, language)}</span>}
      </p>
      {saved?.job_id && (
        <div className="fade-in mt-2 max-w-sm">
          <Line jobId={saved.job_id} label={t.everyVersion} />
          <p className="mt-1 text-body text-muted-foreground [overflow-wrap:anywhere]">
            {saved.versions.join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}

interface RunAgainProps {
  job: ReprocessJob;
  Line: JobViews["Line"];
  lineShown: boolean;
  pending: boolean;
  onRun: () => void;
}

/** The newest re-processing failed: its line, and a way to run it again with what is stored. */
function RunAgain({ job, Line, lineShown, pending, onRun }: RunAgainProps) {
  const t = useMessages(pathsMessages);
  const shared = useMessages(sharedMessages);
  const kind = job.kind === "retag" || job.kind === "rechunk" ? job.kind : "reprocess";
  return (
    <div className="fade-in mt-5 max-w-sm">
      {!lineShown && (
        <>
          <p className="font-medium">{t.lastFailed[kind]}</p>
          <div className="mt-2">
            <Line jobId={job.id} label={t.everyVersion} />
          </div>
        </>
      )}
      <Button
        type="button"
        aria-disabled={pending}
        aria-busy={pending}
        onClick={() => {
          if (!pending) onRun();
        }}
        variant="outline"
        className="mt-3 min-w-32"
      >
        <RotateCcw aria-hidden="true" data-icon-motion="refresh" />
        {pending ? shared.queueing : t.runAgain}
        <span className="sr-only">{t.runAgainWhat[kind]}</span>
      </Button>
    </div>
  );
}

/**
 * Which files the library takes and the tags its articles get by path. Saving sends the whole
 * set and, once a version exists, re-processes every version: the warning says so first.
 */
export function PathsSection({ owner, repo, library, Line, Preview, activity, onStart }: Props) {
  const language = useLanguage();
  const t = pathsMessages[language];
  const queryClient = useQueryClient();
  const focusAfterRender = useFocusAfterRender();
  // What the server stored last; until this page saves, what the library was loaded with.
  const [stored, setStored] = useState<SavedSettings>();
  const base = stored ?? library.settings;
  // Only what the person typed is state; untouched, the form shows what is stored.
  const [edits, setEdits] = useState<SelectionDraft>();
  const draft = edits ?? draftOf(base);
  const [showRuleErrors, setShowRuleErrors] = useState(false);
  const [errors, setErrors] = useState<{ paths?: string; tags?: string }>({});
  const [problem, setProblem] = useState<Problem>();
  const [confirming, setConfirming] = useState(false);
  // What the open warning is about; kept while it closes, after the form has been reset.
  const [warned, setWarned] = useState(() => effectiveChange("paths", null));
  const save = useRef<HTMLButtonElement>(null);
  // Where focus goes once the warning closes: back to Save, or to what the server refused.
  const after = useRef<() => HTMLElement | null | undefined>(() => save.current);

  const { data: recent } = useQuery(reprocessJobsQueryOptions(owner, repo));
  const { data: access } = useQuery(accessQueryOptions(owner, repo));
  const failed = unhealedJob(recent);

  const change = selectionChange(base, draft);
  useReportDirty("paths", change !== null);
  const refs = library.versions.map((v) => v.ref);
  const current = activity.by === "paths";

  const mutation = useMutation({
    mutationFn: (settings: SelectionDraft) => saveSelection(owner, repo, settings),
    onSuccess: (data) => {
      setStored(data);
      toast.success(t.savedToast, {
        description: savedHeadline(data, language),
      });
      setEdits(undefined);
      setShowRuleErrors(false);
      setProblem(undefined);
      after.current = () => document.getElementById("paths-status");
      // Without the warning (Run again, or no version yet) nothing closes to move focus: do it here.
      if (!confirming) focusAfterRender(after.current);
      setConfirming(false);
      refreshLibraries(queryClient);
    },
    onError: (error) => {
      const p = explainSettings(error, language);
      if (p.field === "paths" || p.field === "tags") {
        setErrors({ [p.field]: p.message });
        const id = p.field === "paths" ? "include" : "add-rule";
        after.current = () => document.getElementById(id);
      } else {
        setProblem(p);
        after.current = () => save.current;
      }
      if (!confirming) focusAfterRender(after.current);
      setConfirming(false);
    },
  });

  const edit = (patch: Partial<SelectionDraft>) => {
    setEdits({ ...draft, ...patch });
    setErrors((e) => ({
      ...(patch.rules ? {} : { tags: e.tags }),
      ...(patch.include !== undefined || patch.exclude !== undefined ? {} : { paths: e.paths }),
    }));
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    if (mutation.isPending || change === null) return;
    const found = validateSelection(draft, language);
    setProblem(undefined);
    setErrors(found.paths ? { paths: found.paths } : {});
    setShowRuleErrors(true);
    if (found.paths) {
      focusAfterRender(() => document.getElementById("include"));
      return;
    }
    if (found.badRule) {
      const key = found.badRule.key;
      focusAfterRender(() => document.getElementById(`rule-path-${key}`));
      return;
    }
    onStart();
    mutation.reset();
    // With no version yet nothing is re-processed: there is nothing to warn about.
    if (refs.length === 0) mutation.mutate(draft);
    else {
      setWarned(effectiveChange(change, recent));
      setConfirming(true);
    }
  }

  const shown = current && mutation.isSuccess ? mutation.data : undefined;
  const shownProblem = current ? problem : undefined;

  return (
    <SettingsSection
      id="paths"
      title={pageMessages[language].sections.paths}
      description={t.description}
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-6">
        <FormAlert id="paths-alert" message={shownProblem?.message} link={shownProblem?.link} />
        <PathFields
          include={draft.include}
          exclude={draft.exclude}
          error={errors.paths}
          onInclude={(include) => edit({ include })}
          onExclude={(exclude) => edit({ exclude })}
        />
        {access?.private ? (
          <p className="text-body text-muted-foreground">{t.privatePreview}</p>
        ) : (
          <Preview
            url={library.source_url}
            version={library.default_version}
            include={draft.include}
            exclude={draft.exclude}
          />
        )}
        <TagRules
          rules={draft.rules}
          showErrors={showRuleErrors}
          error={errors.tags}
          onChange={(rules) => edit({ rules })}
        />
        <SaveRow
          ref={save}
          blocked={mutation.isPending || change === null}
          busy={mutation.isPending && !confirming}
          hint={saveHint(change, refs.length, language)}
        />
      </form>
      <SavedStatus saved={shown} Line={Line} />
      {failed && (
        <RunAgain
          job={failed}
          Line={Line}
          // The line of a job this page started is on screen already.
          lineShown={shown?.job_id === failed.id}
          pending={mutation.isPending}
          onRun={() => {
            onStart();
            setProblem(undefined);
            mutation.reset();
            mutation.mutate(draftOf(base));
          }}
        />
      )}
      <ReprocessConfirm
        open={confirming}
        onOpenChange={setConfirming}
        change={warned.change}
        afterFailure={warned.afterFailure}
        refs={refs}
        pending={mutation.isPending}
        onConfirm={() => {
          after.current = () => save.current;
          mutation.mutate(draft);
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          after.current()?.focus();
        }}
      />
    </SettingsSection>
  );
}
