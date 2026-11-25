import {
  type CellData,
  type Cell as CoreCell,
  type ColumnDef as CoreColumnDef,
  type FilterFn as CoreFilterFn,
  type Header as CoreHeader,
  type Row as CoreRow,
  type SortFn as CoreSortFn,
  type Table as CoreTable,
  columnFacetingFeature,
  columnFilteringFeature,
  columnVisibilityFeature,
  createFacetedRowModel,
  createFacetedUniqueValues,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  filterFn_arrHas,
  globalFilteringFeature,
  metaHelper,
  type RowData,
  rowPaginationFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_datetime,
  sortFn_text,
  tableFeatures,
} from "@tanstack/react-table";
import type { DataColumnMeta } from "./columns";

/*
 * The TanStack Table features every table here uses (v9 registers them explicitly). Server mode
 * sets the manual flags, so its row models pass the server's rows through untouched.
 */
export const features = tableFeatures({
  columnVisibilityFeature,
  columnFilteringFeature,
  globalFilteringFeature,
  columnFacetingFeature,
  rowSortingFeature,
  rowPaginationFeature,
  filteredRowModel: createFilteredRowModel(),
  sortedRowModel: createSortedRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
  facetedRowModel: createFacetedRowModel(),
  facetedUniqueValues: createFacetedUniqueValues(),
  // Facet columns filter by "any of these"; the global filter's `includesString` needs no entry.
  filterFns: { arrHas: filterFn_arrHas },
  // What sorting's "auto" picks from a column's values (`basic` is its built-in fallback).
  sortFns: { alphanumeric: sortFn_alphanumeric, text: sortFn_text, datetime: sortFn_datetime },
  columnMeta: metaHelper<DataColumnMeta>(),
});

type Features = typeof features;

export type ColumnDef<T extends RowData, V extends CellData = unknown> = CoreColumnDef<
  Features,
  T,
  V
>;
export type Table<T extends RowData> = CoreTable<Features, T>;
export type Row<T extends RowData> = CoreRow<Features, T>;
export type Cell<T extends RowData> = CoreCell<Features, T, unknown>;
export type Header<T extends RowData> = CoreHeader<Features, T, unknown>;
export type FilterFn<T extends RowData> = CoreFilterFn<Features, T>;
export type SortFn<T extends RowData> = CoreSortFn<Features, T>;
