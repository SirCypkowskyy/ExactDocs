import { useMemo } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { type SyncState, useLibraries, useSyncStates } from "../hooks/use-libraries";
import { failedFirst } from "../model/library";
import { LibrariesList } from "./libraries-list";

const kindOf = (s: SyncState | undefined) => (s && "kind" in s ? s.kind : undefined);

export function LibrariesPage() {
  const { data: libraries } = useLibraries();
  const { syncs, failedToLoad, loading, retry } = useSyncStates(libraries);
  const heading = usePageTitle("Libraries");
  const sorted = useMemo(
    () => failedFirst(libraries, (id) => kindOf(syncs.get(id)) === "failed"),
    [libraries, syncs],
  );
  const all = [...syncs.values()];
  const failed = all.filter((s) => kindOf(s) === "failed").length;
  const running = all.filter((s) => kindOf(s) === "running").length;
  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <h1
        ref={heading}
        tabIndex={-1}
        className="font-serif text-3xl font-semibold tracking-tight outline-none"
      >
        Libraries
      </h1>
      {libraries.length > 0 && (
        <>
          {/* Atomic: one sentence is announced, and the sync counts only once they are known. */}
          <p role="status" aria-atomic="true" className="mt-2 text-muted-foreground">
            {libraries.length} {libraries.length === 1 ? "library" : "libraries"}
            {!loading && failed > 0 && (
              <>
                {" · "}
                <span className="font-medium text-destructive">{failed} sync failed</span>
              </>
            )}
            {!loading && running > 0 && ` · ${running} importing`}
          </p>
          {failedToLoad && (
            <p className="mt-1 text-sm text-muted-foreground">
              Couldn't load sync status.{" "}
              <button
                type="button"
                onClick={retry}
                className="min-h-11 rounded underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
              >
                Retry
              </button>
            </p>
          )}
        </>
      )}
      <div className="mt-6">
        <LibrariesList libraries={sorted} syncs={syncs} />
      </div>
    </main>
  );
}
