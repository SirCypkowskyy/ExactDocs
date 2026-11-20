import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { Fragment, useId, useState } from "react";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import type { SyncState } from "../hooks/use-libraries";
import { type Library, orderedVersions, shortSha, sourceLabel } from "../model/library";
import { FailureDetail, SyncStatus } from "./sync-status";

const SHOWN = 5;
export const columns =
  "md:grid md:grid-cols-[minmax(0,1.2fr)_minmax(0,2fr)_9rem_minmax(0,13rem)] md:gap-x-6";

const normalize = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, "");
/** `Next.js` under `/vercel/next.js` says nothing the id does not. */
const repeatsId = (title: string, id: string) =>
  normalize(title) === normalize(id.split("/").pop() ?? "");

/** Break long ids after each slash, not in the middle of a word. */
function Id({ id }: { id: string }) {
  return id
    .split("/")
    .slice(1)
    .map((part) => (
      <Fragment key={part}>
        /<wbr />
        {part}
      </Fragment>
    ));
}

function Versions({ library }: { library: Library }) {
  const [all, setAll] = useState(false);
  const list = useId();
  const versions = orderedVersions(library);
  const visible = all ? versions : versions.slice(0, SHOWN);
  const shas = new Map(library.refs.map((r) => [r.ref, r.commit_sha]));
  return (
    <ul id={list} aria-label="Versions" className="flex flex-wrap items-center gap-1.5">
      {visible.map((version, i) => {
        const isDefault = version === library.default_version;
        const sha = shas.get(version);
        return (
          <li
            key={version}
            title={[
              isDefault && (library.default_pinned ? "Pinned default version" : "Default version"),
              sha && `commit ${sha}`,
            ]
              .filter(Boolean)
              .join(" · ")}
            className={cn("max-w-full", i >= SHOWN && "fade-in")}
          >
            <span
              className={cn(
                "inline-flex max-w-full items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-[13px] tabular-nums",
                isDefault
                  ? "bg-mark/10 font-semibold text-mark ring-1 ring-mark/30"
                  : "bg-secondary text-secondary-foreground",
              )}
            >
              <span className="truncate">{version}</span>
              {isDefault && (
                <span className="sr-only">
                  {library.default_pinned ? " (pinned default)" : " (default)"}
                </span>
              )}
              {isDefault && sha && (
                <span aria-hidden="true" className="font-normal">
                  {shortSha(sha)}
                </span>
              )}
            </span>
          </li>
        );
      })}
      {versions.length > SHOWN && (
        <li>
          <button
            type="button"
            aria-expanded={all}
            aria-controls={list}
            aria-label={
              all
                ? `Show fewer versions of ${library.id}`
                : `Show ${versions.length - SHOWN} more versions of ${library.id}`
            }
            onClick={() => setAll(!all)}
            className="min-h-11 rounded-md px-2 py-0.5 text-sm text-muted-foreground ring-1 ring-inset ring-border outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
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
  const [, owner = "", repo = ""] = library.id.split("/");
  const imported = library.last_imported_at;
  const [open, setOpen] = useState(false);
  const panel = useId();
  const failed = "kind" in sync && sync.kind === "failed" ? sync : null;
  return (
    <li aria-busy={"status" in sync && sync.status === "pending"} className="py-4 md:py-3">
      <div className={cn("flex flex-col gap-y-2.5 md:items-start md:gap-y-0", columns)}>
        <div className="min-w-0">
          <h2 className="font-mono text-[15px] font-medium [overflow-wrap:anywhere]">
            <Link
              to="/libraries/$owner/$repo"
              params={{ owner, repo }}
              className="rounded underline decoration-mark/40 underline-offset-4 outline-none hover:decoration-mark focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Id id={library.id} />
            </Link>
          </h2>
          {library.title && !repeatsId(library.title, library.id) && (
            <p className="truncate text-sm text-muted-foreground" title={library.title}>
              {library.title}
            </p>
          )}
          <a
            href={library.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex max-w-full items-center gap-1 rounded text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="truncate">{sourceLabel(library.source_url)}</span>
            <ExternalLink aria-hidden="true" className="size-3 shrink-0" />
            <span className="sr-only">(opens the repository)</span>
          </a>
        </div>
        <div className="min-w-0 space-y-1.5">
          <Versions library={library} />
          {library.tags.length > 0 && (
            <p
              className="truncate text-[13px] text-muted-foreground"
              title={library.tags.join(", ")}
            >
              <span className="sr-only">Tags: </span>
              {library.tags.join(" · ")}
            </p>
          )}
        </div>
        <div className="flex items-start justify-between gap-4 md:contents">
          <p className="whitespace-nowrap text-sm">
            {imported ? (
              <time dateTime={imported} title={absoluteTimeWithZone(imported)}>
                <span className="text-muted-foreground md:sr-only">Imported </span>
                {relativeTime(imported, now)}
              </time>
            ) : (
              <span className="text-muted-foreground">-</span>
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
      </div>
      {failed && (
        <div
          id={panel}
          className={cn(
            "grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none",
            open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
          )}
        >
          <div className="overflow-hidden" inert={!open}>
            <FailureDetail job={failed.job} open={open} />
          </div>
        </div>
      )}
    </li>
  );
}
