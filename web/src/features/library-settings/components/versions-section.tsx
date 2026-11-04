import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { type FormEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { type RefChoice, refToSend } from "@/shared/lib/refs";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { FormAlert } from "@/shared/ui/form-alert";
import { RefPicker } from "@/shared/ui/ref-picker";
import { addVersion, refreshLibraries, removeVersion } from "../api/settings";
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

function AddVersionForm({
  owner,
  repo,
  library,
  Import,
  onClose,
  onStart,
}: Props & { onClose: () => void }) {
  const queryClient = useQueryClient();
  // No version is preselected: adding one is a decision, not a default.
  const [choice, setChoice] = useState<RefChoice>({ kind: "none" });
  const [typed, setTyped] = useState("");
  const [fieldError, setFieldError] = useState<ReactNode>();
  const [problem, setProblem] = useState<Problem>();
  const [added, setAdded] = useState<AddedVersion>();

  const ref = refToSend(choice, typed);

  const add = useMutation({
    mutationFn: (target: string) => addVersion(owner, repo, target),
    onSuccess: (result) => {
      setAdded(result);
      refreshLibraries(queryClient);
    },
    onError: (error, target) => {
      const p = explainAddVersion(error, target);
      if (p.field) {
        setFieldError(fieldMessage(p));
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
      setFieldError("Choose a branch or tag from the list, or pick “Another ref or commit…”.");
      requestAnimationFrame(() =>
        (document.getElementById("ref-typed") ?? document.getElementById("ref"))?.focus(),
      );
      return;
    }
    setFieldError(undefined);
    onStart();
    add.mutate(ref);
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
        <RefPicker
          url={library.source_url}
          choice={choice}
          typed={typed}
          error={fieldError}
          explicit
          exclude={library.versions.map((v) => v.ref)}
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

  useEffect(() => {
    if (activity.by !== "versions") setNotice("");
  }, [activity]);

  // `transitionend` ends it; this covers reduced motion, where no transition runs.
  useEffect(() => {
    if (adding || !mounted) return;
    const id = setTimeout(() => setMounted(false), 260);
    return () => clearTimeout(id);
  }, [adding, mounted]);

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
        {notice && (
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
