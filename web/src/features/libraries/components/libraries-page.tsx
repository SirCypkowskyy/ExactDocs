import { usePageTitle } from "@/shared/lib/use-page-title";
import { useLibraries } from "../hooks/use-libraries";
import { LibrariesTable } from "./libraries-table";

export function LibrariesPage() {
  const { data: libraries } = useLibraries();
  const heading = usePageTitle("Libraries");
  return (
    <main className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <h1
        ref={heading}
        tabIndex={-1}
        className="font-serif text-3xl font-semibold tracking-tight outline-none"
      >
        Libraries
      </h1>
      <p className="mt-2 text-muted-foreground">Documentation indexed by ExactDocs, per version.</p>
      <div className="mt-8">
        <LibrariesTable libraries={libraries} />
      </div>
    </main>
  );
}
