import { FileText, Folder, Info } from "lucide-react";
import { useState } from "react";
import { lines } from "@/shared/lib/path-selection";
import { Button } from "@/shared/ui/button";
import { FormAlert } from "@/shared/ui/form-alert";
import { type Extra, type PreviewForm, usePreview } from "../hooks/use-preview";
import {
  type AddProblem,
  type Context7,
  type PreviewFolder,
  previewCountText,
  previewKey,
  type RepositoryPreview,
} from "../model/add-library";
import { shortSha } from "../model/library";
import { JobLine } from "./import-progress";

const count = "font-normal text-muted-foreground tabular-nums";

function FolderRow({ folder }: { folder: PreviewFolder }) {
  return (
    <li>
      <span className="inline-flex items-start gap-1.5">
        <Folder aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span className="[overflow-wrap:anywhere]">
          {folder.name}/ <span className={count}>({folder.count})</span>
        </span>
      </span>
      <Entries folder={folder} />
    </li>
  );
}

/** A folder's content: subfolders first, then files. Paths are repository text: shown, never linked. */
function Entries({ folder, root = false }: { folder: PreviewFolder; root?: boolean }) {
  return (
    <ul className={root ? "space-y-1" : "mt-1 space-y-1 border-l border-border pl-4 ml-2"}>
      {folder.folders.map((f) => (
        <FolderRow key={f.path} folder={f} />
      ))}
      {folder.files.map((name) => (
        <li key={`${folder.path}/${name}`} className="inline-flex w-full items-start gap-1.5">
          <FileText aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <span className="[overflow-wrap:anywhere]">{name}</span>
        </li>
      ))}
    </ul>
  );
}

/** What the repository's `context7.json` said, or why it was ignored. All of it is untrusted text. */
function Context7Note({
  context7,
  warning,
  prefilled,
}: {
  context7: Context7 | null | undefined;
  warning: string | null | undefined;
  prefilled: boolean;
}) {
  if (!context7 && !warning) return null;
  return (
    <div className="mt-4 rounded-md bg-accent px-3 py-2.5 text-body">
      <p className="inline-flex items-start gap-2 font-medium">
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-route" />
        {context7
          ? "This repository has a context7.json."
          : "This repository's context7.json is ignored."}
      </p>
      <div className="mt-1 space-y-1 pl-6 text-muted-foreground [overflow-wrap:anywhere]">
        {warning && <p>{warning}</p>}
        {context7?.project_title && (
          <p>
            Title: <span className="text-foreground">{context7.project_title}</span>
          </p>
        )}
        {context7?.description && (
          <p>
            Description: <span className="text-foreground">{context7.description}</span>
          </p>
        )}
        {prefilled && (
          <p>Its paths are filled in under “Choose files and tags”. Change them if you like.</p>
        )}
        {context7 && context7.rules.length > 0 && (
          <p>
            {context7.rules.length === 1
              ? "Its rule is shown to agents with every answer."
              : `Its ${context7.rules.length} rules are shown to agents with every answer.`}
          </p>
        )}
        {context7?.notes?.map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    </div>
  );
}

interface VersionsProps {
  versions: Context7["previous_versions"];
  /** The ref picked above: it is imported anyway, so it is not offered again. */
  current: string | null;
  selected: ReadonlySet<string>;
  onSelect: (tag: string, on: boolean) => void;
}

/** The older tags `previousVersions` offers: ticked ones are imported once the library is added. */
function OlderVersions({ versions: all, current, selected, onSelect }: VersionsProps) {
  const versions = all.filter((v) => v.tag !== current);
  if (versions.length === 0) return null;
  return (
    <fieldset className="mt-5" aria-describedby="older-hint">
      <legend className="text-body font-medium">Also import older versions</legend>
      <p id="older-hint" className="mt-1 text-body text-muted-foreground">
        The repository's context7.json offers these tags. Each one ticked is imported after the
        library is added.
      </p>
      <ul className="mt-2 space-y-1">
        {versions.map((v) => (
          <li key={v.tag}>
            <label className="-ml-2 inline-flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-2 hover:bg-accent md:min-h-9">
              <input
                type="checkbox"
                checked={selected.has(v.tag)}
                onChange={(e) => onSelect(v.tag, e.target.checked)}
                className="size-4 accent-primary"
              />
              <span className="font-mono text-mono [overflow-wrap:anywhere]">{v.tag}</span>
              {v.title && <span className="text-body text-muted-foreground">{v.title}</span>}
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

interface Props {
  preview: RepositoryPreview;
  tree: PreviewFolder;
  /** The form changed since: the files may differ now. */
  stale: boolean;
  /** The include and exclude boxes were filled from `context7.json`. */
  prefilled: boolean;
  selected: ReadonlySet<string>;
  onSelect: (tag: string, on: boolean) => void;
  /** The ref the form will add now. */
  current: string | null;
  /** Inside another page's section (library settings): a sub-heading, and only the files. */
  compact?: boolean;
}

/** The files an import would take, as a tree with counts, and what `context7.json` adds. */
function FilePreview({
  preview,
  tree,
  stale,
  prefilled,
  selected,
  onSelect,
  current,
  compact = false,
}: Props) {
  const Heading = compact ? "h3" : "h2";
  return (
    <section
      aria-labelledby="preview-title"
      className="fade-in rounded-lg border border-border bg-raised px-4 py-4"
    >
      <Heading id="preview-title" className="text-section font-semibold">
        {compact ? "Files these paths take" : "Files to import"}
      </Heading>
      <p className="mt-0.5 text-body text-muted-foreground">
        <span className="font-mono text-mono [overflow-wrap:anywhere]">{preview.ref}</span>
        <span aria-hidden="true"> · </span>
        <span className="font-mono text-mono">{shortSha(preview.commit_sha)}</span>
        <span className="sr-only"> commit</span>
      </p>
      <p className="mt-3 text-body font-medium">{previewCountText(preview)}</p>
      {stale && (
        <p className="mt-1 text-body text-muted-foreground">
          The form changed since this preview. Preview again to see the files it takes now.
        </p>
      )}
      {preview.total > 0 && (
        // Up to 1000 paths: the list scrolls on its own, and takes focus so every browser can scroll it.
        <section
          // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling list must be reachable by keyboard (Safari does not focus scrollers)
          tabIndex={0}
          aria-label="Matching files"
          className={`mt-3 max-h-80 overflow-y-auto rounded-md bg-code px-3 py-2.5 font-mono text-mono outline-none focus-visible:ring-2 focus-visible:ring-ring ${stale ? "opacity-60" : ""}`}
        >
          <Entries folder={tree} root />
        </section>
      )}
      {!compact && (
        <>
          <Context7Note
            context7={preview.context7}
            warning={preview.context7_warning}
            prefilled={prefilled}
          />
          <OlderVersions
            versions={preview.context7?.previous_versions ?? []}
            current={current}
            selected={selected}
            onSelect={onSelect}
          />
        </>
      )}
    </section>
  );
}

function PreviewButton({ pending, onClick }: { pending: boolean; onClick: () => void }) {
  return (
    <Button
      variant="outline"
      aria-disabled={pending}
      aria-busy={pending}
      aria-describedby="preview-hint"
      onClick={onClick}
      className="w-fit"
    >
      {pending && (
        <span
          aria-hidden="true"
          className="spin size-4 rounded-full border-2 border-foreground/30 border-t-foreground"
        />
      )}
      {pending ? "Previewing" : "Preview"}
    </Button>
  );
}

/** The Preview button and, once asked, the files the form as it stands would import. */
export function PreviewPanel({
  preview,
  form,
}: {
  preview: ReturnType<typeof usePreview>;
  form: PreviewForm;
}) {
  const shown = preview.preview;
  return (
    <>
      <div className="flex flex-col gap-1">
        <PreviewButton pending={preview.pending} onClick={() => void preview.start(form)} />
        <p id="preview-hint" className="text-body text-muted-foreground">
          See which files this version and these paths take, before importing.
        </p>
      </div>
      <p role="status" className="sr-only">
        {shown && !preview.pending ? previewCountText(shown.result) : ""}
      </p>
      {shown && preview.tree && (
        <FilePreview
          preview={shown.result}
          tree={preview.tree}
          stale={shown.key !== previewKey(form)}
          prefilled={shown.prefilled}
          selected={preview.selected}
          onSelect={preview.select}
          current={form.ref}
        />
      )}
    </>
  );
}

interface SelectionPreviewProps {
  /** The library's repository. */
  url: string;
  /** The version to look at (the default one); null: the default branch. */
  version: string | null;
  include: string;
  exclude: string;
}

/**
 * The Preview button and its files for a library that exists already (its settings page): which
 * files the paths as typed take in one version, before they are saved. No paths means every
 * Markdown file there, so `**` is sent: an empty selection would take the repository's
 * context7.json paths instead, which a stored library no longer follows.
 */
export function SelectionPreview({ url, version, include, exclude }: SelectionPreviewProps) {
  const [problem, setProblem] = useState<AddProblem>();
  const preview = usePreview({
    onFail: setProblem,
    onPrefill: () => undefined,
    onStart: () => setProblem(undefined),
  });
  const empty = lines(include).length + lines(exclude).length === 0;
  const form: PreviewForm = { url, ref: version, include: empty ? "**" : include, exclude };
  const shown = preview.preview;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <PreviewButton pending={preview.pending} onClick={() => void preview.start(form)} />
        <p id="preview-hint" className="text-body text-muted-foreground">
          See which files these paths take in{" "}
          {version ? <span className="font-mono text-mono">{version}</span> : "the default branch"},
          before saving.
        </p>
      </div>
      <FormAlert id="preview-alert" message={problem?.message} link={problem?.link} />
      <p role="status" className="sr-only">
        {shown && !preview.pending ? previewCountText(shown.result) : ""}
      </p>
      {shown && preview.tree && (
        <FilePreview
          preview={shown.result}
          tree={preview.tree}
          // `form` has `**` in place of empty boxes, as it was sent: clearing the boxes after an
          // empty-box preview keeps it current, because it asked for exactly that.
          stale={shown.key !== previewKey(form)}
          prefilled={false}
          selected={preview.selected}
          onSelect={preview.select}
          current={version}
          compact
        />
      )}
    </div>
  );
}

/** The older versions ticked in the preview, each a line of its own under the library's import. */
export function ExtraVersions({
  extras,
  libraryId,
  onRetry,
}: {
  extras: readonly Extra[];
  libraryId: string;
  onRetry: (tag: string) => void;
}) {
  if (extras.length === 0) return null;
  return (
    <section aria-labelledby="extras-title" className="mt-8">
      <h3 id="extras-title" className="text-section font-semibold">
        Older versions
      </h3>
      <ul className="mt-3 space-y-4">
        {extras.map((x) => (
          <li key={x.tag}>
            {/* Focus lands here when Try again unmounts its button: the row stays, its state changes. */}
            <p
              data-tag-name
              tabIndex={-1}
              className="w-fit rounded font-mono text-mono outline-none [overflow-wrap:anywhere] focus-visible:ring-2 focus-visible:ring-ring"
            >
              {x.tag}
            </p>
            {x.jobId ? (
              <JobLine jobId={x.jobId} label={`${libraryId} ${x.tag}`} />
            ) : x.error ? (
              <div className="flex flex-wrap items-center gap-x-3">
                <p className="text-body text-destructive">{x.error}</p>
                {x.retry && (
                  <Button
                    variant="ghost"
                    className="-ml-3 h-11 md:h-8"
                    aria-label={`Try again to import ${x.tag}`}
                    onClick={(e) => {
                      // The button goes away with the retry; keep the keyboard on this tag's row.
                      e.currentTarget
                        .closest("li")
                        ?.querySelector<HTMLElement>("[data-tag-name]")
                        ?.focus();
                      onRetry(x.tag);
                    }}
                  >
                    Try again
                  </Button>
                )}
              </div>
            ) : (
              <p className="text-body text-muted-foreground">Waiting to be queued</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
