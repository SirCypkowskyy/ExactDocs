import { Link } from "@tanstack/react-router";
import { Check, ChevronsUpDown } from "lucide-react";
import { Popover } from "radix-ui";
import { type KeyboardEvent, useRef, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { type BrowseSearch, orderVersions, shortSha, type Version } from "../model/browse";

interface VersionPickerProps {
  owner: string;
  repo: string;
  versions: readonly Version[];
  current: string | undefined;
  /** What stays when the version changes: the open article and the tag filter. */
  keep: Pick<BrowseSearch, "path" | "tags">;
}

const FILTER_FROM = 8;

/** Switches the version and keeps the article path, so the same page can be compared across versions. */
export function VersionPicker({ owner, repo, versions, current, keep }: VersionPickerProps) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const list = useRef<HTMLUListElement>(null);
  const ordered = orderVersions(versions);
  const shown = ordered.filter((v) => v.ref.toLowerCase().includes(filter.trim().toLowerCase()));
  const now = ordered.find((v) => v.ref === current);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const links = [...(list.current?.querySelectorAll<HTMLElement>("a") ?? [])];
    const at = links.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? at + 1 : at - 1;
    if (next < 0 && at >= 0)
      (event.currentTarget.querySelector("input") as HTMLElement | null)?.focus();
    else links[Math.min(next, links.length - 1)]?.focus();
    event.preventDefault();
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setFilter("");
      }}
    >
      <Popover.Trigger
        aria-label={`Version: ${current ?? "none"}. Change version`}
        className="group inline-flex h-11 max-w-full cursor-pointer items-center gap-2 rounded-md bg-secondary px-3 font-mono text-sm outline-none ring-1 ring-inset ring-border transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.98] data-[state=open]:ring-ring [@media(hover:hover)]:hover:bg-accent"
      >
        <span className="font-sans text-muted-foreground">Version</span>
        <span className="truncate font-semibold">{current ?? "none"}</span>
        {now?.is_default && <span className="font-sans text-xs text-mark">default</span>}
        <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          onKeyDown={onKeyDown}
          className="z-50 w-[min(22rem,calc(100vw-1.5rem))] origin-(--radix-popover-content-transform-origin) rounded-lg border border-border bg-popover text-popover-foreground shadow-lg outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-safe:data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:duration-150 data-[state=closed]:duration-100"
        >
          {versions.length >= FILTER_FROM && (
            <div className="border-b border-border p-2">
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={`Filter ${versions.length} versions`}
                aria-label="Filter versions"
                autoComplete="off"
                spellCheck={false}
                className="h-10 w-full rounded-md bg-secondary px-3 font-mono text-sm outline-none ring-1 ring-inset ring-input placeholder:font-sans placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          )}
          <ul
            ref={list}
            aria-label="Versions"
            className="max-h-[min(22rem,60dvh)] overflow-y-auto p-1"
          >
            {shown.map((v) => {
              const isCurrent = v.ref === current;
              return (
                <li key={v.ref}>
                  <Link
                    to="/libraries/$owner/$repo"
                    params={{ owner, repo }}
                    search={{ version: v.ref, ...keep }}
                    aria-current={isCurrent ? "true" : undefined}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "flex min-h-11 items-center gap-2 rounded-md px-2.5 py-1.5 text-sm outline-none transition-colors duration-100 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                      isCurrent ? "bg-mark/10" : "[@media(hover:hover)]:hover:bg-accent",
                    )}
                  >
                    <Check
                      aria-hidden="true"
                      className={cn("size-4 shrink-0 text-mark", !isCurrent && "invisible")}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono font-medium [overflow-wrap:anywhere]">
                        {v.ref}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {v.is_default ? "Default " : ""}
                        {v.kind}
                      </span>
                    </span>
                    <span className="font-mono text-xs text-muted-foreground tabular-nums">
                      {shortSha(v.commit_sha)}
                    </span>
                  </Link>
                </li>
              );
            })}
            {shown.length === 0 && (
              <li className="px-3 py-4 text-sm text-muted-foreground">
                No version matches "{filter.trim()}".
              </li>
            )}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
