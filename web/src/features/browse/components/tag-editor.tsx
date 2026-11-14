import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { type FormEvent, type ReactNode, type RefObject, useId, useRef, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { MAX_TAG_LENGTH, MAX_TAGS } from "@/shared/lib/tags";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { Input } from "@/shared/ui/input";
import { refreshTags, setManualTags } from "../api/manual-tags";
import {
  type AddResult,
  addedNothing,
  addTag,
  keptNotice,
  type ManualTag,
  tagGroups,
  withoutTag,
} from "../model/article-tags";
import type { Article } from "../model/browse";

interface TagEditorProps {
  owner: string;
  repo: string;
  article: Pick<Article, "path" | "tags" | "manual_tags" | "tag_origins">;
}

const small =
  "inline-flex h-11 cursor-pointer items-center gap-1 rounded-md px-3 text-[13px] font-medium outline-none transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] disabled:cursor-progress disabled:opacity-60 lg:h-7 lg:px-2";
/** One manual tag's identity: the same tag can be set on this path and on an older one. */
const keyOf = (m: ManualTag) => `${m.path}\u0000${m.tag}`;
const quiet = `${small} bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent`;

const REASONS: Record<Extract<AddResult, { ok: false }>["reason"], string> = {
  invalid: `A tag starts with a letter or digit and goes on with letters, digits and . _ + - (${MAX_TAG_LENGTH} characters at most).`,
  duplicate: "This article already has that tag.",
  "too-many": `An article path takes at most ${MAX_TAGS} tags by hand.`,
};

function explain(error: unknown): string {
  if (error instanceof HttpError && error.status === 422) {
    return error.code === "invalid_tags" ? REASONS.invalid : error.message;
  }
  if (error instanceof HttpError && error.status === 401) return "Sign in again to change tags.";
  if (error instanceof HttpError && error.status === 404) {
    return "This library is no longer imported. Reload the page.";
  }
  return "The tags could not be saved. Try again.";
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <dt className="w-24 shrink-0 text-xs text-muted-foreground/80">{label}</dt>
      <dd className="m-0 min-w-0 flex-1">{children}</dd>
    </div>
  );
}

function Plain({ tags, label }: { tags: readonly string[]; label: string }) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-x-3 text-[13px] text-muted-foreground">
      {tags.map((t) => (
        <li key={t}>{t}</li>
      ))}
    </ul>
  );
}

const chipButton =
  "inline-flex size-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring aria-disabled:cursor-progress aria-disabled:opacity-60 lg:size-7 [@media(hover:hover)]:hover:text-foreground";

/** One manual tag, where it was set when that is an older path, and its remove button. */
function ManualChip({
  tag,
  inherited,
  busy,
  buttonRef,
  onRemove,
}: {
  tag: ManualTag;
  inherited: boolean;
  busy: boolean;
  buttonRef: (button: HTMLButtonElement | null) => void;
  onRemove: () => void;
}) {
  return (
    <li className="inline-flex items-center gap-0.5 rounded-md bg-secondary pl-2.5 text-[13px] lg:pl-2">
      <span>{tag.tag}</span>
      {inherited && (
        <span className="ml-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">
          set on <span className="font-mono">{tag.path}</span>
        </span>
      )}
      <button
        ref={buttonRef}
        type="button"
        // Not `disabled`: that would drop the focus while the change is saved.
        aria-disabled={busy || undefined}
        onClick={onRemove}
        aria-label={
          inherited ? `Remove tag ${tag.tag}, set on ${tag.path}` : `Remove tag ${tag.tag}`
        }
        title={inherited ? `Removes it from ${tag.path} in every version` : undefined}
        className={chipButton}
      >
        <X aria-hidden="true" className="size-3.5" />
      </button>
    </li>
  );
}

interface AddTagFormProps {
  inputId: string;
  statusId: string;
  field: RefObject<HTMLInputElement | null>;
  text: string;
  invalid: boolean;
  busy: boolean;
  onText: (text: string) => void;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
}

/** The field a new manual tag is typed in; Escape or Cancel closes it. */
function AddTagForm({
  inputId,
  statusId,
  field,
  text,
  invalid,
  busy,
  onText,
  onSubmit,
  onClose,
}: AddTagFormProps) {
  const hintId = `${inputId}-hint`;
  return (
    <form
      onSubmit={onSubmit}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      className="mt-2 flex max-w-md flex-wrap items-center gap-2"
    >
      <label htmlFor={inputId} className="sr-only">
        New tag
      </label>
      <Input
        ref={field}
        id={inputId}
        autoFocus
        value={text}
        onChange={(e) => onText(e.target.value)}
        placeholder="onboarding"
        autoComplete="off"
        spellCheck={false}
        aria-invalid={invalid || undefined}
        // The reason a value was refused is read with the field.
        aria-describedby={invalid ? `${statusId} ${hintId}` : hintId}
        className="h-11 min-w-0 flex-1 text-sm lg:h-8"
      />
      <button
        type="submit"
        disabled={busy}
        className={`${small} bg-primary text-primary-foreground hover:bg-primary/90`}
      >
        {busy ? "Saving…" : "Add"}
      </button>
      <button type="button" onClick={onClose} className={quiet}>
        Cancel
      </button>
      <p id={hintId} className="w-full text-xs text-muted-foreground">
        For this path in every version of the library, and where it was renamed to later.
      </p>
    </form>
  );
}

/** An error, or a notice that a removed tag stays; always mounted so it is announced. */
function Status({
  id,
  error,
  notice,
}: {
  id: string;
  error: string | undefined;
  notice: string | undefined;
}) {
  const tone = error ? "mt-1.5 text-xs text-destructive" : "mt-1.5 text-xs text-muted-foreground";
  return (
    <p id={id} role="status" className={error || notice ? tone : "sr-only"}>
      {error ?? notice ?? ""}
    </p>
  );
}

/**
 * The article's tags by origin (front matter, path rules, by hand; a tag with several origins
 * shows under each), and the editor of the manual ones (TAG-01). A manual tag holds for every version of the library; one set on an older path the
 * article was renamed from is changed on that path, and says so. Focus never falls to the page:
 * closing the field returns it to "Add tag", removing a tag moves it to the next one.
 */
export function TagEditor({ owner, repo, article }: TagEditorProps) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const statusId = `${inputId}-status`;
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | undefined>();
  /** The tag last removed by hand, to say so when the import keeps giving it. */
  const [removed, setRemoved] = useState<string | undefined>();
  const addButton = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const removeButtons = useRef(new Map<string, HTMLButtonElement>());
  const focusAfterRender = useFocusAfterRender();
  const save = useMutation({
    mutationFn: ({ path, tags }: { path: string; tags: string[] }) =>
      setManualTags(owner, repo, path, tags),
    // Wait for the reload, so the change shows the moment the controls come back.
    onSuccess: () => refreshTags(queryClient, owner, repo),
  });
  const groups = tagGroups(article);
  const busy = save.isPending;
  const error = problem ?? (save.isError ? explain(save.error) : undefined);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setRemoved(undefined);
    const added = addTag(article, text);
    setProblem(added.ok ? undefined : REASONS[added.reason]);
    if (added.ok) {
      const before = added.tags.slice(0, -1);
      save.mutate(
        { path: article.path, tags: added.tags },
        {
          onSuccess: (saved) => {
            setText("");
            // The server made the tag; a spelling of one the path had adds nothing.
            if (saved && addedNothing(before, saved.tags)) setProblem(REASONS.duplicate);
          },
        },
      );
    }
  }

  function remove(tag: ManualTag, index: number) {
    if (busy) return;
    setProblem(undefined);
    setRemoved(undefined);
    // Focus goes to the chip that takes this one's place, else the one before, else "Add tag".
    const neighbour = groups.manual[index + 1] ?? groups.manual[index - 1];
    const next = neighbour ? removeButtons.current.get(keyOf(neighbour)) : undefined;
    save.mutate(
      { path: tag.path, tags: withoutTag(article.manual_tags, tag) },
      {
        onSuccess: () => {
          setRemoved(tag.tag);
          focusAfterRender(() => next ?? addButton.current ?? field.current);
        },
      },
    );
  }

  function close() {
    setAdding(false);
    setText("");
    setProblem(undefined);
    save.reset();
    focusAfterRender(() => addButton.current);
  }

  return (
    <section aria-label="Tags" className="mt-3">
      <dl className="m-0 space-y-1.5">
        {groups.frontMatter.length > 0 && (
          <Group label="Front matter">
            <Plain tags={groups.frontMatter} label="Tags from front matter" />
          </Group>
        )}
        {groups.rules.length > 0 && (
          <Group label="Path rules">
            <Plain tags={groups.rules} label="Tags from path rules" />
          </Group>
        )}
        {groups.imported.length > 0 && (
          <Group label="Imported">
            <Plain tags={groups.imported} label="Tags from front matter or path rules" />
            <p className="mt-0.5 text-xs text-muted-foreground">
              This version was imported before ExactDocs kept which is which. Importing it again, or
              changing a tag rule, tells them apart.
            </p>
          </Group>
        )}
        <Group label="By hand">
          <ul aria-label="Tags added by hand" className="flex flex-wrap items-center gap-1.5">
            {groups.manual.map((m, index) => (
              <ManualChip
                key={keyOf(m)}
                tag={m}
                inherited={m.path !== article.path}
                busy={busy}
                buttonRef={(button) => {
                  if (button) removeButtons.current.set(keyOf(m), button);
                  else removeButtons.current.delete(keyOf(m));
                }}
                onRemove={() => remove(m, index)}
              />
            ))}
            {!adding && (
              <li>
                <button
                  ref={addButton}
                  type="button"
                  onClick={() => {
                    setAdding(true);
                    setRemoved(undefined);
                  }}
                  className={quiet}
                >
                  <Plus aria-hidden="true" className="size-3.5" />
                  Add tag
                </button>
              </li>
            )}
          </ul>
        </Group>
      </dl>
      {adding && (
        <AddTagForm
          inputId={inputId}
          statusId={statusId}
          field={field}
          text={text}
          invalid={error !== undefined}
          busy={busy}
          onText={(value) => {
            setText(value);
            setProblem(undefined);
          }}
          onSubmit={submit}
          onClose={close}
        />
      )}
      <Status id={statusId} error={error} notice={keptNotice(article, removed)} />
    </section>
  );
}
