import { type Cell, flexRender, type Row } from "@tanstack/react-table";
import type { LucideIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { PHONE_QUERY, useMediaQuery } from "@/shared/lib/use-media-query";
import { cn } from "@/shared/lib/utils";
import { messages } from "../messages";
import { Skeleton } from "../skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../table";
import { columnLabel, SortHeader } from "./columns";
import { type RowActions, RowActionsMenu, RowContextMenu } from "./row-actions";
import { SkeletonRows, TableEmpty, TableError, TableNoMatch } from "./states";
import type { DataTableModel } from "./use-data-table";

/*
 * DataTable v2 (blocks-map §2.2), after the free shadcnblocks Data Table 1 (`data-table1`) for its
 * structure and Data Table 4 (`data-table4`) for the horizontal scroll, on the shadcn/ui table
 * primitives. The rows of one page in a hairline frame; the states (loading, empty, no match,
 * error) in the same place; below `md` each row becomes a card (title, two or three meta cells by
 * `meta.priority`, the kebab on the right), so the main lists never scroll sideways.
 *
 * Page changes swap rows at once; only rows that arrive while a page is shown (a polled list) fade
 * in (`row-in`). `aria-rowcount` and `aria-rowindex` place the page within the whole list.
 */

interface DataTableProps<T> {
  model: DataTableModel<T>;
  /** The table's accessible name (usually the page title). */
  label: string;
  /** One list for the row's kebab and its context menu. */
  rowActions?: RowActions<T>;
  /** Names a row for its kebab ("More actions for …"); the row ID otherwise. */
  rowLabel?: (row: T) => string;
  /** Nothing to list yet (no filter): what the list is for and how to fill it. */
  empty?: { icon?: LucideIcon; title: ReactNode; body?: ReactNode; action?: ReactNode };
  /** Filters that match nothing (default: "Nothing matches these filters."). */
  noMatch?: { title: ReactNode; body?: ReactNode };
  /** The sentence when the list fails to load. */
  errorMessage?: ReactNode;
}

/** Rows that arrived while the same page was shown (a refresh), so they can fade in. */
function useFreshRows(viewKey: string, ids: readonly string[], busy: boolean): ReadonlySet<string> {
  const idsKey = ids.join("\n");
  const [seen, setSeen] = useState({
    viewKey,
    idsKey,
    fresh: new Set<string>() as ReadonlySet<string>,
  });
  if (!busy && (seen.viewKey !== viewKey || seen.idsKey !== idsKey)) {
    const before = new Set(seen.idsKey.split("\n"));
    const fresh =
      seen.viewKey === viewKey ? new Set(ids.filter((id) => !before.has(id))) : new Set<string>();
    setSeen({ viewKey, idsKey, fresh });
    return fresh;
  }
  return seen.fresh;
}

function cellClass<T>(cell: Cell<T, unknown>) {
  const meta = cell.column.columnDef.meta;
  return cn(meta?.align === "end" && "text-right", meta?.className);
}

export function DataTable<T>({
  model,
  label,
  rowActions,
  rowLabel,
  empty,
  noMatch,
  errorMessage,
}: DataTableProps<T>) {
  const t = useMessages(messages).dataTable;
  const phone = useMediaQuery(PHONE_QUERY);
  const { table, status, rows } = model;
  const fresh = useFreshRows(
    model.viewKey,
    rows.map((r) => r.id),
    model.busy || status !== "ready",
  );
  const actionsOf = (row: Row<T>) => rowActions?.(row.original) ?? [];
  const nameOf = (row: Row<T>) => rowLabel?.(row.original) ?? row.id;

  let body: ReactNode;
  if (status === "error") {
    body = <TableError message={errorMessage} onRetry={model.retry} />;
  } else if (status === "ready" && rows.length === 0 && !model.busy) {
    body = model.filtered ? (
      <TableNoMatch title={noMatch?.title} onClear={model.clearFilters}>
        {noMatch?.body}
      </TableNoMatch>
    ) : (
      <TableEmpty
        {...(empty?.icon && { icon: empty.icon })}
        title={empty?.title}
        action={empty?.action}
      >
        {empty?.body}
      </TableEmpty>
    );
  } else if (phone) {
    body =
      status === "ready" ? (
        <Cards model={model} label={label} actionsOf={actionsOf} nameOf={nameOf} fresh={fresh} />
      ) : (
        <ul
          aria-hidden="true"
          className="pending-in divide-y divide-rule rounded-lg border border-border"
        >
          {Array.from({ length: Math.min(model.size, 20) }, (_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
            <li key={i} className="flex flex-col gap-2 px-4 py-3">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-1/2" />
            </li>
          ))}
        </ul>
      );
  } else {
    const columns = table.getVisibleLeafColumns();
    body = (
      <Table
        aria-label={label}
        aria-busy={model.busy || status === "pending" || undefined}
        aria-rowcount={model.total !== undefined ? model.total + 1 : -1}
        containerClassName="rounded-lg border border-border"
      >
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} aria-rowindex={1} className="can-hover:hover:bg-transparent">
              {group.headers.map((header) => {
                const sorted = header.column.getIsSorted();
                const meta = header.column.columnDef.meta;
                return (
                  <TableHead
                    key={header.id}
                    aria-sort={
                      sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined
                    }
                    className={cn(meta?.align === "end" && "text-right", meta?.className)}
                  >
                    {header.isPlaceholder ? null : <SortHeader header={header} />}
                  </TableHead>
                );
              })}
              {rowActions && (
                <TableHead className="w-0">
                  <span className="sr-only">{t.actions}</span>
                </TableHead>
              )}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody className={cn(status === "pending" && "pending-in")}>
          {status === "pending" ? (
            <SkeletonRows columns={columns} rows={model.size} actions={Boolean(rowActions)} />
          ) : (
            rows.map((row, i) => {
              const actions = actionsOf(row);
              return (
                <RowContextMenu key={row.id} row={row.original} actions={actions}>
                  <TableRow
                    tabIndex={-1}
                    data-row-id={row.id}
                    aria-rowindex={model.offset + i + 2}
                    className={cn(fresh.has(row.id) && "row-in", model.busy && "opacity-60")}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className={cellClass(cell)}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                    {rowActions && (
                      <TableCell className="w-0 py-2 text-right">
                        <RowActionsMenu
                          row={row.original}
                          actions={actions}
                          rowLabel={nameOf(row)}
                        />
                      </TableCell>
                    )}
                  </TableRow>
                </RowContextMenu>
              );
            })
          )}
        </TableBody>
      </Table>
    );
  }

  return (
    <div ref={model.frameRef} className="scroll-mt-20">
      {body}
    </div>
  );
}

/** Below `md`: each row a card, its title cell first, its meta cells under it, the kebab on the right. */
function Cards<T>({
  model,
  label,
  actionsOf,
  nameOf,
  fresh,
}: {
  model: DataTableModel<T>;
  label: string;
  actionsOf: (row: Row<T>) => ReturnType<RowActions<T>>;
  nameOf: (row: Row<T>) => string;
  fresh: ReadonlySet<string>;
}) {
  const visible = model.table.getVisibleLeafColumns();
  const title =
    visible.find((c) => c.columnDef.meta?.priority === 1)?.id ?? visible[0]?.id ?? undefined;
  const meta = visible
    .filter((c) => c.columnDef.meta?.priority === 2 || c.columnDef.meta?.priority === 3)
    .sort((a, b) => (a.columnDef.meta?.priority ?? 0) - (b.columnDef.meta?.priority ?? 0))
    .map((c) => c.id);
  return (
    <ul
      aria-label={label}
      aria-busy={model.busy || undefined}
      className="divide-y divide-rule rounded-lg border border-border"
    >
      {model.rows.map((row) => {
        const actions = actionsOf(row);
        const cells = new Map(row.getVisibleCells().map((cell) => [cell.column.id, cell]));
        const head = title ? cells.get(title) : undefined;
        return (
          <RowContextMenu key={row.id} row={row.original} actions={actions}>
            <li
              tabIndex={-1}
              data-row-id={row.id}
              className={cn(
                "flex items-start gap-3 px-4 py-3 outline-none focus-visible:bg-raised",
                fresh.has(row.id) && "row-in",
                model.busy && "opacity-60",
              )}
            >
              <div className="min-w-0 flex-1">
                {head && (
                  <div className="min-w-0 font-medium">
                    {flexRender(head.column.columnDef.cell, head.getContext())}
                  </div>
                )}
                {meta.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-small text-muted-foreground">
                    {meta.map((id) => {
                      const cell = cells.get(id);
                      if (!cell) return null;
                      return (
                        <span key={id} className="inline-flex min-w-0 items-center">
                          <span className="sr-only">{columnLabel(cell.column)}: </span>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
              <RowActionsMenu row={row.original} actions={actions} rowLabel={nameOf(row)} />
            </li>
          </RowContextMenu>
        );
      })}
    </ul>
  );
}
