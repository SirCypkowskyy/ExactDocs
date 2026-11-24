import { CircleAlert, Inbox, type LucideIcon, RefreshCw, SearchX, X } from "lucide-react";
import type { ReactNode } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "../button";
import { messages } from "../messages";
import { Skeleton } from "../skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../table";
import type { SkeletonShape } from "./columns";

/*
 * The table's states (blocks-map §2.2, DESIGN.md "States and feedback"): loading is skeleton rows
 * at the page size, each cell in its column's final shape, shown only after 150 ms; empty keeps
 * the table's frame with a dashed border and says what to do next; an error is one sentence and
 * Retry inside the frame.
 */

const SHAPES: Record<SkeletonShape, ReactNode> = {
  text: <Skeleton className="h-4 w-4/5 max-w-48" />,
  mono: <Skeleton className="h-4 w-28" />,
  pill: <Skeleton className="h-5 w-16 rounded-full" />,
  avatar: (
    <span className="flex items-center gap-2">
      <Skeleton className="size-6 flex-none rounded-full" />
      <Skeleton className="h-4 w-24" />
    </span>
  ),
  number: <Skeleton className="ml-auto h-4 w-10" />,
  meter: (
    <span className="flex flex-col gap-1.5">
      <Skeleton className="h-1.5 w-28 rounded-full" />
      <Skeleton className="h-3 w-20" />
    </span>
  ),
};

/** A column as a skeleton draws it: the shape of its values and its own classes. */
export interface SkeletonCell {
  id: string;
  shape?: SkeletonShape | undefined;
  /** The column's own classes (`max-lg:hidden`), so the frame has the final columns. */
  className?: string | undefined;
}

/** `rows` placeholder rows, one cell per visible column in its final shape. */
export function SkeletonRows({
  columns,
  rows,
  actions,
}: {
  columns: readonly SkeletonCell[];
  rows: number;
  actions: boolean;
}) {
  return Array.from({ length: rows }, (_, i) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
    <TableRow key={i} aria-hidden="true" className="can-hover:hover:bg-transparent">
      {columns.map((column) => (
        <TableCell key={column.id} className={column.className}>
          {SHAPES[column.shape ?? "text"]}
        </TableCell>
      ))}
      {actions && (
        <TableCell className="w-0">
          <Skeleton className="size-6" />
        </TableCell>
      )}
    </TableRow>
  ));
}

/** The frame of a table with nothing in it: a dashed border, a large muted icon, the next step. */
export function TableMessage({
  icon: Icon,
  title,
  children,
  action,
  role,
  className,
}: {
  icon: LucideIcon;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  role?: "alert";
  className?: string;
}) {
  return (
    <div
      role={role}
      className={cn(
        "flex flex-col items-start gap-3 rounded-lg border border-dashed border-input px-5 py-8 sm:items-center sm:text-center",
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-8 text-muted-foreground" strokeWidth={1.5} />
      <div>
        <p className="text-body font-medium">{title}</p>
        {children && (
          <div className="mt-1 max-w-[60ch] text-body text-muted-foreground">{children}</div>
        )}
      </div>
      {action}
    </div>
  );
}

/** Nothing to list yet: what the list is for and how to fill it. */
export function TableEmpty({
  icon = Inbox,
  title,
  children,
  action,
}: {
  icon?: LucideIcon;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const t = useMessages(messages).dataTable;
  return (
    <TableMessage icon={icon} title={title ?? t.empty} action={action}>
      {children}
    </TableMessage>
  );
}

/** Filters that match nothing: say so, and offer the way back. */
export function TableNoMatch({
  title,
  children,
  onClear,
}: {
  title?: ReactNode;
  children?: ReactNode;
  onClear: () => void;
}) {
  const t = useMessages(messages).dataTable;
  return (
    <TableMessage
      icon={SearchX}
      title={title ?? t.noMatchTitle}
      action={
        <Button variant="outline" size="sm" onClick={onClear}>
          <X aria-hidden="true" data-icon-motion="turn" />
          {t.clearFilters}
        </Button>
      }
    >
      {children ?? t.noMatch}
    </TableMessage>
  );
}

/** The list could not be loaded: one sentence and Retry. */
export function TableError({ message, onRetry }: { message?: ReactNode; onRetry: () => void }) {
  const t = useMessages(messages).dataTable;
  const c = useMessages(common);
  return (
    <TableMessage
      role="alert"
      icon={CircleAlert}
      title={message ?? t.loadFailed}
      action={
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
          {c.retry}
        </Button>
      }
    />
  );
}

/** A column of the table a page will show: its header, and how its skeleton cells look. */
export interface SkeletonColumn extends SkeletonCell {
  header: ReactNode;
}

/**
 * A DataTable v2 page before its first rows (a route's `pendingComponent`, inside the page's
 * header): the toolbar, the table's frame with its real headers and skeleton rows in each
 * column's shape, the pagination's line; cards on a phone. No pulse; nothing moves when the rows
 * land. Hidden from assistive technology: the page says "Loading" in a status line.
 */
export function DataTableSkeleton({
  columns,
  filters = 0,
  search = true,
  actions = true,
  rows = 8,
}: {
  columns: readonly SkeletonColumn[];
  /** How many filter buttons the toolbar has. */
  filters?: number;
  /** The toolbar has a search box. */
  search?: boolean;
  /** The table has a column of row menus. */
  actions?: boolean;
  rows?: number;
}) {
  return (
    <div aria-hidden="true" data-slot="data-table-skeleton">
      {(search || filters > 0) && (
        <div className="mb-4 flex flex-wrap items-end gap-2">
          {search && (
            <div className="flex min-w-0 max-w-md flex-1 basis-60 flex-col gap-2">
              <Skeleton className="h-5 w-28" />
              <Skeleton className="h-11 w-full fine:h-9" />
            </div>
          )}
          {Array.from({ length: filters }, (_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
            <Skeleton key={i} className="h-11 w-24 fine:h-8" />
          ))}
        </div>
      )}
      <Table containerClassName="rounded-lg border border-border max-md:hidden">
        <TableHeader>
          <TableRow className="can-hover:hover:bg-transparent">
            {columns.map((c) => (
              <TableHead key={c.id} className={c.className}>
                {c.header}
              </TableHead>
            ))}
            {actions && <TableHead className="w-0" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          <SkeletonRows columns={columns} rows={rows} actions={actions} />
        </TableBody>
      </Table>
      <ul className="divide-y divide-rule rounded-lg border border-border md:hidden">
        {Array.from({ length: rows }, (_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
          <li key={i} className="flex flex-col gap-2 px-4 py-3">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-1/2" />
          </li>
        ))}
      </ul>
      <div className="mt-4 flex items-center justify-between gap-4">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-8 w-40" />
      </div>
    </div>
  );
}
