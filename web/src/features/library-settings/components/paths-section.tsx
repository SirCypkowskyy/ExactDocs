import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type Ref, useRef, useState } from "react";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { Button } from "@/shared/ui/button";
import {
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import { FormAlert } from "@/shared/ui/form-alert";
import { PathFields, TagRules } from "@/shared/ui/path-selection";
import { refreshLibraries, saveSelection } from "../api/settings";
import {
  type Activity,
  draftOf,
  explainSettings,
  type JobViews,
  type Problem,
  reprocessWarning,
  type SavedSettings,
  type SelectionDraft,
  type SettingsLibrary,
  savedHeadline,
  saveHint,
  selectionChange,
  validateSelection,
} from "../model/settings";
import { sectionHeading } from "./styles";

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
  change: "paths" | "tags";
  refs: readonly string[];
  pending: boolean;
  onConfirm: () => void;
  onCloseAutoFocus: (event: Event) => void;
}

/** The warning saving waits for: every version is re-processed. It cannot close mid-request. */
function ReprocessConfirm({ open, onOpenChange, change, refs, pending, ...p }: ConfirmProps) {
  const words = reprocessWarning(change, refs);
  return (
    <ConfirmRoot
      open={open}
      onOpenChange={(next) => {
        if (!next && pending) return;
        onOpenChange(next);
      }}
    >
      <ConfirmContent
        className="sm:top-[22vh] sm:translate-y-0"
        onCloseAutoFocus={p.onCloseAutoFocus}
      >
        <ConfirmTitle>{words.title}</ConfirmTitle>
        <ConfirmDescription asChild>
          <div>
            <p className="text-foreground [overflow-wrap:anywhere]">{words.what}</p>
            <p className="mt-1.5">{words.safe}</p>
          </div>
        </ConfirmDescription>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <ConfirmCancel asChild>
            <Button variant="ghost" aria-disabled={pending}>
              Cancel
            </Button>
          </ConfirmCancel>
          <Button
            type="button"
            aria-disabled={pending}
            aria-busy={pending}
            onClick={() => {
              if (!pending) p.onConfirm();
            }}
            className="min-w-32"
          >
            {pending ? "Saving" : words.confirm}
          </Button>
        </div>
      </ConfirmContent>
    </ConfirmRoot>
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
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Button
        ref={ref}
        type="submit"
        aria-disabled={blocked}
        aria-busy={busy}
        aria-describedby="paths-save-hint"
        className="min-w-32 aria-disabled:cursor-default"
      >
        {busy ? "Saving" : "Save paths and tags"}
      </Button>
      <p id="paths-save-hint" className="text-sm text-muted-foreground">
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
  return (
    <div
      id="paths-status"
      tabIndex={-1}
      className={saved ? "mt-5 rounded outline-none" : "outline-none"}
    >
      <p role="status" className={saved ? "font-medium" : undefined}>
        {saved && <span className="fade-in">{savedHeadline(saved)}</span>}
      </p>
      {saved?.job_id && (
        <div className="fade-in mt-2 max-w-sm">
          <Line jobId={saved.job_id} label="every version" />
          <p className="mt-1 text-sm text-muted-foreground [overflow-wrap:anywhere]">
            {saved.versions.join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * Which files the library takes and the tags its articles get by path. Saving sends the whole
 * set and, once a version exists, re-processes every version: the warning says so first.
 */
export function PathsSection({ owner, repo, library, Line, Preview, activity, onStart }: Props) {
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
  const [warned, setWarned] = useState<"paths" | "tags">("paths");
  const save = useRef<HTMLButtonElement>(null);
  // Where focus goes once the warning closes: back to Save, or to what the server refused.
  const after = useRef<() => HTMLElement | null | undefined>(() => save.current);

  const change = selectionChange(base, draft);
  const refs = library.versions.map((v) => v.ref);
  const current = activity.by === "paths";

  const mutation = useMutation({
    mutationFn: () => saveSelection(owner, repo, draft),
    onSuccess: (data) => {
      setStored(data);
      setEdits(undefined);
      setShowRuleErrors(false);
      setProblem(undefined);
      after.current = () => document.getElementById("paths-status");
      setConfirming(false);
      refreshLibraries(queryClient);
    },
    onError: (error) => {
      const p = explainSettings(error);
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
    const found = validateSelection(draft);
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
    if (refs.length === 0) mutation.mutate();
    else {
      setWarned(change);
      setConfirming(true);
    }
  }

  const shown = current && mutation.isSuccess ? mutation.data : undefined;
  const shownProblem = current ? problem : undefined;

  return (
    <section aria-labelledby="paths-heading" className="mt-12 border-t border-border pt-10">
      <h2 id="paths-heading" className={sectionHeading}>
        Files and tags
      </h2>
      <p className="mt-1.5 max-w-prose text-muted-foreground">
        Which files of the repository become articles, and the tags they get by path. Saving a
        change re-processes every version.
      </p>
      <form onSubmit={submit} noValidate className="mt-5 flex flex-col gap-6">
        <FormAlert id="paths-alert" message={shownProblem?.message} link={shownProblem?.link} />
        <PathFields
          include={draft.include}
          exclude={draft.exclude}
          error={errors.paths}
          onInclude={(include) => edit({ include })}
          onExclude={(exclude) => edit({ exclude })}
        />
        <Preview
          url={library.source_url}
          version={library.default_version}
          include={draft.include}
          exclude={draft.exclude}
        />
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
          hint={saveHint(change, refs.length)}
        />
      </form>
      <SavedStatus saved={shown} Line={Line} />
      <ReprocessConfirm
        open={confirming}
        onOpenChange={setConfirming}
        change={warned}
        refs={refs}
        pending={mutation.isPending}
        onConfirm={() => {
          after.current = () => save.current;
          mutation.mutate();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          after.current()?.focus();
        }}
      />
    </section>
  );
}
