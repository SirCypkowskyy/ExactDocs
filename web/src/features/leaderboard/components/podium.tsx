import { Link } from "@tanstack/react-router";
import { formatNumber, useLanguage, useMessages } from "@/shared/lib/i18n";
import { reducedMotion } from "@/shared/lib/preferences";
import { cn } from "@/shared/lib/utils";
import { Avatar } from "@/shared/ui/avatar";
import { LibraryMark } from "@/shared/ui/library-mark";
import { Skeleton } from "@/shared/ui/skeleton";
import { leaderboardMessages } from "../messages";
import {
  type Entry,
  fillOf,
  keyOf,
  type Metric,
  movementOf,
  nameOf,
  type Subject,
  TOP,
} from "../model/leaderboard";
import { MovementMark } from "./movement";
import { movementWords } from "./movement-words";

/*
 * The top ten as upright columns that rise from the bottom (after the free shadcnblocks
 * leaderboard1 (`leaderboard1`), its bars turned upright; blocks-map §5.3). Each column is a
 * full-height track whose fill is scaled with `transform: scaleY(value / top)` from its bottom
 * edge. Columns are keyed by library or account, so a switch of period grows or shrinks each fill
 * from where it is, staggered 30 ms from left to right; a newcomer fades in and grows from 0.
 * Only transform and opacity move, and nothing travels under reduced motion. The `<ol>` carries
 * the meaning ("3. alice, 128 reads"); the bars are decoration over it.
 */

const STAGGER_MS = 30;

/** First show: grow the fill from 0 to its height (the Web Animations API, transform only). */
function growIn(fill: HTMLSpanElement | null) {
  if (!fill || typeof fill.animate !== "function" || reducedMotion()) return;
  const tokens = getComputedStyle(fill);
  const duration = Number.parseFloat(tokens.getPropertyValue("--dur-slow")) || 240;
  const easing = tokens.getPropertyValue("--ease-out").trim() || "ease-out";
  const index = Number(fill.style.getPropertyValue("--i")) || 0;
  fill.animate([{ transform: "scaleY(0)", offset: 0 }], {
    duration,
    easing,
    delay: index * STAGGER_MS,
    fill: "backwards",
  });
}

function Column({
  entry,
  index,
  top,
  subject,
  metric,
}: {
  entry: Entry;
  index: number;
  top: number;
  subject: Subject;
  metric: Metric;
}) {
  const t = useMessages(leaderboardMessages);
  const language = useLanguage();
  const name = nameOf(entry);
  const value = t.value[metric](entry.value);
  const movement = movementOf(entry);
  const sentence = `${t.item(entry.rank, name, value)}${entry.you ? t.youSuffix : ""}, ${movementWords(t, movement)}`;
  const [, owner = "", repo = ""] = name.split("/");
  const label = (
    <>
      <span className="sr-only">{sentence}</span>
      <span aria-hidden="true" className="block truncate">
        {subject === "libraries" ? name.replace(/^\//, "") : name}
      </span>
    </>
  );
  return (
    <li className="fade-in flex min-w-0 flex-col items-stretch gap-1.5">
      <span aria-hidden="true" className="num text-center text-small font-medium">
        {formatNumber(entry.value, language)}
      </span>
      <span
        aria-hidden="true"
        className="relative h-40 overflow-hidden rounded-t-md bg-secondary sm:h-52"
      >
        <span
          ref={growIn}
          data-slot="leaderboard-fill"
          className={cn(
            "absolute inset-0 origin-bottom rounded-t-md transition-transform duration-(--dur-slow) ease-(--ease-out) motion-reduce:transition-none",
            entry.you ? "bg-chart-highlight" : "bg-chart-series",
          )}
          style={
            {
              "--i": index,
              transform: `scaleY(${fillOf(entry.value, top)})`,
              transitionDelay: `${index * STAGGER_MS}ms`,
            } as React.CSSProperties
          }
        />
      </span>
      <span aria-hidden="true" className="flex items-center justify-center gap-1 text-small">
        <span className="num font-semibold">#{entry.rank}</span>
        <MovementMark movement={movement} />
      </span>
      <span className="flex min-w-0 flex-col items-center gap-1 text-center text-small">
        {subject === "libraries" ? <LibraryMark id={name} size="sm" /> : <Avatar name={name} />}
        {subject === "libraries" && owner && repo ? (
          <Link
            to="/libraries/$owner/$repo"
            params={{ owner, repo }}
            className="inline-flex min-h-11 w-full min-w-0 items-start justify-center rounded-sm font-mono underline-offset-4 outline-none fine:min-h-0 focus-visible:ring-2 focus-visible:ring-ring can-hover:hover:underline"
          >
            {label}
          </Link>
        ) : (
          <span className="w-full min-w-0">{label}</span>
        )}
        {entry.you && (
          <span
            aria-hidden="true"
            className="rounded-full bg-route-soft px-1.5 text-small font-medium text-foreground"
          >
            {t.you}
          </span>
        )}
      </span>
    </li>
  );
}

const columns = "grid min-w-[36rem] grid-cols-10 items-end gap-2 sm:gap-3";

/** The ten columns' frame while the board loads. */
export function PodiumSkeleton() {
  return (
    <div className="relative overflow-x-auto pb-1">
      <div className={columns}>
        {Array.from({ length: TOP }, (_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed placeholders
          <div key={i} className="flex flex-col items-stretch gap-1.5">
            <Skeleton className="mx-auto h-4 w-8" />
            <Skeleton className="h-40 rounded-b-none sm:h-52" />
            <Skeleton className="mx-auto h-4 w-6" />
            <Skeleton className="mx-auto size-6" />
            <Skeleton className="mx-auto h-4 w-12" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function Podium({
  entries,
  subject,
  metric,
}: {
  entries: readonly Entry[];
  subject: Subject;
  metric: Metric;
}) {
  const t = useMessages(leaderboardMessages);
  const top = entries[0]?.value ?? 0;
  return (
    <div className="relative overflow-x-auto pb-1">
      <ol aria-label={t.top} className={columns}>
        {entries.slice(0, TOP).map((entry, i) => (
          <Column
            key={keyOf(entry)}
            entry={entry}
            index={i}
            top={top}
            subject={subject}
            metric={metric}
          />
        ))}
      </ol>
    </div>
  );
}
