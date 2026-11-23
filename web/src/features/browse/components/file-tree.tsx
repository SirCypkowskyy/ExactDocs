import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, CircleAlert } from "lucide-react";
import { type KeyboardEvent, memo, useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { Spinner } from "@/shared/ui/spinner";
import { type Row, showFileName } from "../model/browse";

type ScopeState = "idle" | "paging" | "error";

interface FileTreeProps {
  owner: string;
  repo: string;
  version: string;
  tags: string | undefined;
  /** The open article's path. */
  selected: string | undefined;
  rows: readonly Row[];
  /** Whether a listing is fetching its next page, or failed. */
  scopeState: (scope: string) => ScopeState;
  label: string;
  onToggle: (folder: string, open?: boolean) => void;
  onMore: (scope: string) => void;
  onOpen: () => void;
}

const INDENT = 12;
const MAX_INDENT_LEVELS = 6;
const rowBase =
  "flex min-h-11 w-full cursor-pointer items-center gap-1.5 rounded-md pr-2 text-left text-body outline-none transition-colors duration-(--dur-fast) focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring lg:min-h-8 lg:text-body";
const hoverable = "[@media(hover:hover)]:hover:bg-accent";

const indent = (depth: number) => ({
  paddingLeft: `${Math.min(depth, MAX_INDENT_LEVELS) * INDENT + 8}px`,
});

/** Rows are plain data of primitives: equal fields mean an equal row. */
function sameRow(a: Row, b: Row): boolean {
  const x = a as unknown as Record<string, unknown>;
  const y = b as unknown as Record<string, unknown>;
  const keys = Object.keys(x);
  return keys.length === Object.keys(y).length && keys.every((k) => x[k] === y[k]);
}

interface TreeRowProps {
  row: Row;
  stop: boolean;
  selected: boolean;
  state: ScopeState;
  owner: string;
  repo: string;
  version: string;
  tags: string | undefined;
  onToggle: (folder: string, open?: boolean) => void;
  onMore: (scope: string) => void;
  onOpen: () => void;
  onFocusRow: (key: string) => void;
}

type FolderRow = Extract<Row, { kind: "folder" }>;
type FileRow = Extract<Row, { kind: "file" }>;
type PagerRow = Extract<Row, { kind: "more" | "failed" }>;

/** What every focusable row shares: its key, depth, tab stop and focus tracking. */
function rowProps(row: Row, stop: boolean, onFocusRow: (key: string) => void) {
  return {
    "data-key": row.key,
    "aria-level": row.depth + 1,
    tabIndex: stop ? 0 : -1,
    onFocus: () => onFocusRow(row.key),
    style: indent(row.depth),
  };
}

function Folder({
  row,
  stop,
  onToggle,
  onFocusRow,
}: Pick<TreeRowProps, "stop" | "onToggle" | "onFocusRow"> & { row: FolderRow }) {
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: keys are handled once, on the tree
    <div
      {...rowProps(row, stop, onFocusRow)}
      role="treeitem"
      tabIndex={stop ? 0 : -1}
      aria-posinset={row.pos}
      aria-setsize={row.size}
      aria-expanded={row.open}
      aria-selected="false"
      onClick={() => onToggle(row.path)}
      className={cn(rowBase, hoverable)}
      title={row.path}
    >
      <ChevronRight
        aria-hidden="true"
        className={cn(
          "size-4 shrink-0 text-muted-foreground transition-transform duration-(--dur) ease-(--ease-out) motion-reduce:transition-none",
          row.open && "rotate-90",
        )}
      />
      <span className="truncate font-medium">{row.name}</span>
    </div>
  );
}

function pagerText(row: PagerRow, state: ScopeState, bad: boolean): string {
  const where = row.scope ? row.scope.split("/").pop() : "";
  if (bad) return `Couldn't load ${where || "more files"}. Try again`;
  if (state === "paging") return "Loading more";
  return where ? `Show more in ${where}` : "Show more files";
}

function Pager({
  row,
  stop,
  state,
  onMore,
  onFocusRow,
}: Pick<TreeRowProps, "stop" | "state" | "onMore" | "onFocusRow"> & { row: PagerRow }) {
  const bad = row.kind === "failed" || state === "error";
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: keys are handled once, on the tree
    <div
      {...rowProps(row, stop, onFocusRow)}
      role="treeitem"
      tabIndex={stop ? 0 : -1}
      aria-selected="false"
      aria-busy={state === "paging"}
      onClick={() => onMore(row.scope)}
      className={cn(
        rowBase,
        hoverable,
        "underline-offset-4 hover:underline focus-visible:underline",
        bad ? "text-destructive" : "text-foreground",
      )}
    >
      {bad ? (
        <CircleAlert aria-hidden="true" className="size-4 shrink-0" />
      ) : state === "paging" ? (
        <Spinner className="text-muted-foreground" />
      ) : (
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-route" />
      )}
      <span className="truncate">{pagerText(row, state, bad)}</span>
    </div>
  );
}

function File({
  row,
  stop,
  selected,
  owner,
  repo,
  version,
  tags,
  onOpen,
  onFocusRow,
}: Omit<TreeRowProps, "row" | "state" | "onToggle" | "onMore"> & { row: FileRow }) {
  return (
    <Link
      {...rowProps(row, stop, onFocusRow)}
      role="treeitem"
      tabIndex={stop ? 0 : -1}
      aria-posinset={row.pos}
      aria-setsize={row.size}
      to="/libraries/$owner/$repo"
      params={{ owner, repo }}
      search={{ version, path: row.path, tags }}
      aria-selected={selected}
      aria-current={selected ? "page" : undefined}
      onClick={onOpen}
      title={`${row.title}\n${row.path}`}
      className={cn(rowBase, "py-1", selected ? "bg-route-soft font-medium" : hoverable)}
    >
      <span aria-hidden="true" className="size-4 shrink-0" />
      <span className="min-w-0">
        <span className="block truncate leading-snug">{row.title}</span>
        {showFileName(row.title, row.name) && (
          <span className="block truncate font-mono text-small leading-snug text-muted-foreground">
            <span className="sr-only">File </span>
            {row.name}
          </span>
        )}
      </span>
    </Link>
  );
}

function Loading({ depth }: { depth: number }) {
  return (
    <div
      role="treeitem"
      tabIndex={-1}
      aria-selected="false"
      aria-disabled="true"
      aria-level={depth + 1}
      style={indent(depth)}
      className="flex min-h-9 items-center gap-2 text-body text-muted-foreground"
    >
      <Spinner className="ml-[18px] size-3.5" />
      Loading
    </div>
  );
}

/** One row; it re-renders only when its own data, tab stop or selection changes. */
const TreeRow = memo(
  function TreeRow(props: TreeRowProps) {
    const { row } = props;
    if (row.kind === "loading") return <Loading depth={row.depth} />;
    if (row.kind === "folder") return <Folder {...props} row={row} />;
    if (row.kind === "file") return <File {...props} row={row} />;
    return <Pager {...props} row={row} />;
  },
  (a, b) =>
    sameRow(a.row, b.row) &&
    a.stop === b.stop &&
    a.selected === b.selected &&
    a.state === b.state &&
    a.version === b.version &&
    a.tags === b.tags &&
    a.onToggle === b.onToggle &&
    a.onMore === b.onMore &&
    a.onOpen === b.onOpen,
);

const treeItems = (tree: HTMLElement | null) => [
  ...(tree?.querySelectorAll<HTMLElement>("[role=treeitem][data-key]") ?? []),
];
const focusRow = (tree: HTMLElement | null, key: string | undefined) =>
  treeItems(tree)
    .find((e) => e.dataset.key === key)
    ?.focus();

const labelOf = (row: Row) =>
  row.kind === "folder" ? row.name : row.kind === "file" ? row.title : "";

/**
 * A file tree with the WAI-ARIA tree pattern: one tab stop, arrows move and open/close, Home and
 * End jump, Enter or Space opens, letters jump to the next name, `*` opens the siblings. Rows are a
 * flat list with `aria-level`, so closed folders cost no DOM and large versions stay cheap; they
 * only re-render when their own data changes.
 */
export function FileTree({
  owner,
  repo,
  version,
  tags,
  selected,
  rows,
  scopeState,
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

  const items = () => treeItems(tree.current);
  const focusKey = (key: string | undefined) => focusRow(tree.current, key);

  // After "Show more" the row that was activated is gone: keep the reader's place by moving
  // focus to the first row the new page added.
  const pending = useRef<{
    keys: ReadonlySet<string>;
    more: string;
    anchor: string | undefined;
  } | null>(null);
  const latest = useRef(rows);
  useEffect(() => {
    latest.current = rows;
  }, [rows]);
  const more = useCallback(
    (scope: string) => {
      const all = latest.current;
      const at = all.findIndex((r) => r.kind !== "loading" && "scope" in r && r.scope === scope);
      pending.current = {
        keys: new Set(all.map((r) => r.key)),
        more: all[at]?.key ?? "",
        anchor: all[at - 1]?.key,
      };
      onMore(scope);
    },
    [onMore],
  );
  useEffect(() => {
    const wait = pending.current;
    if (!wait) return;
    const fresh = rows.find(
      (r) => (r.kind === "file" || r.kind === "folder") && !wait.keys.has(r.key),
    );
    const gone = !rows.some((r) => r.key === wait.more);
    // New rows get focus; when the page only added rows inside closed folders, the row above.
    if (fresh) focusRow(tree.current, fresh.key);
    else if (gone) focusRow(tree.current, wait.anchor);
    else return;
    pending.current = null;
  }, [rows]);

  // The open article scrolls into view once, when its row first exists.
  const scrolled = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!selected || scrolled.current === selected) return;
    const row = rows.find((r) => r.kind === "file" && r.path === selected);
    if (!row) return;
    scrolled.current = selected;
    treeItems(tree.current)
      .find((e) => e.dataset.key === row.key)
      ?.scrollIntoView({ block: "nearest" });
  }, [rows, selected]);

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
      case "ArrowRight": {
        if (row?.kind !== "folder") return;
        if (!row.open) onToggle(row.path, true);
        else {
          // Only into the folder's own rows; an empty or still loading folder has none yet.
          const next = focusable[focusable.findIndex((r) => r.key === row.key) + 1];
          if (next && next.depth === row.depth + 1) go(index + 1);
        }
        break;
      }
      case "ArrowLeft":
        if (row?.kind === "folder" && row.open) onToggle(row.path, false);
        else if (row && "parent" in row && row.parent) focusKey(`d:${row.parent}`);
        break;
      case "*":
        if (row?.kind !== "folder" && row?.kind !== "file") return;
        for (const r of rows) {
          if (r.kind === "folder" && r.parent === row.parent && !r.open) onToggle(r.path, true);
        }
        break;
      case " ":
      case "Enter":
        // A link already opens on Enter; Space is the one key it ignores.
        if (row?.kind === "file" && event.key === "Enter") return;
        current.click();
        break;
      default: {
        // Type-ahead: a letter jumps to the next name that starts with it.
        if (event.key.length !== 1 || !/[\p{L}\p{N}]/u.test(event.key)) return;
        const letter = event.key.toLowerCase();
        const named = focusable.filter((r) => labelOf(r) !== "");
        const from = named.findIndex((r) => r.key === current.dataset.key);
        const hit = [...named.slice(from + 1), ...named.slice(0, from + 1)].find((r) =>
          labelOf(r).toLowerCase().startsWith(letter),
        );
        if (!hit) return;
        focusKey(hit.key);
      }
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
      {rows.map((row) => (
        <TreeRow
          key={row.key}
          row={row}
          stop={row.key === stop}
          selected={row.kind === "file" && row.path === selected}
          state={row.kind === "more" || row.kind === "failed" ? scopeState(row.scope) : "idle"}
          owner={owner}
          repo={repo}
          version={version}
          tags={tags}
          onToggle={onToggle}
          onMore={more}
          onOpen={onOpen}
          onFocusRow={setActive}
        />
      ))}
    </div>
  );
}
