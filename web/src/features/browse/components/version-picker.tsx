import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouter, useRouterState } from "@tanstack/react-router";
import { ChevronsUpDown } from "lucide-react";
import { Popover } from "radix-ui";
import { type KeyboardEvent, type MouseEvent, useRef, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { control, controlHeight, trigger } from "@/shared/ui/recipes";
import { Spinner } from "@/shared/ui/spinner";
import { pathInVersionQueryOptions } from "../api/browse-queries";
import { messages } from "../messages";
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

/** A version as a station on the library's line: filled where you are, a double ring for the default. */
function Station({ current, isDefault }: { current: boolean; isDefault: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative z-10 size-3 flex-none rounded-full border-2 border-route bg-background transition-colors duration-(--dur-fast)",
        current && "bg-route",
        isDefault && "ring-2 ring-route/30 ring-offset-1 ring-offset-background",
      )}
    />
  );
}

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
  const t = useMessages(messages).versions;
  const defaultLabel = pinned ? t.pinnedDefault : t.default;
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
          waitingFor === null ? t.trigger(current.ref) : t.switching(current.ref, waitingFor.ref)
        }
        aria-busy={waitingFor !== null || undefined}
        className={cn(trigger, "w-full data-[state=open]:border-ring")}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Station current isDefault={shownVersion.is_default} />
          <span
            title={shownVersion.ref}
            className={cn(
              "truncate font-mono text-mono font-semibold",
              waitingFor !== null && "text-muted-foreground",
            )}
          >
            {shownVersion.ref}
          </span>
          {shownVersion.is_default && (
            <span className="text-small text-muted-foreground max-sm:hidden">{defaultLabel}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-small text-muted-foreground max-lg:hidden">
            {shortSha(shownVersion.commit_sha)}
          </span>
          {waitingFor === null ? (
            <ChevronsUpDown aria-hidden="true" className="size-4 text-muted-foreground" />
          ) : (
            <Spinner className="text-muted-foreground" />
          )}
        </span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          onKeyDown={onKeyDown}
          className="z-50 w-[min(22rem,calc(100vw-1.5rem))] origin-(--radix-popover-content-transform-origin) rounded-lg border border-border bg-popover text-popover-foreground shadow-float outline-none transition-none data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-safe:data-[state=open]:zoom-in-[0.97] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:duration-(--dur-menu) data-[state=open]:ease-(--ease-out) data-[state=closed]:duration-(--dur-exit)"
        >
          {versions.length >= FILTER_FROM && (
            <div className="border-b border-rule p-2">
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={t.filterPlaceholder(versions.length)}
                aria-label={t.filter}
                autoComplete="off"
                spellCheck={false}
                className={cn(control, controlHeight, "px-3 font-mono placeholder:font-sans")}
              />
            </div>
          )}
          <ul
            ref={list}
            aria-label={t.list}
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
                      // The list is the line: a rule runs through every station (DESIGN.md, The idea).
                      "relative flex min-h-11 items-center gap-2.5 rounded-md px-2.5 py-1 text-body outline-none transition-colors duration-(--dur-fast) before:absolute before:top-0 before:bottom-0 before:left-[15px] before:w-0.5 before:bg-route/25 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring lg:min-h-9",
                      i === 0 && "before:top-1/2",
                      i === shown.length - 1 && "before:bottom-1/2",
                      isCurrent ? "bg-route-soft" : "can-hover:hover:bg-accent",
                    )}
                  >
                    <Station current={isCurrent} isDefault={v.is_default} />
                    <span className="flex min-w-0 flex-1 items-baseline gap-2">
                      <span className="truncate font-mono text-mono font-medium">{v.ref}</span>
                      {v.is_default && (
                        <span className="text-small text-muted-foreground">{defaultLabel}</span>
                      )}
                      {v.kind !== "tag" && (
                        <span className="text-small text-muted-foreground">{t.kind[v.kind]}</span>
                      )}
                    </span>
                    {resolved[i]?.isFetching && (
                      // The rename lookup for this version is still on its way.
                      <Spinner className="text-muted-foreground" />
                    )}
                    <span className="font-mono text-small text-muted-foreground tabular-nums">
                      {shortSha(v.commit_sha)}
                    </span>
                  </Link>
                </li>
              );
            })}
            {shown.length === 0 && (
              <li className="px-3 py-4 text-body text-muted-foreground">
                {t.noMatch(filter.trim())}
              </li>
            )}
          </ul>
          <DefaultPin owner={owner} repo={repo} current={current} pinned={pinned} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
