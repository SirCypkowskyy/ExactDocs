import type { Column } from "@tanstack/react-table";
import type { ReactNode } from "react";
import type { SkeletonShape } from "@/shared/ui/data-table/columns";
import { SkeletonRows } from "@/shared/ui/data-table/states";
import { Skeleton } from "@/shared/ui/skeleton";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/shared/ui/table";

/** A column of the table a page will show: its header, the shape of its values, where it hides. */
export interface SkeletonColumn {
  id: string;
  header: ReactNode;
  shape?: SkeletonShape;
  /** The column's own classes (`max-lg:hidden`), so the frame has the final columns. */
  className?: string;
}

const ROWS = 8;

/**
 * A DataTable v2 page before its first rows (a route's `pendingComponent`): the toolbar, the
 * table's frame with its real headers and skeleton rows in each column's shape, the pagination's
 * line; cards on a phone. No pulse; nothing moves when the rows land.
 */
export function TableSkeleton({
  columns,
  filters,
  actions = true,
}: {
  columns: readonly SkeletonColumn[];
  /** How many filter buttons the toolbar has. */
  filters: number;
  /** The table has a column of row menus. */
  actions?: boolean;
}) {
  // SkeletonRows reads only a column's ID and its meta (shape and classes).
  const shaped = columns.map((c) => ({
    id: c.id,
    columnDef: { meta: { skeleton: c.shape ?? "text", className: c.className } },
  })) as unknown as Column<unknown>[];
  return (
    <div aria-hidden="true">
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div className="flex min-w-0 max-w-md flex-1 basis-60 flex-col gap-2">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-11 w-full fine:h-9" />
        </div>
        {Array.from({ length: filters }, (_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
          <Skeleton key={i} className="h-11 w-24 fine:h-8" />
        ))}
      </div>
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
          <SkeletonRows columns={shaped} rows={ROWS} actions={actions} />
        </TableBody>
      </Table>
      <ul className="divide-y divide-rule rounded-lg border border-border md:hidden">
        {Array.from({ length: ROWS }, (_, i) => (
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
