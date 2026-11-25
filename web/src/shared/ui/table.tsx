import type * as React from "react";
import { cn } from "@/shared/lib/utils";

/*
 * Table primitives (shadcn/ui, MIT), restyled to the tokens: headers in `text-small` muted ink,
 * rows separated by `rule` hairlines, cells 14 px with 12 px sides, figures tabular (styles.css).
 * A hovered row takes the `raised` tone where hover exists. `DataTable` (data-table/) builds every
 * list with many rows from these; a short static table can use them directly.
 */

function Table({
  className,
  containerClassName,
  ...props
}: React.ComponentProps<"table"> & {
  containerClassName?: string;
}) {
  return (
    <div
      data-slot="table-container"
      className={cn("relative w-full overflow-x-auto", containerClassName)}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom border-collapse text-left text-body", className)}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn(
        "text-small text-muted-foreground [&_tr]:border-b [&_tr]:border-rule",
        className,
      )}
      {...props}
    />
  );
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn("border-t border-rule bg-raised font-medium [&>tr]:last:border-b-0", className)}
      {...props}
    />
  );
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b border-rule outline-none transition-colors duration-(--dur-fast) focus-visible:bg-raised data-[state=selected]:bg-route-soft can-hover:hover:bg-raised",
        className,
      )}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-10 px-3 text-left align-middle font-normal whitespace-nowrap first:pl-4 last:pr-4",
        className,
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn("px-3 py-3 align-top first:pl-4 last:pr-4", className)}
      {...props}
    />
  );
}

/** A body cell that names its row (`<th scope="row">`), set like any other cell. */
function TableRowHeader({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-cell"
      scope="row"
      className={cn("px-3 py-3 text-left align-top font-normal first:pl-4 last:pr-4", className)}
      {...props}
    />
  );
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-small text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
  TableRowHeader,
};
