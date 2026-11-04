import { cn } from "@/shared/lib/utils";
import { toggleTag } from "../model/browse";

interface TagFilterProps {
  /** The tags to offer, selected ones first. */
  tags: readonly string[];
  selected: readonly string[];
  loading: boolean;
  /** The version has more tags than are offered. */
  truncated: boolean;
  onChange: (tags: string | undefined) => void;
}

/** Narrows the tree to articles with any of the chosen tags (the server does the filtering). */
export function TagFilter({ tags, selected, loading, truncated, onChange }: TagFilterProps) {
  if (!loading && tags.length === 0) return null;
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1.5 text-sm font-medium text-muted-foreground">
        {selected.length > 1 ? "Filter by tag (any of)" : "Filter by tag"}
      </legend>
      {/* Padding inside the scroller keeps the focus and pressed rings from being clipped. */}
      <div className="-mx-4 -my-0.5 flex gap-1.5 overflow-x-auto px-4 py-0.5 sm:-mx-6 sm:px-6 lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0">
        {loading
          ? ["w-14", "w-10", "w-16"].map((w) => (
              <span
                key={w}
                aria-hidden="true"
                className={`h-11 shrink-0 rounded-md bg-muted-foreground/[0.14] motion-safe:animate-pulse lg:h-8 ${w}`}
              />
            ))
          : tags.map((tag) => {
              const on = selected.some((t) => t.toLowerCase() === tag.toLowerCase());
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onChange(toggleTag(selected, tag))}
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
      {truncated && (
        <p className="mt-1.5 text-xs text-muted-foreground">Showing the most used tags only.</p>
      )}
    </fieldset>
  );
}
