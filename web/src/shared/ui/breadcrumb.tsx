import { MoreHorizontal } from "lucide-react";
import { Slot } from "radix-ui";
import type * as React from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { messages } from "./messages";

/*
 * Breadcrumb (shadcn/ui, MIT): slash separators (the look of the free shadcnblocks breadcrumb
 * `standard-6`; no code taken from it), the current page in ink, the way back in muted ink. One
 * component for the library page, settings, sharing and the library's access log. A library ID
 * crumb is set in mono by the caller. Below `md` the middle crumbs can collapse into
 * `BreadcrumbEllipsis` inside a DropdownMenu (the idea of the basic `home-icon-2`).
 */

function Breadcrumb({ ...props }: React.ComponentProps<"nav">) {
  const t = useMessages(messages).breadcrumb;
  return <nav aria-label={t.label} data-slot="breadcrumb" {...props} />;
}

function BreadcrumbList({ className, ...props }: React.ComponentProps<"ol">) {
  return (
    <ol
      data-slot="breadcrumb-list"
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-1.5 text-body break-words text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function BreadcrumbItem({ className, ...props }: React.ComponentProps<"li">) {
  return (
    <li
      data-slot="breadcrumb-item"
      className={cn("inline-flex min-w-0 items-center gap-1.5", className)}
      {...props}
    />
  );
}

/**
 * A crumb that leads back; `asChild` takes the router's `Link`. A 44 px target on touch, as tall
 * as the line with a mouse (DESIGN.md, Accessibility).
 */
function BreadcrumbLink({
  asChild,
  className,
  ...props
}: React.ComponentProps<"a"> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "a";
  return (
    <Comp
      data-slot="breadcrumb-link"
      className={cn(
        "inline-flex min-h-11 items-center rounded-sm underline-offset-2 outline-none fine:min-h-7 transition-colors duration-(--dur-fast) hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      {...props}
    />
  );
}

/** Where you are: ink, not a link. */
function BreadcrumbPage({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="breadcrumb-page"
      aria-current="page"
      // The full text one hover away when it is cut short.
      title={typeof props.children === "string" ? props.children : undefined}
      className={cn("truncate font-medium text-foreground", className)}
      {...props}
    />
  );
}

function BreadcrumbSeparator({ children, className, ...props }: React.ComponentProps<"li">) {
  return (
    <li
      data-slot="breadcrumb-separator"
      role="presentation"
      aria-hidden="true"
      className={cn("text-muted-foreground/70 select-none", className)}
      {...props}
    >
      {children ?? "/"}
    </li>
  );
}

/** The collapsed middle crumbs (put it in a DropdownMenuTrigger). */
function BreadcrumbEllipsis({ className, ...props }: React.ComponentProps<"span">) {
  const t = useMessages(messages).breadcrumb;
  return (
    <span
      data-slot="breadcrumb-ellipsis"
      className={cn("flex size-6 items-center justify-center", className)}
      {...props}
    >
      <MoreHorizontal aria-hidden="true" className="size-4" />
      <span className="sr-only">{t.more}</span>
    </span>
  );
}

export {
  Breadcrumb,
  BreadcrumbEllipsis,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
};
