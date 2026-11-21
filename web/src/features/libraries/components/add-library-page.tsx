import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, Check } from "lucide-react";
import { type FormEvent, type ReactNode, type Ref, useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import { type Credential, type CredentialDraft, credentialKindFor } from "@/shared/lib/credentials";
import { filledRules, lines, type TagRuleDraft } from "@/shared/lib/path-selection";
import { type RefChoice, refToSend } from "@/shared/lib/refs";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button, buttonVariants } from "@/shared/ui/button";
import { CredentialField } from "@/shared/ui/credential-field";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { Page, PageHeader } from "@/shared/ui/page";
import { RefPicker } from "@/shared/ui/ref-picker";
import { addLibrary, checkRepository, importJobQueryOptions } from "../api/add-library";
import { librariesKeys } from "../api/libraries-query";
import { useOlderVersions, usePreview } from "../hooks/use-preview";
import { usePrivateAccess } from "../hooks/use-private-access";
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
import { type AddPhase, AddSteps } from "./add-steps";
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
  credential: "credential",
  id: "library-id",
  ref: "ref",
  paths: "include",
  tags: "add-rule",
};

function RepoFound({ checked }: { checked: Checked | undefined }) {
  return (
    <>
      <p role="status" className="min-h-5 text-body text-muted-foreground">
        {checked && (
          <span className="fade-in inline-flex items-start gap-1.5">
            <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-route" />
            <span>
              Found on {HOSTS[checked.host] ?? "a git server"}.{" "}
              {checked.default_branch
                ? `Default branch is ${checked.default_branch}.`
                : "It has no default branch, so choose one below."}
            </span>
          </span>
        )}
      </p>
      {checked?.host_key_fingerprint && <HostKey fingerprint={checked.host_key_fingerprint} />}
    </>
  );
}

/** An SSH server's key, to compare with the one the host publishes before anything is added. */
function HostKey({ fingerprint }: { fingerprint: string }) {
  return (
    <div className="fade-in rounded-md border border-border bg-secondary/60 px-3 py-2.5 text-body">
      <p className="font-medium">SSH host key of the server</p>
      <code className="mt-1 block font-mono text-small break-all text-foreground select-all">
        {fingerprint}
      </code>
      <p className="mt-1 text-muted-foreground">
        Compare it with the fingerprint your git host publishes before you add the library. If they
        differ, don't add it: someone may be in the middle.
      </p>
    </div>
  );
}

/** Opt in to a token or deploy key; the kind follows the address (https or ssh). */
function PrivateAccess({
  open,
  url,
  draft,
  error,
  onOpen,
  onChange,
}: {
  open: boolean;
  url: string;
  draft: CredentialDraft;
  error: string | undefined;
  onOpen: (open: boolean) => void;
  onChange: (draft: CredentialDraft) => void;
}) {
  const kind = credentialKindFor(url);
  return (
    <div className="flex flex-col gap-3">
      <label className="inline-flex min-h-11 cursor-pointer items-center gap-2.5 self-start text-body font-medium md:min-h-8">
        <input
          id="private"
          type="checkbox"
          checked={open}
          onChange={(e) => onOpen(e.target.checked)}
          className="size-4 cursor-pointer accent-primary"
        />
        This repository is private
      </label>
      {open &&
        (kind ? (
          <div className="fade-in">
            <CredentialField
              id="credential"
              kind={kind}
              draft={draft}
              error={error}
              onChange={onChange}
            />
          </div>
        ) : (
          <p
            id="credential"
            tabIndex={-1}
            className={
              error
                ? "fade-in text-body font-medium text-destructive outline-none"
                : "fade-in text-body text-muted-foreground outline-none"
            }
          >
            {error ??
              "A private repository needs an https:// address (with an access token) or an ssh:// or git@host:path address (with a deploy key)."}
          </p>
        ))}
    </div>
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
    <Button type="submit" pending={pending} aria-disabled={pending} className="min-w-36">
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
  /** The token or key the check passed with; every later request of this form sends it. */
  credential?: Credential | undefined;
}

/** The address, and how to get into it when it is private; then what the check found. */
function AddressStep({
  url,
  error,
  taken,
  alertId,
  access,
  accessError,
  checked,
  onEdit,
  onAccessChanged,
}: {
  url: string;
  error: string | undefined;
  /** The library that holds the ID this address proposes (`/owner/repo`): the error links to it. */
  taken: string | undefined;
  alertId: string | undefined;
  access: ReturnType<typeof usePrivateAccess>;
  accessError: string | undefined;
  checked: Checked | undefined;
  onEdit: (url: string) => void;
  /** `restart`: what was checked no longer holds, so the form goes back to the check. */
  onAccessChanged: (restart: boolean) => void;
}) {
  return (
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
        error={error}
        errorAction={taken ? <LibraryLink id={taken} /> : undefined}
        alertId={alertId}
        hint={error ? undefined : "A git repository with Markdown docs."}
        onChange={(e) => onEdit(e.target.value)}
      />
      <PrivateAccess
        open={access.open}
        url={url}
        draft={access.draft}
        error={accessError}
        onOpen={(open) => {
          access.setOpen(open);
          onAccessChanged(Boolean(checked && (open || checked.credential)));
        }}
        onChange={(draft) => {
          access.setDraft(draft);
          onAccessChanged(Boolean(checked));
        }}
      />
      <RepoFound checked={checked} />
    </div>
  );
}

/** `/owner/repo` as a link to that library's page, named so it reads well out of context too. */
function LibraryLink({ id }: { id: string }) {
  const [owner = "", repo = ""] = id.slice(1).split("/");
  return (
    <Link
      to="/libraries/$owner/$repo"
      params={{ owner, repo }}
      className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      Open {id}
    </Link>
  );
}

function FormActions({ pending, checked }: { pending: boolean; checked: boolean }) {
  return (
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      <Link to="/" className={buttonVariants({ variant: "ghost" })}>
        Cancel
      </Link>
      <SubmitButton pending={pending} checked={checked} />
    </div>
  );
}

/** The way back to the list, above the title. */
const backToList = (
  <Link
    to="/"
    className="-ml-2 inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-body text-muted-foreground outline-none transition-colors duration-(--dur-fast) hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
  >
    <ArrowLeft aria-hidden="true" className="size-4" />
    Libraries
  </Link>
);

function LibraryIdField({
  value,
  error,
  onChange,
}: {
  value: string;
  error: string | undefined;
  onChange: (value: string) => void;
}) {
  return (
    <Field
      id="library-id"
      label="Library ID"
      autoComplete="off"
      spellCheck={false}
      value={value}
      error={error}
      hint="How agents refer to this library, as /owner/repo."
      className="font-mono"
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** The same query the progress screen polls: one request, shared. */
function useAddPhase(added: AddedLibrary | undefined, checked: boolean): AddPhase {
  const jobState = useQuery({
    ...importJobQueryOptions(added?.job_id ?? ""),
    enabled: Boolean(added),
  }).data?.state;
  if (!added) return checked ? "choose" : "check";
  if (jobState === "succeeded") return "done";
  return jobState === "failed" ? "failed" : "import";
}

function AddFrame({
  phase,
  added,
  heading,
  children,
}: {
  phase: AddPhase;
  added: boolean;
  heading: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <Page>
      <PageHeader
        above={backToList}
        {...(!added && { headingRef: heading })}
        title={added ? "Import" : "Add a library"}
        description={
          added
            ? "Reading the repository and indexing its documents."
            : "Point ExactDocs at a git repository with Markdown docs. It imports one version at a time, exactly as it was."
        }
      />
      <div className="lg:grid lg:grid-cols-[13rem_minmax(0,42rem)] lg:gap-12">
        <AddSteps phase={phase} />
        <div>{children}</div>
      </div>
    </Page>
  );
}

export function AddLibraryPage() {
  const queryClient = useQueryClient();
  const heading = usePageTitle("Add a library");
  const focusAfterRender = useFocusAfterRender();
  const [url, setUrl] = useState("");
  // The secret lives there and in `checked` only: never a query, storage or the URL.
  const access = usePrivateAccess();
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
  /** The library holding the ID the checked address proposes; shown only with the address's error. */
  const [taken, setTaken] = useState<string>();
  const [pending, setPending] = useState(false);
  const [added, setAdded] = useState<AddedLibrary>();
  const current = useRef(url);
  // Every action takes a number; only the latest may touch state or release the lock, so a stale
  // check (the address changed) never blocks the next one and two fast submits send one request.
  const run = useRef(0);
  const busy = useRef(false);

  function fail(p: AddProblem) {
    setTaken(p.field === "url" ? p.library : undefined);
    if (p.field) {
      const field = p.field;
      setErrors({ [field]: p.message });
      setProblem(undefined);
      if (field === "paths" || field === "tags") setAdvanced(true);
      if (field === "credential") access.setOpen(true);
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

  /** Whatever was in flight is about the old address or credential now. */
  function cancelRun() {
    run.current++;
    busy.current = false;
    setPending(false);
  }

  /** A different repository, or another way in: start the form over from the check. */
  function startOver() {
    setChecked(undefined);
    setChoice({ kind: "default" });
    setTypedRef("");
    setProblem(undefined);
    setErrors({});
    setShowRuleErrors(false);
    preview.forget();
  }

  function edit(value: string) {
    setUrl(value);
    current.current = value;
    cancelRun();
    setErrors((e) => ({ ...e, url: undefined, credential: undefined }));
    if (checked && value.trim() !== checked.url) startOver();
  }

  /** Another token, key or none: what was checked no longer says how to get in. */
  function accessChanged(restart: boolean) {
    cancelRun();
    clear("credential");
    if (restart) startOver();
  }

  async function check() {
    const invalid = validateUrl(url);
    if (invalid) return fail({ field: "url", message: invalid });
    const sent = access.toSend(url);
    if (sent.error) return fail({ field: "credential", message: sent.error });
    const target = url.trim();
    const mine = ++run.current;
    busy.current = true;
    setErrors({});
    setProblem(undefined);
    setPending(true);
    try {
      const result = await checkRepository(target, sent.credential);
      if (run.current !== mine) return;
      setChecked({ ...result, url: target, credential: sent.credential });
      setLibraryId(result.library_id);
    } catch (error) {
      if (run.current === mine) fail(explainCheckError(error, sent.credential?.kind));
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
        ...(checked.credential && { credential: checked.credential }),
      });
      // Only the list and the newest-job feed; the progress screen owns the job's own query.
      void queryClient.invalidateQueries({ queryKey: librariesKeys.list() });
      void queryClient.invalidateQueries({ queryKey: librariesKeys.latestJobs() });
      // Stored encrypted on the server now: the form lets go of its copy.
      access.forget();
      setChecked((c) => c && { ...c, credential: undefined });
      if (run.current === mine) {
        setAdded(result);
        toast.success(`Added ${result.library_id}`, {
          description: `Importing ${result.ref} now. You can leave this page.`,
        });
        const tags = preview.chosen([ref, result.ref]);
        if (tags.length) void older.queue(result.library_id, tags);
      }
    } catch (error) {
      if (run.current === mine) fail(explainAddError(error, ref, checked.credential?.kind));
    } finally {
      if (run.current === mine) {
        busy.current = false;
        setPending(false);
      }
    }
  }

  const phase = useAddPhase(added, Boolean(checked));

  function reset() {
    setUrl("");
    current.current = "";
    access.reset();
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
    <AddFrame phase={phase} added={Boolean(added)} heading={heading}>
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
          <AddressStep
            url={url}
            error={errors.url}
            taken={errors.url ? taken : undefined}
            alertId={problem?.message ? ALERT_ID : undefined}
            access={access}
            accessError={errors.credential}
            checked={checked}
            onEdit={edit}
            onAccessChanged={accessChanged}
          />

          {checked && (
            <div className="fade-in flex flex-col gap-6">
              <LibraryIdField
                value={libraryId}
                error={errors.id}
                onChange={(v) => {
                  setLibraryId(v);
                  clear("id");
                }}
              />
              <RefPicker
                url={checked.url}
                credential={checked.credential}
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
                form={{
                  url: checked.url,
                  ref: refToSend(choice, typedRef),
                  include,
                  exclude,
                  credential: checked.credential,
                }}
              />
            </div>
          )}

          <FormActions pending={pending} checked={Boolean(checked)} />
        </form>
      )}
    </AddFrame>
  );
}
