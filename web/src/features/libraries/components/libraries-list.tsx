import { Check, Copy, LibraryBig } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/page";
import { codeWell } from "@/shared/ui/recipes";
import { type SyncState, useNow } from "../hooks/use-libraries";
import type { Library } from "../model/library";
import { AddLibraryLink } from "./add-library-link";
import { columns, LibraryRow } from "./library-row";

interface LibrariesListProps {
  libraries: readonly Library[];
  syncs: ReadonlyMap<string, SyncState>;
}

const COMMAND = "exactdocs add https://github.com/acme/payments --path docs/";

function FirstRun() {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(COMMAND).then(() => {
      setCopied(true);
      toast.success("Command copied");
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <EmptyState
      icon={<LibraryBig aria-hidden="true" />}
      title="No libraries yet"
      action={<AddLibraryLink />}
      className="max-w-2xl"
    >
      <p>
        Add a git repository and choose its Markdown docs. Agents and people then read them at the
        exact version you import.
      </p>
      <p className="mt-4">Or index one from the command line:</p>
      <div className="mt-2 flex items-start gap-1">
        <pre className={cn(codeWell, "min-w-0 flex-1 whitespace-pre-wrap")}>
          <code>{COMMAND}</code>
        </pre>
        <Button variant="ghost" size="icon" onClick={copy} aria-label="Copy command">
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        </Button>
      </div>
    </EmptyState>
  );
}

export function LibrariesList({ libraries, syncs }: LibrariesListProps) {
  const now = useNow();
  if (libraries.length === 0) return <FirstRun />;
  return (
    <div>
      {/* Column titles for sighted users; each cell below says what it is in its own text. */}
      <div
        aria-hidden="true"
        className={`hidden border-b border-border pb-2 pl-[3.25rem] text-small text-muted-foreground ${columns}`}
      >
        <span>Library</span>
        <span>Versions</span>
        <span>Last imported</span>
        <span>Sync</span>
      </div>
      <ul aria-label="Libraries" className="divide-y divide-rule">
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
