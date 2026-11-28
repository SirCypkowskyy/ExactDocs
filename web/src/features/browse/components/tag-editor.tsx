import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { type FormEvent, type ReactNode, type RefObject, useId, useRef, useState } from "react";
import { toast } from "sonner";
import { HttpError } from "@/shared/lib/http";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { MAX_TAG_LENGTH, MAX_TAGS } from "@/shared/lib/tags";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { cn } from "@/shared/lib/utils";
import { Button, IconButton } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { pill, pillTone } from "@/shared/ui/recipes";
import { refreshTags, setManualTags } from "../api/manual-tags";
import { messages } from "../messages";
import {
  type AddResult,
  addedNothing,
  addTag,
  keptNotice,
  type ManualTag,
  tagGroups,
  tagsSetOn,
  withoutTag,
} from "../model/article-tags";
import type { Article } from "../model/browse";

interface TagEditorProps {
  owner: string;
  repo: string;
  article: Pick<Article, "path" | "tags" | "manual_tags" | "tag_origins">;
}

const small =
  "inline-flex h-11 cursor-pointer items-center gap-1 rounded-full px-3 text-small font-medium outline-none transition-[background-color,color,scale] duration-(--dur-fast) focus-visible:ring-2 focus-visible:ring-ring motion-safe:active:scale-[0.97] disabled:cursor-progress disabled:opacity-60 lg:h-6 lg:px-2.5";
/** One manual tag's identity: the same tag can be set on this path and on an older one. */
const keyOf = (m: ManualTag) => `${m.path}\u0000${m.tag}`;
const quiet = `${small} border border-dashed border-input text-muted-foreground can-hover:hover:bg-accent can-hover:hover:text-foreground`;

type Texts = (typeof messages)["en"]["tags"];
type Reason = Extract<AddResult, { ok: false }>["reason"];

/** Why a typed tag was refused, in words. */
function reasonText(reason: Reason, t: Texts): string {
  if (reason === "invalid") return t.invalid(MAX_TAG_LENGTH);
  if (reason === "duplicate") return t.duplicate;
  return t.tooMany(MAX_TAGS);
}

function explain(error: unknown, t: Texts): string {
  if (error instanceof HttpError && error.status === 422) {
    return error.code === "invalid_tags" ? reasonText("invalid", t) : error.message;
  }
  if (error instanceof HttpError && error.status === 401) return t.signIn;
  if (error instanceof HttpError && error.status === 404) return t.gone;
  return t.saveFailed;
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <dt className="text-small text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0">{children}</dd>
    </div>
  );
}

function Plain({ tags, label }: { tags: readonly string[]; label: string }) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-1.5">
      {tags.map((t) => (
        <li key={t} className={cn(pill, "h-6", pillTone.neutral, "text-foreground")}>
          {t}
        </li>
      ))}
    </ul>
  );
}

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
  const t = useMessages(messages).tags;
  return (
    <li className="row-in inline-flex items-center gap-0.5 rounded-full bg-route-soft pl-2.5 text-small font-medium">
      <span>{tag.tag}</span>
      {inherited && (
        <span className="ml-1 font-normal text-muted-foreground [overflow-wrap:anywhere]">
          {t.setOn(<span className="font-mono">{tag.path}</span>)}
        </span>
      )}
      <IconButton
        ref={buttonRef}
        label={inherited ? t.removeTagSetOn(tag.tag, tag.path) : t.removeTag(tag.tag)}
        size="icon-sm"
        motion="turn"
        // Not `disabled`: that would drop the focus while the change is saved.
        aria-disabled={busy || undefined}
        onClick={onRemove}
        className="rounded-full text-muted-foreground hover:bg-background/70 fine:size-6 [&_svg]:size-3.5"
      >
        <X aria-hidden="true" />
      </IconButton>
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
  const t = useMessages(messages).tags;
  const c = useMessages(common);
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
        {t.newTag}
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
        className="h-11 min-w-0 flex-1 text-body lg:h-8"
      />
      <Button type="submit" size="sm" pending={busy}>
        {!busy && <Plus aria-hidden="true" data-icon-motion="turn" />}
        {t.add}
      </Button>
      <button type="button" onClick={onClose} className={quiet}>
        <X aria-hidden="true" data-icon-motion="turn" className="size-3.5" />
        {c.cancel}
      </button>
      <p id={hintId} className="w-full text-small text-muted-foreground">
        {t.hint}
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
  const tone = error
    ? "mt-1.5 text-small text-destructive"
    : "mt-1.5 text-small text-muted-foreground";
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
  const t = useMessages(messages).tags;
  const c = useMessages(common);
  const language = useLanguage();
  const queryClient = useQueryClient();
  const inputId = useId();
  const statusId = `${inputId}-status`;
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<Reason | undefined>();
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
    // The line under the tags says the same; a refused value has nothing to retry, a lost
    // connection does.
    onError: (failure, variables) =>
      toast.error(explain(failure, t), {
        ...(!(failure instanceof HttpError && failure.status < 500) && {
          action: { label: c.retry, onClick: () => save.mutate(variables) },
        }),
      }),
  });
  const groups = tagGroups(article);
  const busy = save.isPending;
  const error =
    problem !== undefined
      ? reasonText(problem, t)
      : save.isError
        ? explain(save.error, t)
        : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setRemoved(undefined);
    const added = addTag(article, text);
    setProblem(added.ok ? undefined : added.reason);
    if (added.ok) {
      const before = added.tags.slice(0, -1);
      save.mutate(
        { path: article.path, tags: added.tags },
        {
          onSuccess: (saved) => {
            setText("");
            const addedTag = added.tags.at(-1) ?? "";
            if (!(saved && addedNothing(before, saved.tags)))
              toast.success(t.added, { description: addedTag });
            // The server made the tag; a spelling of one the path had adds nothing.
            if (saved && addedNothing(before, saved.tags)) setProblem("duplicate");
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
          const previous = tagsSetOn(article.manual_tags, tag.path);
          toast.success(t.removed, {
            description: tag.tag,
            action: {
              label: t.undo,
              onClick: () => save.mutate({ path: tag.path, tags: previous }),
            },
          });
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
    <section aria-label={t.region} className="min-w-0">
      <dl className="m-0 flex flex-wrap items-center gap-x-4 gap-y-2">
        {groups.frontMatter.length > 0 && (
          <Group label={t.fromFile}>
            <Plain tags={groups.frontMatter} label={t.fromFrontMatter} />
          </Group>
        )}
        {groups.rules.length > 0 && (
          <Group label={t.fromRules}>
            <Plain tags={groups.rules} label={t.fromRulesList} />
          </Group>
        )}
        {groups.imported.length > 0 && (
          <Group label={t.imported}>
            <Plain tags={groups.imported} label={t.importedList} />
            <p className="mt-1 text-small text-muted-foreground">{t.importedNote}</p>
          </Group>
        )}
        <Group label={t.addedHere}>
          <ul aria-label={t.addedList} className="flex flex-wrap items-center gap-1.5">
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
                  <Plus aria-hidden="true" data-icon-motion="turn" className="size-3.5" />
                  {t.addTag}
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
      <Status id={statusId} error={error} notice={keptNotice(article, removed, language)} />
    </section>
  );
}
