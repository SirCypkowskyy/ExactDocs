import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type Table,
  useReactTable,
  type VisibilityState,
} from "@tanstack/react-table";
import { useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "./button";
import { SortHeader } from "./data-table/columns";
import { sortingOf } from "./data-table/table-search";
import { messages } from "./messages";
import { Skeleton } from "./skeleton";

/*
 * DataTable v1: "Load more" tables. The pages not yet on DataTable v2 (`./data-table/`: numbered
 * pages, faceted filters, row actions) use these; the sort header, the Columns menu and the search
 * box are v2's, re-exported here so both look alike. Remove this file once the last page moved.
 */

export { ColumnsMenu, SortHeader } from "./data-table/columns";
export { SearchFilter } from "./data-table/search-filter";
export { sortingOf };

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
  const t = useMessages(messages).table;
  return (
    <div className="flex items-center gap-3 pt-4 text-small text-muted-foreground">
      <p className="num">{t.showing(shown, total)}</p>
      {hasMore && (
        <Button variant="outline" onClick={onLoadMore} disabled={loadingMore}>
          {t.loadMore}
        </Button>
      )}
    </div>
  );
}
