import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Check, Copy, LibraryBig } from "lucide-react";
import { useEffect, useEffectEvent, useId, useState } from "react";
import { toast } from "sonner";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { EmptyState } from "@/shared/ui/page";
import { codeWell } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import { type SyncState, useNow } from "../hooks/use-libraries";
import type { Library } from "../model/library";
import { isFiltered, type ListView } from "../model/list-view";
import { AddLibraryLink } from "./add-library-link";
import { columns, LibraryRow } from "./library-row";

interface LibrariesListProps {
  libraries: readonly Library[];
  syncs: ReadonlyMap<string, SyncState>;
  view: ListView;
  onView: (view: ListView) => void;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

/** Sorting is done by the API, so the table only holds the state and draws the headers. */
const columnDefs: ColumnDef<Library>[] = [
  { accessorKey: "title", header: "Library" },
  { accessorKey: "version_count", header: "Versions", sortDescFirst: true },
  { accessorKey: "last_imported_at", header: "Last imported", sortDescFirst: true },
  { id: "sync", header: "Sync", enableSorting: false },
];
const sortingOf = (sort: string | undefined): SortingState =>
  sort ? [{ id: sort.replace(/^-/, ""), desc: sort.startsWith("-") }] : [];

const COMMAND = "exactdocs add https://github.com/acme/payments --path docs/";

function FirstRun() {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(COMMAND).then(() => {
      setCopied(true);
      toast.success("Command copied");
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <EmptyState
      icon={<LibraryBig aria-hidden="true" />}
      title="No libraries yet"
      action={<AddLibraryLink />}
      className="max-w-2xl"
    >
      <p>
        Add a git repository and choose its Markdown docs. Agents and people then read them at the
        exact version you import.
      </p>
      <p className="mt-4">Or index one from the command line:</p>
      <div className="mt-2 flex items-start gap-1">
        <pre className={cn(codeWell, "min-w-0 flex-1 whitespace-pre-wrap")}>
          <code>{COMMAND}</code>
        </pre>
        <Button variant="ghost" size="icon" onClick={copy} aria-label="Copy command">
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        </Button>
      </div>
    </EmptyState>
  );
}

function Toolbar({
  view,
  onView,
  text,
  setText,
}: Pick<LibrariesListProps, "view" | "onView"> & { text: string; setText: (v: string) => void }) {
  const id = useId();
  const commit = useEffectEvent((value: string) => {
    if ((view.q ?? "") !== value.trim()) onView({ ...view, q: value.trim() || undefined });
  });
  // Typing waits a moment before it asks the server.
  useEffect(() => {
    const t = setTimeout(() => commit(text), 300);
    return () => clearTimeout(t);
  }, [text]);
  return (
    <search className="mb-4 flex flex-wrap items-end gap-3">
      <div className="flex min-w-0 flex-1 basis-60 flex-col gap-2">
        <label htmlFor={`${id}-q`} className="text-body font-medium">
          Find a library
        </label>
        <Input
          id={`${id}-q`}
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Name, ID or description"
        />
      </div>
      <div className="w-40">
        <SelectField
          id={`${id}-ai`}
          label="AI"
          value={view.ai ?? ""}
          onChange={(e) =>
            onView({
              ...view,
              ai: e.target.value === "" ? undefined : (e.target.value as "on" | "off"),
            })
          }
        >
          <option value="">Any</option>
          <option value="on">AI on</option>
          <option value="off">AI off</option>
        </SelectField>
      </div>
      <div className="w-48 md:hidden">
        <SelectField
          id={`${id}-sort`}
          label="Sort by"
          value={view.sort ?? ""}
          onChange={(e) => onView({ ...view, sort: e.target.value || undefined })}
        >
          <option value="">Default</option>
          <option value="title">Name, A to Z</option>
          <option value="-title">Name, Z to A</option>
          <option value="-last_imported_at">Recently imported</option>
          <option value="last_imported_at">Least recently imported</option>
          <option value="-version_count">Most versions</option>
          <option value="version_count">Fewest versions</option>
        </SelectField>
      </div>
    </search>
  );
}

export function LibrariesList({
  libraries,
  syncs,
  view,
  onView,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
}: LibrariesListProps) {
  const now = useNow();
  const [text, setText] = useState(view.q ?? "");
  const table = useReactTable({
    data: libraries as Library[],
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (library) => library.id,
    manualSorting: true,
    manualFiltering: true,
    state: { sorting: sortingOf(view.sort) },
    onSortingChange: (updater) => {
      const [next] = typeof updater === "function" ? updater(sortingOf(view.sort)) : updater;
      onView({ ...view, sort: next ? `${next.desc ? "-" : ""}${next.id}` : undefined });
    },
  });
  if (total === 0 && !isFiltered(view)) return <FirstRun />;
  return (
    <div>
      <Toolbar view={view} onView={onView} text={text} setText={setText} />
      {libraries.length === 0 ? (
        <EmptyState title="No libraries match" className="max-w-2xl">
          <p>Nothing matches these filters.</p>
          <Button
            variant="ghost"
            className="mt-3"
            onClick={() => {
              setText("");
              onView({ sort: view.sort });
            }}
          >
            Clear filters
          </Button>
        </EmptyState>
      ) : (
        <>
          <div
            className={`hidden border-b border-rule pb-2 pl-[3.25rem] text-small text-muted-foreground ${columns}`}
          >
            {table.getHeaderGroups()[0]?.headers.map((header) => {
              const dir = header.column.getIsSorted();
              const label = flexRender(header.column.columnDef.header, header.getContext());
              if (!header.column.getCanSort()) return <span key={header.id}>{label}</span>;
              return (
                <span key={header.id}>
                  <button
                    type="button"
                    aria-label={`Sort by ${String(header.column.columnDef.header)}${dir ? `, sorted ${dir === "asc" ? "ascending" : "descending"}` : ""}`}
                    onClick={header.column.getToggleSortingHandler()}
                    className="inline-flex cursor-pointer items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {label}
                    {dir === "asc" ? (
                      <ArrowUp aria-hidden="true" className="size-3.5" />
                    ) : dir === "desc" ? (
                      <ArrowDown aria-hidden="true" className="size-3.5" />
                    ) : (
                      <ArrowUpDown aria-hidden="true" className="size-3.5 opacity-50" />
                    )}
                  </button>
                </span>
              );
            })}
          </div>
          <ul aria-label="Libraries" className="divide-y divide-rule">
            {table.getRowModel().rows.map(({ original: library }) => (
              <LibraryRow
                key={library.id}
                library={library}
                sync={syncs.get(library.id) ?? { status: "pending" }}
                now={now}
              />
            ))}
            {loadingMore && (
              <li aria-hidden="true" className="py-4">
                <Skeleton className="h-12 w-full" />
              </li>
            )}
          </ul>
          <div className="flex items-center gap-3 pt-4 text-small text-muted-foreground">
            <p className="num">
              Showing {libraries.length} of {total}
            </p>
            {hasMore && (
              <Button variant="outline" onClick={onLoadMore} disabled={loadingMore}>
                Load more
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
