import { Command as C } from "cmdk";
import { SearchIcon } from "lucide-react";
import type * as React from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { menuLabel, menuRow, menuSeparator } from "./dropdown-menu";
import { messages } from "./messages";

/*
 * Command (shadcn/ui on cmdk, MIT): a filterable list for pickers and faceted filters, usually in
 * a Popover. Rows use the menu recipe (44 px on touch, 32 px with a mouse, the highlighted row on
 * `accent`), so a picker and a menu feel like one family. Arrow keys move, Enter picks, typing
 * filters.
 */

function Command({ className, ...props }: React.ComponentProps<typeof C>) {
  return (
    <C
      data-slot="command"
      className={cn(
        "flex size-full flex-col overflow-hidden rounded-lg bg-popover text-popover-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandInput({ className, ...props }: React.ComponentProps<typeof C.Input>) {
  return (
    <div
      data-slot="command-input-wrapper"
      className="flex items-center gap-2 border-b border-rule px-3"
    >
      <SearchIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      <C.Input
        data-slot="command-input"
        className={cn(
          "flex h-11 w-full min-w-0 bg-transparent text-section outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 fine:h-9 fine:text-body",
          className,
        )}
        {...props}
      />
    </div>
  );
}

function CommandList({ className, ...props }: React.ComponentProps<typeof C.List>) {
  return (
    <C.List
      data-slot="command-list"
      className={cn("max-h-72 scroll-py-1 overflow-x-hidden overflow-y-auto p-1", className)}
      {...props}
    />
  );
}

function CommandEmpty({ className, children, ...props }: React.ComponentProps<typeof C.Empty>) {
  const t = useMessages(messages).command;
  return (
    <C.Empty
      data-slot="command-empty"
      className={cn("px-2 py-6 text-center text-body text-muted-foreground", className)}
      {...props}
    >
      {children ?? t.empty}
    </C.Empty>
  );
}

function CommandGroup({ className, ...props }: React.ComponentProps<typeof C.Group>) {
  return (
    <C.Group
      data-slot="command-group"
      className={cn(
        "overflow-hidden text-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-1.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-small [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandSeparator({ className, ...props }: React.ComponentProps<typeof C.Separator>) {
  return (
    <C.Separator
      data-slot="command-separator"
      className={cn(menuSeparator, className)}
      {...props}
    />
  );
}

function CommandItem({ className, ...props }: React.ComponentProps<typeof C.Item>) {
  return (
    <C.Item
      data-slot="command-item"
      className={cn(
        menuRow,
        "data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 [&_svg:not([class*='text-'])]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandLabel({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="command-label" className={cn(menuLabel, className)} {...props} />;
}

function CommandShortcut({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="command-shortcut"
      className={cn("ml-auto text-small text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandLabel,
  CommandList,
  CommandSeparator,
  CommandShortcut,
};
