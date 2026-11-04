import { useQuery } from "@tanstack/react-query";
import { ChevronDown, CircleAlert } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import {
  decodeChoice,
  encodeChoice,
  filterRefs,
  type RefChoice,
  type RepositoryRefs,
  repositoryRefsQueryOptions,
} from "@/shared/lib/refs";
import { Input } from "./input";

const FILTER_FROM = 15;
const selectClass =
  "h-11 w-full cursor-pointer appearance-none rounded-md border border-input bg-secondary pr-10 pl-3 text-base outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/60 aria-invalid:border-destructive aria-invalid:ring-destructive/25";

interface Props {
  url: string;
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
            Filter branches and tags
          </label>
          <Input
            id="ref-filter"
            type="search"
            autoComplete="off"
            placeholder="Filter branches and tags"
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
          <p role="status" className="mt-1 min-h-5 text-sm text-muted-foreground tabular-nums">
            {query.trim() &&
              `${branches.length + tags.length} of ${refs.branches.length + refs.tags.length} match`}
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
              Choose a branch or tag…
            </option>
          ) : (
            <option value="default">
              Default branch{refs.default_branch ? ` (${refs.default_branch})` : ""}
            </option>
          )}
          {branches.length > 0 && (
            <optgroup label={`Branches (${branches.length})`}>
              {branches.map((b) => (
                <option key={b.name} value={`branch:${b.name}`}>
                  {b.name}
                </option>
              ))}
            </optgroup>
          )}
          {tags.length > 0 && (
            <optgroup label={`Tags (${tags.length})`}>
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
          <option value="other">Another ref or commit…</option>
        </select>
        <ChevronDown
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
        />
      </div>
      {none && (
        <p className="mt-2 text-sm text-muted-foreground">
          Nothing matches “{query.trim()}”. Pick “Another ref or commit…” to type it.
        </p>
      )}
    </>
  );
}

/** Branch and tag picker for the repository that was just checked. */
export function RefPicker({
  url,
  choice,
  typed,
  error,
  exclude,
  explicit,
  onChoice,
  onUnavailable,
  onTyped,
}: Props) {
  const { data, isPending, isError, refetch, isFetching } = useQuery(
    repositoryRefsQueryOptions(url),
  );
  // Without a list the only way to name a version is to type it, so the typed value must count.
  useEffect(() => {
    if (isError) onUnavailable();
  }, [isError, onUnavailable]);
  const message = error ? (
    <p
      id="ref-error"
      className="fade-in flex items-start gap-1.5 text-sm font-medium text-destructive"
    >
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{error}</span>
    </p>
  ) : null;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={data ? "ref" : "ref-typed"} className="text-sm font-medium">
        Version to import
      </label>
      {isPending && (
        <div
          aria-hidden="true"
          className="h-11 rounded-md bg-muted-foreground/10 motion-safe:animate-pulse"
        />
      )}
      {isPending && (
        <p className="sr-only" role="status">
          Loading branches and tags
        </p>
      )}
      {isError && (
        <p className="text-sm text-muted-foreground">
          Couldn't load branches and tags. Type a version below, or leave it empty for the default
          branch.{" "}
          <button
            type="button"
            onClick={() => void refetch()}
            aria-disabled={isFetching}
            className="min-h-11 rounded underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
          >
            Try again
          </button>
        </p>
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
          placeholder="v1.4.0, release/2, or a commit SHA"
          aria-label="Branch, tag or commit"
          aria-invalid={error ? true : undefined}
          aria-describedby={["ref-hint", error && "ref-error"].filter(Boolean).join(" ")}
          onChange={(e) => onTyped(e.target.value)}
          className="mt-1 font-mono text-[15px]"
        />
      )}
      <p
        id="ref-hint"
        className={
          data?.truncated
            ? "flex items-start gap-1.5 text-sm text-foreground"
            : "text-sm text-muted-foreground"
        }
      >
        {data?.truncated ? (
          <>
            <CircleAlert
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-muted-foreground"
            />
            <span>
              Only the first 1000 branches and 1000 tags are listed. Pick “Another ref or commit…”
              for the rest.
            </span>
          </>
        ) : (
          "The version is pinned to the commit it points to today, so the docs stay exact."
        )}
      </p>
      {message}
    </div>
  );
}
