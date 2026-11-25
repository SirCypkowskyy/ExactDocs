import { flexRender, type RowData } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Columns3 } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { Button } from "../button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "../dropdown-menu";
import { messages } from "../messages";
import type { Header, Table } from "./features";

/** The skeleton a column shows while its rows load: its final shape, not a generic bar. */
export type SkeletonShape = "text" | "mono" | "pill" | "avatar" | "number" | "meter";

/** What a column says about itself in `meta` (the `columnMeta` slot of `features`). */
export interface DataColumnMeta {
  /** Classes of the column's cells, e.g. `max-md:hidden` to drop it on narrow screens. */
  className?: string;
  /** The column's name in words, where the header is not (the Columns menu, sort buttons). */
  label?: string;
  /**
   * Its place on a phone, where rows become cards: 1 is the card's title, 2 and 3 the meta
   * line under it; a column without one is left out of the card.
   */
  priority?: 1 | 2 | 3;
  /** The shape of its loading placeholder (DataTable v2); text by default. */
  skeleton?: SkeletonShape;
  /** Figures align at the end. */
  align?: "end";
}

/** A column's name in words: its `meta.label`, else its header when that is text. */
export function columnLabel(column: {
  id: string;
  columnDef: { header?: unknown; meta?: { label?: string } | undefined };
}): string {
  const { header, meta } = column.columnDef;
  return meta?.label ?? (typeof header === "string" ? header : column.id);
}

/** A column header; a sortable one is a button that says how the column is sorted. */
export function SortHeader<T extends RowData>({ header }: { header: Header<T> }) {
  const t = useMessages(messages).table;
  const label = flexRender(header.column.columnDef.header, header.getContext());
  if (!header.column.getCanSort()) return <>{label}</>;
  const dir = header.column.getIsSorted();
  return (
    <button
      type="button"
      aria-label={t.sortBy(columnLabel(header.column), dir)}
      onClick={header.column.getToggleSortingHandler()}
      className="-mx-1 inline-flex cursor-pointer items-center gap-1 rounded px-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
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
export function ColumnsMenu<T extends RowData>({ table }: { table: Table<T> }) {
  const t = useMessages(messages).table;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Columns3 aria-hidden="true" />
          {t.columns}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{t.showColumns}</DropdownMenuLabel>
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
              {columnLabel(column)}
            </DropdownMenuCheckboxItem>
          ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
