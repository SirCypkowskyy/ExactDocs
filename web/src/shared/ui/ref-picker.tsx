import { ChevronDown, CircleAlert } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import type { Credential } from "@/shared/lib/credentials";
import { common, useMessages } from "@/shared/lib/i18n";
import {
  decodeChoice,
  encodeChoice,
  filterRefs,
  type RefChoice,
  type RepositoryRefs,
} from "@/shared/lib/refs";
import { useRepositoryRefs } from "@/shared/lib/use-repository-refs";
import { Input } from "./input";
import { messages } from "./messages";
import { select } from "./recipes";
import { Skeleton } from "./skeleton";

const FILTER_FROM = 15;
const selectClass = select;

interface Props {
  url: string;
  /** A private repository's token or key: the list is asked for with it, outside the cache. */
  credential?: Credential | undefined;
  /**
   * Why there is no list to ask for (a private repository and no credential at hand): nothing is
   * requested and this is shown instead, with the box to type a version.
   */
  unlisted?: ReactNode;
  /** The words for a list asked for with `credential` that failed (a refused token, say). */
  explainRefusal?: ((error: unknown) => ReactNode) | undefined;
  choice: RefChoice;
  typed: string;
  error: ReactNode;
  /** Branches and tags to leave out (already imported versions). */
  exclude?: readonly string[] | undefined;
  /** Ask for a choice instead of presetting the default branch (add-a-version forms). */
  explicit?: boolean | undefined;
  onChoice: (choice: RefChoice) => void;
  /** The list could not be loaded: only typing a version is left. */
  onUnavailable: () => void;
  onTyped: (value: string) => void;
}

function Select({
  refs: all,
  choice,
  error,
  exclude,
  explicit,
  onChoice,
}: {
  refs: RepositoryRefs;
  choice: RefChoice;
  error: ReactNode;
  exclude: readonly string[] | undefined;
  explicit: boolean | undefined;
  onChoice: (c: RefChoice) => void;
}) {
  const t = useMessages(messages).refs;
  const [query, setQuery] = useState("");
  const left = new Set(exclude);
  const refs = {
    ...all,
    branches: all.branches.filter((b) => !left.has(b.name)),
    tags: all.tags.filter((t) => !left.has(t.name)),
  };
  const many = refs.branches.length + refs.tags.length > FILTER_FROM;
  const branches = filterRefs(refs.branches, query);
  const tags = filterRefs(refs.tags, query);
  const none = many && query.trim() !== "" && branches.length + tags.length === 0;
  return (
    <>
      {many && (
        <div className="mb-1">
          <label htmlFor="ref-filter" className="sr-only">
            {t.filter}
          </label>
          <Input
            id="ref-filter"
            type="search"
            autoComplete="off"
            placeholder={t.filter}
            value={query}
            onKeyDown={(e) => {
              // Enter here means "apply the filter", never "add the library".
              if (e.key === "Enter") e.preventDefault();
            }}
            onChange={(e) => {
              setQuery(e.target.value);
              const hits = [
                ...filterRefs(refs.branches, e.target.value).map((r) => ({
                  kind: "branch" as const,
                  name: r.name,
                })),
                ...filterRefs(refs.tags, e.target.value).map((r) => ({
                  kind: "tag" as const,
                  name: r.name,
                })),
              ];
              if (e.target.value.trim() && hits.length === 1 && hits[0]) onChoice(hits[0]);
            }}
          />
          <p role="status" className="mt-1 min-h-5 text-body text-muted-foreground tabular-nums">
            {query.trim() &&
              t.matches(branches.length + tags.length, refs.branches.length + refs.tags.length)}
          </p>
        </div>
      )}
      <div className="relative">
        <select
          id="ref"
          value={encodeChoice(choice)}
          aria-invalid={error ? true : undefined}
          aria-describedby={["ref-hint", error && "ref-error"].filter(Boolean).join(" ")}
          onChange={(e) => onChoice(decodeChoice(e.target.value))}
          className={selectClass}
        >
          {explicit ? (
            <option value="none" disabled>
              {t.choose}
            </option>
          ) : (
            <option value="default">{t.defaultBranch(refs.default_branch)}</option>
          )}
          {branches.length > 0 && (
            <optgroup label={t.branches(branches.length)}>
              {branches.map((b) => (
                <option key={b.name} value={`branch:${b.name}`}>
                  {b.name}
                </option>
              ))}
            </optgroup>
          )}
          {tags.length > 0 && (
            <optgroup label={t.tags(tags.length)}>
              {tags.map((t) => (
                <option key={t.name} value={`tag:${t.name}`}>
                  {t.name}
                </option>
              ))}
            </optgroup>
          )}
          {/* The chosen ref stays selectable while a filter hides it. */}
          {(choice.kind === "branch" || choice.kind === "tag") &&
            ![...branches, ...tags].some((r) => r.name === choice.name) && (
              <option value={encodeChoice(choice)}>{choice.name}</option>
            )}
          <option value="other">{t.another}</option>
        </select>
        <ChevronDown
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
        />
      </div>
      {none && <p className="mt-2 text-body text-muted-foreground">{t.noMatch(query.trim())}</p>}
    </>
  );
}

/** No list: why (nothing was asked), or the request failed and may be tried again. */
function Unavailable({
  why,
  fetching,
  onRetry,
}: {
  why: ReactNode;
  fetching: boolean;
  onRetry: () => unknown;
}) {
  const t = useMessages(messages).refs;
  const c = useMessages(common);
  if (why) return <p className="text-body text-muted-foreground">{why}</p>;
  return (
    <p className="text-body text-muted-foreground">
      {t.unavailable}{" "}
      <button
        type="button"
        onClick={() => void onRetry()}
        aria-disabled={fetching}
        className="min-h-11 rounded underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
      >
        {c.retry}
      </button>
    </p>
  );
}

/** Branch and tag picker for the repository that was just checked. */
export function RefPicker({
  url,
  credential,
  unlisted,
  explainRefusal,
  choice,
  typed,
  error,
  exclude,
  explicit,
  onChoice,
  onUnavailable,
  onTyped,
}: Props) {
  const {
    data,
    isPending,
    isError,
    error: listError,
    refetch,
    isFetching,
  } = useRepositoryRefs(url, credential, !unlisted);
  const t = useMessages(messages).refs;
  // Without a list the only way to name a version is to type it, so the typed value must count.
  useEffect(() => {
    if (isError) onUnavailable();
  }, [isError, onUnavailable]);

  const message = error ? (
    <p
      id="ref-error"
      className="fade-in flex items-start gap-1.5 text-body font-medium text-destructive"
    >
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{error}</span>
    </p>
  ) : null;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={data ? "ref" : "ref-typed"} className="text-body font-medium">
        {t.label}
      </label>
      {isPending && <Skeleton className="h-11" />}
      {isPending && (
        <p className="sr-only" role="status">
          {t.loading}
        </p>
      )}
      {isError && (
        <Unavailable
          why={credential ? (listError ? explainRefusal?.(listError) : undefined) : unlisted}
          fetching={isFetching}
          onRetry={refetch}
        />
      )}
      {data && (
        <Select
          refs={data}
          choice={choice}
          error={error}
          exclude={exclude}
          explicit={explicit}
          onChoice={onChoice}
        />
      )}
      {(choice.kind === "other" || isError) && (
        <Input
          id="ref-typed"
          value={typed}
          autoComplete="off"
          spellCheck={false}
          placeholder={t.typedPlaceholder}
          aria-label={t.typedLabel}
          aria-invalid={error ? true : undefined}
          aria-describedby={["ref-hint", error && "ref-error"].filter(Boolean).join(" ")}
          onChange={(e) => onTyped(e.target.value)}
          className="mt-1 font-mono"
        />
      )}
      <p
        id="ref-hint"
        className={
          data?.truncated
            ? "flex items-start gap-1.5 text-body text-foreground"
            : "text-body text-muted-foreground"
        }
      >
        {data?.truncated ? (
          <>
            <CircleAlert
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-muted-foreground"
            />
            <span>{t.truncated}</span>
          </>
        ) : (
          t.pinned
        )}
      </p>
      {message}
    </div>
  );
}
