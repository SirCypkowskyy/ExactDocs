import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { type FormEvent, useCallback, useRef, useState } from "react";
import { type RefChoice, refToSend } from "@/shared/lib/refs";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { FormAlert } from "@/shared/ui/form-alert";
import { RefPicker } from "@/shared/ui/ref-picker";
import { addVersion, refreshLibraries, removeVersion } from "../api/settings";
import {
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
import { secondary } from "./styles";
import { TypedConfirm } from "./typed-confirm";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  Import: JobViews["Import"];
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
        className="shrink-0 text-destructive hover:bg-destructive/10 md:h-9"
      >
        Remove
      </Button>
    </li>
  );
}

function AddVersionForm({
  owner,
  repo,
  library,
  Import,
  onClose,
}: Props & { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState<RefChoice>({ kind: "default" });
  const [typed, setTyped] = useState("");
  const [fieldError, setFieldError] = useState<string>();
  const [problem, setProblem] = useState<Problem>();
  const [added, setAdded] = useState<AddedVersion>();

  const ref = refToSend(choice, typed) ?? library.default_branch;

  const add = useMutation({
    mutationFn: (target: string) => addVersion(owner, repo, target),
    onSuccess: (result) => {
      setAdded(result);
      refreshLibraries(queryClient);
    },
    onError: (error, target) => {
      const p = explainAddVersion(error, target);
      if (p.field) {
        setFieldError(p.detail ? `${p.message} ${p.detail}` : p.message);
        setProblem(undefined);
        requestAnimationFrame(() =>
          (document.getElementById("ref-typed") ?? document.getElementById("ref"))?.focus(),
        );
      } else {
        setProblem(p);
      }
      // A 409 means the library changed under us: reload what the page shows.
      refreshLibraries(queryClient);
    },
  });

  const unavailable = useCallback(() => setChoice({ kind: "other" }), []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (add.isPending) return;
    setProblem(undefined);
    if (!ref) {
      setFieldError("Choose a branch, a tag or a commit to add.");
      requestAnimationFrame(() => document.getElementById("ref")?.focus());
      return;
    }
    setFieldError(undefined);
    add.mutate(ref);
  }

  if (added) {
    return (
      <Import
        added={added}
        finish={
          <Button type="button" onClick={onClose}>
            Done
          </Button>
        }
      />
    );
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-5">
      <FormAlert id="add-version-alert" message={problem?.message} link={problem?.link} />
      <RefPicker
        url={library.source_url}
        choice={choice}
        typed={typed}
        error={fieldError}
        onChoice={(c) => {
          setChoice(c);
          setFieldError(undefined);
          if (c.kind === "other") {
            requestAnimationFrame(() => document.getElementById("ref-typed")?.focus());
          }
        }}
        onUnavailable={unavailable}
        onTyped={(v) => {
          setTyped(v);
          setFieldError(undefined);
        }}
      />
      <p className="text-sm text-muted-foreground">
        It is imported with the same paths and tag rules as the other versions.
      </p>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="submit"
          aria-disabled={add.isPending}
          aria-busy={add.isPending}
          className="min-w-32"
        >
          {add.isPending ? "Adding" : "Add version"}
        </Button>
      </div>
    </form>
  );
}

/** The imported versions, an add form, and a typed-confirmation remove per version. */
export function VersionsSection(props: Props) {
  const { owner, repo, library } = props;
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<SettingsVersion>();
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<Problem>();
  const heading = useRef<HTMLHeadingElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const removedOk = useRef(false);
  const [now] = useState(() => Date.now());

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
    requestAnimationFrame(() => addButton.current?.focus());
  }

  return (
    <section aria-labelledby="versions-heading" className="mt-12 border-t border-border pt-10">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="max-w-prose">
          <h2
            id="versions-heading"
            ref={heading}
            tabIndex={-1}
            className="font-serif text-2xl font-semibold tracking-tight outline-none"
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
            setAdding(!adding);
          }}
          className={secondary}
        >
          Add a version
        </Button>
      </div>

      <div
        id="add-version"
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none",
          adding ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden" inert={!adding}>
          {adding && (
            <div className="mt-6 max-w-xl rounded-lg bg-secondary/60 p-4 sm:p-5">
              <h3 className="mb-4 text-lg font-semibold">Add a version</h3>
              <AddVersionForm {...props} onClose={closeAdd} />
            </div>
          )}
        </div>
      </div>

      <p role="status" className="mt-4 min-h-5 text-sm">
        {notice && (
          <span className="fade-in inline-flex items-start gap-1.5">
            <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
            {notice}
          </span>
        )}
      </p>

      <div className="mt-2 max-w-xl">
        {versions.length === 0 ? (
          <p className="text-muted-foreground">
            No versions yet. Add one, or wait for the first import to finish.
          </p>
        ) : (
          <ul
            aria-label="Imported versions"
            className="divide-y divide-border border-y border-border"
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
        title={`Remove ${removing?.ref ?? "version"}?`}
        consequence={
          <>
            Its articles leave browse, search and agents right away. Text that other versions share
            is kept, and the repository itself is untouched. This can't be undone, but you can add
            the version again.
          </>
        }
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
