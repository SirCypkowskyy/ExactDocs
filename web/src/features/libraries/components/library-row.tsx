import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { Fragment, useId, useState } from "react";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { pill, pillTone } from "@/shared/ui/recipes";
import { LibraryBullet } from "@/shared/ui/route";
import type { SyncState } from "../hooks/use-libraries";
import { type Library, orderedVersions, shortSha, sourceLabel } from "../model/library";
import { FailureDetail, SyncStatus } from "./sync-status";

const SHOWN = 5;
export const columns =
  "md:grid md:grid-cols-[minmax(0,1.6fr)_minmax(0,1.6fr)_8rem_minmax(0,13rem)] md:gap-x-6";

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
                pill,
                "h-6 max-w-full gap-1.5 pr-2.5 pl-2 font-mono text-small",
                isDefault ? pillTone.route : "bg-secondary text-foreground",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "size-2 flex-none rounded-full border-2 border-route",
                  isDefault ? "bg-route" : "bg-background",
                )}
              />
              <span className="truncate">{version}</span>
              {isDefault && (
                <span className="sr-only">
                  {library.default_pinned ? " (pinned default)" : " (default)"}
                </span>
              )}
              {isDefault && sha && (
                <span aria-hidden="true" className="font-normal text-muted-foreground">
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
            className="min-h-11 cursor-pointer rounded-full px-2.5 text-small font-medium text-muted-foreground outline-none transition-colors duration-(--dur-fast) hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:min-h-6"
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
    <li
      aria-busy={"status" in sync && sync.status === "pending"}
      className="relative -mx-3 rounded-lg px-3 py-4 transition-colors duration-(--dur-fast) has-[h2_a:hover]:bg-raised md:py-3.5"
    >
      <div className={cn("flex flex-col gap-y-2.5 md:items-start md:gap-y-0", columns)}>
        <div className="flex min-w-0 gap-3">
          <LibraryBullet id={library.id} size="lg" className="mt-0.5" />
          <div className="min-w-0">
            <h2 className="text-section font-semibold [overflow-wrap:anywhere]">
              <Link
                to="/libraries/$owner/$repo"
                params={{ owner, repo }}
                className="rounded outline-none after:absolute after:inset-0 after:content-[''] hover:text-route focus-visible:ring-2 focus-visible:ring-ring"
              >
                {library.title || <Id id={library.id} />}
              </Link>
            </h2>
            {library.title && (
              <p className="font-mono text-mono text-muted-foreground [overflow-wrap:anywhere]">
                <Id id={library.id} />
              </p>
            )}
            <a
              href={library.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="relative z-10 inline-flex max-w-full items-center gap-1 rounded text-small text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="truncate">{sourceLabel(library.source_url)}</span>
              <ExternalLink aria-hidden="true" className="size-3 shrink-0" />
              <span className="sr-only">(opens the repository)</span>
            </a>
          </div>
        </div>
        <div className="relative z-10 min-w-0 space-y-1.5">
          <Versions library={library} />
          {library.tags.length > 0 && (
            <p
              className="truncate text-small text-muted-foreground"
              title={library.tags.join(", ")}
            >
              <span className="sr-only">Tags: </span>
              {library.tags.join(" · ")}
            </p>
          )}
        </div>
        <div className="relative z-10 flex items-start justify-between gap-4 md:contents">
          <p className="relative z-10 whitespace-nowrap text-body">
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
        <div id={panel} className="relative z-10">
          {open && (
            <div className="reveal">
              <FailureDetail job={failed.job} open={open} />
            </div>
          )}
        </div>
      )}
    </li>
  );
}
