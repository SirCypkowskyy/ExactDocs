import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, Check } from "lucide-react";
import { type FormEvent, useCallback, useRef, useState } from "react";
import { filledRules, lines, type TagRuleDraft } from "@/shared/lib/path-selection";
import { type RefChoice, refToSend } from "@/shared/lib/refs";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { RefPicker } from "@/shared/ui/ref-picker";
import { addLibrary, checkRepository } from "../api/add-library";
import { librariesKeys } from "../api/libraries-query";
import { useOlderVersions, usePreview } from "../hooks/use-preview";
import {
  type AddedLibrary,
  type AddField,
  type AddProblem,
  type CheckedRepository,
  explainAddError,
  explainCheckError,
  validateForm,
  validateUrl,
} from "../model/add-library";
import { ExtraVersions, PreviewPanel } from "./file-preview";
import { AdvancedOptions } from "./file-selection";
import { ImportProgress } from "./import-progress";

const ALERT_ID = "add-alert";
const HOSTS: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  bitbucket: "Bitbucket",
  gitea: "Gitea",
  git: "a git server",
};
const FOCUS: Record<AddField, string> = {
  url: "url",
  id: "library-id",
  ref: "ref",
  paths: "include",
  tags: "add-rule",
};

function RepoFound({ checked }: { checked: Checked | undefined }) {
  return (
    <p role="status" className="min-h-5 text-sm text-muted-foreground">
      {checked && (
        <span className="fade-in inline-flex items-start gap-1.5">
          <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
          <span>
            Found on {HOSTS[checked.host] ?? "a git server"}.{" "}
            {checked.default_branch
              ? `Default branch is ${checked.default_branch}.`
              : "It has no default branch, so choose one below."}
          </span>
        </span>
      )}
    </p>
  );
}

/** `aria-disabled` while busy keeps focus on the button; the submit handler ignores repeats. */
function SubmitButton({ pending, checked }: { pending: boolean; checked: boolean }) {
  const label = checked
    ? pending
      ? "Adding"
      : "Add library"
    : pending
      ? "Checking"
      : "Check repository";
  return (
    <Button type="submit" aria-disabled={pending} aria-busy={pending}>
      {pending && (
        <span
          aria-hidden="true"
          className="spin size-4 rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground"
        />
      )}
      {label}
    </Button>
  );
}

/** Focus goes to the first mistake, in the order the form reads. */
function firstMistake(form: { id?: string | undefined; paths?: string | undefined }) {
  const target =
    (form.id && "library-id") ||
    (form.paths && "include") ||
    document.querySelector<HTMLElement>("[data-rules] [aria-invalid=true]")?.id ||
    "add-rule";
  return document.getElementById(target);
}

interface Checked extends CheckedRepository {
  url: string;
}

export function AddLibraryPage() {
  const queryClient = useQueryClient();
  const heading = usePageTitle("Add a library");
  const focusAfterRender = useFocusAfterRender();
  const [url, setUrl] = useState("");
  const [checked, setChecked] = useState<Checked>();
  const [libraryId, setLibraryId] = useState("");
  const [choice, setChoice] = useState<RefChoice>({ kind: "default" });
  const [typedRef, setTypedRef] = useState("");
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");
  const [rules, setRules] = useState<TagRuleDraft[]>([]);
  const [advanced, setAdvanced] = useState(false);
  const [errors, setErrors] = useState<{ [K in AddField]?: string | undefined }>({});
  const [showRuleErrors, setShowRuleErrors] = useState(false);
  const [problem, setProblem] = useState<AddProblem>();
  const [pending, setPending] = useState(false);
  const [added, setAdded] = useState<AddedLibrary>();
  const current = useRef(url);
  // Every action takes a number; only the latest may touch state or release the lock, so a stale
  // check (the address changed) never blocks the next one and two fast submits send one request.
  const run = useRef(0);
  const busy = useRef(false);

  function fail(p: AddProblem) {
    if (p.field) {
      const field = p.field;
      setErrors({ [field]: p.message });
      setProblem(undefined);
      if (field === "paths" || field === "tags") setAdvanced(true);
      // In the commit that shows the field (or opens its details), never a frame later.
      focusAfterRender(
        () =>
          (field === "ref" && document.getElementById("ref-typed")) ||
          document.getElementById(FOCUS[field]),
      );
    } else {
      setErrors({});
      setProblem(p);
    }
  }

  // A preview never blocks an add; it shares the form's place for refusals.
  const preview = usePreview({
    onFail: fail,
    onStart: () => {
      setErrors({});
      setProblem(undefined);
    },
    onPrefill: (inc, exc) => {
      setInclude(inc);
      setExclude(exc);
      setAdvanced(true);
    },
  });
  const older = useOlderVersions();

  const unavailable = useCallback(() => setChoice({ kind: "other" }), []);
  const clear = (field: AddField) => setErrors((e) => ({ ...e, [field]: undefined }));

  function edit(value: string) {
    setUrl(value);
    current.current = value;
    // Whatever was in flight is about the old address now.
    run.current++;
    busy.current = false;
    setPending(false);
    setErrors((e) => ({ ...e, url: undefined }));
    // A different address is a different repository: start the form over from the check.
    if (checked && value.trim() !== checked.url) {
      setChecked(undefined);
      setChoice({ kind: "default" });
      setTypedRef("");
      setProblem(undefined);
      setErrors({});
      setShowRuleErrors(false);
      preview.forget();
    }
  }

  async function check() {
    const invalid = validateUrl(url);
    if (invalid) return fail({ field: "url", message: invalid });
    const target = url.trim();
    const mine = ++run.current;
    busy.current = true;
    setErrors({});
    setProblem(undefined);
    setPending(true);
    try {
      const result = await checkRepository(target);
      if (run.current !== mine) return;
      setChecked({ ...result, url: target });
      setLibraryId(result.library_id);
    } catch (error) {
      if (run.current === mine) fail(explainCheckError(error));
    } finally {
      if (run.current === mine) {
        busy.current = false;
        setPending(false);
      }
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    if (!checked) return check();

    const form = validateForm({ libraryId, include, exclude, rules });
    if (!form.ok) {
      setProblem(undefined);
      setShowRuleErrors(true);
      setErrors({ id: form.id, paths: form.paths });
      if (form.paths || form.badRule) setAdvanced(true);
      focusAfterRender(() => firstMistake(form));
      return;
    }

    const mine = ++run.current;
    busy.current = true;
    setErrors({});
    setProblem(undefined);
    setPending(true);
    const ref = refToSend(choice, typedRef);
    try {
      const result = await addLibrary({
        url: checked.url,
        library_id: libraryId.trim(),
        ...(ref && { ref }),
        include_paths: lines(include),
        exclude_paths: lines(exclude),
        tag_rules: filledRules(rules).map((r) => ({
          pattern: r.pattern.trim(),
          tag: r.tag.trim(),
        })),
      });
      // Only the list and the newest-job feed; the progress screen owns the job's own query.
      void queryClient.invalidateQueries({ queryKey: librariesKeys.list() });
      void queryClient.invalidateQueries({ queryKey: librariesKeys.latestJobs() });
      if (run.current === mine) {
        setAdded(result);
        const tags = preview.chosen([ref, result.ref]);
        if (tags.length) void older.queue(result.library_id, tags);
      }
    } catch (error) {
      if (run.current === mine) fail(explainAddError(error, ref));
    } finally {
      if (run.current === mine) {
        busy.current = false;
        setPending(false);
      }
    }
  }

  function reset() {
    setUrl("");
    current.current = "";
    setChecked(undefined);
    setChoice({ kind: "default" });
    setTypedRef("");
    setInclude("");
    setExclude("");
    setRules([]);
    setAdvanced(false);
    setErrors({});
    setShowRuleErrors(false);
    setAdded(undefined);
    older.clear();
    preview.forget();
    focusAfterRender(() => document.getElementById("url"));
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <Link
        to="/"
        className="-ml-2 inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-sm text-muted-foreground outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Libraries
      </Link>
      <h1
        ref={added ? undefined : heading}
        tabIndex={-1}
        className="mt-2 font-serif text-3xl font-semibold tracking-tight outline-none"
      >
        {added ? "Import" : "Add a library"}
      </h1>

      <div className="mt-8 max-w-xl">
        {added ? (
          <ImportProgress added={added} onAddAnother={reset}>
            <ExtraVersions
              extras={older.extras}
              libraryId={added.library_id}
              onRetry={(tag) => void older.retry(tag)}
            />
          </ImportProgress>
        ) : (
          <form onSubmit={submit} noValidate className="flex flex-col gap-6">
            <FormAlert id={ALERT_ID} message={problem?.message} link={problem?.link} />
            <div className="flex flex-col gap-3">
              <Field
                id="url"
                label="Repository address"
                type="url"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                placeholder="https://github.com/acme/payments"
                value={url}
                error={errors.url}
                alertId={problem?.message ? ALERT_ID : undefined}
                hint={errors.url ? undefined : "A public git repository with Markdown docs."}
                onChange={(e) => edit(e.target.value)}
              />
              <RepoFound checked={checked} />
            </div>

            {checked && (
              <div className="fade-in flex flex-col gap-6">
                <Field
                  id="library-id"
                  label="Library ID"
                  autoComplete="off"
                  spellCheck={false}
                  value={libraryId}
                  error={errors.id}
                  hint="How agents refer to this library, as /owner/repo."
                  className="font-mono text-[15px]"
                  onChange={(e) => {
                    setLibraryId(e.target.value);
                    clear("id");
                  }}
                />
                <RefPicker
                  url={checked.url}
                  choice={choice}
                  typed={typedRef}
                  error={errors.ref}
                  onChoice={(c) => {
                    setChoice(c);
                    clear("ref");
                    // A new field appears for a typed ref: the user's next move is to type.
                    if (c.kind === "other") {
                      focusAfterRender(() => document.getElementById("ref-typed"));
                    }
                  }}
                  onUnavailable={unavailable}
                  onTyped={(v) => {
                    setTypedRef(v);
                    clear("ref");
                  }}
                />
                <AdvancedOptions
                  open={advanced}
                  onOpen={setAdvanced}
                  include={include}
                  exclude={exclude}
                  rules={rules}
                  pathError={errors.paths}
                  tagError={errors.tags}
                  showRuleErrors={showRuleErrors}
                  onInclude={(v) => {
                    setInclude(v);
                    clear("paths");
                  }}
                  onExclude={(v) => {
                    setExclude(v);
                    clear("paths");
                  }}
                  onRules={(r) => {
                    setRules(r);
                    clear("tags");
                  }}
                />
                <PreviewPanel
                  preview={preview}
                  form={{ url: checked.url, ref: refToSend(choice, typedRef), include, exclude }}
                />
              </div>
            )}

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Link
                to="/"
                className="inline-flex h-11 items-center justify-center rounded-md px-3 text-sm font-medium outline-none transition-colors duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
              >
                Cancel
              </Link>
              <SubmitButton pending={pending} checked={Boolean(checked)} />
            </div>
          </form>
        )}
      </div>
    </main>
  );
}
