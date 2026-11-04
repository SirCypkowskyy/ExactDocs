import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, Check, ChevronRight } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { addLibrary, checkRepository } from "../api/add-library";
import { librariesKeys } from "../api/libraries-query";
import {
  type AddedLibrary,
  type AddField,
  type AddProblem,
  type CheckedRepository,
  explainAddError,
  explainCheckError,
  filledRules,
  lines,
  type RefChoice,
  refToSend,
  type TagRuleDraft,
  validateLibraryId,
  validatePatterns,
  validateRule,
  validateUrl,
} from "../model/add-library";
import { PathFields, TagRules } from "./file-selection";
import { ImportProgress } from "./import-progress";
import { RefPicker } from "./ref-picker";

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

interface Checked extends CheckedRepository {
  url: string;
}

export function AddLibraryPage() {
  const queryClient = useQueryClient();
  const heading = usePageTitle("Add a library");
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

  function fail(p: AddProblem) {
    if (p.field) {
      const field = p.field;
      setErrors({ [field]: p.message });
      setProblem(undefined);
      if (field === "paths" || field === "tags") setAdvanced(true);
      // After the field (or its details) is on screen.
      requestAnimationFrame(() => {
        const id = field === "ref" && choice.kind === "other" ? "ref-typed" : FOCUS[field];
        document.getElementById(id)?.focus();
      });
    } else {
      setErrors({});
      setProblem(p);
    }
  }

  function edit(value: string) {
    setUrl(value);
    current.current = value;
    setErrors((e) => ({ ...e, url: undefined }));
    // A different address is a different repository: start the form over from the check.
    if (checked && value.trim() !== checked.url) {
      setChecked(undefined);
      setChoice({ kind: "default" });
      setTypedRef("");
      setProblem(undefined);
    }
  }

  async function check() {
    const invalid = validateUrl(url);
    if (invalid) return fail({ field: "url", message: invalid });
    const target = url.trim();
    setErrors({});
    setProblem(undefined);
    setPending(true);
    try {
      const result = await checkRepository(target);
      if (current.current.trim() !== target) return;
      setChecked({ ...result, url: target });
      setLibraryId(result.library_id);
    } catch (error) {
      if (current.current.trim() === target) fail(explainCheckError(error));
    } finally {
      setPending(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    if (!checked) return check();

    const idError = validateLibraryId(libraryId);
    const pathError = validatePatterns(include) ?? validatePatterns(exclude);
    const ruleErrors = filledRules(rules).some((r) => {
      const p = validateRule(r);
      return p.pattern || p.tag;
    });
    if (idError || pathError || ruleErrors) {
      setProblem(undefined);
      setShowRuleErrors(true);
      setErrors({ id: idError, paths: pathError });
      if (pathError || ruleErrors) setAdvanced(true);
      const first = idError ? "library-id" : pathError ? "include" : undefined;
      requestAnimationFrame(() => {
        const target =
          first ??
          document.querySelector<HTMLElement>("[data-rules] [aria-invalid=true]")?.id ??
          "add-rule";
        document.getElementById(target)?.focus();
      });
      return;
    }

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
      void queryClient.invalidateQueries({ queryKey: librariesKeys.all });
      setAdded(result);
    } catch (error) {
      fail(explainAddError(error, ref));
    } finally {
      setPending(false);
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
    requestAnimationFrame(() => document.getElementById("url")?.focus());
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
        Add a library
      </h1>

      <div className="mt-8 max-w-xl">
        {added ? (
          <ImportProgress added={added} onAddAnother={reset} />
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
                    setErrors((x) => ({ ...x, id: undefined }));
                  }}
                />
                <RefPicker
                  url={checked.url}
                  choice={choice}
                  typed={typedRef}
                  error={errors.ref}
                  onChoice={(c) => {
                    setChoice(c);
                    setErrors((x) => ({ ...x, ref: undefined }));
                  }}
                  onTyped={(v) => {
                    setTypedRef(v);
                    setErrors((x) => ({ ...x, ref: undefined }));
                  }}
                />
                <details
                  open={advanced}
                  onToggle={(e) => setAdvanced(e.currentTarget.open)}
                  className="group"
                >
                  <summary className="-ml-2 flex min-h-11 w-fit cursor-pointer list-none items-center gap-2 rounded-md px-2 text-sm font-medium outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                    <ChevronRight
                      aria-hidden="true"
                      className="size-4 text-muted-foreground transition-transform duration-150 ease-out group-open:rotate-90 motion-reduce:transition-none"
                    />
                    Choose files and tags
                    <span className="font-normal text-muted-foreground">(optional)</span>
                  </summary>
                  <div className="mt-4 flex flex-col gap-6" data-rules>
                    <PathFields
                      include={include}
                      exclude={exclude}
                      error={errors.paths}
                      onInclude={(v) => {
                        setInclude(v);
                        setErrors((x) => ({ ...x, paths: undefined }));
                      }}
                      onExclude={(v) => {
                        setExclude(v);
                        setErrors((x) => ({ ...x, paths: undefined }));
                      }}
                    />
                    <TagRules
                      rules={rules}
                      showErrors={showRuleErrors}
                      error={errors.tags}
                      onChange={(r) => {
                        setRules(r);
                        setErrors((x) => ({ ...x, tags: undefined }));
                      }}
                    />
                  </div>
                </details>
              </div>
            )}

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Link
                to="/"
                className="inline-flex h-11 items-center justify-center rounded-md px-3 text-sm font-medium outline-none transition-colors duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
              >
                Cancel
              </Link>
              <Button type="submit" aria-disabled={pending} aria-busy={pending}>
                {pending && (
                  <span
                    aria-hidden="true"
                    className="spin size-4 rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground"
                  />
                )}
                {checked
                  ? pending
                    ? "Adding"
                    : "Add library"
                  : pending
                    ? "Checking"
                    : "Check repository"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </main>
  );
}
