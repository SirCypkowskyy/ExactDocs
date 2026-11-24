import { type LucideIcon, MoreHorizontal } from "lucide-react";
import { type KeyboardEvent, type ReactElement, useRef } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { IconButton, type IconMotion } from "../button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "../context-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../dropdown-menu";
import { messages } from "../messages";

/*
 * Row actions (blocks-map §2.2): one list feeds both the row's visible "More actions" menu and its
 * context menu (DESIGN.md, "A context menu mirrors a visible menu"), so nothing is reachable by
 * right-click alone. Shift+F10 or the Menu key on a focused row (or anything focused in it) opens
 * the context menu where the focus is.
 */

export interface RowAction<T> {
  id: string;
  label: string;
  /** Every item has a leading icon (decorative). */
  icon: LucideIcon;
  /** Its reaction when the item is highlighted (icon-motion.css). */
  motion?: IconMotion;
  onSelect: (row: T) => void;
  /** Removes or stops something: the item is red. */
  destructive?: boolean;
  /** Starts a new group: a separator above it. */
  group?: boolean;
}

/** A row's actions; return none for a row that has none. */
export type RowActions<T> = (row: T) => readonly RowAction<T>[];

// What opened the last row menu (its kebab, or the row), so a dialog an action opened can give
// focus back to it: the menu item that had focus is gone by then.
let opener: HTMLElement | null = null;

/**
 * For a dialog opened from a row action (`onCloseAutoFocus`): focus goes back to the kebab or the
 * row the action came from, as long as it is still on the page.
 */
export function restoreRowFocus(event: Event): void {
  if (opener?.isConnected) {
    event.preventDefault();
    opener.focus();
  }
}

type ItemComponent = typeof DropdownMenuItem | typeof ContextMenuItem;
type SeparatorComponent = typeof DropdownMenuSeparator | typeof ContextMenuSeparator;

function Items<T>({
  row,
  actions,
  Item,
  Separator,
}: {
  row: T;
  actions: readonly RowAction<T>[];
  Item: ItemComponent;
  Separator: SeparatorComponent;
}) {
  return actions.map((action, i) => {
    const Icon = action.icon;
    return [
      action.group && i > 0 ? <Separator key={`${action.id}-separator`} /> : null,
      <Item
        key={action.id}
        variant={action.destructive ? "destructive" : "default"}
        onSelect={() => action.onSelect(row)}
      >
        <Icon aria-hidden="true" {...(action.motion && { "data-icon-motion": action.motion })} />
        {action.label}
      </Item>,
    ];
  });
}

/** The row's visible menu: a kebab at the row's end (a card's top right on a phone). */
export function RowActionsMenu<T>({
  row,
  actions,
  rowLabel,
}: {
  row: T;
  actions: readonly RowAction<T>[];
  /** Names the row in the button's name: "More actions for /acme/payments v1.4.0". */
  rowLabel: string;
}) {
  const t = useMessages(messages).dataTable;
  const trigger = useRef<HTMLButtonElement>(null);
  if (actions.length === 0) return null;
  return (
    <DropdownMenu
      onOpenChange={(open) => {
        // Always the kebab: opened with the mouse it never had focus (Radix keeps focus where it
        // was on pointerdown), so what has focus now is something else on the page.
        if (open && trigger.current) opener = trigger.current;
      }}
    >
      <DropdownMenuTrigger asChild>
        <IconButton
          ref={trigger}
          label={t.moreActions(rowLabel)}
          size="icon-sm"
          className="-my-1.5 text-muted-foreground data-[state=open]:bg-accent data-[state=open]:text-foreground"
        >
          <MoreHorizontal aria-hidden="true" />
        </IconButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-48">
        <Items
          row={row}
          actions={actions}
          Item={DropdownMenuItem}
          Separator={DropdownMenuSeparator}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const opensMenu = (event: KeyboardEvent) =>
  event.key === "ContextMenu" || (event.shiftKey && event.key === "F10");

/**
 * The row's context menu: `children` is the row (a `<tr>`, or a card on a phone), which must take
 * a ref and props. The row is focusable from script (`tabIndex={-1}`), so a click on it lets the
 * keyboard open its menu.
 */
export function RowContextMenu<T>({
  row,
  actions,
  children,
}: {
  row: T;
  actions: readonly RowAction<T>[];
  children: ReactElement;
}) {
  if (actions.length === 0) return children;
  return (
    <ContextMenu>
      <ContextMenuTrigger
        asChild
        onContextMenu={(event) => {
          if (!event.defaultPrevented && event.currentTarget instanceof HTMLElement) {
            opener =
              document.activeElement instanceof HTMLElement &&
              event.currentTarget.contains(document.activeElement)
                ? document.activeElement
                : event.currentTarget;
          }
        }}
        onKeyDown={(event) => {
          if (!opensMenu(event)) return;
          event.preventDefault();
          const focused =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
          const box = (focused ?? event.currentTarget).getBoundingClientRect();
          // The browser fires `contextmenu` for these keys on its own only sometimes; ask for it.
          event.currentTarget.dispatchEvent(
            new MouseEvent("contextmenu", {
              bubbles: true,
              cancelable: true,
              clientX: box.left + 8,
              clientY: box.bottom,
            }),
          );
        }}
      >
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent
        className="min-w-48"
        onCloseAutoFocus={(event) => {
          // Back to where the keyboard was (or the row), not the top of the page.
          if (opener?.isConnected) {
            event.preventDefault();
            opener.focus({ preventScroll: true });
          }
        }}
      >
        <Items
          row={row}
          actions={actions}
          Item={ContextMenuItem}
          Separator={ContextMenuSeparator}
        />
      </ContextMenuContent>
    </ContextMenu>
  );
}
