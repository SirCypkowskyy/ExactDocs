import type { ReactNode } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Skeleton } from "@/shared/ui/skeleton";
import { parseTags, sameTag, toggleTag, visibleTags } from "../lib/tags";
import { messages } from "./messages";
import { Tag } from "./tags";

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
 * The tag filter: one toggle `Tag` per tag, selected ones first so a filter can always be undone.
 * The selected state is a solid fill (not a tint), so it reads at a glance and without colour.
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
          ? SKELETON.map((w) => (
              <Skeleton key={w} className={`h-11 shrink-0 rounded-full fine:h-8 ${w}`} />
            ))
          : shown.map((tag) => {
              const on = selected.some((t) => sameTag(t, tag));
              const count = counts.get(tag.toLowerCase());
              return (
                <Tag key={tag} pressed={on} onClick={() => onChange(toggleTag(selected, tag))}>
                  {tag}
                  {count !== undefined && (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "font-normal tabular-nums",
                        on ? "text-route-foreground/75" : "text-muted-foreground",
                      )}
                    >
                      {t.count(count)}
                    </span>
                  )}
                </Tag>
              );
            })}
      </div>
      {truncated && <p className="mt-1.5 text-small text-muted-foreground">{t.truncated}</p>}
    </fieldset>
  );
}
