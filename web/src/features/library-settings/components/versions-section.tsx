import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { type FormEvent, type ReactNode, useCallback, useRef, useState } from "react";
import {
  type Credential,
  type CredentialDraft,
  credentialKindFor,
  credentialOf,
  EMPTY_CREDENTIAL,
  validateCredential,
} from "@/shared/lib/credentials";
import { type RefChoice, refToSend } from "@/shared/lib/refs";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { CredentialField } from "@/shared/ui/credential-field";
import { FormAlert } from "@/shared/ui/form-alert";
import { RefPicker } from "@/shared/ui/ref-picker";
import { accessQueryOptions, addVersion, refreshLibraries, removeVersion } from "../api/settings";
import { useNow } from "../hooks/use-now";
import {
  type Activity,
  type AddedVersion,
  explainAddVersion,
  explainRemove,
  isAlreadyGone,
  type JobViews,
  type Problem,
  type SettingsLibrary,
  type SettingsVersion,
  shortSha,
} from "../model/settings";
import { secondary, sectionHeading } from "./styles";
import { TypedConfirm } from "./typed-confirm";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  Import: JobViews["Import"];
  activity: Activity;
  onStart: () => void;
}

function VersionRow({
  version,
  now,
  onRemove,
}: {
  version: SettingsVersion;
  now: number;
  onRemove: (version: SettingsVersion, trigger: HTMLElement) => void;
}) {
  return (
    <li className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-mono text-[15px] font-medium [overflow-wrap:anywhere]">
            {version.ref}
          </span>
          {version.is_default && <span className="text-xs font-medium text-mark">default</span>}
        </p>
        <p className="text-sm text-muted-foreground">
          {version.kind !== "tag" && <span className="capitalize">{version.kind} · </span>}
          <span className="font-mono text-[13px]">{shortSha(version.commit_sha)}</span>
          <span className="sr-only"> commit</span>
          <span aria-hidden="true"> · </span>
          <time dateTime={version.imported_at} title={absoluteTimeWithZone(version.imported_at)}>
            imported {relativeTime(version.imported_at, now)}
          </time>
        </p>
      </div>
      <Button
        type="button"
        variant="ghost"
        aria-label={`Remove version ${version.ref}`}
        onClick={(e) => onRemove(version, e.currentTarget)}
        className="-mr-3 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive focus-visible:text-destructive md:h-9"
      >
        Remove
      </Button>
    </li>
  );
}

/** A refusal's words, with the way out when the answer is elsewhere on this page. */
function fieldMessage(p: Problem): ReactNode {
  if (!p.jump) return p.message;
  return (
    <>
      {p.message}{" "}
      <a href={p.jump.href} className="underline underline-offset-2">
        {p.jump.label}
      </a>
      .
    </>
  );
}

/** The field a ref error belongs to: the typed ref when it is shown, else the picker. */
const refField = () => document.getElementById("ref-typed") ?? document.getElementById("ref");

/** Where a refusal goes: the credential box, else the typed ref when shown, else the picker. */
const fieldOf = (p: Problem) =>
  p.field === "credential" ? () => document.getElementById("version-credential") : refField;

function AddVersionForm({
  owner,
  repo,
  library,
  Import,
  onClose,
  onStart,
}: Props & { onClose: () => void }) {
  const queryClient = useQueryClient();
  const focusAfterRender = useFocusAfterRender();
  // Known before the picker asks anything: a private repository's refs need a credential.
  const { data: access, isPending: accessPending } = useQuery(accessQueryOptions(owner, repo));
  // No version is preselected: adding one is a decision, not a default.
  const [choice, setChoice] = useState<RefChoice>({ kind: "none" });
  const [typed, setTyped] = useState("");
  const [fieldError, setFieldError] = useState<ReactNode>();
  const [credentialError, setCredentialError] = useState<string>();
  const [problem, setProblem] = useState<Problem>();
  const [added, setAdded] = useState<AddedVersion>();
  const [pending, setPending] = useState(false);
  // A replacement token or key: component state only (no mutation, query key or cache holds it).
  const [askCredential, setAskCredential] = useState(false);
  const [draft, setDraft] = useState<CredentialDraft>(EMPTY_CREDENTIAL);
  // What the ref list was asked with: set when focus leaves the box, not on every keystroke.
  const [listedWith, setListedWith] = useState<Credential>();
  const busy = useRef(false);

  const ref = refToSend(choice, typed);
  const kind = credentialKindFor(library.source_url);
  const showCredential = Boolean(kind && (access?.private || askCredential));

  function typedCredential(): { credential?: Credential; error?: string } {
    if (!kind || !showCredential || !draft.secret.trim()) return {};
    const error = validateCredential(kind, draft);
    if (error) return { error };
    const credential = credentialOf(kind, draft);
    return credential ? { credential } : {};
  }

  function commit() {
    const next = typedCredential();
    if (next.error) return;
    // Same secret, same object: the list is not asked for again.
    setListedWith((was) =>
      JSON.stringify(was) === JSON.stringify(next.credential) ? was : next.credential,
    );
  }

  function refuse(p: Problem) {
    if (p.field === "credential") {
      setAskCredential(true);
      setCredentialError(p.message);
      setFieldError(undefined);
      setProblem(undefined);
    } else if (p.field) {
      setFieldError(fieldMessage(p));
      setProblem(undefined);
    } else {
      setProblem(p);
      return;
    }
    // In the commit that shows the error, never a frame later.
    focusAfterRender(fieldOf(p));
  }

  const unavailable = useCallback(() => setChoice({ kind: "other" }), []);
  // A replacement that does not even list the refs would not import either: say so now.
  const listRefused = (error: unknown) => {
    const p = explainAddVersion(error, "", kind);
    return p.field === "credential" ? p.message : undefined;
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    setProblem(undefined);
    if (!ref) {
      setFieldError("Choose a branch or tag from the list, or pick “Another ref or commit…”.");
      focusAfterRender(refField);
      return;
    }
    setFieldError(undefined);
    const sent = typedCredential();
    if (sent.error) {
      refuse({ field: "credential", message: sent.error });
      return;
    }
    setCredentialError(undefined);
    onStart();
    busy.current = true;
    setPending(true);
    try {
      const result = await addVersion(owner, repo, ref, sent.credential);
      // Stored encrypted on the server now: the form lets go of its copy.
      setDraft(EMPTY_CREDENTIAL);
      setListedWith(undefined);
      setAdded(result);
    } catch (error) {
      refuse(explainAddVersion(error, ref, sent.credential?.kind));
    } finally {
      busy.current = false;
      setPending(false);
      // A 409 means the library changed under us: reload what the page shows either way.
      refreshLibraries(queryClient);
    }
  }

  if (added) {
    return (
      <Import
        added={added}
        finish={
          <Button type="button" onClick={onClose}>
            Close
          </Button>
        }
      />
    );
  }

  return (
    <form onSubmit={submit} noValidate>
      <h3 className="text-lg font-semibold">Add a version</h3>
      <div className="mt-4">
        <FormAlert id="add-version-alert" message={problem?.message} link={problem?.link} />
      </div>
      <div className="flex flex-col gap-5">
        {showCredential && kind && (
          <div className="fade-in">
            <CredentialField
              id="version-credential"
              kind={kind}
              draft={draft}
              error={credentialError}
              hint={
                access?.private
                  ? `Optional. Leave it empty to use the ${kind === "token" ? "token" : "key"} stored for this library; a new one replaces it.`
                  : "A new one is stored encrypted for this library, replacing any stored one."
              }
              onChange={(d) => {
                setDraft(d);
                setCredentialError(undefined);
              }}
              onCommit={commit}
            />
          </div>
        )}
        {!accessPending && (
          <RefPicker
            url={library.source_url}
            credential={listedWith}
            explainRefusal={listRefused}
            unlisted={
              access?.private
                ? "Branches and tags of a private repository are listed with its token or key: enter it above to see them, or type a version below."
                : undefined
            }
            choice={choice}
            typed={typed}
            error={fieldError}
            explicit
            exclude={library.versions.map((v) => v.ref)}
            onChoice={(c) => {
              setChoice(c);
              setFieldError(undefined);
              if (c.kind === "other") {
                focusAfterRender(() => document.getElementById("ref-typed"));
              }
            }}
            onUnavailable={unavailable}
            onTyped={(v) => {
              setTyped(v);
              setFieldError(undefined);
            }}
          />
        )}
        <p className="text-sm text-muted-foreground">
          It is imported with the same paths and tag rules as the other versions.
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" aria-disabled={pending} aria-busy={pending} className="min-w-32">
            {pending ? "Adding" : "Add version"}
          </Button>
        </div>
      </div>
    </form>
  );
}

const defaultNote = (v: SettingsVersion | undefined) =>
  v?.is_default
    ? " It is the default version, so the library's default moves to another version."
    : "";

/** The imported versions, an add form, and a typed-confirmation remove per version. */
export function VersionsSection(props: Props) {
  const { owner, repo, library, activity, onStart } = props;
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  // The card stays mounted while its row collapses, so it does not vanish before the space does.
  const [mounted, setMounted] = useState(false);
  const [removing, setRemoving] = useState<SettingsVersion>();
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<Problem>();
  const heading = useRef<HTMLHeadingElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const removedOk = useRef(false);
  const now = useNow();
  const focusAfterRender = useFocusAfterRender();

  const remove = useMutation({
    mutationFn: (version: SettingsVersion) =>
      removeVersion(owner, repo, version.ref).catch((error: unknown) => {
        // Gone already (another window): the row should go either way.
        if (isAlreadyGone(error)) return undefined;
        throw error;
      }),
    onSuccess: (result, version) => {
      removedOk.current = true;
      setProblem(undefined);
      setNotice(
        result?.default_version
          ? `Removed ${version.ref}. The default version is now ${result.default_version}.`
          : result
            ? `Removed ${version.ref}. This library has no versions left.`
            : `${version.ref} was already removed.`,
      );
      setRemoving(undefined);
      refreshLibraries(queryClient);
    },
    onError: (error, version) => {
      setProblem(explainRemove(error, `version ${version.ref}`));
      refreshLibraries(queryClient);
    },
  });

  const versions = library.versions;

  function closeAdd() {
    setAdding(false);
    // `transitionend` unmounts the card; without a transition (reduced motion) nothing fires it.
    setTimeout(() => setMounted(false), 300);
    // The button sits outside the card, so it is on screen in the commit that closes it.
    focusAfterRender(() => addButton.current);
  }

  return (
    <section aria-labelledby="versions-heading" className="mt-12 border-t border-border pt-10">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="max-w-prose">
          <h2
            id="versions-heading"
            ref={heading}
            tabIndex={-1}
            className={cn(sectionHeading, "outline-none")}
          >
            Versions
          </h2>
          <p className="mt-1.5 text-muted-foreground">
            Each version is a branch, tag or commit imported as it was.
          </p>
        </div>
        <Button
          ref={addButton}
          type="button"
          aria-expanded={adding}
          aria-controls="add-version"
          onClick={() => {
            setNotice("");
            if (adding) return closeAdd();
            setMounted(true);
            setAdding(true);
          }}
          className={secondary}
        >
          Add a version
        </Button>
      </div>

      <div
        id="add-version"
        onTransitionEnd={(e) => {
          if (e.target === e.currentTarget && !adding) setMounted(false);
        }}
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none",
          adding ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden" inert={!adding}>
          {mounted && (
            <div className="mt-6 rounded-lg bg-secondary/60 p-4 sm:p-5">
              <AddVersionForm {...props} onClose={closeAdd} />
            </div>
          )}
        </div>
      </div>

      <p role="status" className="mt-4 min-h-5 text-sm">
        {notice && activity.by === "versions" && (
          <span className="fade-in inline-flex items-start gap-1.5">
            <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
            {notice}
          </span>
        )}
      </p>

      <div className="mt-2">
        {versions.length === 0 ? (
          <p className="text-muted-foreground">
            No versions yet. Add one, or wait for the first import to finish.
          </p>
        ) : (
          // No bottom rule: the next section brings its own.
          <ul
            aria-label="Imported versions"
            className="divide-y divide-border border-t border-border"
          >
            {versions.map((v) => (
              <VersionRow
                key={v.ref}
                version={v}
                now={now}
                onRemove={(version, el) => {
                  trigger.current = el;
                  removedOk.current = false;
                  remove.reset();
                  setProblem(undefined);
                  onStart();
                  setRemoving(version);
                }}
              />
            ))}
          </ul>
        )}
      </div>

      <TypedConfirm
        open={removing !== undefined}
        onOpenChange={(open) => {
          if (!open) setRemoving(undefined);
        }}
        title={
          <>
            Remove <span className="font-mono text-[0.9em]">{removing?.ref ?? "version"}</span>?
          </>
        }
        loss="Its articles disappear from browse, search and agents now."
        safe={`Nothing in the repository changes. Content that other versions share stays available. You can add this version again.${defaultNote(removing)}`}
        phrase={removing?.ref ?? ""}
        confirmLabel="Remove version"
        pending={remove.isPending}
        problem={problem}
        onConfirm={() => removing && remove.mutate(removing)}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          // A removed row is gone: land on the heading. Otherwise back on the button that opened it.
          (removedOk.current ? heading.current : trigger.current)?.focus();
        }}
      />
    </section>
  );
}
