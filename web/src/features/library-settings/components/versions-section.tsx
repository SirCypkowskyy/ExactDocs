import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, X } from "lucide-react";
import { type FormEvent, type ReactNode, useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import {
  type Credential,
  type CredentialDraft,
  credentialKindFor,
  credentialOf,
  EMPTY_CREDENTIAL,
  validateCredential,
} from "@/shared/lib/credentials";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { type RefChoice, refToSend } from "@/shared/lib/refs";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { Button } from "@/shared/ui/button";
import { TypedConfirmDialog } from "@/shared/ui/confirm-dialog";
import { CredentialField } from "@/shared/ui/credential-field";
import { restoreRowFocus } from "@/shared/ui/data-table/row-actions";
import { FormAlert } from "@/shared/ui/form-alert";
import { RefPicker } from "@/shared/ui/ref-picker";
import { accessQueryOptions, addVersion, refreshLibraries, removeVersion } from "../api/settings";
import { errorMessages } from "../messages/errors";
import { pageMessages } from "../messages/page";
import { versionsMessages } from "../messages/versions";
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
} from "../model/settings";
import { SettingsSection } from "./settings-section";
import { VersionsTable } from "./versions-table";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  Import: JobViews["Import"];
  activity: Activity;
  onStart: () => void;
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
  const language = useLanguage();
  const t = versionsMessages[language];
  const { cancel, close } = common[language];
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
    const error = validateCredential(kind, draft, language);
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
    const p = explainAddVersion(error, "", kind, language);
    return p.field === "credential" ? p.message : undefined;
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    setProblem(undefined);
    if (!ref) {
      setFieldError(t.chooseRef);
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
      toast.success(t.importingToast(ref), {
        description: t.importingDescription,
      });
    } catch (error) {
      refuse(explainAddVersion(error, ref, sent.credential?.kind, language));
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
            <X aria-hidden="true" data-icon-motion="turn" />
            {close}
          </Button>
        }
      />
    );
  }

  return (
    <form onSubmit={submit} noValidate>
      <h3 className="text-section font-semibold">{t.add}</h3>
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
              hint={access?.private ? t.storedHint[kind === "token" ? "token" : "key"] : t.newHint}
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
            unlisted={access?.private ? t.unlisted : undefined}
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
        <p className="text-body text-muted-foreground">{t.sameRules}</p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={onClose}>
            {cancel}
          </Button>
          <Button type="submit" pending={pending} aria-disabled={pending} className="min-w-32">
            {!pending && <Plus aria-hidden="true" data-icon-motion="turn" />}
            {pending ? t.adding : t.addVersion}
          </Button>
        </div>
      </div>
    </form>
  );
}

/** The imported versions, an add form, and a typed-confirmation remove per version. */
export function VersionsSection(props: Props) {
  const { owner, repo, activity, onStart } = props;
  const language = useLanguage();
  const t = versionsMessages[language];
  const page = useMessages(pageMessages);
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<SettingsVersion>();
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<Problem>();
  const heading = useRef<HTMLHeadingElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const removedOk = useRef(false);
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
          ? t.removedNewDefault(version.ref, result.default_version)
          : result
            ? t.removedLast(version.ref)
            : t.alreadyRemoved(version.ref),
      );
      setRemoving(undefined);
      toast.success(t.removedToast(version.ref), {
        ...(result?.default_version && {
          description: t.newDefault(result.default_version),
        }),
      });
      refreshLibraries(queryClient);
    },
    onError: (error, version) => {
      setProblem(
        explainRemove(error, errorMessages[language].remove.version(version.ref), language),
      );
      refreshLibraries(queryClient);
    },
  });

  function closeAdd() {
    setAdding(false);
    // The button sits outside the card, so it is on screen in the commit that closes it.
    focusAfterRender(() => addButton.current);
  }

  return (
    <SettingsSection
      id="versions"
      title={page.sections.versions}
      description={t.description}
      headingRef={heading}
    >
      <div className="mb-4">
        <Button
          ref={addButton}
          type="button"
          variant="outline"
          aria-expanded={adding}
          aria-controls="add-version"
          onClick={() => {
            setNotice("");
            if (adding) return closeAdd();
            setAdding(true);
          }}
        >
          <Plus aria-hidden="true" data-icon-motion="turn" />
          {t.add}
        </Button>
      </div>

      <div id="add-version">
        {adding && (
          <div className="reveal mb-4 rounded-lg bg-raised p-4 sm:p-5">
            <AddVersionForm {...props} onClose={closeAdd} />
          </div>
        )}
      </div>

      <p role="status" className="min-h-5 text-body">
        {notice && activity.by === "versions" && (
          <span className="fade-in inline-flex items-start gap-1.5">
            <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-route" />
            {notice}
          </span>
        )}
      </p>

      <div className="mt-2">
        <VersionsTable
          owner={owner}
          repo={repo}
          pinned={props.library.default_pinned}
          onRemove={(version) => {
            removedOk.current = false;
            remove.reset();
            setProblem(undefined);
            onStart();
            setRemoving(version);
          }}
        />
      </div>

      <TypedConfirmDialog
        open={removing !== undefined}
        onOpenChange={(open) => {
          if (!open) setRemoving(undefined);
        }}
        title={page.confirm.title(
          <span className="font-mono [overflow-wrap:anywhere]">
            {removing?.ref ?? t.versionFallback}
          </span>,
        )}
        description={<span className="text-foreground">{t.loss}</span>}
        phrase={removing?.ref ?? ""}
        initialFocus="phrase"
        confirmLabel={t.confirm}
        pendingLabel={page.confirm.removing}
        pending={remove.isPending}
        error={problem?.message}
        errorTone={problem?.tone}
        errorLink={problem?.link}
        onConfirm={() => removing && remove.mutate(removing)}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          // A removed row is gone: land on the heading. Otherwise back to the row's menu.
          if (removedOk.current) heading.current?.focus();
          else restoreRowFocus(event);
        }}
      >
        <p className="mt-1.5">{t.safe(removing?.is_default ? t.defaultNote : "")}</p>
      </TypedConfirmDialog>
    </SettingsSection>
  );
}
