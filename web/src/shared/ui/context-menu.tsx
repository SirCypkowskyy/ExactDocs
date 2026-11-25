import { CheckIcon, ChevronRightIcon, CircleIcon } from "lucide-react";
import { ContextMenu as C } from "radix-ui";
import type * as React from "react";
import { cn } from "@/shared/lib/utils";
import {
  menuContent,
  menuIndicator,
  menuItem,
  menuItemTone,
  menuLabel,
  menuSeparator,
} from "./dropdown-menu";

/*
 * Context menu (shadcn/ui on Radix, MIT), on the same recipes as DropdownMenu so both menus look
 * and move alike: it scales in from where it opened, 150 ms in and 100 ms out.
 *
 * A context menu only ever mirrors a menu that is also on screen (DESIGN.md, "A context menu
 * mirrors a visible menu"): nothing may be reachable by right-click alone, because touch, keyboard
 * and new users would never find it. `RowActions` (data-table/row-actions.tsx) feeds both from
 * one list.
 */

const contextContent = cn(
  menuContent,
  "max-h-(--radix-context-menu-content-available-height) origin-(--radix-context-menu-content-transform-origin)",
);

function ContextMenu(props: React.ComponentProps<typeof C.Root>) {
  return <C.Root data-slot="context-menu" {...props} />;
}

function ContextMenuTrigger(props: React.ComponentProps<typeof C.Trigger>) {
  return <C.Trigger data-slot="context-menu-trigger" {...props} />;
}

function ContextMenuGroup(props: React.ComponentProps<typeof C.Group>) {
  return <C.Group data-slot="context-menu-group" {...props} />;
}

function ContextMenuContent({ className, ...props }: React.ComponentProps<typeof C.Content>) {
  return (
    <C.Portal>
      <C.Content
        data-slot="context-menu-content"
        collisionPadding={8}
        className={cn(contextContent, className)}
        {...props}
      />
    </C.Portal>
  );
}

function ContextMenuItem({
  className,
  inset,
  variant = "default",
  ...props
}: React.ComponentProps<typeof C.Item> & {
  inset?: boolean;
  variant?: "default" | "destructive";
}) {
  return (
    <C.Item
      data-slot="context-menu-item"
      data-inset={inset}
      data-variant={variant}
      className={cn(menuItem, menuItemTone, className)}
      {...props}
    />
  );
}

function ContextMenuCheckboxItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof C.CheckboxItem>) {
  return (
    <C.CheckboxItem
      data-slot="context-menu-checkbox-item"
      className={cn(menuItem, "pl-8", className)}
      {...props}
    >
      <span className={menuIndicator}>
        <C.ItemIndicator>
          <CheckIcon className="size-4 text-selection" />
        </C.ItemIndicator>
      </span>
      {children}
    </C.CheckboxItem>
  );
}

function ContextMenuRadioGroup(props: React.ComponentProps<typeof C.RadioGroup>) {
  return <C.RadioGroup data-slot="context-menu-radio-group" {...props} />;
}

function ContextMenuRadioItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof C.RadioItem>) {
  return (
    <C.RadioItem
      data-slot="context-menu-radio-item"
      className={cn(menuItem, "pl-8", className)}
      {...props}
    >
      <span className={menuIndicator}>
        <C.ItemIndicator>
          <CircleIcon className="size-2 fill-current text-selection" />
        </C.ItemIndicator>
      </span>
      {children}
    </C.RadioItem>
  );
}

function ContextMenuLabel({
  className,
  inset,
  ...props
}: React.ComponentProps<typeof C.Label> & { inset?: boolean }) {
  return (
    <C.Label
      data-slot="context-menu-label"
      data-inset={inset}
      className={cn(menuLabel, "data-inset:pl-8", className)}
      {...props}
    />
  );
}

function ContextMenuSeparator({ className, ...props }: React.ComponentProps<typeof C.Separator>) {
  return (
    <C.Separator
      data-slot="context-menu-separator"
      className={cn(menuSeparator, className)}
      {...props}
    />
  );
}

function ContextMenuShortcut({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="context-menu-shortcut"
      className={cn("ml-auto text-small text-muted-foreground", className)}
      {...props}
    />
  );
}

function ContextMenuSub(props: React.ComponentProps<typeof C.Sub>) {
  return <C.Sub data-slot="context-menu-sub" {...props} />;
}

function ContextMenuSubTrigger({
  className,
  inset,
  children,
  ...props
}: React.ComponentProps<typeof C.SubTrigger> & { inset?: boolean }) {
  return (
    <C.SubTrigger
      data-slot="context-menu-sub-trigger"
      data-inset={inset}
      className={cn(menuItem, "data-inset:pl-8 data-[state=open]:bg-accent", className)}
      {...props}
    >
      {children}
      <ChevronRightIcon className="ml-auto size-4" />
    </C.SubTrigger>
  );
}

function ContextMenuSubContent({ className, ...props }: React.ComponentProps<typeof C.SubContent>) {
  return (
    <C.SubContent
      data-slot="context-menu-sub-content"
      className={cn(contextContent, "max-h-none", className)}
      {...props}
    />
  );
}

export {
  ContextMenu,
  ContextMenuCheckboxItem,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuRadioGroup,
  ContextMenuRadioItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
};
