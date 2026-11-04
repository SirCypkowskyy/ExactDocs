import { useQuery } from "@tanstack/react-query";
import { cn } from "@/shared/lib/utils";
import { searchTagsQueryOptions } from "../api/search-queries";
import type { SearchContext } from "../model/context";
import { parseTags, type TagMatch } from "../model/search";

interface TagChipsProps {
  ctx: SearchContext;
  onTags: (tags: string | undefined) => void;
  onMatch: (match: TagMatch) => void;
}

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
const SHOWN = 14;

const modeButton =
  "h-9 cursor-pointer px-3 text-xs font-medium outline-none transition-colors duration-150 focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring lg:h-7";

/** Tag chips for the search plus the any/all switch. Selected tags always show, so they can be undone. */
export function TagChips({ ctx, onTags, onMatch }: TagChipsProps) {
  const counted = useQuery(searchTagsQueryOptions(ctx));
  const selected = parseTags(ctx.tags);
  const facets = counted.data?.tags.map((t) => t.tag) ?? [];
  const shown = [...selected, ...facets.filter((f) => !selected.some((s) => same(s, f)))].slice(
    0,
    Math.max(SHOWN, selected.length),
  );
  if (!counted.isPending && shown.length === 0) return null;

  const toggle = (tag: string) => {
    const next = selected.some((s) => same(s, tag))
      ? selected.filter((s) => !same(s, tag))
      : [...selected, tag];
    onTags(next.length ? next.join(",") : undefined);
  };

  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex min-h-9 lg:min-h-7 items-center justify-between gap-2 text-sm font-medium text-muted-foreground">
        <span id="search-tags-label">Filter by tag</span>
        {selected.length > 1 && (
          // A segmented switch: "any" widens the search, "all" narrows it.
          <fieldset className="flex min-w-0 overflow-hidden rounded-md ring-1 ring-inset ring-border">
            <legend className="sr-only">Match</legend>
            {(["any", "all"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={ctx.match === mode}
                onClick={() => onMatch(mode)}
                className={cn(
                  modeButton,
                  ctx.match === mode
                    ? "bg-mark/[0.16] text-foreground"
                    : "bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent",
                )}
              >
                {mode === "any" ? "Any of" : "All of"}
              </button>
            ))}
          </fieldset>
        )}
      </div>
      <div className="-mx-4 -my-0.5 flex gap-1.5 overflow-x-auto px-4 py-0.5 sm:-mx-6 sm:px-6 lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0">
        {counted.isPending
          ? ["w-14", "w-10", "w-16"].map((w) => (
              <span
                key={w}
                aria-hidden="true"
                className={`h-11 shrink-0 rounded-md bg-muted-foreground/[0.14] motion-safe:animate-pulse lg:h-8 ${w}`}
              />
            ))
          : shown.map((tag) => {
              const on = selected.some((s) => same(s, tag));
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(tag)}
                  className={cn(
                    "inline-flex h-11 shrink-0 cursor-pointer items-center rounded-md px-3 text-sm outline-none transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] lg:h-8 lg:px-2.5",
                    on
                      ? "bg-mark/[0.16] ring-1 ring-mark/40"
                      : "bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent",
                  )}
                >
                  {tag}
                </button>
              );
            })}
      </div>
    </div>
  );
}
