import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouter, useRouterState } from "@tanstack/react-router";
import { Check, ChevronsUpDown, LoaderCircle } from "lucide-react";
import { Popover } from "radix-ui";
import { type KeyboardEvent, type MouseEvent, useRef, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { pathInVersionQueryOptions } from "../api/browse-queries";
import { type BrowseSearch, orderVersions, shortSha, type Version } from "../model/browse";
import { DefaultPin } from "./default-pin";

interface VersionPickerProps {
  owner: string;
  repo: string;
  versions: readonly Version[];
  current: Version;
  /** The default version is pinned by an owner, not chosen by the default-version rule. */
  pinned: boolean;
  /** What stays when the version changes: the open article, the tag filter and the search. */
  keep: Pick<BrowseSearch, "path" | "tags" | "q" | "match">;
}

const FILTER_FROM = 8;

/** A click the browser should handle itself: new tab, new window, or (Alt) download. */
const handledByBrowser = (event: MouseEvent) =>
  event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;

/**
 * Switches the version and keeps the article, so the same page can be compared across versions.
 * An article renamed between the two versions is followed through the rename maps of every
 * version in between, even ones the list skips; one that did not move keeps its path (the article
 * pane then offers the version's root when it is not there).
 *
 * The renames are looked up when the list opens, once per version, and each link carries the path
 * it resolved to, so a new tab or a copied link lands on the renamed article too. Only a click on
 * a version whose answer is still on its way waits for it, and a later click or navigation
 * cancels that wait.
 */
export function VersionPicker({
  owner,
  repo,
  versions,
  current,
  pinned,
  keep,
}: VersionPickerProps) {
  const defaultLabel = pinned ? "pinned default" : "default";
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  /** The version a click waits to switch to, and the page it was clicked on. */
  const [switching, setSwitching] = useState<{ to: Version; from: string } | null>(null);
  const href = useRouterState({ select: (s) => s.location.href });
  // Once the user is on another page, the wait is over for them, whatever the lookup still does.
  const waitingFor = switching?.from === href ? switching.to : null;
  /** What the trigger shows: the version being switched to while a click waits. */
  const shownVersion = waitingFor ?? current;
  const client = useQueryClient();
  const navigate = useNavigate();
  const router = useRouter();
  const list = useRef<HTMLUListElement>(null);
  /** The latest click: an older switch that resolves late must not navigate. */
  const latest = useRef(0);
  const ordered = orderVersions(versions);
  const shown = ordered.filter((v) => v.ref.toLowerCase().includes(filter.trim().toLowerCase()));
  const path = keep.path;
  const resolved = useQueries({
    queries: shown.map((v) => ({
      ...pathInVersionQueryOptions(owner, repo, current, v, path ?? ""),
      enabled: open && path !== undefined && v.ref !== current.ref,
    })),
  });

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

  /** Waits for the rename answer of `target`, then switches, unless the user went elsewhere. */
  async function switchTo(target: Version, at: string) {
    const mine = ++latest.current;
    const from = router.state.location.href;
    setSwitching({ to: target, from });
    try {
      const moved = await client
        .fetchQuery(pathInVersionQueryOptions(owner, repo, current, target, at))
        .then((answer) => answer.path)
        .catch(() => at);
      if (mine !== latest.current || router.state.location.href !== from) return;
      await navigate({
        to: "/libraries/$owner/$repo",
        params: { owner, repo },
        search: { version: target.ref, ...keep, path: moved },
      });
    } finally {
      if (mine === latest.current) setSwitching(null);
    }
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
        aria-label={
          waitingFor === null
            ? `Version: ${current.ref}. Change version`
            : `Version: ${current.ref}, switching to ${waitingFor.ref}. Change version`
        }
        aria-busy={waitingFor !== null || undefined}
        className="flex h-11 w-full min-w-0 cursor-pointer items-center justify-between gap-2 rounded-md bg-secondary px-3 text-sm outline-none ring-1 ring-inset ring-border transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.98] data-[state=open]:ring-ring [@media(hover:hover)]:hover:bg-accent"
      >
        <span className="flex min-w-0 items-baseline gap-2">
          <span
            className={cn(
              "truncate font-mono font-semibold",
              waitingFor !== null && "text-muted-foreground",
            )}
          >
            {shownVersion.ref}
          </span>
          {shownVersion.is_default && (
            <span className="text-xs text-mark max-sm:hidden">{defaultLabel}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground max-lg:hidden">
            {shortSha(shownVersion.commit_sha)}
          </span>
          {waitingFor === null ? (
            <ChevronsUpDown aria-hidden="true" className="size-4 text-muted-foreground" />
          ) : (
            <LoaderCircle
              aria-hidden="true"
              className="size-4 text-muted-foreground motion-safe:animate-spin"
            />
          )}
        </span>
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
            {shown.map((v, i) => {
              const isCurrent = v.ref === current.ref;
              const moved = resolved[i]?.data?.path;
              const waits = path !== undefined && !isCurrent && moved === undefined;
              return (
                <li key={v.ref}>
                  <Link
                    to="/libraries/$owner/$repo"
                    params={{ owner, repo }}
                    search={{ version: v.ref, ...keep, path: moved ?? path }}
                    aria-current={isCurrent ? "true" : undefined}
                    onClick={(event) => {
                      setOpen(false);
                      if (handledByBrowser(event)) return;
                      if (!waits) {
                        latest.current++;
                        setSwitching(null);
                        return;
                      }
                      event.preventDefault();
                      void switchTo(v, path);
                    }}
                    className={cn(
                      "flex min-h-11 items-center gap-2 rounded-md px-2.5 py-1 text-sm lg:min-h-9 outline-none transition-colors duration-100 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                      isCurrent ? "bg-mark/[0.16]" : "[@media(hover:hover)]:hover:bg-accent",
                    )}
                  >
                    <Check
                      aria-hidden="true"
                      className={cn("size-4 shrink-0 text-mark", !isCurrent && "invisible")}
                    />
                    <span className="flex min-w-0 flex-1 items-baseline gap-2">
                      <span className="truncate font-mono font-medium">{v.ref}</span>
                      {v.is_default && <span className="text-xs text-mark">{defaultLabel}</span>}
                      {v.kind !== "tag" && (
                        <span className="text-xs text-muted-foreground">{v.kind}</span>
                      )}
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
          <DefaultPin owner={owner} repo={repo} current={current} pinned={pinned} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
