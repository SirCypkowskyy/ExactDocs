import { cn } from "@/shared/lib/utils";
import { toggleTag } from "../model/browse";

interface TagFilterProps {
  /** Every tag seen in this version, most used first. */
  facets: readonly string[];
  selected: readonly string[];
  onChange: (tags: string | undefined) => void;
}

/** Narrows the tree to articles with any of the chosen tags (the server does the filtering). */
export function TagFilter({ facets, selected, onChange }: TagFilterProps) {
  if (facets.length === 0) return null;
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1.5 text-sm font-medium text-muted-foreground">Filter by tag</legend>
      <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:-mx-6 sm:px-6 lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0 lg:pb-0">
        {facets.map((tag) => {
          const on = selected.some((t) => t.toLowerCase() === tag.toLowerCase());
          return (
            <button
              key={tag}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(toggleTag(selected, tag))}
              className={cn(
                "inline-flex h-11 shrink-0 cursor-pointer items-center rounded-md px-3 text-sm outline-none transition-[background-color,color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] lg:h-8 lg:px-2.5",
                on
                  ? "bg-mark/10 font-medium text-foreground ring-1 ring-mark/40"
                  : "bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent",
              )}
            >
              {tag}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
