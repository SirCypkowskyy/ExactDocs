import { type SyncState, useNow } from "../hooks/use-libraries";
import type { Library } from "../model/library";
import { columns, LibraryRow } from "./library-row";

interface LibrariesListProps {
  libraries: readonly Library[];
  syncs: ReadonlyMap<string, SyncState>;
}

export function LibrariesList({ libraries, syncs }: LibrariesListProps) {
  const now = useNow();
  if (libraries.length === 0) {
    return (
      <div className="max-w-xl">
        <p>No libraries yet. Index one from a git repository:</p>
        <pre className="mt-3 overflow-x-auto rounded-md bg-secondary px-4 py-3 text-sm">
          <code>exactdocs add https://github.com/acme/payments --path docs/</code>
        </pre>
      </div>
    );
  }
  return (
    <div>
      {/* Column titles for sighted users; each cell below says what it is in its own text. */}
      <div
        aria-hidden="true"
        className={`hidden border-b border-border px-3 pb-2 text-sm text-muted-foreground ${columns}`}
      >
        <span>Library</span>
        <span>Versions</span>
        <span>Updated</span>
        <span>Sync</span>
      </div>
      <ul aria-label="Libraries" className="divide-y divide-border">
        {libraries.map((library) => (
          <LibraryRow
            key={library.id}
            library={library}
            sync={syncs.get(library.id) ?? { status: "pending" }}
            now={now}
          />
        ))}
      </ul>
    </div>
  );
}
