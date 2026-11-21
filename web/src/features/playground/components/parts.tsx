import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { cn } from "@/shared/lib/utils";
import { LibraryBullet, VersionStation } from "@/shared/ui/route";
import { Skeleton } from "@/shared/ui/skeleton";
import { splitLibrary } from "../model/playground";

/** A line under a heading: an error (alert), or a neutral note about how the answer came about. */
export function Notice({ tone, children }: { tone: "error" | "note"; children: ReactNode }) {
  return (
    <p
      role={tone === "error" ? "alert" : undefined}
      className={cn(
        "rounded-md px-3 py-2.5 text-body",
        tone === "error"
          ? "bg-destructive-soft font-medium text-destructive-ink"
          : "bg-route-soft text-foreground",
      )}
    >
      {children}
    </p>
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
  const { owner, repo } = splitLibrary(library);
  return (
    <>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-body">
        <LibraryBullet id={library} size="sm" />
        <span className="font-medium">{library}</span>
        <span className="sr-only">version </span>
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

/** Bars the size of the answer, while a mode or the agent is working. */
export function ResultsSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-2">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-24 rounded-lg" />
      ))}
    </div>
  );
}
