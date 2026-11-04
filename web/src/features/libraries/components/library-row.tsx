import { useId, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import type { SyncState } from "../hooks/use-libraries";
import { type Library, orderedVersions } from "../model/library";
import { absoluteTime, relativeTime } from "../model/time";
import { FailureDetail, SyncStatus } from "./sync-status";

const SHOWN = 5;
export const columns =
  "md:grid md:grid-cols-[minmax(0,1.2fr)_minmax(0,2fr)_8rem_minmax(0,13rem)] md:gap-x-6";

function Versions({ library }: { library: Library }) {
  const [all, setAll] = useState(false);
  const versions = orderedVersions(library);
  const visible = all ? versions : versions.slice(0, SHOWN);
  return (
    <ul aria-label="Versions" className="flex flex-wrap items-center gap-1.5">
      {visible.map((version) => {
        const isDefault = version === library.default_version;
        return (
          <li
            key={version}
            title={isDefault ? "Default version" : undefined}
            className="max-w-full"
          >
            <Badge
              variant={isDefault ? "default" : "secondary"}
              className="max-w-full rounded-md px-2 text-sm tabular-nums"
            >
              <span className="truncate">{version}</span>
              {isDefault && <span className="sr-only"> (default)</span>}
            </Badge>
          </li>
        );
      })}
      {versions.length > SHOWN && (
        <li>
          <button
            type="button"
            aria-expanded={all}
            onClick={() => setAll(!all)}
            className="rounded-md px-2 py-1 text-sm text-muted-foreground outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            {all ? "Show fewer" : `+${versions.length - SHOWN} more`}
          </button>
        </li>
      )}
    </ul>
  );
}

interface LibraryRowProps {
  library: Library;
  sync: SyncState;
  now: number;
}

export function LibraryRow({ library, sync, now }: LibraryRowProps) {
  const imported = library.last_imported_at;
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <li className="px-3 py-4 md:py-3">
      <div className={cn("flex flex-col gap-y-2.5 md:items-start md:gap-y-0", columns)}>
        <div className="min-w-0">
          <h2 className="text-base font-medium [overflow-wrap:anywhere]">{library.id}</h2>
          {library.title && library.title !== library.id && (
            <p className="truncate text-sm text-muted-foreground" title={library.title}>
              {library.title}
            </p>
          )}
        </div>
        <Versions library={library} />
        <p className="text-sm">
          {imported ? (
            <time dateTime={imported} title={absoluteTime(imported)}>
              <span className="text-muted-foreground md:sr-only">Updated </span>
              {relativeTime(imported, now)}
              <span className="block text-xs text-muted-foreground">{absoluteTime(imported)}</span>
            </time>
          ) : (
            <span className="text-muted-foreground">Nothing imported</span>
          )}
        </p>
        <SyncStatus
          sync={sync}
          now={now}
          open={open}
          onToggle={() => setOpen(!open)}
          panel={panel}
        />
      </div>
      <div id={panel}>
        {open && "kind" in sync && sync.kind === "failed" && (
          <FailureDetail job={sync.job} now={now} />
        )}
      </div>
    </li>
  );
}
