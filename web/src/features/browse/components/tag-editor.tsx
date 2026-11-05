import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { MAX_TAGS } from "@/shared/lib/tags";
import { Input } from "@/shared/ui/input";
import { refreshTags, setManualTags } from "../api/manual-tags";
import {
  type AddResult,
  addTag,
  type ManualTag,
  tagGroups,
  withoutTag,
} from "../model/article-tags";
import type { Article } from "../model/browse";

interface TagEditorProps {
  owner: string;
  repo: string;
  article: Pick<Article, "path" | "tags" | "manual_tags" | "front_matter">;
}

const small =
  "inline-flex h-11 cursor-pointer items-center gap-1 rounded-md px-3 text-[13px] font-medium outline-none transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] disabled:cursor-progress disabled:opacity-60 lg:h-7 lg:px-2";
const quiet = `${small} bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent`;

const REASONS: Record<Extract<AddResult, { ok: false }>["reason"], string> = {
  invalid: "A tag starts with a letter or digit and goes on with letters, digits and . _ + -.",
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

/**
 * The article's tags by origin (front matter, path rules, by hand), and the editor of the manual
 * ones (TAG-01). A manual tag holds for every version of the library; one set on an older path the
 * article was renamed from is changed on that path, and says so.
 */
export function TagEditor({ owner, repo, article }: TagEditorProps) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | undefined>();
  const save = useMutation({
    mutationFn: ({ path, tags }: { path: string; tags: string[] }) =>
      setManualTags(owner, repo, path, tags),
    // Wait for the reload, so the change shows the moment the controls come back.
    onSuccess: () => refreshTags(queryClient),
  });
  const groups = tagGroups(article);
  const busy = save.isPending;
  const message = problem ?? (save.isError ? explain(save.error) : undefined);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const added = addTag(article.manual_tags, article.path, text);
    if (!added.ok) {
      setProblem(REASONS[added.reason]);
      return;
    }
    setProblem(undefined);
    save.mutate({ path: article.path, tags: added.tags }, { onSuccess: () => setText("") });
  }

  function remove(tag: ManualTag) {
    setProblem(undefined);
    save.mutate({ path: tag.path, tags: withoutTag(article.manual_tags, tag) });
  }

  function close() {
    setAdding(false);
    setText("");
    setProblem(undefined);
    save.reset();
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
        <Group label="By hand">
          <ul aria-label="Tags added by hand" className="flex flex-wrap items-center gap-1.5">
            {groups.manual.map((m) => {
              const inherited = m.path !== article.path;
              return (
                <li
                  key={`${m.path}\u0000${m.tag}`}
                  className="inline-flex items-center gap-0.5 rounded-md bg-secondary pl-2.5 text-[13px] lg:pl-2"
                >
                  <span>{m.tag}</span>
                  {inherited && (
                    <span className="ml-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">
                      set on <span className="font-mono">{m.path}</span>
                    </span>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => remove(m)}
                    aria-label={
                      inherited ? `Remove tag ${m.tag}, set on ${m.path}` : `Remove tag ${m.tag}`
                    }
                    title={inherited ? `Removes it from ${m.path} in every version` : undefined}
                    className="inline-flex size-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-progress disabled:opacity-60 lg:size-7 [@media(hover:hover)]:hover:text-foreground"
                  >
                    <X aria-hidden="true" className="size-3.5" />
                  </button>
                </li>
              );
            })}
            {!adding && (
              <li>
                <button type="button" onClick={() => setAdding(true)} className={quiet}>
                  <Plus aria-hidden="true" className="size-3.5" />
                  Add tag
                </button>
              </li>
            )}
          </ul>
        </Group>
      </dl>
      {adding && (
        <form
          onSubmit={submit}
          onKeyDown={(e) => {
            if (e.key === "Escape") close();
          }}
          className="mt-2 flex max-w-md flex-wrap items-center gap-2"
        >
          <label htmlFor={inputId} className="sr-only">
            New tag
          </label>
          <Input
            id={inputId}
            // biome-ignore lint/a11y/noAutofocus: the field opens because the user asked for it
            autoFocus
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setProblem(undefined);
            }}
            placeholder="onboarding"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={message ? true : undefined}
            aria-describedby={`${inputId}-hint`}
            className="h-11 min-w-0 flex-1 text-sm lg:h-8"
          />
          <button
            type="submit"
            disabled={busy}
            className={`${small} bg-primary text-primary-foreground hover:bg-primary/90`}
          >
            {busy ? "Saving…" : "Add"}
          </button>
          <button type="button" onClick={close} className={quiet}>
            Cancel
          </button>
          <p id={`${inputId}-hint`} className="w-full text-xs text-muted-foreground">
            For this path in every version of the library, and where it was renamed to later.
          </p>
        </form>
      )}
      <p role="status" className={message ? "mt-1.5 text-xs text-destructive" : "sr-only"}>
        {message ?? ""}
      </p>
    </section>
  );
}
