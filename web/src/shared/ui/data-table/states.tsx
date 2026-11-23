import type { Column } from "@tanstack/react-table";
import { CircleAlert, Inbox, type LucideIcon, RefreshCw, SearchX, X } from "lucide-react";
import type { ReactNode } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "../button";
import { messages } from "../messages";
import { Skeleton } from "../skeleton";
import { TableCell, TableRow } from "../table";
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

/** `rows` placeholder rows, one cell per visible column in its final shape. */
export function SkeletonRows<T>({
  columns,
  rows,
  actions,
}: {
  columns: Column<T>[];
  rows: number;
  actions: boolean;
}) {
  return Array.from({ length: rows }, (_, i) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
    <TableRow key={i} aria-hidden="true" className="can-hover:hover:bg-transparent">
      {columns.map((column) => (
        <TableCell key={column.id} className={column.columnDef.meta?.className}>
          {SHAPES[column.columnDef.meta?.skeleton ?? "text"]}
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
