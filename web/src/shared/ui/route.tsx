import { Fragment, type ReactNode } from "react";
import { cn } from "@/shared/lib/utils";

/*
 * The signature of the UI (DESIGN.md, "The route"): every library is a line with its own colour,
 * every version a station on it. A library's bullet, a version's station and the route between
 * them say where a piece of text comes from, the way a wayfinding sign does.
 */

const LINES = 8;
const LINE_BG = [
  "bg-line-1",
  "bg-line-2",
  "bg-line-3",
  "bg-line-4",
  "bg-line-5",
  "bg-line-6",
  "bg-line-7",
  "bg-line-8",
] as const;

/** The same library always gets the same line colour (a stable hash of its ID). */
export function lineIndex(libraryId: string): number {
  let h = 2166136261;
  for (let i = 0; i < libraryId.length; i++) {
    h ^= libraryId.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) % LINES;
}

/** Two letters for a bullet: the repository's initials ("docs-repo" → "DR", "payments" → "PA"). */
export function monogram(libraryId: string): string {
  const repo = libraryId.split("/").filter(Boolean).at(-1) ?? libraryId;
  const words = repo.split(/[-_.\s]+/).filter(Boolean);
  const letters =
    words.length > 1 ? `${words[0]?.[0] ?? ""}${words[1]?.[0] ?? ""}` : repo.slice(0, 2);
  return letters.toUpperCase();
}

/** A library's round bullet in its line colour. Decorative: the library's name is always beside it. */
export function LibraryBullet({
  id,
  size = "md",
  className,
}: {
  id: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex flex-none items-center justify-center rounded-full font-semibold tracking-tight text-white select-none dark:text-white",
        LINE_BG[lineIndex(id)],
        size === "sm" && "size-5 text-[9px]",
        size === "md" && "size-7 text-[11px]",
        size === "lg" && "size-9 text-[13px]",
        className,
      )}
    >
      {monogram(id)}
    </span>
  );
}

/** A version as a station: a ring on the line, and its ref in monospace. */
export function VersionStation({
  version,
  isDefault = false,
  className,
}: {
  version: string;
  isDefault?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", className)}>
      <span
        aria-hidden="true"
        className={cn(
          "size-2.5 flex-none rounded-full border-2 border-route bg-background",
          // The default version is the interchange: a filled ring.
          isDefault && "bg-route",
        )}
      />
      <span className="truncate font-mono text-[13px] font-medium">{version}</span>
    </span>
  );
}

/** The short commit, the product's trust anchor: always monospace, always 7 characters. */
export function Commit({ sha, className }: { sha: string; className?: string }) {
  return (
    <span className={cn("font-mono text-[12px] text-muted-foreground", className)} title={sha}>
      {sha.slice(0, 7)}
    </span>
  );
}

/**
 * The route strip: library bullet, then each stop (version, path…) joined by a short rule that
 * draws in when the stop changes. `stops` are rendered in order; pass a key on the strip's parent
 * (or let React re-mount a stop) to replay the draw.
 */
export function RouteStrip({
  libraryId,
  label,
  stops,
  className,
}: {
  libraryId: string;
  /** What the bullet stands for, in words (the library's ID or title). */
  label: ReactNode;
  stops: { key: string; node: ReactNode }[];
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1", className)}>
      <span className="inline-flex min-w-0 items-center gap-2">
        <LibraryBullet id={libraryId} size="sm" />
        <span className="min-w-0 truncate text-body font-medium">{label}</span>
      </span>
      {stops.map((stop) => (
        <Fragment key={stop.key}>
          <span
            aria-hidden="true"
            className="route-draw h-0.5 w-4 flex-none rounded-full bg-route/60"
          />
          <span className="inline-flex min-w-0 items-center">{stop.node}</span>
        </Fragment>
      ))}
    </div>
  );
}
