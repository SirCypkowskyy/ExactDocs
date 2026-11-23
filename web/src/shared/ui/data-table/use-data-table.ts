import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  type ColumnDef,
  type ColumnFiltersState,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type Row,
  type SortingState,
  type Table,
  type Updater,
  useReactTable,
  type VisibilityState,
} from "@tanstack/react-table";
import type { LucideIcon } from "lucide-react";
import { type RefObject, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { pageQueryOptions, type ServerSource } from "./server-pages";
import {
  type PageSize,
  pageOf,
  rememberSize,
  sizesFor,
  sortingOf,
  sortOf,
  type TableConfig,
  type TableSearch,
  valuesOf,
} from "./table-search";

/*
 * DataTable v2's state (blocks-map §2.2): one hook for both modes.
 *
 * - Server mode (`source`): the API sorts, filters and pages; the hook shows one numbered page
 *   (server-pages.ts) and fetches the pages on either side ahead, so Previous and Next are instant.
 * - Client mode (`query`): a bounded list arrives in one request; TanStack sorts, filters, pages
 *   and counts the facets in the browser.
 *
 * Either way the view lives in the URL (table-search.ts): `q`, the filters, `sort`, `page`,
 * `size`. A new filter, sort or size goes back to page 1; the URL wins over the size remembered in
 * this browser. A filterable column is one the server filters (no client filter over one server
 * page: it would hide rows silently), a sortable one one the API sorts.
 */

export interface FilterOption {
  value: string;
  label: string;
  icon?: LucideIcon;
}

/** A faceted filter: a URL parameter whose values are picked from a list. */
export interface TableFilter {
  /** The URL (and API) parameter; in client mode also the column it filters. */
  id: string;
  title: string;
  options: readonly FilterOption[];
  /** One value at a time (a date preset) instead of several. */
  single?: boolean;
}

/** Another URL parameter that narrows the list (a library, a version): a chip and Clear all. */
export interface TableParam {
  id: string;
  title: string;
  /** Set the value in mono (an ID, a ref). */
  mono?: boolean;
}

/** What client mode needs of a query: a `useQuery` result whose data is the rows. */
export interface ClientQuery<T> {
  data: readonly T[] | undefined;
  isPending: boolean;
  isError: boolean;
  isPlaceholderData?: boolean;
  refetch: () => unknown;
}

interface BaseOptions<T> {
  config: TableConfig;
  /** The view as the route parsed it from the URL (`validateSearch`): its filters by name. */
  search: TableSearch;
  columns: ColumnDef<T>[];
  getRowId: (row: T) => string;
  filters?: readonly TableFilter[];
  params?: readonly TableParam[];
  /** Columns hidden until someone shows them in the Columns menu. */
  initialColumnVisibility?: VisibilityState;
}

export type DataTableOptions<T> = BaseOptions<T> &
  ({ source: ServerSource<T>; query?: never } | { query: ClientQuery<T>; source?: never });

export interface DataTableModel<T> {
  table: Table<T>;
  mode: "server" | "client";
  filters: readonly TableFilter[];
  params: readonly TableParam[];
  /** 1-based. */
  page: number;
  size: PageSize;
  sizes: readonly PageSize[];
  /** Rows that match across every page, once known. */
  total: number | undefined;
  /** At least 1. */
  pageCount: number;
  /** The rows of the shown page. */
  rows: Row<T>[];
  /** How many rows come before the shown page. */
  offset: number;
  status: "pending" | "error" | "ready";
  /** Rows of the previous view stay on screen while the new ones load. */
  busy: boolean;
  /** Any page can be reached in one step: Last is offered. */
  canJump: boolean;
  /** Any filter (the search box included) narrows the list. */
  filtered: boolean;
  /** Changes when what the rows answer changes (view, page or size), not on a refresh. */
  viewKey: string;
  q: string | undefined;
  selected: (filter: string) => readonly string[];
  param: (id: string) => string | undefined;
  /** Rows per value of a filter (client mode; the server does not count them). */
  counts: (filter: string) => ReadonlyMap<unknown, number> | undefined;
  setQ: (q: string | undefined) => void;
  setFilter: (filter: string, values: readonly string[]) => void;
  setParam: (id: string, value: string | undefined) => void;
  clearFilters: () => void;
  goTo: (page: number) => void;
  setSize: (size: PageSize) => void;
  retry: () => void;
  /** The table's frame: a page change scrolls its top into view. */
  frameRef: RefObject<HTMLDivElement | null>;
}

type Patch = Record<string, string | number | undefined>;

/** Writes part of the view to the URL, in the URL's form (`a,b` lists, no empty values). */
function useWriteSearch() {
  const navigate = useNavigate();
  return (patch: Patch, keepPage: boolean) => {
    const update = (prev: Record<string, unknown>) => {
      const next: Record<string, unknown> = { ...prev, ...patch };
      if (!keepPage) delete next.page;
      for (const [key, value] of Object.entries(next)) {
        if (Array.isArray(value)) next[key] = value.length ? value.join(",") : undefined;
        if (next[key] === undefined || next[key] === "") delete next[key];
      }
      return next;
    };
    // The current path; only its search changes. Scroll stays where it is (pagination scrolls the
    // table's own top into view).
    void navigate({ search: update, replace: true, resetScroll: false } as never);
  };
}

const columnId = <T>(c: ColumnDef<T>): string | undefined =>
  c.id ?? ("accessorKey" in c && typeof c.accessorKey === "string" ? c.accessorKey : undefined);

export function useDataTable<T>(options: DataTableOptions<T>): DataTableModel<T> {
  const { config, search, getRowId, source, query: clientQuery } = options;
  const values = search as Readonly<Record<string, unknown>>;
  const filters = options.filters ?? [];
  const params = options.params ?? [];
  const mode = source ? "server" : "client";
  const { page, size } = pageOf(search, config);
  const sizes = sizesFor(config);
  const write = useWriteSearch();
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    options.initialColumnVisibility ?? {},
  );

  const selected = (id: string) => valuesOf(values[id]);
  const sorting = sortingOf(search.sort ?? config.defaultSort);
  const filterKey = JSON.stringify(filters.map((f) => [f.id, selected(f.id)]));

  // Server mode: one numbered page, its neighbours fetched ahead.
  const pageQuery = useQuery({
    ...pageQueryOptions((source ?? NO_SOURCE) as ServerSource<T>, page, size),
    enabled: Boolean(source),
  });

  // Client mode: facet columns filter by "any of these values".
  const filterIds = useMemo(() => new Set(filters.map((f) => f.id)), [filters]);
  const columns = useMemo(
    () =>
      mode === "client"
        ? options.columns.map((c) => {
            const id = columnId(c);
            return id && filterIds.has(id) && !c.filterFn
              ? ({ ...c, filterFn: "arrIncludesSome" } as ColumnDef<T>)
              : c;
          })
        : options.columns,
    [mode, options.columns, filterIds],
  );
  const columnIds = useMemo(() => new Set(columns.map(columnId)), [columns]);
  const columnFilters: ColumnFiltersState = useMemo(
    () =>
      (JSON.parse(filterKey) as [string, string[]][])
        .filter(([id, values]) => values.length > 0 && columnIds.has(id))
        .map(([id, value]) => ({ id, value })),
    [filterKey, columnIds],
  );

  const serverRows = pageQuery.data?.rows;
  const data = useMemo(
    () => ((mode === "server" ? serverRows : clientQuery?.data) ?? []) as T[],
    [mode, serverRows, clientQuery?.data],
  );

  const setSort = (updater: Updater<SortingState>) => {
    const next = typeof updater === "function" ? updater(sorting) : updater;
    const sort = sortOf(next);
    write({ sort: sort === config.defaultSort ? undefined : sort }, false);
  };

  const table = useReactTable<T>({
    data,
    columns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    ...(mode === "client" && {
      getSortedRowModel: getSortedRowModel(),
      getFilteredRowModel: getFilteredRowModel(),
      getPaginationRowModel: getPaginationRowModel(),
      getFacetedRowModel: getFacetedRowModel(),
      getFacetedUniqueValues: getFacetedUniqueValues(),
    }),
    manualSorting: mode === "server",
    manualFiltering: mode === "server",
    manualPagination: mode === "server",
    // The view lives in the URL: never let the table reset it on its own (a reset on new data
    // would be a state update per render, and a URL write).
    autoResetAll: false,
    enableSortingRemoval: true,
    ...(mode === "server" && { rowCount: pageQuery.data?.total ?? -1 }),
    state: {
      sorting,
      columnVisibility,
      columnFilters,
      globalFilter: search.q ?? "",
      pagination: { pageIndex: page - 1, pageSize: size },
    },
    onSortingChange: setSort,
    onColumnVisibilityChange: setColumnVisibility,
  });

  const total =
    mode === "server"
      ? pageQuery.data?.total
      : clientQuery?.data
        ? table.getFilteredRowModel().rows.length
        : undefined;
  const pageCount = Math.max(1, Math.ceil((total ?? 0) / size));
  const status =
    mode === "server"
      ? pageQuery.data
        ? "ready"
        : pageQuery.isError
          ? "error"
          : "pending"
      : clientQuery?.data
        ? "ready"
        : clientQuery?.isError
          ? "error"
          : "pending";

  const goTo = (next: number) => {
    const target = Math.min(Math.max(1, Math.round(next)), pageCount);
    write({ page: target > 1 ? target : undefined, size: sizeParam(size) }, true);
  };

  // A page past the end (rows went away, a hand-edited URL): show the last one instead.
  const clamp = useEffectEvent(() => goTo(pageCount));
  useEffect(() => {
    if (status === "ready" && total !== undefined && page > pageCount) clamp();
  }, [status, total, page, pageCount]);

  // Server mode: the pages on either side, fetched while the reader looks at this one.
  const client = useQueryClient();
  const sourceKey = JSON.stringify(source?.key ?? null);
  const loaded = Boolean(pageQuery.data) && !pageQuery.isPlaceholderData;
  const neighbours =
    source && loaded
      ? [page + 1, page - 1]
          .filter((n) => n >= 1 && n <= pageCount)
          .map((n) => pageQueryOptions(source, n, size))
      : [];
  const neighboursKey = JSON.stringify(neighbours.map((n) => n.queryKey));
  const prefetch = useEffectEvent(() => {
    for (const neighbour of neighbours) {
      if (client.getQueryData(neighbour.queryKey) === undefined) {
        void client.prefetchQuery(neighbour);
      }
    }
  });
  useEffect(() => {
    if (neighboursKey !== "[]") prefetch();
  }, [neighboursKey]);

  const filtered =
    Boolean(search.q) ||
    filters.some((f) => selected(f.id).length > 0) ||
    params.some((p) => values[p.id] !== undefined);

  return {
    table,
    mode,
    filters,
    params,
    page,
    size,
    sizes,
    total,
    pageCount,
    rows: table.getRowModel().rows,
    offset: (page - 1) * size,
    status,
    busy:
      mode === "server"
        ? Boolean(pageQuery.isPlaceholderData)
        : Boolean(clientQuery?.isPlaceholderData),
    canJump: mode === "client" || source?.paging === "offset",
    filtered,
    viewKey: JSON.stringify([sourceKey, search.q, filterKey, search.sort, page, size]),
    q: search.q,
    selected,
    param: (id) => {
      const value = values[id];
      return typeof value === "string" && value ? value : undefined;
    },
    counts: (id) =>
      mode === "client" && columnIds.has(id)
        ? table.getColumn(id)?.getFacetedUniqueValues()
        : undefined,
    setQ: (q) => write({ q, size: sizeParam(size) }, false),
    setFilter: (id, values) =>
      write({ [id]: values.length ? values.join(",") : undefined, size: sizeParam(size) }, false),
    setParam: (id, value) => write({ [id]: value, size: sizeParam(size) }, false),
    clearFilters: () =>
      write(
        Object.fromEntries([
          ["q", undefined],
          ...filters.map((f) => [f.id, undefined]),
          ...params.map((p) => [p.id, undefined]),
          ["size", sizeParam(size)],
        ]),
        false,
      ),
    goTo,
    setSize: (next) => {
      rememberSize(config, next);
      write({ size: sizeParam(next) }, false);
    },
    retry: () => void (mode === "server" ? pageQuery.refetch() : clientQuery?.refetch()),
    frameRef,
  };
}

/** The size as the URL writes it: left out at the default, so most links stay short. */
const sizeParam = (size: PageSize) => (size === 20 ? undefined : size);

/** Stands in for the source in client mode (the query is disabled). */
const NO_SOURCE: ServerSource<never> = {
  key: ["data-table", "no-source"],
  fetchPage: () => Promise.reject(new Error("no source")),
};
