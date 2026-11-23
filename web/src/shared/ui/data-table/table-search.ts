import { stringifySearchWith } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { pickSort, textParam } from "@/shared/lib/list-sort";

/*
 * A table's view in the URL (blocks-map §2.2): `q`, its filters, `sort`, `page` (1-based) and
 * `size`. Pure functions, so a route's `validateSearch` and loader read the URL exactly as the
 * table does. Multi-value filters are written `state=failed,queued`, so a link that names one
 * value (`/jobs?state=failed`) is the same view the table writes.
 */

export const PAGE_SIZES = [5, 20, 50, 100] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
export const DEFAULT_PAGE_SIZE: PageSize = 20;

/** What every table keeps in the URL; a page's view adds its filters to it. */
export interface TableSearch {
  q?: string | undefined;
  sort?: string | undefined;
  page?: number | undefined;
  size?: PageSize | undefined;
}

export interface TableConfig {
  /** Names the table in this browser's memory of its page size ("jobs"). */
  id: string;
  /** The API's sort fields (or the client columns that sort); anything else is dropped. */
  sortFields: readonly string[];
  /** The order when `sort` is absent ("-id"): shown on the headers, never written to the URL. */
  defaultSort?: string;
  /** The most rows the list can ever have (a client list's cap): larger sizes are not offered. */
  maxRows?: number;
}

/** The page sizes a table offers: 5, 20, 50, 100, without those above its cap (5 at least). */
export function sizesFor(config: Pick<TableConfig, "maxRows">): readonly PageSize[] {
  const cap = config.maxRows;
  if (!cap) return PAGE_SIZES;
  const sizes = PAGE_SIZES.filter((s) => s <= cap);
  return sizes.length ? sizes : [PAGE_SIZES[0]];
}

/** A page number from the URL: a whole number from 1; anything else is page 1. */
export function parsePage(value: unknown): number | undefined {
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isInteger(n) && n > 1 && n <= 1_000_000 ? n : undefined;
}

/** A page size from the URL, when it is one the table offers. */
export function parseSize(
  value: unknown,
  sizes: readonly PageSize[] = PAGE_SIZES,
): PageSize | undefined {
  const n = typeof value === "string" ? Number(value) : value;
  return sizes.find((s) => s === n);
}

/**
 * The values of a multi-select filter: `a,b` or a list, kept in the options' order, unknown ones
 * dropped (a hand-edited URL never reaches the API). Undefined when none is left.
 */
export function parseFacet<T extends string>(
  value: unknown,
  options: readonly T[],
): T[] | undefined {
  const raw = Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : typeof value === "string"
      ? value.split(",")
      : [];
  const picked = options.filter((o) => raw.some((r) => r.trim() === o));
  return picked.length ? picked : undefined;
}

/** One value of a single-choice filter (a date preset). */
export const parseChoice = <T extends string>(
  value: unknown,
  options: readonly T[],
): T | undefined => parseFacet(value, options)?.[0];

/** The common part of a table's view, read from the URL. */
export function parseTableSearch(
  search: Record<string, unknown>,
  config: TableConfig,
): TableSearch {
  return {
    q: textParam(search.q),
    sort: pickSort(search.sort, config.sortFields),
    page: parsePage(search.page),
    size: parseSize(search.size, sizesFor(config)),
  };
}

const STORAGE_KEY = "exactdocs-table-sizes";

function readSizes(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** The page size last chosen for this table in this browser, if any (a convenience only). */
export function rememberedSize(config: TableConfig): PageSize | undefined {
  return parseSize(readSizes()[config.id], sizesFor(config));
}

export function rememberSize(config: TableConfig, size: PageSize): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readSizes(), [config.id]: size }));
  } catch {
    // Storage is off or full: the URL still holds the size.
  }
}

/**
 * The page and size a view shows. The URL wins; a URL with a page but no size was written at
 * the default size (so a shared link shows the same rows); otherwise the size remembered for this
 * table, else 20 (or the largest size the table offers, when that is smaller).
 */
export function pageOf(search: TableSearch, config: TableConfig): { page: number; size: PageSize } {
  const sizes = sizesFor(config);
  const fallback = sizes.includes(DEFAULT_PAGE_SIZE) ? DEFAULT_PAGE_SIZE : (sizes.at(-1) ?? 5);
  const page = search.page ?? 1;
  const size =
    (search.size && sizes.includes(search.size) ? search.size : undefined) ??
    (page > 1 ? fallback : (rememberedSize(config) ?? fallback));
  return { page, size };
}

/** The table's sorting from an API `sort` value (a field, `-` in front for descending). */
export const sortingOf = (sort: string | undefined): SortingState =>
  sort ? [{ id: sort.replace(/^-/, ""), desc: sort.startsWith("-") }] : [];

/** The API `sort` value of a sorting state. */
export const sortOf = (sorting: SortingState): string | undefined => {
  const [first] = sorting;
  return first ? `${first.desc ? "-" : ""}${first.id}` : undefined;
};

/** A filter's values as the URL writes them: `a,b`, or nothing. */
export const facetParam = (values: readonly string[] | undefined): string | undefined =>
  values?.length ? values.join(",") : undefined;

/** A URL parameter's value as a list (facets) whatever form it arrived in. */
export function valuesOf(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((v): v is string => typeof v === "string");
  if (typeof value === "string" && value) return value.split(",");
  return [];
}

/** A facet's values: plain words, written `a,b` rather than as JSON. */
const isFacetList = (value: unknown): value is string[] =>
  Array.isArray(value) &&
  value.length > 0 &&
  value.every((v) => typeof v === "string" && v !== "" && !v.includes(","));

/**
 * The app router's `stringifySearch`. A route's `validateSearch` turns `state=failed,queued` into
 * a list, and the router writes the validated search back to the URL: a list of words goes back
 * as `failed,queued` (what `parseFacet` reads), never as `["failed","queued"]`. Everything else is
 * written as TanStack Router's default does.
 */
export const stringifySearch = stringifySearchWith(
  (value: unknown) => (isFacetList(value) ? value.join(",") : JSON.stringify(value)),
  JSON.parse,
);
