import type { ReactNode } from "react";
import { cn } from "@/shared/lib/utils";
import { parseTags, sameTag, toggleTag, visibleTags } from "../lib/tags";

interface TagChipsProps {
  /** The version's tags with article counts, most used first. */
  facets: readonly { tag: string; count: number }[];
  /** The `tags` URL param. */
  value: string | undefined;
  loading: boolean;
  /** The version has more tags than are offered. */
  truncated: boolean;
  onChange: (tags: string | undefined) => void;
  /** Controls that sit at the end of the label row (the search's any/all switch). */
  trailing?: ReactNode;
  /** Keep the label row one fixed height, so `trailing` appearing never moves the chips. */
  fixedRow?: boolean;
}

const SKELETON = ["w-14", "w-10", "w-16"];

/**
 * The tag filter: one chip per tag, selected ones first so a filter can always be undone. The
 * selected state is a solid fill (not a tint), so it reads at a glance and without colour.
 */
export function TagChips({
  facets,
  value,
  loading,
  truncated,
  onChange,
  trailing,
  fixedRow = false,
}: TagChipsProps) {
  const selected = parseTags(value);
  const counts = new Map(facets.map((f) => [f.tag.toLowerCase(), f.count]));
  const shown = visibleTags(
    selected,
    facets.map((f) => f.tag),
  );
  if (!loading && shown.length === 0) return null;
  return (
    <fieldset className="min-w-0">
      <legend className="sr-only">Filter by tag</legend>
      <div
        className={cn(
          "mb-1.5 flex items-center justify-between gap-2 text-sm font-medium text-muted-foreground",
          fixedRow && "h-11 lg:h-7",
        )}
      >
        <span aria-hidden="true">Filter by tag</span>
        {trailing}
      </div>
      {/* Padding inside the scroller keeps the focus and pressed rings from being clipped. */}
      <div className="-mx-4 -my-0.5 flex gap-1.5 overflow-x-auto px-4 py-0.5 sm:-mx-6 sm:px-6 lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0">
        {loading
          ? SKELETON.map((w) => (
              <span
                key={w}
                aria-hidden="true"
                className={`h-11 shrink-0 rounded-md bg-muted-foreground/[0.14] motion-safe:animate-pulse lg:h-8 ${w}`}
              />
            ))
          : shown.map((tag) => {
              const on = selected.some((t) => sameTag(t, tag));
              const count = counts.get(tag.toLowerCase());
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onChange(toggleTag(selected, tag))}
                  className={cn(
                    "inline-flex h-11 shrink-0 cursor-pointer items-center gap-1.5 rounded-md px-3 text-sm outline-none transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:scale-[0.97] lg:h-8 lg:px-2.5",
                    on
                      ? "bg-route text-primary-foreground"
                      : "bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent",
                  )}
                >
                  {tag}
                  {count !== undefined && (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "text-xs tabular-nums",
                        on ? "text-primary-foreground/75" : "text-muted-foreground",
                      )}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
      </div>
      {truncated && (
        <p className="mt-1.5 text-xs text-muted-foreground">Showing the most used tags only.</p>
      )}
    </fieldset>
  );
}
