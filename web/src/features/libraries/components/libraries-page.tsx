import { usePageTitle } from "@/shared/lib/use-page-title";
import { useLibraries, useSyncStates } from "../hooks/use-libraries";
import { LibrariesList } from "./libraries-list";

export function LibrariesPage() {
  const { data: libraries } = useLibraries();
  const syncs = useSyncStates(libraries);
  const heading = usePageTitle("Libraries");
  const all = [...syncs.values()];
  const failed = all.filter((s) => "kind" in s && s.kind === "failed").length;
  const running = all.filter((s) => "kind" in s && s.kind === "running").length;
  const summary = [
    `${libraries.length} ${libraries.length === 1 ? "library" : "libraries"}`,
    failed > 0 && `${failed} sync failed`,
    running > 0 && `${running} importing`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <h1
        ref={heading}
        tabIndex={-1}
        className="font-serif text-3xl font-semibold tracking-tight outline-none"
      >
        Libraries
      </h1>
      {/* A polite live region: a sync that starts, finishes or fails is announced here. */}
      <p role="status" className="mt-2 text-muted-foreground">
        {libraries.length > 0 ? summary : "Documentation indexed by ExactDocs, per version."}
      </p>
      <div className="mt-6">
        <LibrariesList libraries={libraries} syncs={syncs} />
      </div>
    </main>
  );
}
