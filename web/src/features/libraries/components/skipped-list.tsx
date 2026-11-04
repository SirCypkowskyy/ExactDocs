import { useState } from "react";
import type { ProblemSummary, SkipGroup } from "../model/add-library";

const SHOWN = 8;

function Group({ group }: { group: SkipGroup }) {
  const [all, setAll] = useState(false);
  const files = all ? group.files : group.files.slice(0, SHOWN);
  const rest = group.files.length - SHOWN;
  return (
    <li>
      <h4 className="text-sm font-medium">
        {group.label}{" "}
        <span className="font-normal text-muted-foreground tabular-nums">
          ({group.files.length})
        </span>
      </h4>
      <ul className="mt-1.5 space-y-1">
        {files.map((f) => (
          <li key={f.path} className="text-sm [overflow-wrap:anywhere]">
            <span className="font-mono text-[13px]">{f.path}</span>
            {!group.known && <span className="text-muted-foreground"> {f.reason}</span>}
          </li>
        ))}
      </ul>
      {!all && rest > 0 && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-1 min-h-11 rounded text-sm text-muted-foreground underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
        >
          Show {rest} more
        </button>
      )}
    </li>
  );
}

/** The files an import left out, grouped by why, plus files it kept with a note. */
export function SkippedList({ summary }: { summary: ProblemSummary }) {
  const { skipGroups, skipped, notes, truncated } = summary;
  if (skipped === 0 && notes.length === 0 && !truncated) return null;
  return (
    <div className="mt-8 space-y-8">
      {(skipped > 0 || truncated) && (
        <section aria-labelledby="skipped-title">
          <h3 id="skipped-title" className="text-base font-semibold">
            Skipped files{" "}
            <span className="font-normal text-muted-foreground tabular-nums">({skipped})</span>
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            These were left out of the version. The rest was imported.
          </p>
          <ul className="mt-4 space-y-5">
            {skipGroups.map((g) => (
              <Group key={g.code} group={g} />
            ))}
          </ul>
          {truncated && (
            <p className="mt-4 text-sm text-muted-foreground">
              More files were skipped than are listed here.
            </p>
          )}
        </section>
      )}
      {notes.length > 0 && (
        <section aria-labelledby="notes-title">
          <h3 id="notes-title" className="text-base font-semibold">
            Imported with a note{" "}
            <span className="font-normal text-muted-foreground tabular-nums">({notes.length})</span>
          </h3>
          <ul className="mt-3 space-y-1">
            {notes.map((n) => (
              <li key={n.path} className="text-sm [overflow-wrap:anywhere]">
                <span className="font-mono text-[13px]">{n.path}</span>
                <span className="text-muted-foreground"> {n.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
