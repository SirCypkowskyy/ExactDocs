import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type Header,
  type RowData,
  type SortingState,
  type Table,
  useReactTable,
  type VisibilityState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Columns3 } from "lucide-react";
import { useEffect, useEffectEvent, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { Button } from "./button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { Input } from "./input";
import { Skeleton } from "./skeleton";

declare module "@tanstack/react-table" {
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Classes of the column's cells, e.g. `max-md:hidden` to drop it on narrow screens. */
    className?: string;
  }
}

/** The table's sorting from an API `sort` value (a field, `-` in front for descending). */
export const sortingOf = (sort: string | undefined): SortingState =>
  sort ? [{ id: sort.replace(/^-/, ""), desc: sort.startsWith("-") }] : [];

interface ServerTableOptions<T> {
  data: readonly T[];
  columns: ColumnDef<T>[];
  getRowId: (row: T) => string;
  sort: string | undefined;
  onSort: (sort: string | undefined) => void;
}

/**
 * A table whose rows the server sorts and filters (manual mode): it holds the sort, which lives in
 * the URL, and which columns are shown.
 */
export function useServerTable<T>({
  data,
  columns,
  getRowId,
  sort,
  onSort,
}: ServerTableOptions<T>) {
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  return useReactTable({
    data: data as T[],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId,
    manualSorting: true,
    manualFiltering: true,
    // The server pages. Left on, every new `data` array queues a page reset (a state update),
    // which renders again with a new array: an endless render loop once anything re-renders.
    manualPagination: true,
    autoResetAll: false,
    state: { sorting: sortingOf(sort), columnVisibility },
    onColumnVisibilityChange: setColumnVisibility,
    onSortingChange: (updater) => {
      const [next] = typeof updater === "function" ? updater(sortingOf(sort)) : updater;
      onSort(next ? `${next.desc ? "-" : ""}${next.id}` : undefined);
    },
  });
}

/** A column header; a sortable one is a button that says how the column is sorted. */
export function SortHeader<T>({ header }: { header: Header<T, unknown> }) {
  const label = flexRender(header.column.columnDef.header, header.getContext());
  if (!header.column.getCanSort()) return <>{label}</>;
  const dir = header.column.getIsSorted();
  return (
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
  );
}

/** Show or hide the columns that can be hidden. */
export function ColumnsMenu<T>({ table }: { table: Table<T> }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Columns3 aria-hidden="true" />
          Columns
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Show columns</DropdownMenuLabel>
        {table
          .getAllLeafColumns()
          .filter((c) => c.getCanHide())
          .map((column) => (
            <DropdownMenuCheckboxItem
              key={column.id}
              checked={column.getIsVisible()}
              onCheckedChange={(on) => column.toggleVisibility(on)}
              onSelect={(e) => e.preventDefault()}
            >
              {String(column.columnDef.header)}
            </DropdownMenuCheckboxItem>
          ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The rows of a server-side table, with a skeleton row while the next page is on its way. */
export function DataTable<T>({
  table,
  label,
  loadingMore,
}: {
  table: Table<T>;
  label: string;
  loadingMore: boolean;
}) {
  const visible = table.getVisibleLeafColumns().length;
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full border-collapse text-left text-body">
        <thead className="text-small text-muted-foreground">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="border-b border-rule">
              {group.headers.map((header) => (
                <th
                  key={header.id}
                  scope="col"
                  aria-sort={
                    header.column.getIsSorted() === "asc"
                      ? "ascending"
                      : header.column.getIsSorted() === "desc"
                        ? "descending"
                        : undefined
                  }
                  className={cn("py-2 pr-4 font-normal", header.column.columnDef.meta?.className)}
                >
                  <SortHeader header={header} />
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-rule">
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  className={cn("py-3 pr-4 align-top", cell.column.columnDef.meta?.className)}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
          {loadingMore && (
            <tr>
              <td colSpan={visible} className="py-3">
                <Skeleton className="h-8 w-full" />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** How many rows are shown of how many match, and the button for the next page. */
export function ListFooter({
  shown,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
}: {
  shown: number;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}) {
  return (
    <div className="flex items-center gap-3 pt-4 text-small text-muted-foreground">
      <p className="num">
        Showing {shown} of {total}
      </p>
      {hasMore && (
        <Button variant="outline" onClick={onLoadMore} disabled={loadingMore}>
          Load more
        </Button>
      )}
    </div>
  );
}

/**
 * A text filter that waits until typing pauses before it changes the view (and asks the server).
 * `value` is the filter in the view: when it changes elsewhere (Clear filters), the box follows.
 */
export function SearchFilter({
  id,
  label,
  placeholder,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  placeholder?: string | undefined;
  value: string | undefined;
  onCommit: (value: string | undefined) => void;
}) {
  const [text, setText] = useState(value ?? "");
  const [seen, setSeen] = useState(value);
  if (seen !== value) {
    setSeen(value);
    if (text.trim() !== (value ?? "")) setText(value ?? "");
  }
  const commit = useEffectEvent((next: string) => {
    if ((value ?? "") !== next.trim()) onCommit(next.trim() || undefined);
  });
  useEffect(() => {
    const t = setTimeout(() => commit(text), 300);
    return () => clearTimeout(t);
  }, [text]);
  return (
    <div className="flex min-w-0 flex-1 basis-60 flex-col gap-2">
      <label htmlFor={id} className="text-body font-medium">
        {label}
      </label>
      <Input
        id={id}
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
