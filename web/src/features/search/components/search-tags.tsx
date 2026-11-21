import { useQuery } from "@tanstack/react-query";
import { tagsQueryOptions } from "@/shared/lib/tags-query";
import { cn } from "@/shared/lib/utils";
import { TagChips } from "@/shared/ui/tag-chips";
import type { SearchContext } from "../model/context";
import type { TagMatch } from "../model/search";

interface SearchTagsProps {
  ctx: SearchContext;
  onTags: (tags: string | undefined) => void;
  onMatch: (match: TagMatch) => void;
  tagCount: number;
}

const mode =
  "h-11 cursor-pointer px-3 text-small font-medium outline-none transition-colors duration-(--dur-fast) focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring lg:h-7";

/** The tag filter of a search: the shared chips plus "Match any / Match all" once two tags are chosen. */
export function SearchTags({ ctx, onTags, onMatch, tagCount }: SearchTagsProps) {
  const counted = useQuery(tagsQueryOptions(ctx));
  return (
    <TagChips
      facets={counted.data?.tags ?? []}
      value={ctx.tags}
      loading={counted.isPending}
      truncated={counted.data?.truncated ?? false}
      onChange={onTags}
      fixedRow
      trailing={
        tagCount > 1 && (
          <fieldset className="flex min-w-0 overflow-hidden rounded-md ring-1 ring-inset ring-border">
            <legend className="sr-only">Tags must match</legend>
            {(["any", "all"] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={ctx.match === m}
                onClick={() => onMatch(m)}
                className={cn(
                  mode,
                  ctx.match === m
                    ? "bg-route text-primary-foreground"
                    : "bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent",
                )}
              >
                {m === "any" ? "Match any" : "Match all"}
              </button>
            ))}
          </fieldset>
        )
      }
    />
  );
}
