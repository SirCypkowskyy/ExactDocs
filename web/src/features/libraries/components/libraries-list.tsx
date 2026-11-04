import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { type SyncState, useNow } from "../hooks/use-libraries";
import type { Library } from "../model/library";
import { columns, LibraryRow } from "./library-row";

interface LibrariesListProps {
  libraries: readonly Library[];
  syncs: ReadonlyMap<string, SyncState>;
}

const COMMAND = "exactdocs add https://github.com/acme/payments --path docs/";

function EmptyState() {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(COMMAND).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <div className="max-w-xl">
      <p>No libraries yet. Index one from a git repository.</p>
      <pre className="mt-3 whitespace-pre-wrap rounded-md bg-secondary px-4 py-3 font-mono text-[13px] [overflow-wrap:anywhere]">
        <code>{COMMAND}</code>
      </pre>
      <button
        type="button"
        onClick={copy}
        className="mt-2 inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-sm text-muted-foreground outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] md:min-h-8"
      >
        {copied ? (
          <Check aria-hidden="true" className="size-4" />
        ) : (
          <Copy aria-hidden="true" className="size-4" />
        )}
        Copy command
      </button>
      <span role="status" className="sr-only">
        {copied ? "Copied" : ""}
      </span>
    </div>
  );
}

export function LibrariesList({ libraries, syncs }: LibrariesListProps) {
  const now = useNow();
  if (libraries.length === 0) return <EmptyState />;
  return (
    <div>
      {/* Column titles for sighted users; each cell below says what it is in its own text. */}
      <div
        aria-hidden="true"
        className={`hidden border-b border-border pb-2 text-[13px] text-muted-foreground ${columns}`}
      >
        <span>Library</span>
        <span>Versions</span>
        <span>Last imported</span>
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
