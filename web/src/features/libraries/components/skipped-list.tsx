import { useState } from "react";
import { type ProblemSummary, type SkipGroup, skippedLabel } from "../model/add-library";

const SHOWN = 8;
/** Past this many files the list folds away, so a huge skip never pushes the buttons off screen. */
const FOLD_FROM = 30;

function Group({ group }: { group: SkipGroup }) {
  const [all, setAll] = useState(false);
  const files = all ? group.files : group.files.slice(0, SHOWN);
  const rest = group.files.length - SHOWN;
  return (
    <li>
      <h4 className="text-body font-semibold">
        {group.label}{" "}
        <span className="font-normal text-muted-foreground tabular-nums">
          ({group.files.length})
        </span>
      </h4>
      <ul className="mt-1.5 space-y-1">
        {files.map((f) => (
          <li key={`${f.code}:${f.path}`} className="text-body [overflow-wrap:anywhere]">
            <span className="font-mono text-mono">{f.path}</span>
            {!group.known && (
              <span className="text-muted-foreground max-sm:mt-0.5 max-sm:block sm:ml-2">
                {f.reason}
              </span>
            )}
          </li>
        ))}
      </ul>
      {!all && rest > 0 && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-1 min-h-11 rounded text-body text-muted-foreground underline underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
        >
          Show {rest} more
        </button>
      )}
    </li>
  );
}

function Skipped({ summary }: { summary: ProblemSummary }) {
  const { skipGroups, skipped, truncated } = summary;
  return (
    <>
      <p className="mt-1 text-body text-muted-foreground">
        These were left out of the version. The rest was imported.
      </p>
      <ul className="mt-4 space-y-5">
        {skipGroups.map((g) => (
          <Group key={g.code} group={g} />
        ))}
      </ul>
      {truncated && (
        <p className="mt-4 text-body text-muted-foreground">
          Showing the first {skipped} skipped files. More were skipped for the same kinds of
          reasons.
        </p>
      )}
    </>
  );
}

/** The files an import left out, grouped by why, plus files it kept with a note. */
export function SkippedList({ summary }: { summary: ProblemSummary }) {
  const { skipped, notes, truncated } = summary;
  if (skipped === 0 && notes.length === 0 && !truncated) return null;
  const fold = skipped >= FOLD_FROM;
  const title = (
    <>
      Skipped files{" "}
      <span className="font-normal text-muted-foreground tabular-nums">
        ({skippedLabel(summary)})
      </span>
    </>
  );
  return (
    <div className="fade-in mt-8 space-y-8">
      {(skipped > 0 || truncated) &&
        (fold ? (
          <details aria-labelledby="skipped-title">
            <summary
              id="skipped-title"
              className="min-h-11 cursor-pointer text-section font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {title}
            </summary>
            <Skipped summary={summary} />
          </details>
        ) : (
          <section aria-labelledby="skipped-title">
            <h3 id="skipped-title" className="text-section font-semibold">
              {title}
            </h3>
            <Skipped summary={summary} />
          </section>
        ))}
      {notes.length > 0 && (
        <section aria-labelledby="notes-title">
          <h3 id="notes-title" className="text-section font-semibold">
            Imported with a note{" "}
            <span className="font-normal text-muted-foreground tabular-nums">({notes.length})</span>
          </h3>
          <ul className="mt-3 space-y-2">
            {notes.map((n) => (
              <li key={`${n.code}:${n.path}`} className="text-body [overflow-wrap:anywhere]">
                <span className="font-mono text-mono">{n.path}</span>
                <span className="mt-0.5 block text-muted-foreground">{n.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
