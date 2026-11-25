import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type RowData,
  type SortingState,
  type Updater,
  useTable,
} from "@tanstack/react-table";
import type { LucideIcon } from "lucide-react";
import { type RefObject, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { type ColumnDef, features, type Row, type Table } from "./features";
import { lastJumpPage, pageQueryOptions, type ServerSource } from "./server-pages";
import {
  type PageSize,
  pageOf,
  parseTableSearch,
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
 *   (server-pages.ts: by offset, a page is one request) and fetches the pages on either side
 *   ahead, so Previous and Next are instant.
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
  /** The value in words for its chip (an account's name for its ID); the value itself if left out. */
  format?: (value: string) => string;
}

/** What client mode needs of a query: a `useQuery` result whose data is the rows. */
export interface ClientQuery<T extends RowData> {
  data: readonly T[] | undefined;
  isPending: boolean;
  isError: boolean;
  /** Why it failed, for a page that explains it (`model.error`). */
  error?: unknown;
  isPlaceholderData?: boolean;
  refetch: () => unknown;
}

interface BaseOptions<T extends RowData> {
  config: TableConfig;
  /** The view as the route parsed it from the URL (`validateSearch`): its filters by name. */
  search: TableSearch;
  columns: ColumnDef<T>[];
  getRowId: (row: T) => string;
  filters?: readonly TableFilter[];
  params?: readonly TableParam[];
  /** Columns hidden until someone shows them in the Columns menu. */
  initialColumnVisibility?: ColumnVisibilityState;
  /**
   * The URL parameter the search box writes, when `q` already belongs to the page (the library
   * page's `q` is its search, so its articles table filters by `filter`). The route hands its
   * value to the table as `search.q`.
   */
  qParam?: string;
}

export type DataTableOptions<T extends RowData> = BaseOptions<T> &
  ({ source: ServerSource<T>; query?: never } | { query: ClientQuery<T>; source?: never });

/** A table inside another page whose URL is not its own: the view lives in the component. */
export type LocalDataTableOptions<T extends RowData> = Omit<BaseOptions<T>, "search" | "qParam"> & {
  /** The whole bounded list (client mode). */
  rows: readonly T[];
};

export interface DataTableModel<T extends RowData> {
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
  /** Why the rows failed to load (`status` is "error"), for a page that explains it. */
  error: unknown;
  /** Rows of the previous view stay on screen while the new ones load. */
  busy: boolean;
  /**
   * Pages can be reached in one step (client mode, or a source that pages by offset): numbered
   * jumps and Last are offered.
   */
  canJump: boolean;
  /**
   * The farthest page a jump reaches: `pageCount`, unless the list goes past the API's offset
   * bound (more than 10,000 rows); the pages after it are reached with Next.
   */
  lastJump: number;
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

/** Writes part of the view (to the URL, or to the component in local mode). */
type Write = (patch: Patch, keepPage: boolean) => void;

/** Applies part of the view in the URL's form (`a,b` lists, no empty values). */
function patched(prev: Record<string, unknown>, patch: Patch, keepPage: boolean) {
  const next: Record<string, unknown> = { ...prev, ...patch };
  if (!keepPage) delete next.page;
  for (const [key, value] of Object.entries(next)) {
    if (Array.isArray(value)) next[key] = value.length ? value.join(",") : undefined;
    if (next[key] === undefined || next[key] === "") delete next[key];
  }
  return next;
}

/** Writes part of the view to the URL. */
function useWriteSearch(): Write {
  const navigate = useNavigate();
  return (patch, keepPage) =>
    // The current path and its hash (a section the page scrolled to); only its search changes.
    // Scroll stays where it is (pagination scrolls the table's own top into view).
    void navigate({
      search: (prev: Record<string, unknown>) => patched(prev, patch, keepPage),
      hash: true,
      replace: true,
      resetScroll: false,
    } as never);
}

const columnId = <T extends RowData>(c: ColumnDef<T>): string | undefined =>
  c.id ?? ("accessorKey" in c && typeof c.accessorKey === "string" ? c.accessorKey : undefined);

const NONE: readonly never[] = [];

type Status = DataTableModel<RowData>["status"];

/** Loaded, failed, or still on its way (no rows yet). */
const statusOf = (data: unknown, isError: boolean | undefined): Status =>
  data ? "ready" : isError ? "error" : "pending";

/** The size as the URL writes it: left out at the default, so most links stay short. */
const sizeParam = (size: PageSize) => (size === 20 ? undefined : size);

/** Stands in for the source in client mode (the query is disabled). */
const NO_SOURCE: ServerSource<never> = {
  key: ["data-table", "no-source"],
  fetchPage: () => Promise.reject(new Error("no source")),
};

/** Client mode: a facet column filters by "any of these values" unless it says otherwise. */
function useTableColumns<T extends RowData>(
  mode: "server" | "client",
  columns: ColumnDef<T>[],
  filters: readonly TableFilter[],
) {
  const filterIds = useMemo(() => new Set(filters.map((f) => f.id)), [filters]);
  const shaped = useMemo(() => {
    if (mode === "server") return columns;
    return columns.map((c) => {
      const id = columnId(c);
      return id && filterIds.has(id) && !c.filterFn
        ? ({ ...c, filterFn: "arrHas" } as ColumnDef<T>)
        : c;
    });
  }, [mode, columns, filterIds]);
  const ids = useMemo(() => new Set(shaped.map(columnId)), [shaped]);
  return { columns: shaped, columnIds: ids };
}

/** Server mode: the pages on either side, fetched while the reader looks at this one. */
function usePrefetchNeighbours<T extends RowData>(
  source: ServerSource<T> | undefined,
  loaded: boolean,
  page: number,
  pageCount: number,
  size: PageSize,
) {
  const client = useQueryClient();
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
}

/** A page past the end (rows went away, a hand-edited URL): show the last one instead. */
function useClampPage(
  ready: boolean,
  page: number,
  pageCount: number,
  goTo: (page: number) => void,
) {
  const clamp = useEffectEvent(() => goTo(pageCount));
  useEffect(() => {
    if (ready && page > pageCount) clamp();
  }, [ready, page, pageCount]);
}

/** The setters of the view: each writes the URL, and all but paging go back to page 1. */
function viewSetters(
  write: Write,
  config: TableConfig,
  size: PageSize,
  filters: readonly TableFilter[],
  params: readonly TableParam[],
  qParam = "q",
) {
  const keep = sizeParam(size);
  return {
    setQ: (q: string | undefined) => write({ [qParam]: q, size: keep }, false),
    setFilter: (id: string, values: readonly string[]) =>
      write({ [id]: values.length ? values.join(",") : undefined, size: keep }, false),
    setParam: (id: string, value: string | undefined) => write({ [id]: value, size: keep }, false),
    clearFilters: () =>
      write(
        Object.fromEntries([
          [qParam, undefined],
          ...filters.map((f) => [f.id, undefined]),
          ...params.map((p) => [p.id, undefined]),
          ["size", keep],
        ]),
        false,
      ),
    setSize: (next: PageSize) => {
      rememberSize(config, next);
      write({ size: sizeParam(next) }, false);
    },
  };
}

/** Any filter (the search box included) narrows the list. */
const isFiltered = (
  values: Readonly<Record<string, unknown>>,
  filters: readonly TableFilter[],
  params: readonly TableParam[],
) =>
  Boolean(values.q) ||
  filters.some((f) => valuesOf(values[f.id]).length > 0) ||
  params.some((p) => values[p.id] !== undefined);

/** Where the rows come from, the same shape in both modes. */
interface Feed<T extends RowData> {
  rows: readonly T[] | undefined;
  status: Status;
  error: unknown;
  /** Rows of the previous view are shown while the new ones load. */
  busy: boolean;
  retry: () => void;
}

/** Server mode: one numbered page of the source (idle without one). */
function useServerFeed<T extends RowData>(
  source: ServerSource<T> | undefined,
  page: number,
  size: PageSize,
) {
  const query = useQuery({
    ...pageQueryOptions((source ?? NO_SOURCE) as ServerSource<T>, page, size),
    enabled: Boolean(source),
  });
  const feed: Feed<T> & { total: number | undefined; loaded: boolean } = {
    rows: query.data?.rows,
    total: query.data?.total,
    status: statusOf(query.data, query.isError),
    error: query.error ?? undefined,
    busy: Boolean(query.isPlaceholderData),
    retry: () => void query.refetch(),
    loaded: Boolean(query.data) && !query.isPlaceholderData,
  };
  return feed;
}

/** Client mode: the whole bounded list from one query. */
const clientFeed = <T extends RowData>(query: ClientQuery<T> | undefined): Feed<T> => ({
  rows: query?.data,
  status: statusOf(query?.data, query?.isError),
  error: query?.isError ? query.error : undefined,
  busy: Boolean(query?.isPlaceholderData),
  retry: () => void query?.refetch(),
});

/** The sort as the API writes it, from the header the person pressed. */
function sortWriter(write: Write, sorting: SortingState, defaultSort: string | undefined) {
  return (updater: Updater<SortingState>) => {
    const sort = sortOf(typeof updater === "function" ? updater(sorting) : updater);
    write({ sort: sort === defaultSort ? undefined : sort }, false);
  };
}

/**
 * Client mode sorts, filters, pages and counts facets in the browser (the row models in
 * `features`); server mode leaves all of it to the API and only says how many rows there are.
 */
const rowCountOf = (server: boolean, total: number | undefined) =>
  server ? { rowCount: total ?? -1 } : {};

/** A narrowing parameter's value from the URL, when it has one. */
const paramOf = (values: Readonly<Record<string, unknown>>, id: string) => {
  const value = values[id];
  return typeof value === "string" && value ? value : undefined;
};

export function useDataTable<T extends RowData>(options: DataTableOptions<T>): DataTableModel<T> {
  return useTableModel(options, useWriteSearch());
}

const READY = { isPending: false, isError: false, refetch: () => {} } as const;

/**
 * A client-mode table shown inside another page (a job's problems on the add page or in a
 * library's settings), where the URL already belongs to that page and its own table: the view
 * (`q`, filters, sort, page, size) lives in the component. Everything else is the kit's: the same
 * toolbar, faceted filters, pagination and states.
 */
export function useLocalDataTable<T extends RowData>({
  rows,
  ...options
}: LocalDataTableOptions<T>): DataTableModel<T> {
  const [raw, setRaw] = useState<Record<string, unknown>>({});
  const search = { ...raw, ...parseTableSearch(raw, options.config) };
  return useTableModel({ ...options, search, query: { data: rows, ...READY } }, (patch, keep) =>
    setRaw((prev) => patched(prev, patch, keep)),
  );
}

function useTableModel<T extends RowData>(
  options: DataTableOptions<T>,
  write: Write,
): DataTableModel<T> {
  const { config, search, getRowId, source } = options;
  const values = search as Readonly<Record<string, unknown>>;
  const filters = options.filters ?? NONE;
  const params = options.params ?? NONE;
  const server = source !== undefined;
  const mode = server ? "server" : "client";
  const { page, size } = pageOf(search, config);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>(
    options.initialColumnVisibility ?? {},
  );

  const selected = (id: string) => valuesOf(values[id]);
  const sorting = sortingOf(search.sort ?? config.defaultSort);
  const filterKey = JSON.stringify(filters.map((f) => [f.id, selected(f.id)]));

  // Server mode: one numbered page, its neighbours fetched ahead. Client mode: the whole list.
  const serverFeed = useServerFeed(source, page, size);
  const feed = server ? serverFeed : clientFeed(options.query);

  const { columns, columnIds } = useTableColumns(mode, options.columns, filters);
  const columnFilters: ColumnFiltersState = useMemo(
    () =>
      (JSON.parse(filterKey) as [string, string[]][])
        .filter(([id, values]) => values.length > 0 && columnIds.has(id))
        .map(([id, value]) => ({ id, value })),
    [filterKey, columnIds],
  );

  const rows = feed.rows;
  const data = useMemo(() => (rows ?? []) as T[], [rows]);

  // The view lives in the URL: never let the table reset it on its own (a reset on new data would
  // be a state update per render, and a URL write).
  const table = useTable({
    features,
    data,
    columns,
    getRowId,
    ...rowCountOf(server, serverFeed.total),
    manualSorting: server,
    manualFiltering: server,
    manualPagination: server,
    autoResetAll: false,
    enableSortingRemoval: true,
    state: {
      sorting,
      columnVisibility,
      columnFilters,
      globalFilter: search.q ?? "",
      pagination: { pageIndex: page - 1, pageSize: size },
    },
    onSortingChange: sortWriter(write, sorting, config.defaultSort),
    onColumnVisibilityChange: setColumnVisibility,
  });

  // The client knows its total once the rows are in: the rows left after its filters.
  const total = server ? serverFeed.total : rows && table.getFilteredRowModel().rows.length;
  const pageCount = Math.max(1, Math.ceil((total ?? 0) / size));

  const goTo = (next: number) => {
    const target = Math.min(Math.max(1, Math.round(next)), pageCount);
    write({ page: target > 1 ? target : undefined, size: sizeParam(size) }, true);
  };
  useClampPage(feed.status === "ready" && total !== undefined, page, pageCount, goTo);
  usePrefetchNeighbours(source, serverFeed.loaded, page, pageCount, size);

  return {
    table,
    mode,
    filters,
    params,
    page,
    size,
    sizes: sizesFor(config),
    total,
    pageCount,
    rows: table.getRowModel().rows,
    offset: (page - 1) * size,
    status: feed.status,
    error: feed.error,
    busy: feed.busy,
    canJump: !server || source.paging === "offset",
    lastJump: server ? Math.min(pageCount, lastJumpPage(source, size)) : pageCount,
    filtered: isFiltered(values, filters, params),
    viewKey: JSON.stringify([source?.key, search.q, filterKey, search.sort, page, size]),
    q: search.q,
    selected,
    param: (id) => paramOf(values, id),
    counts: (id) =>
      columnIds.has(id) && !server ? table.getColumn(id)?.getFacetedUniqueValues() : undefined,
    ...viewSetters(write, config, size, filters, params, options.qParam),
    goTo,
    retry: feed.retry,
    frameRef,
  };
}
