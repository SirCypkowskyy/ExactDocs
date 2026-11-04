import { Link } from "@tanstack/react-router";
import { ChevronRight, Loader } from "lucide-react";
import { type KeyboardEvent, useRef, useState } from "react";
import { cn } from "@/shared/lib/utils";
import type { Row } from "../model/browse";

interface FileTreeProps {
  owner: string;
  repo: string;
  version: string;
  tags: string | undefined;
  /** The open article's path. */
  selected: string | undefined;
  rows: readonly Row[];
  /** Folders whose listing failed. */
  failed: ReadonlySet<string>;
  label: string;
  onToggle: (folder: string, open?: boolean) => void;
  onMore: (scope: string) => void;
  onOpen: () => void;
}

const INDENT = 14;
const rowBase =
  "group flex min-h-11 w-full cursor-pointer items-center gap-1.5 rounded-md pr-2 text-left text-[15px] outline-none transition-colors duration-100 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring lg:min-h-9 lg:text-sm";
const hoverable = "[@media(hover:hover)]:hover:bg-accent/70";

/**
 * A file tree with the WAI-ARIA tree pattern: one tab stop, arrows move and open/close, Home and
 * End jump, Enter or Space opens. Rows are a flat list with `aria-level`, so closed folders cost
 * no DOM and large versions stay cheap.
 */
export function FileTree({
  owner,
  repo,
  version,
  tags,
  selected,
  rows,
  failed,
  label,
  onToggle,
  onMore,
  onOpen,
}: FileTreeProps) {
  const tree = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<string | undefined>();
  const focusable = rows.filter((r) => r.kind !== "loading");
  // One tab stop: the row last focused, else the open article, else the first row.
  const stop =
    focusable.find((r) => r.key === active)?.key ??
    focusable.find((r) => r.kind === "file" && r.path === selected)?.key ??
    focusable[0]?.key;

  const items = () => [
    ...(tree.current?.querySelectorAll<HTMLElement>("[role=treeitem][data-key]") ?? []),
  ];
  const focusKey = (key: string | undefined) => {
    const el = items().find((e) => e.dataset.key === key);
    el?.focus();
  };

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = (event.target as HTMLElement).closest<HTMLElement>("[role=treeitem]");
    if (!current || event.altKey || event.ctrlKey || event.metaKey) return;
    const list = items();
    const index = list.indexOf(current);
    const row = rows.find((r) => r.key === current.dataset.key);
    const go = (i: number) => list[Math.max(0, Math.min(list.length - 1, i))]?.focus();
    switch (event.key) {
      case "ArrowDown":
        go(index + 1);
        break;
      case "ArrowUp":
        go(index - 1);
        break;
      case "Home":
        go(0);
        break;
      case "End":
        go(list.length - 1);
        break;
      case "ArrowRight":
        if (row?.kind !== "folder") return;
        if (!row.open) onToggle(row.path, true);
        else go(index + 1);
        break;
      case "ArrowLeft":
        if (row?.kind === "folder" && row.open) onToggle(row.path, false);
        else if (row && "parent" in row && row.parent) focusKey(`d:${row.parent}`);
        break;
      case " ":
      case "Enter":
        // A link already opens on Enter; Space is the one key it ignores.
        if (row?.kind === "file" && event.key === "Enter") return;
        current.click();
        break;
      default:
        return;
    }
    event.preventDefault();
  }

  return (
    <div
      ref={tree}
      role="tree"
      aria-label={label}
      onKeyDown={onKeyDown}
      className="select-none py-1 [&_[role=treeitem]]:[content-visibility:auto] [&_[role=treeitem]]:[contain-intrinsic-size:auto_2.25rem]"
    >
      {rows.map((row) => {
        const pad = { paddingLeft: `${row.depth * INDENT + 8}px` };
        if (row.kind === "loading") {
          return (
            <div
              key={row.key}
              role="treeitem"
              tabIndex={-1}
              aria-selected="false"
              aria-disabled="true"
              aria-level={row.depth + 1}
              style={pad}
              className="flex min-h-9 items-center gap-2 text-sm text-muted-foreground"
            >
              <Loader aria-hidden="true" className="spin ml-[18px] size-3.5" />
              Loading
            </div>
          );
        }
        const common = {
          "data-key": row.key,
          "aria-level": row.depth + 1,
          "aria-posinset": row.pos,
          "aria-setsize": row.size,
          onFocus: () => setActive(row.key),
          style: pad,
        } as const;
        if (row.kind === "folder") {
          return (
            // biome-ignore lint/a11y/useKeyWithClickEvents: keys are handled once, on the tree
            <div
              key={row.key}
              {...common}
              role="treeitem"
              tabIndex={row.key === stop ? 0 : -1}
              aria-expanded={row.open}
              aria-selected="false"
              onClick={() => onToggle(row.path)}
              className={cn(rowBase, hoverable)}
              title={row.path}
            >
              <ChevronRight
                aria-hidden="true"
                className={cn(
                  "size-4 shrink-0 text-muted-foreground transition-transform duration-150 ease-out motion-reduce:transition-none",
                  row.open && "rotate-90",
                )}
              />
              <span className="truncate font-medium">{row.name}</span>
            </div>
          );
        }
        if (row.kind === "more") {
          const bad = failed.has(row.scope);
          return (
            // biome-ignore lint/a11y/useKeyWithClickEvents: keys are handled once, on the tree
            <div
              key={row.key}
              {...common}
              role="treeitem"
              tabIndex={row.key === stop ? 0 : -1}
              aria-selected="false"
              onClick={() => onMore(row.scope)}
              className={cn(
                rowBase,
                hoverable,
                "text-muted-foreground underline-offset-4 hover:text-foreground",
              )}
            >
              <span aria-hidden="true" className="size-4 shrink-0" />
              <span className={cn("truncate", bad && "text-destructive")}>
                {bad ? "Couldn't load more. Try again" : "Show more files"}
              </span>
            </div>
          );
        }
        const open = row.path === selected;
        return (
          <Link
            key={row.key}
            {...common}
            role="treeitem"
            tabIndex={row.key === stop ? 0 : -1}
            to="/libraries/$owner/$repo"
            params={{ owner, repo }}
            search={{ version, path: row.path, tags }}
            aria-selected={open}
            onClick={onOpen}
            title={`${row.title}\n${row.path}`}
            className={cn(
              rowBase,
              "py-1",
              open ? "bg-mark/10 text-foreground ring-1 ring-mark/25" : hoverable,
            )}
          >
            <span aria-hidden="true" className="size-4 shrink-0" />
            <span className="min-w-0">
              <span className={cn("block truncate leading-snug", open && "font-medium")}>
                {row.title}
              </span>
              <span className="block truncate text-xs leading-snug text-muted-foreground">
                <span className="sr-only">File </span>
                {row.name}
                {row.tags.length > 0 && (
                  <>
                    <span aria-hidden="true"> · </span>
                    <span className="sr-only">, tags </span>
                    {row.tags.join(", ")}
                  </>
                )}
              </span>
            </span>
          </Link>
        );
      })}
    </div>
  );
}
