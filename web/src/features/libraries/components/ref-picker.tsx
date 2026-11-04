import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { Input } from "@/shared/ui/input";
import { repositoryRefsQueryOptions } from "../api/add-library";
import {
  decodeChoice,
  encodeChoice,
  filterRefs,
  type RefChoice,
  type RepositoryRefs,
} from "../model/add-library";

const FILTER_FROM = 15;
const selectClass =
  "h-11 w-full cursor-pointer appearance-none rounded-md border border-input bg-secondary pr-10 pl-3 text-base outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 aria-invalid:border-destructive";

interface Props {
  url: string;
  choice: RefChoice;
  typed: string;
  error: string | undefined;
  onChoice: (choice: RefChoice) => void;
  onTyped: (value: string) => void;
}

function Select({
  refs,
  choice,
  error,
  onChoice,
}: {
  refs: RepositoryRefs;
  choice: RefChoice;
  error: string | undefined;
  onChoice: (c: RefChoice) => void;
}) {
  const [query, setQuery] = useState("");
  const many = refs.branches.length + refs.tags.length > FILTER_FROM;
  const branches = filterRefs(refs.branches, query);
  const tags = filterRefs(refs.tags, query);
  const none = many && query.trim() !== "" && branches.length + tags.length === 0;
  return (
    <>
      {many && (
        <div className="mb-2">
          <label htmlFor="ref-filter" className="sr-only">
            Filter branches and tags
          </label>
          <Input
            id="ref-filter"
            type="search"
            autoComplete="off"
            placeholder="Filter branches and tags"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
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
          <option value="default">
            Default branch{refs.default_branch ? ` (${refs.default_branch})` : ""}
          </option>
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
export function RefPicker({ url, choice, typed, error, onChoice, onTyped }: Props) {
  const { data, isPending, isError, refetch, isFetching } = useQuery(
    repositoryRefsQueryOptions(url),
  );
  const message = error ? (
    <p id="ref-error" className="fade-in text-sm font-medium text-destructive">
      {error}
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
        <>
          <p className="text-sm text-muted-foreground">
            Couldn't load the branches and tags.{" "}
            <button
              type="button"
              onClick={() => void refetch()}
              aria-disabled={isFetching}
              className="min-h-11 rounded underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
            >
              Try again
            </button>
          </p>
          <p className="text-sm text-muted-foreground">
            Or leave this empty to use the default branch.
          </p>
        </>
      )}
      {data && <Select refs={data} choice={choice} error={error} onChoice={onChoice} />}
      {(choice.kind === "other" || isError) && (
        <Input
          id="ref-typed"
          value={typed}
          autoComplete="off"
          spellCheck={false}
          placeholder="v1.4.0, release/2, or a commit SHA"
          aria-invalid={error ? true : undefined}
          aria-describedby={["ref-hint", error && "ref-error"].filter(Boolean).join(" ")}
          onChange={(e) => onTyped(e.target.value)}
          className="mt-1 font-mono text-[15px]"
        />
      )}
      <p id="ref-hint" className="text-sm text-muted-foreground">
        {data?.truncated
          ? "This repository has more than 1000 branches or tags, so only the first 1000 of each are listed. Pick “Another ref or commit…” for the rest."
          : "The import is pinned to this commit, so the docs stay exact."}
      </p>
      {message}
    </div>
  );
}
