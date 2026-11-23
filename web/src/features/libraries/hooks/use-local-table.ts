import {
  type ColumnDef,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type SortingState,
  type Updater,
  useReactTable,
  type VisibilityState,
} from "@tanstack/react-table";
import { useMemo, useRef, useState } from "react";
import {
  type PageSize,
  pageOf,
  rememberSize,
  sizesFor,
  sortingOf,
  sortOf,
  type TableConfig,
} from "@/shared/ui/data-table/table-search";
import type { DataTableModel, TableFilter } from "@/shared/ui/data-table/use-data-table";

/*
 * A DataTable v2 model in client mode whose view lives in this component, not in the URL: for a
 * table shown inside another page (a job's problems on the add page or in a library's settings),
 * where the URL already belongs to that page and its own table (`q`, `sort`, `page`, `size`).
 * Everything else is the kit's: the same toolbar, faceted filters, pagination and states.
 */

interface LocalView {
  q?: string | undefined;
  sort?: string | undefined;
  page: number;
  size: PageSize;
  values: Readonly<Record<string, readonly string[]>>;
}

const NONE: readonly never[] = [];

export function useLocalTable<T>({
  config,
  rows,
  columns,
  getRowId,
  filters = NONE,
}: {
  config: TableConfig;
  rows: readonly T[];
  columns: ColumnDef<T>[];
  getRowId: (row: T) => string;
  filters?: readonly TableFilter[];
}): DataTableModel<T> {
  const [view, setView] = useState<LocalView>(() => ({ ...pageOf({}, config), values: {} }));
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const frameRef = useRef<HTMLDivElement | null>(null);
  const filterIds = useMemo(() => new Set(filters.map((f) => f.id)), [filters]);
  // A filtered column matches "any of the picked values".
  const shaped = useMemo(
    () =>
      columns.map((c) => {
        const id = c.id ?? ("accessorKey" in c ? String(c.accessorKey) : undefined);
        return id && filterIds.has(id) && !c.filterFn
          ? ({ ...c, filterFn: "arrIncludesSome" } as ColumnDef<T>)
          : c;
      }),
    [columns, filterIds],
  );
  const sorting = sortingOf(view.sort ?? config.defaultSort);
  const columnFilters = Object.entries(view.values)
    .filter(([, values]) => values.length > 0)
    .map(([id, value]) => ({ id, value }));
  const data = useMemo(() => [...rows], [rows]);
  const table = useReactTable<T>({
    data,
    columns: shaped,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    autoResetAll: false,
    enableSortingRemoval: true,
    state: {
      sorting,
      columnVisibility,
      columnFilters,
      globalFilter: view.q ?? "",
      pagination: { pageIndex: view.page - 1, pageSize: view.size },
    },
    onSortingChange: (updater: Updater<SortingState>) => {
      const sort = sortOf(typeof updater === "function" ? updater(sorting) : updater);
      setView((v) => ({ ...v, sort: sort === config.defaultSort ? undefined : sort, page: 1 }));
    },
    onColumnVisibilityChange: setColumnVisibility,
  });
  const total = table.getFilteredRowModel().rows.length;
  const pageCount = Math.max(1, Math.ceil(total / view.size));
  // Rows can only go away with a filter, which goes back to page 1; clamp anyway.
  const page = Math.min(view.page, pageCount);
  const selected = (id: string) => view.values[id] ?? NONE;
  const filtered = Boolean(view.q) || Object.values(view.values).some((v) => v.length > 0);
  return {
    table,
    mode: "client",
    filters,
    params: NONE,
    page,
    size: view.size,
    sizes: sizesFor(config),
    total,
    pageCount,
    rows: table.getRowModel().rows,
    offset: (page - 1) * view.size,
    status: "ready",
    busy: false,
    canJump: true,
    filtered,
    viewKey: JSON.stringify([view.q, view.values, view.sort, page, view.size]),
    q: view.q,
    selected,
    param: () => undefined,
    counts: (id) => (filterIds.has(id) ? table.getColumn(id)?.getFacetedUniqueValues() : undefined),
    setQ: (q) => setView((v) => ({ ...v, q, page: 1 })),
    setFilter: (id, values) =>
      setView((v) => ({ ...v, values: { ...v.values, [id]: values }, page: 1 })),
    setParam: () => {},
    clearFilters: () => setView((v) => ({ ...v, q: undefined, values: {}, page: 1 })),
    goTo: (next) =>
      setView((v) => ({ ...v, page: Math.min(Math.max(1, Math.round(next)), pageCount) })),
    setSize: (size) => {
      rememberSize(config, size);
      setView((v) => ({ ...v, size, page: 1 }));
    },
    retry: () => {},
    frameRef,
  };
}
