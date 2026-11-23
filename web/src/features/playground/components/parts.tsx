import { Link } from "@tanstack/react-router";
import { CircleAlert, Info, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { LibraryBullet, VersionStation } from "@/shared/ui/route";
import { Skeleton } from "@/shared/ui/skeleton";
import { messages } from "../messages";
import { splitLibrary } from "../model/playground";

/** A line under a heading: an error (alert), or a neutral note about how the answer came about. */
export function Notice({ tone, children }: { tone: "error" | "note"; children: ReactNode }) {
  const error = tone === "error";
  const Icon = error ? CircleAlert : Info;
  return (
    <p
      role={error ? "alert" : undefined}
      className={cn(
        "flex items-start gap-2 rounded-md px-3 py-2.5 text-body",
        error
          ? "bg-destructive-soft font-medium text-destructive-ink"
          : "bg-route-soft text-foreground",
      )}
    >
      <Icon
        aria-hidden="true"
        {...(error && { "data-icon-motion": "alert" })}
        className="mt-0.5 size-4 flex-none"
      />
      <span className="min-w-0">{children}</span>
    </p>
  );
}

/** A results heading with its small muted icon, as a page section's. */
export function ResultsHeading({
  id,
  icon: Icon,
  children,
}: {
  id: string;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <h2 id={id} className="flex items-center gap-2 text-section font-semibold">
      <Icon aria-hidden="true" className="size-4 flex-none text-muted-foreground" />
      {children}
    </h2>
  );
}

/** A result in a ruled list (the rules come from the list, as in search): no card around each. */
export const resultCard = "py-4";
export const resultList = "divide-y divide-rule";

/** The route of a result: library, version, then the article (a link) and its path in mono. */
export function ResultHead({
  library,
  version,
  articlePath,
  anchor,
  headingPath,
}: {
  library: string;
  version: string;
  articlePath: string;
  anchor?: string | null | undefined;
  headingPath: readonly string[];
}) {
  const t = useMessages(messages);
  const { owner, repo } = splitLibrary(library);
  return (
    <>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-body">
        <LibraryBullet id={library} size="sm" />
        <span className="font-medium">{library}</span>
        <span className="sr-only">{t.results.version}</span>
        <VersionStation version={version} />
      </div>
      <Link
        to="/libraries/$owner/$repo"
        params={{ owner, repo }}
        search={{ version, path: articlePath }}
        {...(anchor ? { hash: anchor } : {})}
        className="mt-1.5 block rounded-sm text-body font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        {headingPath.length > 0 ? headingPath.join(" › ") : articlePath}
      </Link>
      <p className="font-mono text-small text-muted-foreground [overflow-wrap:anywhere]">
        {articlePath}
      </p>
    </>
  );
}

const SKELETON_HITS = [
  ["w-32", "w-56", "w-64"],
  ["w-40", "w-48", "w-52"],
  ["w-28", "w-60", "w-44"],
] as const;

/**
 * Results as they will stand, while a mode or the agent is working: the route (bullet, library,
 * version), the article, its path, two lines of text and the ranks; no pulse.
 */
export function ResultsSkeleton() {
  return (
    <ol aria-hidden="true" className={cn(resultList, "pending-in")}>
      {SKELETON_HITS.map(([library, article, path]) => (
        <li key={library} className={cn(resultCard, "flex flex-col gap-2")}>
          <span className="flex items-center gap-2">
            <Skeleton className="size-6 flex-none rounded-full" />
            <Skeleton className={cn("h-4", library)} />
            <Skeleton className="h-4 w-14" />
          </span>
          <Skeleton className={cn("h-4", article)} />
          <Skeleton className={cn("h-3", path)} />
          <Skeleton className="mt-1 h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <span className="flex gap-2">
            <Skeleton className="h-5 w-6" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </span>
        </li>
      ))}
    </ol>
  );
}
