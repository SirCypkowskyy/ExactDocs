import type { ReactNode } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Skeleton } from "@/shared/ui/skeleton";
import { parseTags, sameTag, toggleTag, visibleTags } from "../lib/tags";
import { messages } from "./messages";

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
  const t = useMessages(messages).tags;
  const selected = parseTags(value);
  const counts = new Map(facets.map((f) => [f.tag.toLowerCase(), f.count]));
  const shown = visibleTags(
    selected,
    facets.map((f) => f.tag),
  );
  if (!loading && shown.length === 0) return null;
  return (
    <fieldset className="min-w-0">
      <legend className="sr-only">{t.filter}</legend>
      <div
        className={cn(
          "mb-1.5 flex items-center justify-between gap-2 text-body font-medium text-muted-foreground",
          fixedRow && "h-11 lg:h-7",
          // On a phone the chips explain themselves; the label row only stays for what trails it.
          !(fixedRow || trailing) && "max-lg:hidden",
        )}
      >
        <span aria-hidden="true">{t.filter}</span>
        {trailing}
      </div>
      {/* Padding inside the scroller keeps the focus and pressed rings from being clipped. */}
      <div className="-mx-4 -my-0.5 flex gap-1.5 overflow-x-auto px-4 py-0.5 sm:-mx-6 sm:px-6 lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0">
        {loading
          ? SKELETON.map((w) => <Skeleton key={w} className={`h-11 shrink-0 lg:h-8 ${w}`} />)
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
                    "inline-flex h-11 shrink-0 cursor-pointer items-center gap-1.5 rounded-md px-3 text-body outline-none transition-[background-color,transform] duration-(--dur-fast) focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:scale-[0.97] lg:h-8 lg:px-2.5",
                    on
                      ? "bg-route text-route-foreground"
                      : "bg-secondary text-secondary-foreground can-hover:hover:bg-accent",
                  )}
                >
                  {tag}
                  {count !== undefined && (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "text-small tabular-nums",
                        on ? "text-route-foreground/75" : "text-muted-foreground",
                      )}
                    >
                      {t.count(count)}
                    </span>
                  )}
                </button>
              );
            })}
      </div>
      {truncated && <p className="mt-1.5 text-small text-muted-foreground">{t.truncated}</p>}
    </fieldset>
  );
}
