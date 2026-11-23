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

type TableStates = Pick<DataTableProps<unknown>, "empty" | "noMatch" | "errorMessage">;

/** The frame's message instead of rows: the list failed, is empty, or nothing matches. */
function stateOf<T>(
  model: DataTableModel<T>,
  { empty, noMatch, errorMessage }: TableStates,
): ReactNode {
  if (model.status === "error") return <TableError message={errorMessage} onRetry={model.retry} />;
  if (model.status !== "ready" || model.rows.length > 0 || model.busy) return null;
  if (model.filtered) {
    return (
      <TableNoMatch title={noMatch?.title} onClear={model.clearFilters}>
        {noMatch?.body}
      </TableNoMatch>
    );
  }
  return (
    <TableEmpty
      {...(empty?.icon && { icon: empty.icon })}
      title={empty?.title}
      action={empty?.action}
    >
      {empty?.body}
    </TableEmpty>
  );
}

export function DataTable<T>({ model, label, rowActions, rowLabel, ...states }: DataTableProps<T>) {
  const phone = useMediaQuery(PHONE_QUERY);
  const fresh = useFreshRows(
    model.viewKey,
    model.rows.map((r) => r.id),
    model.busy || model.status !== "ready",
  );
  const rows: RowsProps<T> = {
    model,
    label,
    actions: Boolean(rowActions),
    actionsOf: (row) => rowActions?.(row.original) ?? [],
    nameOf: (row) => rowLabel?.(row.original) ?? row.id,
    fresh,
  };
  return (
    <div ref={model.frameRef} className="scroll-mt-20">
      {stateOf(model, states) ?? (phone ? <PhoneRows {...rows} /> : <DesktopRows {...rows} />)}
    </div>
  );
}

interface RowsProps<T> {
  model: DataTableModel<T>;
  label: string;
  /** The table has row actions (a column for the kebab). */
  actions: boolean;
  actionsOf: (row: Row<T>) => ReturnType<RowActions<T>>;
  nameOf: (row: Row<T>) => string;
  fresh: ReadonlySet<string>;
}

/** From `md` up: the rows of one page in a table, the header sorting on the server or here. */
function DesktopRows<T>({ model, label, actions, actionsOf, nameOf, fresh }: RowsProps<T>) {
  const t = useMessages(messages).dataTable;
  const { table, status, rows } = model;
  return (
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
            {actions && (
              <TableHead className="w-0">
                <span className="sr-only">{t.actions}</span>
              </TableHead>
            )}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody className={cn(status === "pending" && "pending-in")}>
        {status === "pending" ? (
          <SkeletonRows
            columns={table.getVisibleLeafColumns()}
            rows={model.size}
            actions={actions}
          />
        ) : (
          rows.map((row, i) => {
            const rowActions = actionsOf(row);
            return (
              <RowContextMenu key={row.id} row={row.original} actions={rowActions}>
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
                  {actions && (
                    <TableCell className="w-0 py-2 text-right">
                      <RowActionsMenu
                        row={row.original}
                        actions={rowActions}
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

/** Below `md`: cards once the rows are here, two-line placeholders until then. */
function PhoneRows<T>(props: RowsProps<T>) {
  if (props.model.status === "ready") return <Cards {...props} />;
  return (
    <ul
      aria-hidden="true"
      className="pending-in divide-y divide-rule rounded-lg border border-border"
    >
      {Array.from({ length: Math.min(props.model.size, 20) }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
        <li key={i} className="flex flex-col gap-2 px-4 py-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/2" />
        </li>
      ))}
    </ul>
  );
}

/** Below `md`: each row a card, its title cell first, its meta cells under it, the kebab on the right. */
function Cards<T>({ model, label, actionsOf, nameOf, fresh }: RowsProps<T>) {
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
